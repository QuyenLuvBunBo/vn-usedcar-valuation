"""vucar.vn: map the raw records from crawl.py to the 21 unified columns.

Mapping decisions, each checked against the file the source owner produced (`vucar.csv`):

  * **brand + model come from `display_name`** ("Mercedes C Class 2016"), not from the API's `car_brand` /
    `car_model`: those are slugs (`mercedes`, `c_class`) and re-casing a slug cannot reproduce a name like
    "CR-V" or "Lux A2.0". The raw slug is still kept and used to cross-check the split.
  * **`listing_date` comes from `created_at`.** The original export wrote the capture month ("10/2026") in
    every row, which is not a publication date; `created_at` is the real one.
  * **`fuel_type`** is filled from `car_fuel_type`, which the original export left empty.

The site does not expose engine displacement, seats, origin (CKD/CBU) or the seller type, so those stay
empty / `Unknown` instead of being invented.

    python -m src.sources.vucar.unified                    # data/processed/vucar.csv
    python -m src.sources.vucar.unified --out vucar_refresh
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from pathlib import Path

from ...common import config, parsing, schema, storage
from . import PLATFORM, SOURCE

log = logging.getLogger(f"{SOURCE}.unified")

# Canonical make names, the same spellings the other sources use, so brand-based grouping agrees.
BRAND_NAMES = {
    "toyota": "Toyota", "honda": "Honda", "hyundai": "Hyundai", "kia": "Kia",
    "mercedes": "Mercedes-Benz", "mercedes-benz": "Mercedes-Benz", "mitsubishi": "Mitsubishi",
    "ford": "Ford", "vinfast": "VinFast", "mazda": "Mazda", "peugeot": "Peugeot",
    "nissan": "Nissan", "suzuki": "Suzuki", "chevrolet": "Chevrolet", "porsche": "Porsche",
    "mg": "MG", "lexus": "Lexus", "bmw": "BMW", "audi": "Audi", "volkswagen": "Volkswagen",
    "volvo": "Volvo", "subaru": "Subaru", "land rover": "Land Rover", "isuzu": "Isuzu",
    "jaguar": "Jaguar", "infiniti": "Infiniti", "byd": "BYD", "tesla": "Tesla",
    "landrover": "Land Rover", "rolls-royce": "Rolls-Royce", "bentley": "Bentley",
}
# vucar writes the province without diacritics and without spaces ("TP.HCM", "BinhDuong").
LOCATION_NAMES = {
    "tphcm": "TP. Hồ Chí Minh", "hcm": "TP. Hồ Chí Minh", "hanoi": "Hà Nội",
    "binhduong": "Bình Dương", "longan": "Long An", "dongnai": "Đồng Nai",
    "danang": "Đà Nẵng", "cantho": "Cần Thơ", "haiphong": "Hải Phòng", "baria-vungtau": "Bà Rịa - Vũng Tàu",
}
TRANSMISSION_NAMES = {"at": "Automatic", "mt": "Manual", "cvt": "Automatic"}
FUEL_NAMES = {"petrol": "Gasoline", "gasoline": "Gasoline", "oil": "Diesel", "diesel": "Diesel",
              "electric": "Electric", "hybrid": "Hybrid"}
BODY_NAMES = {"suv": "SUV", "sedan": "Sedan", "mpv": "MPV", "hatchback": "Hatchback",
              "cuv": "Crossover", "pickup": "Pickup", "van": "Van", "coupe": "Coupe",
              "wagon": "Wagon", "minibus": "Minibus", "truck": "Truck",
              # the site's own spellings: "Couple" is its label for the coupe class (the 19 rows are
              # Audi TT/A5, Camaro, Mustang…), and "Kiểu dáng khác" literally means "other body style"
              "couple": "Coupe", "kiểu dáng khác": "Other", "kieu dang khac": "Other"}


def split_name(display_name: str) -> tuple[str, str, bool]:
    """'Mercedes C Class 2016' -> ('Mercedes-Benz', 'C Class', brand_table_hit).

    The year is stripped first, then the longest brand in the table wins, so "Land Rover Range Rover"
    keeps Land Rover as the make. When no table entry matches, the API's own `car_brand` is used and the
    third element is False (the caller counts those).
    """
    body = re.sub(r"\s+\d{4}\s*$", "", (display_name or "").strip())
    words = body.split()
    for size in (3, 2, 1):
        candidate = " ".join(words[:size]).lower()
        if candidate in BRAND_NAMES:
            return BRAND_NAMES[candidate], " ".join(words[size:]) or "Unknown", True
    return "", body or "Unknown", False


def province(raw: str | None) -> str:
    """'TP.HCM' / 'HaNoi' / 'Hà nội' -> the canonical province name."""
    key = re.sub(r"[\s._-]+", "", str(raw or "")).lower()
    if key in LOCATION_NAMES:
        return LOCATION_NAMES[key]
    return schema.normalize_province(raw)


def to_unified(raw: dict) -> dict:
    """One raw record -> the 21 unified columns (docs/unified_schema.md)."""
    brand, model, from_table = split_name(raw.get("model_year_name", ""))
    if not from_table:
        brand = BRAND_NAMES.get(str(raw.get("brand_raw") or "").lower(),
                               str(raw.get("brand_raw") or "Unknown").title())

    price = parsing.to_int(raw.get("price_vnd"))
    # The site's created_at is a bulk-import timestamp, not a publication date: 2,039 of the 2,124 cars
    # carry 2025-05-20 and 85 carry 2025-05-21. docs/unified_schema.md says to leave listing_date empty
    # when the source does not expose it, and a value that is identical for 96% of the catalogue would
    # only mislead the time-based analysis. It stays in the raw CSV for anyone who needs it.
    listing_date = ""

    record = dict.fromkeys(schema.SCHEMA_COLUMNS)
    record.update({
        "listing_id": f"VUCAR_{str(raw.get('url', '')).rstrip('/').rsplit('-', 1)[-1]}",
        "source_platform": PLATFORM,
        "brand": brand,
        "model": model,
        "sub_model_trim": "",              # the display name carries no grade
        "manufacture_year": parsing.to_int(raw.get("year")),
        "mileage_km": parsing.to_int(raw.get("odo_km")),
        "transmission": TRANSMISSION_NAMES.get(str(raw.get("transmission") or "").lower(),
                                               "Other" if raw.get("transmission") else "Unknown"),
        "fuel_type": FUEL_NAMES.get(str(raw.get("fuel_raw") or "").lower(), "Unknown"),
        "origin": "Unknown",               # the site never says CKD or CBU
        "body_type": BODY_NAMES.get(str(raw.get("car_type") or "").lower(), "Unknown"),
        "engine_capacity": None,           # not exposed
        "seats": None,                     # not exposed
        "location_province": province(raw.get("location")),
        "seller_type": "Unknown",
        "price_vnd": price,
        "source_url": raw.get("url"),
        "listing_date": listing_date,
        "scraped_at": raw.get("scraped_at_utc"),
        "raw_price_text": "",              # the action returns the number, not the display string
        "price_status": schema.price_status(price, ""),
    })
    return record


def load_raw(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def convert(raw_path: Path, out: str = "vucar") -> list[dict]:
    rows = [to_unified(raw) for raw in load_raw(raw_path)]
    rows = [row for row in rows if row["listing_id"] != "VUCAR_"]     # a broken url would produce this
    rows.sort(key=lambda row: str(row.get("listing_id")))
    path = storage.save_csv(rows, out, schema.SCHEMA_COLUMNS)
    log.info("%d cars -> %s", len(rows), path)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vucar.vn raw records -> 21-column contract CSV")
    parser.add_argument("--raw", default=str(config.DATA_PROCESSED / "vucar_raw.csv"))
    parser.add_argument("--out", default="vucar")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    raw_path = Path(args.raw)
    if not raw_path.exists():
        log.error("raw file not found: %s -> run 'python -m src.sources.vucar' first", raw_path)
        return 1
    convert(raw_path, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
