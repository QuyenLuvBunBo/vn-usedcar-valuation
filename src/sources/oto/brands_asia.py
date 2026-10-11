"""Nhóm xe phổ thông châu Á — phần việc của Lê Thế Quyền.

6 hãng này chiếm phần lớn tồn kho xe cũ trên oto.com.vn (≈2.700/≈5.000 tin).
Chạy:  python -m src.sources.oto --group asia
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
