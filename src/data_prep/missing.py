"""Week 2: missing-value audit, cardinality handling, group-wise imputation.

Report rule: every imputation statistic must be learned on the TRAIN partition only and then
applied unchanged to validation/test (no leakage). Never replace a missing value with 0.
"""

from __future__ import annotations

from collections import Counter

from ..common import schema


def measure_missing(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Measure the missing rate of every column (required for the Milestone 1 report)."""
    total = len(rows) or 1
    report: dict[str, dict[str, float]] = {}
    for col in schema.SCHEMA_COLUMNS:
        missing = sum(1 for r in rows if r.get(col) in (None, "", "Unknown"))
        report[col] = {"missing": missing, "rate": round(missing / total, 4)}
    return report


def cardinality(rows: list[dict], column: str) -> list[tuple[str, int]]:
    """Count occurrences of each value — used to spot rare models (<10 listings)."""
    return Counter(str(r.get(column)) for r in rows).most_common()


def collapse_rare(rows: list[dict], column: str, min_count: int = 10, label: str = "Other") -> list[dict]:
    """Collapse values occurring fewer than `min_count` times into `label` (week 2 plan)."""
    counts = Counter(str(r.get(column)) for r in rows)
    for row in rows:
        value = str(row.get(column))
        if counts[value] < min_count:
            row[column] = label
    return rows


# TODO (week 2 — Missing Data sub-team):
#   - fill_categorical_mode(train_rows, target_rows, column)   # mode within brand/model group
#   - fill_mileage_median(train_rows, target_rows)             # median within vehicle-age group
#   - fill_seats_from_mapping(...)                             # make/model/trim/year lookup
