"""Normalize the muaban.net crawl into the Unified Schema (16 attributes + 5 metadata).

Unlike oto.com.vn, this site *publishes* the car specs on the detail page
(`parameters`: Hãng xe / Dòng xe / Năm sản xuất / Số km đã đi / Hộp số / Nhiên liệu / Số chỗ /
Xuất xứ), so nothing has to be guessed from the title. Two fields the site does not expose are
derived and marked as such below: `body_type` (from the title) and `engine_capacity` (from the title).

Scope: /o-to also lists rentals, parts, services and commercial vehicles. Those ads are skipped
here and counted in the run log, because the project targets passenger cars that are for sale.

Run:
    python -m src.sources.muaban.unified
    python -m src.sources.muaban.unified --out muaban --include-commercial
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys

from ...common import config, schema, storage
from ...common.parsing import clean_text as _clean
from ...common.parsing import parse_km_text, parse_year_text, to_int
from .crawl import DETAIL_TABLE, SOURCE_PLATFORM, TABLE

log = logging.getLogger("muaban_unified")

SCHEMA_COLUMNS = schema.SCHEMA_COLUMNS
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
ENGINE_RE = re.compile(r"(?<![\d.])([0-9]\.[0-9])(?!\d)")
KM_TEXT_RE = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\s*km\b", re.I)

# Ads in /o-to that are not a passenger car for sale.
NON_SALE_URL = ("/cho-thue-", "/dich-vu-", "phu-tung", "vay-mua", "tin-tuc", "sua-chua")
COMMERCIAL_URL = ("xe-tai", "dau-keo", "xe-khach", "xe-ben", "container", "xe-cong-trinh",
                  "mooc", "xe-nang", "may-cong-trinh")

# Cross-source consistency: the site spells some brands differently from oto.com.vn, and the
# duplicate key is built from the brand string, so these must agree before week 2 runs.
BRAND_ALIASES = {
    "mercedes benz": "Mercedes-Benz", "mercedes-benz": "Mercedes-Benz", "mercedes": "Mercedes-Benz",
    "landrover": "Land Rover", "land rover": "Land Rover",
    "vinfast": "VinFast", "vin fast": "VinFast",
    "bmw": "BMW", "mg": "MG", "audi": "Audi",
}
MODEL_ALIASES = {"crv": "CR-V", "cx5": "CX-5", "cx3": "CX-3", "cx8": "CX-8", "cx30": "CX-30"}
PLACEHOLDER = ("các hãng khác", "xe tải, đầu kéo…", "xe tải, đầu kéo...", "unknown", "khác")

# The site has a 'Kiểu dáng' field for ~70% of the ads; these are the labels it uses.
BODY_LABEL_MAP = {
    "suv/crossover": "SUV", "suv": "SUV", "crossover": "Crossover",
    "pick up": "Pickup", "pickup": "Pickup", "bán tải": "Pickup",
    "van/mini van": "Van", "van": "Van", "minivan": "Van",
    "sedan": "Sedan", "hatchback": "Hatchback", "mpv": "MPV",
    "coupe": "Coupe", "convertible": "Convertible", "wagon": "Wagon",
}

# Fallback keywords (the other ~30% of ads publish no body style at all).
BODY_WORDS = (
    ("bán tải", "Pickup"), ("pickup", "Pickup"), ("crossover", "Crossover"),
    ("suv", "SUV"), ("hatchback", "Hatchback"), ("sedan", "Sedan"), ("mpv", "MPV"),
    ("minivan", "Van"), ("van", "Van"),
)



# ------------------------------------------------------------------ helpers
def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Whether a table is present in the SQLite database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _province(location: str) -> str:
    """'TP. Nha Trang, Khánh Hòa' -> 'Khánh Hòa' (the last part is the province)."""
    parts = [part.strip() for part in (location or "").split(",") if part.strip()]
    return schema.normalize_province(parts[-1] if parts else "")


def _origin(raw: str, title: str = "") -> str:
    """Map the site's 'Xuất xứ' to the contract. 'Việt nam' = assembled locally (CKD)."""
    text = (raw or "").strip().lower()
    if not text:
        # the field is missing on ~45% of the ads; the title sometimes says it
        low = (title or "").lower()
        if "nhập khẩu" in low:
            return "CBU"
        if "trong nước" in low or "lắp ráp" in low:
            return "CKD"
        return "Unknown"
    if "việt" in text or "viet" in text:
        return "CKD"
    known = schema.normalize_origin(raw)
    return known if known in schema.ORIGIN_VALUES - {"Unknown"} else "CBU"


