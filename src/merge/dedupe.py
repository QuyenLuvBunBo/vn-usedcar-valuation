"""Week 2: cross-source deduplication and duplicate_group_id generation.

Two steps, as planned:
  1. Duplicates inside one source: by listing_id / source_url (primary key) — handled at crawl time.
  2. Duplicates across sources: composite key (brand, model, sub_model_trim, manufacture_year,
     location_province, +/- mileage tolerance) plus fuzzy matching on model/trim.
"""

from __future__ import annotations

import hashlib


def composite_key(row: dict, mileage_tolerance: int = 5000) -> str:
    """Coarse grouping key used to find cross-source duplicate candidates.

    TODO (week 2): consider adding the normalized sub_model_trim and an age-dependent
    mileage tolerance instead of one global value.
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
    """Assign a duplicate_group_id to each record (same key combination = same vehicle)."""
    groups: dict[str, int] = {}
    for row in rows:
        key = composite_key(row)
        if key not in groups:
            groups[key] = len(groups) + 1
        row["duplicate_group_id"] = f"DUP_{groups[key]:06d}"
    return rows
