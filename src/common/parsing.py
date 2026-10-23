"""Parsing helpers shared by EVERY data source.

Source-independent: the oto, bonbanh, chotot… crawlers all reuse these to extract text
from HTML with lxml, convert Vietnamese price expressions to VND, and read mileage/years.
"""

from __future__ import annotations

import re

# Vietnamese price expressions: "550 triệu", "1 tỷ 250 tr", "1 tỉ 450 triệu", "1,2 tỷ".
# Note: the sites themselves mix "tỷ"/"tỉ" and "nghìn"/"ngàn", so both spellings are accepted.
PRICE_UNITS = {
    "triệu": 10**6, "triêu": 10**6, "tr": 10**6,
    "tỷ": 10**9, "tỉ": 10**9, "ty": 10**9, "ti": 10**9,
    "nghìn": 10**3, "ngàn": 10**3,
}
PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(triệu|triêu|tỷ|tỉ|nghìn|ngàn|tr|ty|ti)\b", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


# --------------------------------------------------------------- HTML/text
def clean_text(value: str | None) -> str:
    """Collapse whitespace and drop non-breaking spaces from HTML."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def first(node, xpath: str) -> str:
    """Return the first value matching `xpath`, or '' when there is none."""
    found = node.xpath(xpath)
    return clean_text(str(found[0])) if found else ""


def text_of(node) -> str:
    """Return the concatenated, cleaned text of an element."""
    return clean_text(" ".join(node.itertext()))


# ------------------------------------------------------------------ numbers
def to_int(value) -> int | None:
    """Coerce to int (SQLite hands back strings); None when empty or invalid."""
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def to_float(value) -> float | None:
    """Coerce to float; None when empty or invalid."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_vnd_price(text: str) -> int | None:
    """Convert a Vietnamese price expression to VND.

    Supports: '335 triệu', '1 tỷ 045 triệu', '1 tỉ 450 triệu', '550 triệu', '1 tỷ 250 tr'.
    Returns None when there is no usable price (empty cell, or 'Thỏa thuận' / 'Liên hệ' /
    instalment wording instead of a full asking price).
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
    """Convert a Vietnamese odometer expression to km.

    The marketplaces print odometers in several shapes, not only '140.000 km':
        '140.000 km' / '106,985'  -> 140000 / 106985   (dot or comma thousands separator)
        '5 vạn'                   -> 50000             (vạn = 10.000)
        '1 vạn km'                -> 10000
        '34k km'                  -> 34000             (k = nghìn = 1.000)
        '5v8km'                   -> 58000             (5 vạn 8 nghìn)
    """
    text = (text or "").replace("\xa0", " ").strip().lower()
    if not text:
        return None

    # '5 vạn', '1,2 vạn', '5v8' — the shorthand "v" is only accepted in front of a digit/space/k.
    van = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:vạn|v(?=\d|\s|k|$))\s*(\d)?", text)
    if van:
        base = float(van.group(1).replace(",", "."))
        tail = int(van.group(2)) if van.group(2) else 0
        return int(round(base * 10_000)) + tail * 1_000

    # '34k km' — the k must be glued to the number, otherwise '140.000 km' would match the '0 k'.
    thousand = re.search(r"(\d+(?:[.,]\d+)?)k(?!m)\b", text)
    if thousand:
        return int(round(float(thousand.group(1).replace(",", ".")) * 1_000))

    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def parse_year_text(*texts: str) -> int | None:
    """Return the first plausible 4-digit year found in the given strings."""
    for text in texts:
        match = YEAR_RE.search(text or "")
        if match:
            year = int(match.group(0))
            if 1980 <= year <= 2100:
                return year
    return None


# Backwards-compatible aliases (older code calls parse_price / parse_km / parse_year)
parse_price = parse_vnd_price
parse_km = parse_km_text
parse_year = parse_year_text
