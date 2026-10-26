"""THE TEAM'S DATA CONTRACT: the unified schema of 16 attributes + 5 metadata columns.

Every source (oto.com.vn, bonbanh, chotot, carmudi, carpla, anycar) MUST export exactly these
21 columns, with these names and these normalized value spellings:

    - transmission : Automatic / Manual / Other
    - fuel_type    : Gasoline / Diesel / Hybrid / Electric / Unknown
    - origin       : CKD (locally assembled) / CBU (imported) / Unknown
    - body_type    : Sedan / SUV / Crossover / MPV / Hatchback / Pickup / Van / Truck / ...
    - seller_type  : Dealership/Salon / Private Individual / Unknown

Only change this file with team agreement — it is the single merge-conflict hotspot.
Validate your CSV before opening a PR:  python -m tools.validate_source_csv <file.csv>
"""

from __future__ import annotations

import re

# --- 16 attributes ---
ATTRIBUTE_COLUMNS = [
    "listing_id", "source_platform", "brand", "model", "sub_model_trim",
    "manufacture_year", "mileage_km", "transmission", "fuel_type", "origin",
    "body_type", "engine_capacity", "seats", "location_province", "seller_type",
    "price_vnd",
]
# --- 5 metadata columns ---
METADATA_COLUMNS = ["source_url", "listing_date", "scraped_at", "raw_price_text", "price_status"]

SCHEMA_COLUMNS = ATTRIBUTE_COLUMNS + METADATA_COLUMNS
NUMERIC_COLUMNS = ("manufacture_year", "mileage_km", "price_vnd", "engine_capacity", "seats")

# Vietnamese source labels -> normalized English labels
TRANSMISSION_MAP = {"số tự động": "Automatic", "số sàn": "Manual", "số hỗn hợp": "Other"}
TRANSMISSION_VALUES = {"Automatic", "Manual", "Other", "Unknown"}

FUEL_MAP = {
    "máy xăng": "Gasoline", "xăng": "Gasoline", "máy dầu": "Diesel", "dầu": "Diesel",
    "hybrid": "Hybrid", "máy điện": "Electric", "điện": "Electric",
    # the site's own "other" label (a few archive pages) carries no fuel information
    "loại khác": "Unknown", "khác": "Unknown", "other": "Unknown",
}
FUEL_VALUES = {"Gasoline", "Diesel", "Hybrid", "Electric", "Unknown"}

ORIGIN_MAP = {"trong nước": "CKD", "nhập khẩu": "CBU", "lắp ráp trong nước": "CKD"}
ORIGIN_VALUES = {"CKD", "CBU", "Unknown"}

BODY_MAP = {
    "bán tải": "Pickup", "van/minivan": "Van", "xe tải": "Truck", "sport car": "Sports",
    "mui trần": "Convertible", "crossover": "Crossover",
}
BODY_VALUES = {"Sedan", "SUV", "Crossover", "MPV", "Hatchback", "Pickup", "Van",
               "Truck", "Coupe", "Convertible", "Sports", "Wagon", "Minibus",
               "Other", "Unknown"}

SELLER_VALUES = {"Dealership/Salon", "Private Individual", "Unknown"}
PRICE_STATUS_VALUES = {"full", "negotiable", "instalment", "invalid"}

PROVINCE_MAP = {
    "tp.hcm": "TP. Hồ Chí Minh", "hcm": "TP. Hồ Chí Minh", "tphcm": "TP. Hồ Chí Minh",
    "sài gòn": "TP. Hồ Chí Minh", "hà nội": "Hà Nội", "hn": "Hà Nội",
    "đà nẵng": "Đà Nẵng", "hải phòng": "Hải Phòng", "cần thơ": "Cần Thơ",
}
CITY_CODE_MAP = {"SG": "TP. Hồ Chí Minh", "HN": "Hà Nội", "DN": "Đà Nẵng"}
BIG_CITY_NEEDLES = (
    ("hcm", "TP. Hồ Chí Minh"), ("hồ chí minh", "TP. Hồ Chí Minh"),
    ("sài gòn", "TP. Hồ Chí Minh"), ("hà nội", "Hà Nội"), ("đà nẵng", "Đà Nẵng"),
    ("hải phòng", "Hải Phòng"), ("cần thơ", "Cần Thơ"),
)
# Official province names that contain a dash: the "district - province" rule below must skip them.
DASH_PROVINCES = {"bà rịa - vũng tàu", "bà rịa-vũng tàu", "thừa thiên - huế", "thừa thiên-huế"}

