"""Normalize carmudi.vn data into the 21-column Unified Schema — USED cars only.

Run:  python -m src.sources.carmudi.unified   ->  data/processed/carmudi.csv

Why this is more than a column rename (see docs/sources/carmudi.md):
  * The card/detail structured fields are placeholders when the seller skipped them
    ("Xe mới" in the mileage slot, "Xăng", "Số sàn", year "No data"). A 2010 Yaris is flagged
    "Xe mới" while its description says "165.000km" and "số tự động".
  * So year comes from the TITLE, mileage/transmission/fuel are cross-checked with the TITLE and
    DESCRIPTION, and the used/new decision does not trust the "Xe mới" tag alone.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone

from ...common import config, schema, storage
from ...common.parsing import parse_km_text, parse_vnd_price, parse_year_text, to_int

SOURCE_PLATFORM = "carmudi"
NEW_YEAR_FROM = datetime.now(timezone.utc).year - 1   # year >= this with no real mileage => treated as NEW
MAX_PLAUSIBLE_KM = 1_000_000                          # e.g. the site shows "10,000,000 km" -> null
ENGINE_RE = re.compile(r"(?<![\d.])([0-9]\.[0-9])(?!\d)")
DESC_KM_RE = re.compile(r"(?:số\s*km|odo|đã\s*đi|chạy|km)\D{0,12}?(\d{1,3}(?:[.,]\d{3})+|\d{4,7}|\d{1,3})\s*(k\b|km|nghìn|ngàn|vạn)?", re.I)
DESC_KM_FALLBACK_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d{4,7})\s*(km)\b",re.I,)
AT_RE = re.compile(r"\b(AT|CVT|DCT|số tự động|tự động)\b", re.I)
MT_RE = re.compile(r"\b(MT|số sàn|số tay)\b", re.I)
DIESEL_RE = re.compile(r"\b(máy dầu|diesel|dầu)\b", re.I)
HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
EV_RE = re.compile(r"\b(thuần điện|chạy điện|electric|EV)\b", re.I)
SALON_RE = re.compile(r"\b(salon|showroom|auto|motor|cars?|đại lý|ô tô|oto)\b", re.I)

log = logging.getLogger("carmudi_unified")


def km_from_text(text: str | None) -> int | None:
    """Mileage from the card ('165,000 km', 'Xe mới' -> None). 0 means 'not filled in'."""
    if not text or "mới" in text.lower():
        return None
    km = parse_km_text(text)
    return km if km else None


def km_from_description(desc: str | None) -> int | None:
    """Extract plausible mileage from Vietnamese car descriptions."""
    text = desc or ""

    # Explicit "7 vạn" -> 70000 km
    m_van = re.search(
        r"(\d{1,3})\s*vạn\b",
        text,
        re.I,
    )
    if m_van:
        value = int(m_van.group(1)) * 10_000
        if 100 <= value <= MAX_PLAUSIBLE_KM:
            return value

    # Explicit "60k" -> 60000 km, only near mileage-related wording
    m_k = re.search(
        r"(?:odo|số\s*km|đã\s*đi|chạy)\D{0,12}?(\d{1,3})\s*k\b",
        text,
        re.I,
    )
    if m_k:
        value = int(m_k.group(1)) * 1_000
        if 100 <= value <= MAX_PLAUSIBLE_KM:
            return value
        
    # First, prefer matches associated with mileage keywords.
    for m in DESC_KM_RE.finditer(text):
        num, unit = m.group(1), (m.group(2) or "").lower()
        value = int(re.sub(r"\D", "", num))

        if unit == "vạn":
            value *= 10_000
        elif unit in ("k", "nghìn", "ngàn") or (
            not unit
            and value < 1000
            and "." not in num
            and "," not in num
            and value >= 5
        ):
            value *= 1000

        if 100 <= value <= MAX_PLAUSIBLE_KM:
            return value

    # Fallback: find a number explicitly followed by "km".
    for m in DESC_KM_FALLBACK_RE.finditer(text):
        num = m.group(1)
        value = int(re.sub(r"\D", "", num))

        if 100 <= value <= MAX_PLAUSIBLE_KM:
            return value

    return None


def derive_trim(brand: str, model: str, title: str) -> str:
    trim = (title or "").strip()
    for prefix in (f"{brand} {model}".strip(), model, brand):
        if prefix and trim.lower().startswith(prefix.lower()):
            trim = trim[len(prefix):]
            break
    trim = re.sub(r"\b(?:19|20)\d{2}\b", " ", trim)
    trim = re.sub(r"^[\s\-–,\.]+|[\s\-–,\.]+$", "", trim)
    return re.sub(r"\s+", " ", trim)


def engine_from(*texts: str) -> float | None:
    for t in texts:
        for f in ENGINE_RE.findall(t or ""):
            if 0.6 <= float(f) <= 6.9:
                return float(f)
    return None


def safe_enum(value: str, allowed: set[str]) -> str:
    """schema.map_value() returns the raw label when it is unmapped; never leak that into the CSV."""
    return value if value in allowed else "Unknown"


def norm_gearbox(field: str | None) -> str:
    """The cards say 'Tự động' / 'Số sàn'; schema.TRANSMISSION_MAP only knows 'số tự động'."""
    key = (field or "").strip().lower()
    if key in ("tự động", "số tự động", "at", "cvt"):
        return "Automatic"
    if key in ("số sàn", "sàn", "số tay", "mt"):
        return "Manual"
    return safe_enum(schema.normalize_transmission(field), schema.TRANSMISSION_VALUES)


def pick_transmission(title: str, desc: str, field: str) -> str:
    """title token > description > structured field (the field defaults to 'Số sàn')."""
    for text in (title, desc):
        at, mt = bool(AT_RE.search(text or "")), bool(MT_RE.search(text or ""))
        if at != mt:
            return "Automatic" if at else "Manual"
    return norm_gearbox(field)


def pick_fuel(title: str, desc: str, field: str) -> str:
    blob = f"{title} {desc}"
    if EV_RE.search(blob):
        return "Electric"
    if HYBRID_RE.search(blob):
        return "Hybrid"
    if DIESEL_RE.search(blob):
        return "Diesel"
    return safe_enum(schema.normalize_fuel(field), schema.FUEL_VALUES)


def is_used(year: int | None, km: int | None, card_km_text: str) -> bool:
    """Used = has real mileage, or is old enough that 'Xe mới' cannot be true.
    A recent-year ad without real mileage is a dealer's NEW car -> dropped."""
    if km and km > 0:
        return True
    if year is not None and year < NEW_YEAR_FROM:
        return True
    return False


