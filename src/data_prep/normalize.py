"""Week 2, data-integration half: make `brand` / `model` comparable, then define the regression cohort.

Two jobs the merge left open, and both block week 3:

1. **One brand is one string.** The master carries 156 brand spellings, but `Mercedes Benz` (898 rows)
   and `Mercedes-Benz` (4 040), `VinFast`/`Vinfast`, `KIA`/`Kia`, `Land Rover`/`LandRover`,
   `MINI`/`Mini`, plus fullwidth junk from a title (FORD written with mathematical bold letters) and
   even emoji (a car emoji in the brand cell). A model that one-hot encodes `brand` treats each
   spelling as a different manufacturer, and `duplicate_group_id` — which keys on brand+model —
   under-groups the same car. Normalization is Unicode NFKC (which is what turns the bold letters
   back into ASCII), then a canonical spelling per key: an explicit table for the cases where the
   wrong spelling is common enough to win a vote, and the train partition's vote for the rest.

2. **The regression cohort.** The split was frozen before the §4.3 outlier rules were applied, so
   `train.csv` still holds a 1025 model year, a 2.5e15 km odometer and a 465-trillion-VND asking
   price. This module names the reason a record leaves the cohort, which is exactly what the report
   has to print ("how many records were excluded, with reasons").

Both statistics are **learned on the train partition only** and then applied unchanged to val/test,
the same rule the imputation follows.

Run:
    python -m src.data_prep.normalize --split train              # alias + cohort audit
    python -m src.data_prep.normalize --split all --write        # write <split>_cohort.csv
    python -m src.data_prep.normalize --split all --write --no-cohort   # normalize only
"""

from __future__ import annotations

import argparse
import json
import logging
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from ..common import config, storage
from ..merge.build_master import (KM_MAX_PLAUSIBLE, PRICE_IMPLAUSIBLE_HIGH, PRICE_REVIEW_LOW,
                                  PRICE_SEPARATE_SEGMENT, YEAR_SCOPE_START)
from .missing import SPLITS, TRAIN, _blank, _num, capture_year, load_split

log = logging.getLogger("normalize")

UNKNOWN = "Unknown"

# A column whose value is a *template default* on one source is not evidence. carmudi's `Kiểu dáng`
# is a seller dropdown and 528 of its 546 rows say `Coupe` (docs/sources/carmudi.md already calls the
# column unreliable) — a 2010 Toyota Yaris is not a coupe. The value becomes `Unknown`, the listing
# stays: dropping 528 real cars would cost more than the wrong label does, and week 3 can impute
# `body_type` from the brand+model mode instead of learning that carmudi sells only coupes.
UNRELIABLE_BODY_TYPE = {"carmudi": "Coupe"}

# Canonical spellings the data cannot decide on its own (the wrong spelling is common enough to win a
# vote, or the right spelling is a brand convention). Key = the normalized comparison key.
BRAND_CANONICALS = {
    "mercedesbenz": "Mercedes-Benz",
    "landrover": "Land Rover",
    "rollsroyce": "Rolls-Royce",
    "vinfast": "VinFast",
    "ssangyong": "SsangYong",
    "lynkco": "Lynk & Co",
    "lynk": "Lynk & Co",
    "mini": "MINI",
    "mg": "MG",
    "mgmotor": "MG",
    "kia": "Kia",
    "bmw": "BMW",
    "byd": "BYD",
    "hyundai": "Hyundai",
    "mitsubishi": "Mitsubishi",
}

# Reason labels, in the order they are tested — the first one that applies is the one reported, so a
# record is never counted twice and the counts add up to the number of excluded rows.
COHORT_RULES = (
    "missing_price",
    "price_unit_error",
    "price_above_luxury_segment",
    "price_below_floor",
    "missing_year",
    "year_out_of_scope",
    "mileage_implausible",
)


# ------------------------------------------------------------------ keys
def _key(value) -> str:
    """Comparison key: NFKC (bold/fullwidth -> ASCII), casefolded, punctuation removed."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in text if char.isalnum())


def _has_letters(value) -> bool:
    """A brand cell holding an emoji or a dash names no manufacturer, whatever else it looks like."""
    return any(char.isalpha() for char in unicodedata.normalize("NFKC", str(value or "")))


def _tidy(value) -> str:
    """NFKC, collapse whitespace, drop the decoration a title leaves behind ('*', '#', emoji)."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    kept = "".join(char for char in text if char.isalnum() or char in " -&.+")
    return " ".join(kept.split())