def _body_type(title: str, raw: str = "") -> str:
    """Body style from the site's 'Kiểu dáng' field, falling back to title keywords."""
    key = (raw or "").strip().lower()
    if key:
        mapped = BODY_LABEL_MAP.get(key) or schema.normalize_body(raw)
        if mapped in schema.BODY_VALUES:
            return mapped
    text = (title or "").lower()
    for needle, label in BODY_WORDS:
        if needle in text:
            return label
    return "Unknown"


def _engine_capacity(title: str) -> float | None:
    """Read a displacement such as '2.0' out of the title (range guard 0.6-6.9 L)."""
    for found in ENGINE_RE.findall(title or ""):
        value = float(found)
        if 0.6 <= value <= 6.9:
            return value
    return None


def _trim(title: str, brand: str, model: str) -> str:
    """Leftover text after brand/model/year/km — the site does not publish a trim field."""
    text = YEAR_RE.sub(" ", title or "")
    text = KM_TEXT_RE.sub(" ", text)
    for prefix in (f"{brand} {model}".strip(), brand, model):
        if prefix and text.lower().lstrip().startswith(prefix.lower()):
            text = text.lstrip()[len(prefix):]
            break
    return _clean(text).strip(" -–,.")[:40]


def is_excluded(url: str, include_commercial: bool = False) -> str:
    """Reason this ad is out of scope ('' when it is a passenger car for sale)."""
    low = (url or "").lower()
    if any(marker in low for marker in NON_SALE_URL):
        return "not_for_sale"
    if not include_commercial and any(marker in low for marker in COMMERCIAL_URL):
        return "commercial"
    return ""


def _safe(value: str, allowed: set[str]) -> str:
    """Keep the contract closed: a site label we cannot map falls back to Unknown."""
    return value if value in allowed else "Unknown"


def _is_new_car(condition: str) -> bool:
    """The site's 'Tình trạng' is 'Đã sử dụng' or 'Xe mới'; unknown counts as used."""
    text = (condition or "").strip().lower()
    return text.startswith("xe mới") or text in ("mới", "new")


def _brand(raw: str) -> str:
    """Clean brand: drop the site's placeholder categories and align the spelling with oto."""
    text = _clean(raw)
    low = text.lower()
    if not text or low in PLACEHOLDER or low.endswith("khác"):
        return "Unknown"
    return BRAND_ALIASES.get(low, text)


def _model(raw: str) -> str:
    """Clean model: drop 'Dòng khác' style placeholders and fix the usual spellings."""
    text = _clean(raw)
    low = text.lower()
    if not text or low in PLACEHOLDER or low.endswith("khác"):
        return "Unknown"
    return MODEL_ALIASES.get(low.replace("-", "").replace(" ", ""), text)


# --------------------------------------------------------------- transform
def _to_row(listing: dict, detail: dict | None) -> dict:
    """One unified record from the listing row plus (when crawled) its detail row."""
    detail = detail or {}
    title = _clean(detail.get("title") or listing.get("title"))
    brand = _brand(detail.get("brand"))
    model = _model(detail.get("model"))
    price = to_int(detail.get("price_vnd") if detail.get("price_vnd") is not None
                   else listing.get("price_vnd")) or None
    # price 0 is how the API encodes "Thỏa thuận" / "Liên hệ" -> keep it as a null target.
    raw_price = _clean(detail.get("price_text") or listing.get("price_text"))
    year = (to_int(detail.get("year")) or parse_year_text(title)
            or to_int(str(listing.get("publish_at") or "")[:4]))
    return {
        "listing_id": f"MUA_{listing.get('id') or ''}",
        "source_platform": SOURCE_PLATFORM,
        "brand": brand or "Unknown",
        "model": model or "Unknown",
        "sub_model_trim": _trim(title, brand, model),
        "manufacture_year": year,
        "mileage_km": parse_km_text(detail.get("km")),
        "transmission": _safe(schema.normalize_transmission(detail.get("gearbox")),
                             schema.TRANSMISSION_VALUES),
        "fuel_type": _safe(schema.normalize_fuel(detail.get("fuel")), schema.FUEL_VALUES),
        "origin": _safe(_origin(detail.get("origin"), title), schema.ORIGIN_VALUES),
        "body_type": _safe(_body_type(title, detail.get("body_style")), schema.BODY_VALUES),
        "engine_capacity": _engine_capacity(title),
        "seats": to_int(detail.get("seats")),
        "location_province": _province(detail.get("address") or listing.get("location")),
        "seller_type": ("Dealership/Salon" if to_int(listing.get("is_company"))
                        else "Private Individual"),
        "price_vnd": price,
        "source_url": listing.get("url"),
        "listing_date": listing.get("publish_at"),
        "scraped_at": listing.get("scraped_at"),
        "raw_price_text": raw_price or None,
        "price_status": schema.price_status(price, raw_price),
    }


