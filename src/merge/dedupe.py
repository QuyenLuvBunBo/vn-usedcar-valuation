"""Tuần 2: lọc trùng đa nguồn + sinh duplicate_group_id.

Hai bước theo kế hoạch:
  1. Trùng trong cùng nguồn: theo listing_id / source_url (khoá chính) — đã xử lý khi cào.
  2. Trùng giữa các nguồn: composite key (brand, model, sub_model_trim, manufacture_year,
     location_province, +/- dung sai mileage_km) và fuzzy match cho model/trim.
"""

from __future__ import annotations

import hashlib


def composite_key(row: dict, mileage_tolerance: int = 5000) -> str:
    """Khoá gộp thô để tìm ứng viên trùng giữa các nguồn.

    TODO (Tuần 2): cân nhắc thêm sub_model_trim đã chuẩn hoá và dung sai km theo nhóm tuổi xe.
    """
    mileage = row.get("mileage_km")
    try:
        bucket = int(float(mileage) // mileage_tolerance) if mileage not in (None, "") else "na"
    except (TypeError, ValueError):
        bucket = "na"
    parts = [
        str(row.get("brand") or "").lower(),
        str(row.get("model") or "").lower(),
        str(row.get("manufacture_year") or ""),
        str(row.get("location_province") or "").lower(),
        str(bucket),
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


def duplicate_groups(rows: list[dict]) -> list[dict]:
    """Gán duplicate_group_id cho từng record (nhóm cùng tổ hợp khoá = cùng xe)."""
    groups: dict[str, int] = {}
    for row in rows:
        key = composite_key(row)
        if key not in groups:
            groups[key] = len(groups) + 1
        row["duplicate_group_id"] = f"DUP_{groups[key]:06d}"
    return rows
