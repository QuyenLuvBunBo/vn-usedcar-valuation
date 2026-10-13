"""Week 2: cross-source deduplication and duplicate_group_id generation.

Two steps, as planned:
  1. Duplicates inside one source: by listing_id / source_url (primary key) — already handled at crawl
     time (every table upserts on url, so a listing is captured exactly once).
  2. Duplicates across sources: composite key (brand, model, sub_model_trim, manufacture_year,
     location_province, mileage within a tolerance) plus fuzzy matching on model/trim.

The key is deliberately coarse, so a group means "candidate for the same vehicle", not proof. That is
why records are never merged or deleted here: they only carry a duplicate_group_id, and every step
downstream (review, train/val/test split) works on the group.

Reading the error direction, because it decides how tight the key should be:
  * too tight  -> different cars stay apart, the same car gets two groups (duplicate survives);
  * too loose  -> two different cars share a group (a real listing is treated as a duplicate).
The report prefers a coarse first pass plus review, so the tolerance only tightens for new cars, where
odometer readings are informative.
"""

from __future__ import annotations

import hashlib
import re

BASE_MILEAGE_TOLERANCE = 5_000  # km — readings closer than this count as the same odometer bucket
NEW_CAR_YEARS = 3               # age (years) at or below which the tolerance is halved
OLD_CAR_YEARS = 10              # age (years) at or above which the tolerance is doubled


def _norm(value) -> str:
    """Collapse whitespace and lowercase ('Hà Nội ' == 'hà  nội')."""
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _trim_norm(value) -> str:
    """'1.5 G CVT', '1.5G' and '1,5 g cvt' are the same grade: keep only letters and digits."""
    return re.sub(r"[^0-9a-z]", "", str(value or "").lower())


def _as_int(value) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _as_float(value) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def tolerance_for(manufacture_year: int | None, capture_year: int | None = None) -> int:
    """Odometer tolerance in km for the grouping key — tighter for new cars.

    A 2022 car with 30,000 km and another with 32,000 km are most likely different vehicles, while on
    a 2008 car a 10,000 km gap still says little. Unknown age -> the base tolerance.
    """
    if not manufacture_year or not capture_year:
        return BASE_MILEAGE_TOLERANCE
    age = capture_year - manufacture_year
    if age <= NEW_CAR_YEARS:
        return BASE_MILEAGE_TOLERANCE // 2
    if age >= OLD_CAR_YEARS:
        return BASE_MILEAGE_TOLERANCE * 2
    return BASE_MILEAGE_TOLERANCE


def _bucket(mileage: float | None, step: int) -> str:
    """Round to the nearest bucket (not floor!), so 4,999 km and 5,000 km land together."""
    return "na" if mileage is None else str(int(round(mileage / step)))


def composite_key(row: dict, tolerance: int | None = None, capture_year: int | None = None) -> str:
    """Exact-match grouping key used to find cross-source duplicate candidates."""
    year = _as_int(row.get("manufacture_year"))
    step = tolerance or tolerance_for(year, capture_year)
    parts = [
        _norm(row.get("brand")),
        _norm(row.get("model")),
        _trim_norm(row.get("sub_model_trim")),
        str(year or ""),
        _norm(row.get("location_province")),
        _bucket(_as_float(row.get("mileage_km")), step),
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


def loose_key(row: dict) -> str:
    """Coarser key (no trim, no mileage): shows what the exact key alone would miss."""
    parts = [
        _norm(row.get("brand")),
        _norm(row.get("model")),
        str(_as_int(row.get("manufacture_year")) or ""),
        _norm(row.get("location_province")),
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


def duplicate_groups(rows: list[dict], capture_year: int | None = None) -> list[dict]:
    """Assign a duplicate_group_id to each record (one key combination = one candidate vehicle)."""
    groups: dict[str, int] = {}
    for row in rows:
        key = composite_key(row, capture_year=capture_year)
        if key not in groups:
            groups[key] = len(groups) + 1
        row["duplicate_group_id"] = f"DUP_{groups[key]:06d}"
    return rows


def group_stats(rows: list[dict]) -> dict[str, int]:
    """Counts for the report: groups, rows that share a group, size of the biggest group."""
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("duplicate_group_id"))
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return {"groups": 0, "rows": 0, "duplicate_rows": 0, "largest_group": 0, "groups_over_one": 0}
    return {
        "groups": len(counts),
        "rows": sum(counts.values()),
        "duplicate_rows": sum(n for n in counts.values() if n > 1),
        "groups_over_one": sum(1 for n in counts.values() if n > 1),
        "largest_group": max(counts.values()),
    }


def repost_stats(rows: list[dict], capture_year: int | None = None) -> dict[str, int]:
    """Stronger evidence than the coarse key: identical vehicle data *and* identical asking price.

    Several 2015 CR-Vs in one province are normal inventory; the same asking price on top of the same
    mileage bucket is what a renewed ad looks like (the report's "renewed/reposted under a new id").
    """
    keys: dict[str, int] = {}
    for row in rows:
        key = f"{composite_key(row, capture_year=capture_year)}|{_as_int(row.get('price_vnd'))}"
        keys[key] = keys.get(key, 0) + 1
    return {
        "groups": sum(1 for count in keys.values() if count > 1),
        "rows": sum(count for count in keys.values() if count > 1),
    }


def top_groups(rows: list[dict], limit: int = 5) -> list[tuple[int, str]]:
    """The biggest candidate groups, with a label to eyeball them ('Toyota Fortuner 2019 Hà Nội')."""
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for row in rows:
        key = str(row.get("duplicate_group_id"))
        counts[key] = counts.get(key, 0) + 1
        if key not in labels:
            labels[key] = " ".join(str(row.get(field) or "?") for field in
                                   ("brand", "model", "manufacture_year", "location_province"))
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [(count, labels[key]) for key, count in ranked if count > 1]