NEGOTIABLE = ("thỏa thuận", "thương lượng", "liên hệ", "tl")
INSTALMENT = ("trả góp", "góp", "/tháng", "mỗi tháng")


def _norm(value: str | None) -> str:
    """Normalize for matching: collapse whitespace and lowercase."""
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip().lower()


def map_value(value: str | None, mapping: dict[str, str], unknown: str = "Unknown") -> str:
    """Map an original label to its normalized form; keep the original / Unknown if unmapped."""
    key = _norm(value)
    if not key:
        return unknown
    if key in mapping:
        return mapping[key]
    compact = key.replace(" ", "")
    if compact in mapping:
        return mapping[compact]
    return value.strip() if value else unknown


def normalize_transmission(raw: str | None) -> str:
    """'Số tự động' -> Automatic."""
    return map_value(raw, TRANSMISSION_MAP)


def normalize_fuel(raw: str | None) -> str:
    """'Máy xăng' -> Gasoline."""
    return map_value(raw, FUEL_MAP)


def normalize_origin(raw: str | None) -> str:
    """'Trong nước' -> CKD, 'Nhập khẩu' -> CBU."""
    return map_value(raw, ORIGIN_MAP)


def normalize_body(raw: str | None) -> str:
    """'Bán tải' -> Pickup."""
    return map_value(raw, BODY_MAP)


def normalize_province(raw: str | None, city_code: str = "") -> str:
    """Normalize a province/city; e.g. 'Thủ Đức - Tp.HCM' -> 'TP. Hồ Chí Minh'."""
    key = _norm(raw)
    if key in PROVINCE_MAP:
        return PROVINCE_MAP[key]
    stripped = key.replace("tp.", "").replace("tp ", "").replace(" ", "")
    if stripped and stripped in PROVINCE_MAP:
        return PROVINCE_MAP[stripped]
    for needle, name in BIG_CITY_NEEDLES:
        if needle in key:
            return name
    # Listing cards print the district first ("Khoái Châu - Hưng Yên", "Đồng Xoài - Bình Phước").
    # This column is the province: keeping the district splits one market into 20+ values and makes the
    # dedupe key needlessly fine. Provinces whose real name has a dash are excluded above.
    if " - " in key and key not in DASH_PROVINCES:
        # take the tail from the raw value so the province keeps its original casing ("Hưng Yên")
        tail = re.split(r"\s+-\s+", str(raw).strip())[-1]
        if tail and _norm(tail) != key:
            return normalize_province(tail, city_code)
    if raw and raw.strip():
        return raw.strip()
    return CITY_CODE_MAP.get((city_code or "").upper(), "Unknown")


def price_status(price_vnd: int | None, raw_price_text: str | None) -> str:
    """Classify the price expression: full / negotiable / instalment / invalid."""
    text = _norm(raw_price_text)
    if any(k in text for k in INSTALMENT):
        return "instalment"
    if any(k in text for k in NEGOTIABLE):
        return "negotiable"
    return "full" if price_vnd else "invalid"


def seller_type_from_subdomain(subdomain_url: str | None) -> str:
    """A source that gives showrooms their own subdomain -> Dealership/Salon, otherwise private."""
    return "Dealership/Salon" if (subdomain_url or "").strip() else "Private Individual"
