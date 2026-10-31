"""Week 2: missing-value audit, cardinality handling, group-wise imputation.

Report rule: every imputation statistic must be learned on the TRAIN partition only and then
applied unchanged to validation/test (no leakage). Never replace a missing value with 0.

Two different jobs live in this module and the report must not confuse them:

  * the **audit** (`measure_missing`, `missing_by_source`, `cardinality`) answers "what is absent,
    and how often" — that is the Milestone 1 table;
  * the **imputation policy** (`fit_*` / `fill_*`) answers "what do we do about it".

Every `fit_*` function is handed `train_rows` only; the matching `fill_*` function is handed the rows
it may change. Calling them in that order is what keeps the statistics leakage-free, and each filled
cell is written into an `imputed` column, so a later analysis can drop imputed values or feed the
missingness itself to the model (report §4.4 asks for an indicator, not a silent fill).
`Unknown` counts as missing for the audit and may be replaced — §4.4 allows hierarchical mode
imputation, but only with the flag kept.

Run:
    python -m src.data_prep.missing                  # audit of train/val/test
    python -m src.data_prep.missing --per-source     # + missing rate per platform
    python -m src.data_prep.missing --fill           # also write *_imputed.csv
    python -m src.data_prep.missing --input-suffix _cohort --fill   # chain after normalize
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from ..common import config, schema, storage

log = logging.getLogger("missing")

TRAIN, VAL, TEST = "train", "val", "test"
SPLITS = (TRAIN, VAL, TEST)
IMPUTED_COLUMN = "imputed"
MODEL_GROUP_COLUMN = "model_group"
UNKNOWN = "Unknown"
# Spellings that mean "no value" once a CSV has been through pandas.
_BLANKS = {"", "none", "nan", "null", "n/a"}

MIN_GROUP = 5            # a group smaller than this is not evidence; fall back to the next level
AGE_BUCKET_YEARS = 5     # the mileage median is learned per 5-year age band
# Engine displacement inside a trim badge: "2.5Q" -> 2.5, "1.5G CVT" -> 1.5, "2.0L 4x4" -> 2.0.
# The decimal point is required, so "RX 300", "V6" and "4x4" never match.
ENGINE_RE = re.compile(r"(?<![\d.,])([1-6][.,]\d)(?![\d.,])")


# ------------------------------------------------------------------- reading
def _blank(value, unknown_is_missing: bool = True) -> bool:
    """True for '', None, NaN spellings and (by default) the literal `Unknown`."""
    text = "" if value is None else str(value).strip()
    if text.lower() in _BLANKS:
        return True
    return unknown_is_missing and text.casefold() == UNKNOWN.casefold()


def _clean(value) -> str | None:
    """The value as text, or None when it carries no information."""
    return None if _blank(value) else str(value).strip()


def _num(value, cast):
    """Cast a CSV cell to int/float, returning None when it is empty or not a number."""
    if _blank(value, unknown_is_missing=False):
        return None
    try:
        return cast(float(str(value).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _group_key(row: dict, columns: tuple[str, ...]) -> str:
    """Lower-cased group key ('toyota|camry') — the level a statistic is learned at."""
    return "|".join(str(row.get(c) or "").strip().casefold() for c in columns)


def _mode(values) -> str | None:
    """Most frequent non-empty value, or None when there is nothing to count."""
    counter = Counter(v for v in values if str(v).strip())
    return counter.most_common(1)[0][0] if counter else None


def capture_year(rows: list[dict]) -> int:
    """Latest capture year in the data (from scraped_at) — vehicle age is measured against it."""
    from datetime import datetime

    years = [int(str(row.get("scraped_at") or "")[:4]) for row in rows
             if str(row.get("scraped_at") or "")[:4].isdigit()]
    return max(years) if years else datetime.now().year


def load_split(path: Path) -> tuple[list[dict], list[str]]:
    """Read one partition back, keeping every value as a string (no dtype surprises)."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        return list(reader), fieldnames


# --------------------------------------------------------------------- audit
def measure_missing(rows: list[dict],
                    columns: list[str] | None = None) -> dict[str, dict[str, float]]:
    """Measure the missing rate of every column (required for the Milestone 1 report)."""
    total = len(rows) or 1
    report: dict[str, dict[str, float]] = {}
    for col in (columns or schema.SCHEMA_COLUMNS):
        missing = sum(1 for r in rows if _blank(r.get(col)))
        report[col] = {"missing": missing, "rate": round(missing / total, 4)}
    return report