# ------------------------------------------------------------ brand / model
def normalize_brand(raw, mapping: dict[str, str] | None = None) -> str:
    """Return one canonical spelling for a brand, or `Unknown` when the cell carries none."""
    if not _has_letters(raw):
        return UNKNOWN
    key = _key(raw)
    if not key:
        return UNKNOWN
    canonical = (mapping or {}).get(key) or BRAND_CANONICALS.get(key)
    return canonical or _tidy(raw)


def learn_brand_map(train_rows: list[dict]) -> dict[str, str]:
    """Canonical spelling per brand key: the explicit table first, then the most frequent spelling.

    Voting on the train partition is what fixes `Mercedes Benz` -> `Mercedes-Benz` without listing
    every manufacturer of the Vietnamese market by hand.
    """
    votes: dict[str, Counter] = defaultdict(Counter)
    for row in train_rows:
        if not _has_letters(row.get("brand")):
            continue
        key = _key(row.get("brand"))
        if key:
            votes[key][_tidy(row.get("brand"))] += 1
    return {key: BRAND_CANONICALS.get(key) or counter.most_common(1)[0][0]
            for key, counter in votes.items()}


def learn_model_map(train_rows: list[dict],
                    brand_map: dict[str, str] | None = None) -> dict[str, str]:
    """Canonical spelling per (brand, model) key, so 'Accent' and 'ACCENT' become one model."""
    brand_map = brand_map if brand_map is not None else learn_brand_map(train_rows)
    votes: dict[str, Counter] = defaultdict(Counter)
    for row in train_rows:
        brand = normalize_brand(row.get("brand"), brand_map)
        model_key = _key(row.get("model"))
        if model_key:
            votes[f"{_key(brand)}|{model_key}"][_tidy(row.get("model"))] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in votes.items()}


def apply_brand_and_model(rows: list[dict], brand_map: dict[str, str],
                          model_map: dict[str, str] | None = None) -> int:
    """Rewrite `brand` / `model` in place from the fitted maps; returns how many cells changed."""
    changed = 0
    for row in rows:
        brand = normalize_brand(row.get("brand"), brand_map)
        if brand != str(row.get("brand") or ""):
            changed += 1
        row["brand"] = brand

        model = str(row.get("model") or "")
        if model_map and _key(model):
            canonical = model_map.get(f"{_key(brand)}|{_key(model)}")
            if canonical and canonical != model:
                changed += 1
                row["model"] = canonical
        elif model and _blank(model, unknown_is_missing=False):
            row["model"] = ""
            changed += 1
    return changed


def alias_report(rows: list[dict], column: str = "brand", limit: int = 20,
                 brand_map: dict[str, str] | None = None) -> list[dict]:
    """Keys carrying more than one spelling — the evidence table behind the normalization."""
    spellings: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if column == "brand":
            if not _has_letters(row.get("brand")):
                continue
            key, value = _key(row.get("brand")), _tidy(row.get("brand"))
        else:
            brand = normalize_brand(row.get("brand"), brand_map) if brand_map else row.get("brand")
            key, value = f"{_key(brand)}|{_key(row.get('model'))}", _tidy(row.get("model"))
        if key and value:
            spellings[key][value] += 1
    report = [{"key": key, "spellings": dict(counter), "variants": len(counter)}
              for key, counter in spellings.items() if len(counter) > 1]
    report.sort(key=lambda item: -sum(item["spellings"].values()))
    return report[:limit] if limit else report


# Plausibility ranges for the two numeric attributes the §4.3 cohort rules do not cover. A `2021` in
# `engine_capacity` is a model year that landed in the wrong column (12 rows, plus 476 zeros on cars
# that are not electric), and a `760`-seat car is a typing error; either one distorts scaling and a
# tree split far more than it costs to blank. A blank is not a deletion — the imputation stage fills
# it from the trim badge or the age band, and the `imputed` flag records that it was filled.
ENGINE_RANGE_L = (0.5, 8.0)
SEATS_RANGE = (2, 60)