def build_unified(conn: sqlite3.Connection, include_commercial: bool = False,
                  used_only: bool = False) -> tuple[list[dict], dict[str, int]]:
    """Join muaban_cars with muaban_car_details and normalize into the Unified Schema."""
    listings = storage.read_rows(conn, TABLE)
    details = {}
    if _table_exists(conn, DETAIL_TABLE):
        details = {row["url"]: row for row in storage.read_rows(conn, DETAIL_TABLE)}

    rows: list[dict] = []
    stats = {"listings": len(listings), "without_detail": 0,
             "not_for_sale": 0, "commercial": 0, "new_car": 0}
    for listing in listings:
        reason = is_excluded(listing.get("url"), include_commercial=include_commercial)
        if reason:
            stats[reason] += 1
            continue
        detail = details.get(listing.get("url"))
        if detail is None:
            stats["without_detail"] += 1
        elif used_only and _is_new_car(detail.get("condition")):
            stats["new_car"] += 1
            continue
        rows.append(_to_row(listing, detail))
    return rows, stats


# ------------------------------------------------------------------- audit
def audit(rows: list[dict]) -> None:
    """Print a coverage/missing-rate audit of every column (a Milestone 1 requirement)."""
    total = len(rows) or 1
    print("\n" + "=" * 74)
    print(f"AUDIT UNIFIED SCHEMA — {len(rows)} listings")
    print("=" * 74)
    print(f"{'column':22s} {'filled':>7s} {'missing':>8s} {'rate':>7s} {'distinct':>9s}")
    for col in SCHEMA_COLUMNS:
        filled = sum(1 for row in rows if row.get(col) not in (None, "", "Unknown"))
        distinct = len({row.get(col) for row in rows if row.get(col) not in (None, "")})
        print(f"{col:22s} {filled:7d} {len(rows) - filled:8d} "
              f"{(len(rows) - filled) / total * 100:6.1f}% {distinct:9d}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export the muaban.net crawl as the 21-column CSV")
    parser.add_argument("--out", default="muaban", help="output CSV/JSONL file name")
    parser.add_argument("--include-commercial", action="store_true",
                        help="keep trucks/buses (default: passenger cars only)")
    parser.add_argument("--used-only", action="store_true",
                        help="drop ads the site marks as 'Xe mới' (used cars only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.ensure_dirs()

    conn = storage.open_db()
    if not _table_exists(conn, TABLE):
        log.error("no crawl data yet -> run: python -m src.sources.muaban --pages 2 --details")
        conn.close()
        return 1
    rows, stats = build_unified(conn, include_commercial=args.include_commercial,
                                used_only=args.used_only)
    conn.close()

    log.info("listings %s | exported %s | skipped: %s not-for-sale, %s commercial, %s new cars | "
             "without detail page: %s",
             stats["listings"], len(rows), stats["not_for_sale"], stats["commercial"],
             stats["new_car"], stats["without_detail"])

    csv_path = storage.save_csv(rows, args.out, SCHEMA_COLUMNS)
    jsonl_path = storage.save_jsonl(rows, args.out)
    audit(rows)
    print(f"\nCSV   : {csv_path}\nJSONL : {jsonl_path}")
    print("Validate before merging: "
          f"python -m tools.validate_source_csv {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
