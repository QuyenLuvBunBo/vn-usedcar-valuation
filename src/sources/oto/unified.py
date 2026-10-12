"""Normalize oto.com.vn data into the Unified Schema (16 attributes + 5 metadata) — week 1.

Run:
    python -m src.sources.oto.unified                 # reuse the cached sitemap if present
    python -m src.sources.oto.unified --fetch-sitemap # refresh listing_date from the sitemap first

Output: data/processed/oto_unified.csv (+ .jsonl) and a per-column coverage audit.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys

from ...common import config, schema, storage
from ...common.http_client import ScraperSession
from ...common.parsing import to_float, to_int

SOURCE_PLATFORM = "oto.com.vn"
LAST_MOD_CACHE = config.DATA_RAW / "sitemap_lastmod.json"
SITEMAPS = ("sitemap-detail-1.xml", "sitemap-detail-2.xml")
ENTRY_RE = re.compile(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Allow letters right after the number (2.5Q, 1.5G, 2.4L) but never match inside a longer number
ENGINE_RE = re.compile(r"(?<![\d.])([0-9]\.[0-9])(?!\d)")

# 16 attributes + 5 metadata — taken from the shared contract in src/common/schema.py
SCHEMA_COLUMNS = schema.SCHEMA_COLUMNS

log = logging.getLogger("unified_schema")


# ------------------------------------------------------------------ helpers
def _km_from_text(value: str | None) -> float | None:
    """Convert '140.000 km' -> 140000.0."""
    km = to_int(value)
    return float(km) if km is not None else None


def derive_trim(brand: str, model: str, title: str, car_name: str) -> str:
    """Extract sub_model_trim (e.g. '1.8G CVT', '2.5Q') from the title or car_name."""
    text = (title or "").strip()
    if not text and car_name:
        # car_name looks like "2021 - Honda CR-V 1.5 G - description..."
        parts = [p.strip() for p in car_name.split(" - ")]
        text = parts[1] if len(parts) > 1 else car_name
    if not text:
        return ""
    trim = text
    for prefix in (f"{brand} {model}".strip(), model, brand):
        if prefix and trim.lower().startswith(prefix.lower()):
            trim = trim[len(prefix):]
            break
    trim = YEAR_RE.sub(" ", trim)
    trim = re.sub(r"^[\s\-–,\.]+|[\s\-–,\.]+$", "", trim)
    return re.sub(r"\s+", " ", trim)


def derive_engine_capacity(*texts: str) -> float | None:
    """Estimate engine displacement (L) from the trim/title — e.g. '1.5 G' -> 1.5."""
    for text in texts:
        for found in ENGINE_RE.findall(text or ""):
            value = float(found)
            if 0.6 <= value <= 6.9:
                return value
    return None


# ------------------------------------------------------- lastmod từ sitemap
def fetch_lastmod_map(session: ScraperSession) -> dict[str, str]:
    """Download sitemap-detail -> dict of url -> lastmod (the listing's publication/bump date)."""
    result: dict[str, str] = {}
    for name in SITEMAPS:
        text = session.get_text(f"https://oto.com.vn/{name}")
        if not text:
            log.warning("could not fetch %s", name)
            continue
        entries = ENTRY_RE.findall(text)
        log.info("%s: %s entry", name, len(entries))
        for url, lastmod in entries:
            result[url] = lastmod
    return result


def load_lastmod_map(fetch: bool = False) -> dict[str, str]:
    """Read the lastmod cache; refresh from the sitemap when --fetch-sitemap is given or no cache."""
    if not fetch and LAST_MOD_CACHE.exists():
        cached = json.loads(LAST_MOD_CACHE.read_text(encoding="utf-8"))
        log.info("Using the cached lastmod map: %s (%s listings)", LAST_MOD_CACHE, len(cached))
        return cached
    with ScraperSession(delay=1.0) as session:
        mapping = fetch_lastmod_map(session)
    if mapping:
        config.ensure_dirs()
        LAST_MOD_CACHE.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        log.info("Saved the lastmod cache: %s (%s listings)", LAST_MOD_CACHE, len(mapping))
    return mapping


# --------------------------------------------------------------- transform
def _load_tables(conn: sqlite3.Connection) -> tuple[list[dict], dict[str, dict]]:
    """Read the oto_cars and oto_car_details tables (the latter only if details were crawled)."""
    cars = storage.read_rows(conn, "oto_cars")
    has_detail = any(
        row[0] == "oto_car_details"
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    )
    details = {r["url"]: r for r in storage.read_rows(conn, "oto_car_details")} if has_detail else {}
    return cars, details


def build_unified(conn: sqlite3.Connection, lastmods: dict[str, str]) -> list[dict]:
    """Join oto_cars with oto_car_details and normalize everything into the Unified Schema."""
    cars, details = _load_tables(conn)

    rows: list[dict] = []
    for car in cars:
        detail = details.get(car["url"], {})
        specs: dict[str, str] = {}
        if detail.get("d_specs"):
            try:
                specs = json.loads(detail["d_specs"])
            except ValueError:
                specs = {}

        trim = derive_trim(
            car.get("brand", ""), car.get("model", ""),
            detail.get("d_title", ""), car.get("car_name", ""),
        )
        # Price: prefer the listing value; fall back to the detail page when the listing is empty
        price_vnd = to_int(car.get("price_vnd")) or to_int(detail.get("d_price_vnd"))
        raw_price = (car.get("price_text") or "").strip() or (detail.get("d_price_text") or "").strip()

        # Fall back to the detail page's ul.list-info: SOLD listings have no data-call on the
        # listing card, so origin/body type/gearbox would otherwise be missing.
        origin_raw = car.get("origin") or specs.get("Xuất xứ", "")
        body_raw = car.get("body_type") or specs.get("Kiểu dáng", "")
        fuel_raw = car.get("fuel") or specs.get("Nhiên liệu", "")
        gear_raw = car.get("gearbox") or specs.get("Hộp số", "")
        year = to_int(car.get("year")) or to_int(specs.get("Năm SX"))
        mileage = to_float(car.get("km")) or _km_from_text(specs.get("Km đã đi"))

        rows.append({
            "listing_id": f"OTO_{car.get('id') or ''}",
            "source_platform": SOURCE_PLATFORM,
            "brand": car.get("brand") or "Unknown",
            "model": car.get("model") or "Unknown",
            "sub_model_trim": trim,
            "manufacture_year": year,
            "mileage_km": mileage,
            "transmission": schema.normalize_transmission(gear_raw),
            "fuel_type": schema.normalize_fuel(fuel_raw),
            "origin": schema.normalize_origin(origin_raw),
            "body_type": schema.normalize_body(body_raw),
            "engine_capacity": derive_engine_capacity(
                trim, detail.get("d_title", ""), car.get("car_name", "")
            ),
            "seats": to_int(detail.get("d_seats")),
            "location_province": schema.normalize_province(
                specs.get("Tỉnh thành") or car.get("province"), detail.get("d_city_code", "")
            ),
            "seller_type": schema.seller_type_from_subdomain(detail.get("d_seller_url")),
            "price_vnd": price_vnd,
            "source_url": car.get("url"),
            "listing_date": lastmods.get(car.get("url") or ""),
            "scraped_at": car.get("scraped_at"),
            "raw_price_text": raw_price or None,
            "price_status": schema.price_status(price_vnd, raw_price),
        })
    return rows



# ------------------------------------------------------------------- audit
def audit(rows: list[dict]) -> None:
    """Print a coverage/missing-rate audit of every column (a Milestone 1 requirement)."""
    total = len(rows) or 1
    print("\n" + "=" * 74)
    print(f"AUDIT UNIFIED SCHEMA — {len(rows)} listings")
    print("=" * 74)
    print(f"{'column':22s} {'filled':>7s} {'missing':>8s} {'rate':>7s} {'distinct':>9s}")
    for col in SCHEMA_COLUMNS:
        filled = sum(1 for r in rows if r.get(col) not in (None, "", "Unknown"))
        distinct = len({r.get(col) for r in rows if r.get(col) not in (None, "")})
        print(f"{col:22s} {filled:7d} {total - filled:8d} {filled / total * 100:6.1f}% {distinct:9d}")

    print("\nDistribution of the categorical columns:")
    for col in ("price_status", "seller_type", "transmission", "fuel_type", "origin"):
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get(col))
            counts[key] = counts.get(key, 0) + 1
        top = ", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        print(f"  {col:15s}: {top}")

    print("\nDomain-rule checks from the report:")
    print(f"  price < 30 million VND (send to review): {sum(1 for r in rows if (r.get('price_vnd') or 0) and r['price_vnd'] < 30_000_000)}")
    print(f"  price > 25 billion VND (own segment)   : {sum(1 for r in rows if (r.get('price_vnd') or 0) > 25_000_000_000)}")
    print(f"  odometer < 100 km              : {sum(1 for r in rows if (r.get('mileage_km') or 0) < 100)}")
    print(f"  odometer > 1,000,000 km        : {sum(1 for r in rows if (r.get('mileage_km') or 0) > 1_000_000)}")
    years = [r["manufacture_year"] for r in rows if r.get("manufacture_year")]
    if years:
        print(f"  manufacture year: {min(years)}–{max(years)} | outside the 1995–present scope: "
              f"{sum(1 for y in years if y < 1995)}")


# --------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export the Unified Schema (16 attributes + 5 metadata) for oto.com.vn data",
    )
    parser.add_argument("--out", default="oto_unified", help="output CSV/JSONL file name")
    parser.add_argument("--fetch-sitemap", action="store_true",
                        help="refresh listing_date (lastmod) from sitemap-detail")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    lastmods = load_lastmod_map(fetch=args.fetch_sitemap)

    conn = storage.open_db()
    rows = build_unified(conn, lastmods)
    conn.close()

    csv_path = storage.save_csv(rows, args.out, SCHEMA_COLUMNS)
    jsonl_path = storage.save_jsonl(rows, args.out)
    audit(rows)
    print(f"\nCSV   : {csv_path}\nJSONL : {jsonl_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