def missing_by_source(rows: list[dict],
                      columns: list[str] | None = None) -> dict[str, dict[str, float]]:
    """Missing rate per platform, because coverage differs source by source.

    The report has to say *where* a column is thin (`engine_capacity` may be fine on oto.com.vn and
    absent on a whole marketplace), and one average over the merged data hides that.
    """
    by_source: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_source[str(row.get("source_platform") or UNKNOWN)].append(row)
    return {source: {col: stats["rate"] for col, stats in measure_missing(part, columns).items()}
            for source, part in sorted(by_source.items())}


def cardinality(rows: list[dict], column: str) -> list[tuple[str, int]]:
    """Count occurrences of each value — used to spot rare models (<10 listings)."""
    return Counter(str(r.get(column)) for r in rows).most_common()


def collapse_rare(rows: list[dict], column: str, min_count: int = 10, label: str = "Other") -> list[dict]:
    """Collapse values occurring fewer than `min_count` times into `label` (week 2 plan).

    Fitted on `rows` as given: call it with the train partition only and reuse `rare_values()` on
    val/test, otherwise a model seen 4 times in train and 4 times in test survives both.
    """
    counts = Counter(str(row.get(column)) for row in rows)
    for row in rows:
        value = str(row.get(column))
        if counts[value] < min_count:
            row[column] = label
    return rows


def rare_values(rows: list[dict], column: str, min_count: int = 10) -> set[str]:
    """The values `collapse_rare` would collapse — fit this on train, then apply it elsewhere."""
    counts = Counter(str(row.get(column)) for row in rows)
    return {value for value, count in counts.items() if count < min_count}


def apply_rare(rows: list[dict], column: str, rare: set[str], label: str = "Other") -> int:
    """Collapse a *fitted* rare-value set (the leakage-free half of `collapse_rare`)."""
    filled = 0
    for row in rows:
        if str(row.get(column)) in rare:
            row[column] = label
            filled += 1
    return filled


def group_rare_models(rows: list[dict], rare: set[str], column: str = "model",
                      label: str = "Other") -> int:
    """Add `model_group`: the model, or `Other` when the train partition saw it < N times.

    The week-2 plan asks to "collapse models with fewer than 10 listings into Other". It is written
    as a **new column** rather than by overwriting `model`, because the raw model is still the best
    key for a target encoding and for the duplicate key; collapsing the source column would throw
    that away for 6,000 rows. Week 3 one-hot encodes `model_group` and may encode `brand|model`.
    """
    collapsed = 0
    for row in rows:
        value = str(row.get(column) or "")
        if not value or value in rare:
            row[MODEL_GROUP_COLUMN] = label
            collapsed += 1
        else:
            row[MODEL_GROUP_COLUMN] = value
    return collapsed


# --------------------------------------------------------------- imputation
def _mark(row: dict, column: str) -> None:
    """Record that `column` was imputed in this row (report §4.4: keep the indicator)."""
    existing = [name for name in str(row.get(IMPUTED_COLUMN) or "").split(";") if name]
    if column not in existing:
        existing.append(column)
    row[IMPUTED_COLUMN] = ";".join(existing)


def fit_categorical(train_rows: list[dict], column: str,
                    group_cols: tuple[str, ...] = ("brand", "model"),
                    min_group: int = MIN_GROUP) -> dict:
    """Learn a hierarchical mode for `column`: brand+model -> brand -> global.

    §4.4 asks for modes "estimated from the training partition only", so the returned dictionary is
    the whole statistic: nothing is filled here and no target row is looked at.
    """
    observed = [_clean(row.get(column)) for row in train_rows]
    fitted: dict = {"column": column, "levels": [], "global": _mode(v for v in observed if v)}

    for size in range(len(group_cols), 0, -1):        # most specific level first
        columns = group_cols[:size]
        counts: dict[str, Counter] = defaultdict(Counter)
        for row in train_rows:
            value = _clean(row.get(column))
            if value:
                counts[_group_key(row, columns)][value] += 1
        level = {key: counter.most_common(1)[0][0]
                 for key, counter in counts.items() if sum(counter.values()) >= min_group}
        fitted["levels"].append({"cols": list(columns), "map": level})
    return fitted


