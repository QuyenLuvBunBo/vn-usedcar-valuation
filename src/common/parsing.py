"""Hàm parse dùng chung cho MỌI nguồn dữ liệu.

Không phụ thuộc nguồn cụ thể — các nhóm crawler (oto, bonbanh, chotot…) đều dùng lại:
bóc text từ HTML bằng lxml, đổi giá tiếng Việt sang VND, đổi số km / năm.
"""

from __future__ import annotations

import re

# Giá tiếng Việt: "550 triệu", "1 tỷ 250 tr", "1 tỉ 450 triệu", "1,2 tỷ"
PRICE_UNITS = {
    "triệu": 10**6, "triêu": 10**6, "tr": 10**6,
    "tỷ": 10**9, "tỉ": 10**9, "ty": 10**9, "ti": 10**9,
    "nghìn": 10**3, "ngàn": 10**3,
}
PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(triệu|triêu|tỷ|tỉ|nghìn|ngàn|tr|ty|ti)\b", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


# --------------------------------------------------------------- HTML/text
def clean_text(value: str | None) -> str:
    """Gộp khoảng trắng, bỏ khoảng trắng đặc biệt của HTML."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def first(node, xpath: str) -> str:
    """Lấy giá trị đầu tiên của xpath; trả '' nếu không có."""
    found = node.xpath(xpath)
    return clean_text(str(found[0])) if found else ""


def text_of(node) -> str:
    """Gộp toàn bộ text con của một element (đã chuẩn hoá)."""
    return clean_text(" ".join(node.itertext()))


# ------------------------------------------------------------------ số
def to_int(value) -> int | None:
    """Ép về int (SQLite trả về chuỗi); None nếu rỗng/không hợp lệ."""
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def to_float(value) -> float | None:
    """Ép về float; None nếu rỗng/không hợp lệ."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_vnd_price(text: str) -> int | None:
    """Đổi biểu thức giá tiếng Việt sang VND.

    Hỗ trợ: '335 triệu', '1 tỷ 045 triệu', '1 tỉ 450 triệu', '550 triệu', '1 tỷ 250 tr'.
    Trả None khi không có giá (ô rỗng, hoặc ghi 'Thỏa thuận' / 'Liên hệ' / 'trả góp').
    """
    if not text:
        return None
    total = 0.0
    for number, unit in PRICE_RE.findall(text):
        total += float(number.replace(",", ".")) * PRICE_UNITS[unit.lower()]
    if total <= 0:
        return None
    return int(round(total))


def parse_km_text(text: str) -> int | None:
    """Đổi '140.000 km' -> 140000."""
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else None


def parse_year_text(*texts: str) -> int | None:
    """Lấy năm 4 chữ số đầu tiên hợp lệ trong các chuỗi truyền vào."""
    for text in texts:
        match = YEAR_RE.search(text or "")
        if match:
            year = int(match.group(0))
            if 1980 <= year <= 2100:
                return year
    return None


# Tên tương thích ngược (code cũ gọi parse_price/parse_km/parse_year)
parse_price = parse_vnd_price
parse_km = parse_km_text
parse_year = parse_year_text