# ------------------------------------------------ source-specific repairs
def repair_body_type(rows: list[dict]) -> dict[str, int]:
    """Drop the value a source writes by default instead of the one it read: coupe on carmudi.

    Returns the number of cells repaired per platform, so the report can state it rather than
    silently changing a column.
    """
    counts: Counter[str] = Counter()
    for row in rows:
        platform = str(row.get("source_platform") or "").strip()
        default = UNRELIABLE_BODY_TYPE.get(platform)
        if default and str(row.get("body_type") or "").strip() == default:
            row["body_type"] = UNKNOWN
            counts[platform] += 1
    return dict(counts)


def repair_implausible_numbers(rows: list[dict]) -> dict[str, int]:
    """Blank an engine displacement or a seat count that cannot be true, keeping the record.

    The value is emptied rather than replaced, so the imputation stage decides what it becomes and
    the `imputed` column says so.
    """
    counts: Counter[str] = Counter()
    for row in rows:
        engine = _num(row.get("engine_capacity"), float)
        if engine is not None and not ENGINE_RANGE_L[0] <= engine <= ENGINE_RANGE_L[1]:
            row["engine_capacity"] = ""
            counts["engine_capacity"] += 1
        seats = _num(row.get("seats"), int)
        if seats is not None and not SEATS_RANGE[0] <= seats <= SEATS_RANGE[1]:
            row["seats"] = ""
            counts["seats"] += 1
    return dict(counts)


# ---------------------------------------------------- the regression cohort
def cohort_reason(row: dict, reference_year: int) -> str:
    """Why this record cannot be a regression example, or '' when it can.

    The order is the `COHORT_RULES` order: the price has to be usable before a range check means
    anything, and a unit error must not be filed as a luxury car (the same precedence as the flags).
    """
    price = _num(row.get("price_vnd"), int)
    year = _num(row.get("manufacture_year"), int)
    km = _num(row.get("mileage_km"), float)

    if price is None:
        return "missing_price"
    if price >= PRICE_IMPLAUSIBLE_HIGH:
        return "price_unit_error"
    if price > PRICE_SEPARATE_SEGMENT:
        return "price_above_luxury_segment"
    if price < PRICE_REVIEW_LOW:
        return "price_below_floor"
    if year is None:
        return "missing_year"
    if not YEAR_SCOPE_START <= year <= reference_year:
        return "year_out_of_scope"
    if km is not None and km > KM_MAX_PLAUSIBLE:
        return "mileage_implausible"
    return ""


def apply_cohort(rows: list[dict], reference_year: int) -> tuple[list[dict], dict[str, int]]:
    """Return the rows that stay and a count per reason for the rows that leave.

    Nothing is deleted from disk: the excluded records stay in the split (the anomaly stage needs
    them), only the regression cohort is a *view* over it. That is the report's rule — flag, then
    count the exclusion, never quietly drop the evidence.
    """
    kept: list[dict] = []
    excluded: Counter[str] = Counter()
    for row in rows:
        reason = cohort_reason(row, reference_year)
        if reason:
            excluded[reason] += 1
        else:
            kept.append(row)
    return kept, {rule: excluded.get(rule, 0) for rule in COHORT_RULES}


def cohort_table(counts: dict[str, int], total: int) -> dict:
    """The report §4.3 numbers: kept, excluded, and why."""
    excluded = sum(counts.values())
    return {
        "rows": total,
        "kept": total - excluded,
        "kept_rate": round((total - excluded) / total, 4) if total else 0.0,
        "excluded": excluded,
        "reasons": {reason: count for reason, count in counts.items() if count},
        "cutoffs": {
            "price_floor_vnd": PRICE_REVIEW_LOW,
            "luxury_segment_vnd": PRICE_SEPARATE_SEGMENT,
            "price_unit_error_vnd": PRICE_IMPLAUSIBLE_HIGH,
            "mileage_max_km": KM_MAX_PLAUSIBLE,
            "year_scope_start": YEAR_SCOPE_START,
        },
    }


# ----------------------------------------------------------------------- CLI
def _print_aliases(title: str, report: list[dict]) -> None:
    print(f"\n{title}")
    if not report:
        print("  (none — every key already has a single spelling)")
        return
    print(f"  {'key':24s} {'variants':>8s}  spellings")
    for item in report:
        shown = ", ".join(f"{value} ({count})" for value, count in
                          sorted(item["spellings"].items(), key=lambda kv: -kv[1])[:3])
        print(f"  {item['key'][:24]:24s} {item['variants']:>8d}  {shown}")