def fill_categorical(rows: list[dict], fitted: dict) -> int:
    """Fill blanks (and `Unknown`) of one column from a fitted hierarchy; returns the cells filled."""
    column = fitted["column"]
    filled = 0
    for row in rows:
        if not _blank(row.get(column)):
            continue
        value = fitted["global"]
        for level in fitted["levels"]:
            candidate = level["map"].get(_group_key(row, tuple(level["cols"])))
            if candidate:
                value = candidate
                break
        if value:
            row[column] = value
            _mark(row, column)
            filled += 1
    return filled


def fit_median_by_age(train_rows: list[dict], column: str = "mileage_km",
                      year_col: str = "manufacture_year",
                      bucket: int = AGE_BUCKET_YEARS,
                      min_group: int = MIN_GROUP,
                      reference_year: int | None = None) -> dict:
    """Learn a median of `column` per vehicle-age band (`column` = mileage, engine, ...).

    An odometer is a function of age far more than of brand: a 12-year-old car and a 2-year-old car
    must not share one median. A band thinner than `min_group` falls back to the global median.
    """
    reference = reference_year or capture_year(train_rows)
    buckets: dict[int, list[float]] = defaultdict(list)
    everything: list[float] = []
    for row in train_rows:
        value = _num(row.get(column), float)
        if value is None:
            continue
        everything.append(value)
        year = _num(row.get(year_col), int)
        if year is None:
            continue
        buckets[max(0, reference - year) // bucket].append(value)
    return {
        "column": column,
        "unit": f"{bucket}-year age band",
        "buckets": {index: median(values) for index, values in buckets.items()
                    if len(values) >= min_group},
        "global": median(everything) if everything else None,
    }


def fill_median_by_age(rows: list[dict], fitted: dict,
                       year_col: str = "manufacture_year",
                       bucket: int = AGE_BUCKET_YEARS,
                       reference_year: int | None = None,
                       cast=float) -> int:
    """Fill a blank numeric column from the fitted per-age-band medians (never with 0)."""
    column = fitted["column"]
    reference = reference_year or capture_year(rows)
    filled = 0
    for row in rows:
        if _num(row.get(column), float) is not None:
            continue
        year = _num(row.get(year_col), int)
        value = None
        if year is not None:
            value = fitted["buckets"].get(max(0, reference - year) // bucket)
        if value is None:
            value = fitted["global"]
        if value is None:
            continue
        row[column] = cast(value)
        _mark(row, column)
        filled += 1
    return filled


def fit_median_by_group(train_rows: list[dict], column: str,
                        group_cols: tuple[str, ...] = ("brand", "model"),
                        min_group: int = MIN_GROUP) -> dict:
    """Learn a median per brand+model, for a column whose value is a property of the car.

    An engine displacement is: a Vios is 1.5 whatever its age. That makes brand+model a better level
    than the age band for `engine_capacity`, while the odometer stays age-driven (`fit_median_by_age`).
    """
    groups: dict[str, list[float]] = defaultdict(list)
    everything: list[float] = []
    for row in train_rows:
        value = _num(row.get(column), float)
        if value is None:
            continue
        everything.append(value)
        groups[_group_key(row, group_cols)].append(value)
    return {
        "column": column,
        "group_cols": list(group_cols),
        "groups": {key: median(values) for key, values in groups.items()
                   if len(values) >= min_group},
        "global": median(everything) if everything else None,
    }


def fill_median_by_group(rows: list[dict], fitted: dict, cast=float) -> int:
    """Fill a blank numeric column from the fitted brand+model medians."""
    column = fitted["column"]
    columns = tuple(fitted["group_cols"])
    filled = 0
    for row in rows:
        if _num(row.get(column), float) is not None:
            continue
        value = fitted["groups"].get(_group_key(row, columns), fitted["global"])
        if value is None:
            continue
        row[column] = cast(value)
        _mark(row, column)
        filled += 1
    return filled


def fill_seats_from_mapping(rows: list[dict], fitted: dict | None = None,
                            train_rows: list[dict] | None = None,
                            min_group: int = MIN_GROUP) -> tuple[dict, int]:
    """Fill `seats` from a brand+model (then brand) mapping learned on train.

    §4.4: "use a verified make/model/trim/year mapping where available. Otherwise retain
    missingness" — so a group thinner than `min_group` is left empty on purpose.
    """
    if fitted is None:
        fitted = fit_categorical(train_rows or [], "seats", ("brand", "model"), min_group)
    filled = 0
    for row in rows:
        if _num(row.get("seats"), int) is not None:
            continue
        value = None
        for level in fitted["levels"]:
            candidate = level["map"].get(_group_key(row, tuple(level["cols"])))
            if candidate:
                value = candidate
                break
        seats = _num(value or fitted.get("global"), int)
        if seats is None:
            continue
        row["seats"] = seats
        _mark(row, "seats")
        filled += 1
    return fitted, filled


def fill_engine_from_trim(rows: list[dict], trim_col: str = "sub_model_trim") -> int:
    """Read the engine displacement out of the trim badge: '2.5Q' -> 2.5.

    This is a *parse*, not a guess, so it needs no training data — but it is still recorded in the
    `imputed` column, because the value did not come from the site's engine field. Battery-electric
    vehicles legitimately have no displacement and are left empty.
    """
    filled = 0
    for row in rows:
        if _num(row.get("engine_capacity"), float) is not None:
            continue
        match = ENGINE_RE.search(str(row.get(trim_col) or ""))
        if not match:
            continue
        row["engine_capacity"] = float(match.group(1).replace(",", "."))
        _mark(row, "engine_capacity")
        filled += 1
    return filled


def impute_parts(parts: dict[str, list[dict]], min_group: int = MIN_GROUP,
                 rare_min: int = 0) -> dict[str, int]:
    """Fit every statistic on train, then fill train/val/test with those same statistics.

    The order is the whole point of the module: nothing below is learned from val or test.
    """
    train_rows = parts[TRAIN]
    reference = capture_year(train_rows)
    filled: dict[str, int] = {}

    for name in SPLITS:
        for row in parts[name]:
            row.setdefault(IMPUTED_COLUMN, "")

    # 1. trim -> engine displacement (a deterministic parse, no statistic involved)
    for name in SPLITS:
        filled[f"engine_capacity ({name})"] = fill_engine_from_trim(parts[name])

    # 2. categorical: mode within brand+model, then brand, then global
    for column in ("body_type", "transmission", "fuel_type", "origin", "seller_type"):
        fitted = fit_categorical(train_rows, column, ("brand", "model"), min_group)
        for name in SPLITS:
            filled[f"{column} ({name})"] = fill_categorical(parts[name], fitted)

    seats_map = fit_categorical(train_rows, "seats", ("brand", "model"), min_group)
    for name in SPLITS:
        _, count = fill_seats_from_mapping(parts[name], seats_map)
        filled[f"seats ({name})"] = count

    # 3. numeric: the odometer is age-driven, the displacement is a property of the model
    age_fit = fit_median_by_age(train_rows, "mileage_km", reference_year=reference,
                                min_group=min_group)
    for name in SPLITS:
        filled[f"mileage_km ({name})"] = fill_median_by_age(
            parts[name], age_fit, reference_year=reference)

    engine_by_model = fit_median_by_group(train_rows, "engine_capacity", min_group=min_group)
    engine_by_age = fit_median_by_age(train_rows, "engine_capacity", reference_year=reference,
                                      min_group=min_group)
    for name in SPLITS:
        count = fill_median_by_group(parts[name], engine_by_model)
        count += fill_median_by_age(parts[name], engine_by_age, reference_year=reference)
        filled[f"engine_capacity ({name})"] = count

    # 4. cardinality: a model the train partition saw < rare_min times joins `Other`
    #    (a separate column — see group_rare_models — so the raw model stays usable)
    if rare_min > 0:
        rare = rare_values(train_rows, "model", min_count=rare_min)
        for name in SPLITS:
            filled[f"model->Other ({name})"] = group_rare_models(parts[name], rare)
    return filled


# ----------------------------------------------------------------------- CLI
def _print_table(title: str, report: dict[str, dict[str, float]], total: int) -> None:
    print(f"\n{title} ({total:,} rows)")
    print(f"  {'column':20s} {'missing':>9s} {'rate':>7s}")
    for column, stats in report.items():
        if stats["missing"] == 0:
            continue
        print(f"  {column:20s} {stats['missing']:>9,} {stats['rate'] * 100:>6.1f}%")


def _print_per_source(rows: list[dict], columns: list[str]) -> None:
    """The Milestone 1 table: how thin each column is, platform by platform."""
    per_source = missing_by_source(rows, columns)
    if not per_source:
        return
    print("\nMissing rate by platform (%) — the Milestone 1 table:")
    print(f"  {'column':20s}" + "".join(f"{source[:14]:>15s}" for source in per_source))
    for column in columns:
        cells = "".join(f"{stats[column] * 100:>14.1f}%" for stats in per_source.values())
        print(f"  {column:20s}{cells}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit missing values and impute them from TRAIN-only statistics")
    parser.add_argument("--split-dir", default=str(config.DATA_MASTER))
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="all",
                        help="which partition to audit")
    parser.add_argument("--input-suffix", default="",
                        help="read '<split><suffix>.csv' — use _cohort to chain after normalize")
    parser.add_argument("--out-suffix", default="_imputed",
                        help="write '<split><input-suffix><out-suffix>.csv'")
    parser.add_argument("--per-source", action="store_true", help="add the per-platform table")
    parser.add_argument("--fill", action="store_true",
                        help="write <split>_imputed.csv (the split itself is never overwritten)")
    parser.add_argument("--min-group", type=int, default=MIN_GROUP,
                        help="a group thinner than this falls back to the next level")
    parser.add_argument("--collapse-rare", type=int, default=0, metavar="N",
                        help="add `model_group`: models seen < N times in train become 'Other'")
    parser.add_argument("--report-out", default="",
                        help="JSON report path (default: <split-dir>/missing_report.json)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    split_dir = Path(args.split_dir)
    names = list(SPLITS) if args.split == "all" else [args.split]

    parts: dict[str, list[dict]] = {}
    fieldnames: dict[str, list[str]] = {}
    for name in names:
        path = split_dir / f"{name}{args.input_suffix}.csv"
        if not path.exists():
            log.error("partition not found: %s -> run 'python -m src.data_prep.split'", path)
            return 1
        parts[name], fieldnames[name] = load_split(path)

    columns = list(schema.SCHEMA_COLUMNS)
    audit = {name: measure_missing(rows, columns) for name, rows in parts.items()}
    for name, rows in parts.items():
        _print_table(f"Missing values — {name}", audit[name], len(rows))
        if args.per_source:
            _print_per_source(rows, columns)

    report: dict = {
        "split_dir": str(split_dir),
        "rows": {name: len(rows) for name, rows in parts.items()},
        "before": {name: {col: stats["rate"] for col, stats in audit[name].items()}
                   for name in parts},
    }

    if args.fill:
        if TRAIN not in parts:
            log.error("--fill needs the train partition in the run (use --split all)")
            return 1
        filled = impute_parts(parts, min_group=args.min_group, rare_min=args.collapse_rare)
        report["filled"] = filled
        report["after"] = {}
        for name, rows in parts.items():
            present = set(rows[0]) if rows else set()
            extra = [column for column in (IMPUTED_COLUMN, MODEL_GROUP_COLUMN)
                     if column in present and column not in fieldnames[name]]
            path = storage.save_csv(rows, f"{name}{args.input_suffix}{args.out_suffix}",
                                    [*fieldnames[name], *extra], directory=split_dir)
            after = measure_missing(rows, columns)
            report["after"][name] = {col: stats["rate"] for col, stats in after.items()}
            _print_table(f"Missing values after imputation — {name}", after, len(rows))
            print(f"  wrote {path.name}")

        print("\nImputed cells (train statistics applied unchanged to every partition):")
        for key, count in filled.items():
            print(f"  {key:28s} {count:>7,}")
        print(f"\n  policy: mode within brand+model -> brand -> global (§4.4), median within a "
              f"{AGE_BUCKET_YEARS}-year age band for mileage/engine, engine read from the trim badge.\n"
              f"          Every filled cell is flagged in `{IMPUTED_COLUMN}`; groups thinner than "
              f"--min-group {args.min_group} stay empty. Nothing is ever filled with 0.")
        if args.collapse_rare:
            print(f"          `{MODEL_GROUP_COLUMN}` collapses models seen < {args.collapse_rare} "
                  f"times in train into 'Other'; `model` itself is untouched.")

    report_path = Path(args.report_out) if args.report_out else split_dir / "missing_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




