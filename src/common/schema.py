"""HỢP ĐỒNG DỮ LIỆU dùng chung cho cả nhóm: Unified Schema 16 thuộc tính + 5 metadata.

Mọi nguồn (oto.com.vn, bonbanh, chotot, carmudi, carpla, anycar) PHẢI xuất ra đúng
21 cột dưới đây, cùng tên và cùng cách viết giá trị:

    - truyền động  : Automatic / Manual / Other
    - nhiên liệu   : Gasoline / Diesel / Hybrid / Electric / Unknown
    - xuất xứ      : CKD (lắp ráp trong nước) / CBU (nhập khẩu) / Unknown
    - loại xe      : Sedan / SUV / Crossover / MPV / Hatchback / Pickup / Van / Truck / ...
    - người bán    : Dealership/Salon / Private Individual / Unknown

Chỉ sửa file này khi cả nhóm đồng ý (đây là điểm xung đột duy nhất khi merge).
Kiểm tra file CSV của bạn trước khi PR:  python -m tools.validate_source_csv <file.csv>
"""

from __future__ import annotations

import re

# --- 16 thuộc tính ---
ATTRIBUTE_COLUMNS = [
    "listing_id", "source_platform", "brand", "model", "sub_model_trim",
    "manufacture_year", "mileage_km", "transmission", "fuel_type", "origin",
    "body_type", "engine_capacity", "seats", "location_province", "seller_type",
    "price_vnd",
]
# --- 5 metadata ---
METADATA_COLUMNS = ["source_url", "listing_date", "scraped_at", "raw_price_text", "price_status"]

SCHEMA_COLUMNS = ATTRIBUTE_COLUMNS + METADATA_COLUMNS
NUMERIC_COLUMNS = ("manufacture_year", "mileage_km", "price_vnd", "engine_capacity", "seats")

TRANSMISSION_MAP = {"số tự động": "Automatic", "số sàn": "Manual", "số hỗn hợp": "Other"}
TRANSMISSION_VALUES = {"Automatic", "Manual", "Other", "Unknown"}

FUEL_MAP = {
    "máy xăng": "Gasoline", "xăng": "Gasoline", "máy dầu": "Diesel", "dầu": "Diesel",
    "hybrid": "Hybrid", "máy điện": "Electric", "điện": "Electric",
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

NEGOTIABLE = ("thỏa thuận", "thương lượng", "liên hệ", "tl")
INSTALMENT = ("trả góp", "góp", "/tháng", "mỗi tháng")


def _norm(value: str | None) -> str:
    """Chuẩn hoá để so khớp: gộp khoảng trắng, về chữ thường."""
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip().lower()


def map_value(value: str | None, mapping: dict[str, str], unknown: str = "Unknown") -> str:
    """Ánh xạ nhãn gốc sang nhãn chuẩn; không khớp -> giữ nhãn gốc / Unknown."""
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
    """Chuẩn hoá tỉnh/thành; gom 'Thủ Đức - Tp.HCM' -> 'TP. Hồ Chí Minh'."""
    key = _norm(raw)
    if key in PROVINCE_MAP:
        return PROVINCE_MAP[key]
    stripped = key.replace("tp.", "").replace("tp ", "").replace(" ", "")
    if stripped and stripped in PROVINCE_MAP:
        return PROVINCE_MAP[stripped]
    for needle, name in BIG_CITY_NEEDLES:
        if needle in key:
            return name
    if raw and raw.strip():
        return raw.strip()
    return CITY_CODE_MAP.get((city_code or "").upper(), "Unknown")


def price_status(price_vnd: int | None, raw_price_text: str | None) -> str:
    """full / negotiable / instalment / invalid."""
    text = _norm(raw_price_text)
    if any(k in text for k in INSTALMENT):
        return "instalment"
    if any(k in text for k in NEGOTIABLE):
        return "negotiable"
    return "full" if price_vnd else "invalid"


def seller_type_from_subdomain(subdomain_url: str | None) -> str:
    """Nguồn có subdomain riêng cho showroom -> Dealership/Salon, ngược lại cá nhân."""
    return "Dealership/Salon" if (subdomain_url or "").strip() else "Private Individual"