def _print_cohort(title: str, table: dict) -> None:
    print(f"\n{title}: {table['kept']:,} kept of {table['rows']:,} "
          f"({table['kept_rate'] * 100:.1f}%), {table['excluded']:,} excluded")
    for reason, count in table["reasons"].items():
        print(f"  {reason:28s} {count:>7,}")
    if not table["reasons"]:
        print("  (no record failed a §4.3 rule)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize brand/model and build the regression cohort from TRAIN-only rules")
    parser.add_argument("--split-dir", default=str(config.DATA_MASTER))
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="all")
    parser.add_argument("--write", action="store_true",
                        help="write <split>_cohort.csv (the split itself is never overwritten)")
    parser.add_argument("--no-cohort", action="store_true",
                        help="normalize brand/model only, keep every record")
    parser.add_argument("--alias-limit", type=int, default=15)
    parser.add_argument("--report-out", default="",
                        help="JSON report path (default: <split-dir>/normalize_report.json)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    split_dir = Path(args.split_dir)
    names = list(SPLITS) if args.split == "all" else [args.split]

    parts: dict[str, list[dict]] = {}
    fieldnames: dict[str, list[str]] = {}
    for name in names:
        path = split_dir / f"{name}.csv"
        if not path.exists():
            log.error("partition not found: %s -> run 'python -m src.data_prep.split'", path)
            return 1
        parts[name], fieldnames[name] = load_split(path)
    if TRAIN not in parts:
        log.error("the maps are fitted on train only — run with --split all (or --split train)")
        return 1

    train_rows = parts[TRAIN]
    reference = capture_year(train_rows)

    # 0. source-specific repairs first: a template default must be gone before anything is learned
    repaired = {name: repair_body_type(rows) for name, rows in parts.items()}
    if any(repaired.values()):
        shown = ", ".join(f"{platform} {count:,}" for platform, count
                          in sorted(repaired[TRAIN].items()))
        print(f"\nTemplate default removed — body_type 'Coupe' -> Unknown on {shown} (train)")

    numbers = {name: repair_implausible_numbers(rows) for name, rows in parts.items()}
    if any(numbers.values()):
        shown = ", ".join(f"{column} {count:,}" for column, count
                          in sorted(numbers[TRAIN].items()))
        print(f"Implausible numbers blanked for imputation — {shown} (train)")

    # 1. the evidence, before anything is rewritten
    brand_aliases = alias_report(train_rows, "brand", args.alias_limit)
    model_aliases = alias_report(train_rows, "model", args.alias_limit)
    brands_before = len({row.get("brand") for row in train_rows})

    # 2. fit on train, apply to every partition
    brand_map = learn_brand_map(train_rows)
    model_map = learn_model_map(train_rows, brand_map)
    changed = {name: apply_brand_and_model(rows, brand_map, model_map)
               for name, rows in parts.items()}
    brands_after = len({row.get("brand") for row in train_rows})

    _print_aliases(f"Brand spellings that collapse ({len(brand_aliases)} shown)", brand_aliases)
    _print_aliases(f"Model spellings that collapse ({len(model_aliases)} shown)", model_aliases)
    print(f"\nBrand cardinality: {brands_before} -> {brands_after} "
          f"(cells rewritten: {sum(changed.values()):,})")

    report: dict = {
        "split_dir": str(split_dir),
        "reference_year": reference,
        "brands_before": brands_before,
        "brands_after": brands_after,
        "brand_aliases": brand_aliases,
        "model_aliases": model_aliases,
        "cells_rewritten": changed,
        "body_type_repaired": repaired,
        "numbers_repaired": numbers,
        "cohort": {},
    }

    # 3. the regression cohort: a view over the split, not a deletion
    outputs: dict[str, list[dict]] = {name: rows for name, rows in parts.items()}
    if not args.no_cohort:
        for name, rows in parts.items():
            kept, counts = apply_cohort(rows, reference)
            table = cohort_table(counts, len(rows))
            report["cohort"][name] = table
            outputs[name] = kept
            _print_cohort(f"Regression cohort — {name}", table)

    if args.write:
        for name, rows in outputs.items():
            path = storage.save_csv(rows, f"{name}_cohort", fieldnames[name], directory=split_dir)
            print(f"  wrote {path.name} ({len(rows):,} rows)")

    report_path = Path(args.report_out) if args.report_out else split_dir / "normalize_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  report: {report_path}")
    print("  note: the excluded records stay in <split>.csv — they are the anomaly stage's evidence, "
          "so only this cohort is filtered, with a reason per record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


