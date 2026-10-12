"""Asian mainstream brands — owned by Lê Thế Quyền.

These six brands make up most of the used-car inventory on oto.com.vn (≈2,700 of ≈5,000 listings).
Run:  python -m src.sources.oto --group asia
"""

from __future__ import annotations

BRANDS: dict[str, str] = {
    "toyota": "Toyota",
    "hyundai": "Hyundai",
    "kia": "Kia",
    "mazda": "Mazda",
    "honda": "Honda",
    "mitsubishi": "Mitsubishi",
}