def iso_date(value: str | None) -> str | None:
    """'2026-10-20' -> midnight UTC; '2026-10-20 14:03:11' / ISO strings -> ISO 8601 (timezone as given)."""
    v = (value or "").strip()
    if not v:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return f"{v}T00:00:00+00:00"
    if re.match(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", v):
        return v.replace(" ", "T")
    return None


def seller_type(name: str | None) -> str:
    return "Dealership/Salon" if name and SALON_RE.search(name) else "Unknown"


# `Kiểu dáng` on carmudi is a seller dropdown whose template default is `Coupe`: 528 of the 546 rows
# collected in week 1 carried it, a 2010 Toyota Yaris included (docs/sources/carmudi.md already calls
# the column unreliable). Emitting it teaches the model that a whole marketplace sells only coupes, so
# the value is written as Unknown here — and `src/data_prep/normalize.py` keeps the same repair for
# files collected before this change.
TEMPLATE_BODY_DEFAULT = "Coupe"


def body_type_of(car: dict, detail: dict) -> str:
    """The body type the site reports, unless it is the dropdown default."""
    value = safe_enum(schema.normalize_body(car.get("body") or detail.get("d_body")),
                      schema.BODY_VALUES)
    return "Unknown" if value == TEMPLATE_BODY_DEFAULT else value


def build_unified(cars: list[dict], details: dict[str, dict]) -> tuple[list[dict], dict]:
    rows, dropped = [], {"new_car": 0, "no_price_or_year": 0, "dup": 0}
    now = config.now_iso()
    seen: set[str] = set()
    for car in cars:
        d = details.get(car["url"], {})
        title = car.get("title") or d.get("d_title") or ""
        desc = car.get("desc") or d.get("d_description") or ""
        year = parse_year_text(title) or to_int(car.get("year_text"))
        km_candidates = [km_from_text(car.get("km_text")),km_from_text(d.get("d_km")),km_from_description(desc),]
        km = next((candidate for candidate in km_candidates if candidate is not None and 100 <= candidate <= MAX_PLAUSIBLE_KM),None,)
        if not is_used(year, km, car.get("km_text", "")):
            dropped["new_car"] += 1
            continue
        raw_price = (car.get("price_text") or d.get("d_price_text") or "").strip()
        price = parse_vnd_price(raw_price)
        listing_id = f"CAR_{car.get('id')}"
        if listing_id in seen:
            dropped["dup"] += 1
            continue
        seen.add(listing_id)
        brand = car.get("brand") or d.get("d_brand") or (title.split(" ")[0] if title else "") or "Unknown"
        model = car.get("model") or d.get("d_model") or "Unknown"
        trim = derive_trim(brand, model, title)
        posted = iso_date(car.get("posted") or d.get("d_posted"))
        rows.append({
            "listing_id": listing_id, "source_platform": SOURCE_PLATFORM,
            "brand": brand, "model": model, "sub_model_trim": trim,
            "manufacture_year": year, "mileage_km": float(km) if km else None,
            "transmission": pick_transmission(title, desc, car.get("gearbox") or d.get("d_gearbox", "")),
            "fuel_type": pick_fuel(title, desc, car.get("fuel") or d.get("d_fuel", "")),
            "origin": safe_enum(schema.normalize_origin(d.get("d_origin")), schema.ORIGIN_VALUES),
            "body_type": body_type_of(car, d),
            "engine_capacity": engine_from(trim, title),
            "seats": to_int(d.get("d_seats")),
            "location_province": schema.normalize_province(car.get("province") or d.get("d_location")),
            "seller_type": seller_type(car.get("seller") or d.get("d_seller")),
            "price_vnd": price, "source_url": car["url"],
            "listing_date": posted,
            "scraped_at": car.get("scraped_at") or now,
            "raw_price_text": raw_price or None,
            "price_status": schema.price_status(price, raw_price),
        })
    return rows, dropped


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = storage.open_db()
    cars = storage.read_rows(conn, "carmudi_cars")
    has = conn.execute("SELECT name FROM sqlite_master WHERE name='carmudi_car_details'").fetchone()
    details = {r["url"]: r for r in storage.read_rows(conn, "carmudi_car_details")} if has else {}
    rows, dropped = build_unified(cars, details)
    path = storage.save_csv(rows, "carmudi", schema.SCHEMA_COLUMNS)
    log.info("read=%s kept(used)=%s dropped=%s -> %s", len(cars), len(rows), dropped, path)
    log.info("NEXT: python -m tools.validate_source_csv data/processed/carmudi.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
