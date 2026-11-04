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
    """Exact-match grouping key used to find cross-source duplicate candidates.

    The mileage part is a *bucket*, not a distance band: two records less than one tolerance apart can
    still fall into neighbouring buckets (4,999 km and 7,498 km both fit a 5,000 km tolerance, yet their
    bucket numbers differ). The key is therefore a coarse candidate signal — see the module docstring.
    """
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


def duplicate_groups(rows: list[dict], capture_year: int | None = None,
                     fuzzy: bool = False) -> list[dict]:
    """Assign a duplicate_group_id to each record (one key combination = one candidate vehicle).

    Pass `fuzzy=True` to also merge the exact-key groups that `fuzzy_groups` considers one vehicle.

    Numbering follows the order the keys first appear, so it is stable for one input order and changes
    when the sources are concatenated differently. Persist the split together with the ids instead of
    rebuilding them later from a different order.
    """
    keys = [composite_key(row, capture_year=capture_year) for row in rows]
    if fuzzy:
        keys, _ = fuzzy_resolve(rows, keys, capture_year)

    groups: dict[str, int] = {}
    for row, key in zip(rows, keys):
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


# --------------------------------------------------------------- fuzzy matching
# Report §4.2 asks for "Composite Hashing + Fuzzy match". The composite key is exact, so it only joins
# records whose trim and odometer agree to the character. Two ads for the same car still miss each other
# when the seller retypes the grade ("1.5 G CVT" vs "1.5G CVT") or corrects the odometer. Fuzzy matching
# looks *inside* one exact-key candidate (brand+model+year+province) and merges the sub-groups that are
# plausibly the same vehicle.
#
# The asymmetry of the two errors decides the thresholds: merging two different cars is harmless for the
# split (they simply travel together), while leaving one car in two groups can put it in both train and
# test. So the rules lean towards merging, but only where the evidence is strong: same open market, same
# year, price within 5% and an odometer inside the tolerance band.
FUZZY_TRIM_THRESHOLD = 0.85    # difflib ratio on the normalized grade
FUZZY_PRICE_TOLERANCE = 0.05   # a repost usually moves the asking price a few percent


def _displacement(trim: str | None) -> str | None:
    """The engine size written inside a grade: '2.7 V 4X4 AT' -> '2.7' (None when the grade has none)."""
    match = re.search(r"(\d[.,]\d)", _norm(trim) or "")
    return match.group(1).replace(",", ".") if match else None


def trim_similarity(left: str | None, right: str | None) -> float:
    """How alike two grades are, after stripping punctuation ('1.5 G CVT' -> '15gcvt').

    An empty grade on either side scores 0: "no grade at all" is not evidence that two ads describe the
    same car, and treating it as a match is what turns one block into a single giant component.
    """
    from difflib import SequenceMatcher

    a, b = _trim_norm(left), _trim_norm(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _mileage(value) -> float | None:
    return _as_float(value)


def _price(value) -> float | None:
    return _as_float(value)


def _same_vehicle(left: dict, right: dict, capture_year: int | None) -> bool:
    """Same car posted twice? Only called inside one brand+model+year+province block.

    Every rule below must hold. The first draft accepted a missing grade or a missing odometer as "no
    evidence against", which merged 181 ads of one model into one group: a chain of weak matches is not
    evidence. The grade and the odometer are the two fields a seller cannot fake by accident, so both are
    required here.
    """
    if not _trim_norm(left.get("sub_model_trim")) or not _trim_norm(right.get("sub_model_trim")):
        return False

    # A grade often carries the engine and the seat count, and those two cannot be a spelling variant:
    # "2.7 V 4X4 AT" and "2.8L 4x4 AT" chain into one group otherwise, and they are different cars.
    displacement_left = _displacement(left.get("sub_model_trim"))
    displacement_right = _displacement(right.get("sub_model_trim"))
    if displacement_left and displacement_right and displacement_left != displacement_right:
        return False

    seats_left, seats_right = _as_int(left.get("seats")), _as_int(right.get("seats"))
    if seats_left and seats_right and seats_left != seats_right:
        return False

    km_left, km_right = _mileage(left.get("mileage_km")), _mileage(right.get("mileage_km"))
    if km_left is None or km_right is None:
        return False
    tolerance = tolerance_for(_as_int(left.get("manufacture_year")), capture_year)
    if abs(km_left - km_right) > tolerance:
        return False

    price_left, price_right = _price(left.get("price_vnd")), _price(right.get("price_vnd"))
    if price_left and price_right:
        high, low = max(price_left, price_right), min(price_left, price_right)
        if high > low * (1 + FUZZY_PRICE_TOLERANCE):
            return False

    return trim_similarity(left.get("sub_model_trim"),
                          right.get("sub_model_trim")) >= FUZZY_TRIM_THRESHOLD


def fuzzy_resolve(rows: list[dict], keys: list[str],
                  capture_year: int | None = None) -> tuple[list[str], dict[str, int]]:
    """Union the exact keys that fuzzy matching considers one vehicle.

    Returns (the representative key per row, the counts the report needs). The rows are not modified.
    """
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        root = key
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(key, key) != root:      # path compression
            parent[key], key = root, parent[key]
        return root

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for key in keys:
        parent.setdefault(key, key)

    blocks: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        blocks.setdefault(loose_key(row), []).append(index)

    compared = 0
    for members in blocks.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda i: (_price(rows[i].get("price_vnd")) or 0.0,
                                    str(rows[i].get("listing_id"))))
        for position, left_index in enumerate(members):
            left_price = _price(rows[left_index].get("price_vnd"))
            for right_index in members[position + 1:]:
                right_price = _price(rows[right_index].get("price_vnd"))
                if left_price and right_price and right_price > left_price * (1 + FUZZY_PRICE_TOLERANCE):
                    break                        # sorted by price: nothing further can match either
                compared += 1
                if keys[left_index] != keys[right_index] and \
                        _same_vehicle(rows[left_index], rows[right_index], capture_year):
                    union(keys[left_index], keys[right_index])

    resolved = [find(key) for key in keys]
    return resolved, {
        "records": len(rows),
        "exact_groups": len(parent),
        "groups": len({find(key) for key in parent}),
        "merged_groups": sum(1 for key in parent if find(key) != key),
        "pairs_compared": compared,
    }


def fuzzy_groups(rows: list[dict], capture_year: int | None = None) -> dict[str, int]:
    """The counts `fuzzy_resolve` produces, without touching the rows (for the audit print)."""
    keys = [composite_key(row, capture_year=capture_year) for row in rows]
    return fuzzy_resolve(rows, keys, capture_year)[1]


