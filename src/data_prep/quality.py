"""Label-quality flags: the four rows that are valid listings and still poison the model.

`tools/audit_master` already *prints* these four diagnostics. This module is the production half: it
**writes them to a side table** instead of editing the data, because the frozen milestone rule
(`CONTRIBUTING.md` §3b) says the row set may not move without a new snapshot.

    data/master/label_flags.csv        one row per listing, keyed by listing_id
    data/master/label_flags_report.json counts per split, per platform, per flag

The flags (docs/deposit_rule_proposal.md, docs/data_limitations.md §4):

* `deposit_suspected` — asking price below `threshold` x the `brand|model` median. The median is
  learned on **train only** (segment needs `segment_min_rows`, else the national median), so no
  validation row can move a flag.
* `placeholder_odometer` — `mileage_km <= 100` or `>= 900_000`: "1 km" on a 2026 car, "999,998 km" on
  a 2024 one. These rows actively mislead `km_per_year`, they are not merely noisy.
* `implausible_year` — `manufacture_year` outside `[1980, capture year]` (1025, 2028, 2030, 2032).
* `repeat_ad` / `is_duplicate_copy` — the same car at the same price more than once. One row per group
  is kept as the **canonical** row (lowest `listing_id`, an identifier-only rule: no target, no price
  statistic, deterministic) and every other row is marked `is_duplicate_copy = 1`, so training can
  drop the copies or weight them `1/k` without touching the dataset.

Nothing here is a feature. `tools/model_gate.FORBIDDEN` carries all the column names, so a table that
smuggles one into `X` fails the gate instead of scoring well.

Run:
    python -m src.data_prep.quality --write
    python -m src.data_prep.quality --threshold 0.15 --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import config  # noqa: E402

TRAIN, VAL, TEST = "train", "val", "test"
SPLITS = (TRAIN, VAL, TEST)

DEPOSIT_THRESHOLD = 0.25      # docs/deposit_rule_proposal.md §3: 0.25 keeps the false-positive rate ~25 %
SEGMENT_MIN_ROWS = 30         # a brand|model thinner than this borrows the national median
PLACEHOLDER_LOW = 100         # "1 km" on a 2026 car
PLACEHOLDER_HIGH = 900_000    # "999,998 km" on a 2024 car
YEAR_MIN = 1980

# The columns this module emits, in output order. `flag_count` is the "drop every flagged row" switch.
FLAG_COLUMNS = (
    "listing_id", "split",
    "deposit_suspected", "deposit_ratio",
    "placeholder_odometer", "implausible_year",
    "repeat_ad", "is_duplicate_copy", "canonical_listing_id",
    "flag_count",
)
BOOLEAN_FLAGS = ("deposit_suspected", "placeholder_odometer", "implausible_year", "repeat_ad")
REPEAT_KEY = ("brand", "model", "manufacture_year", "mileage_km", "price_vnd")
MISSING = "\x00missing\x00"    # sentinel so NaN groups with NaN instead of being dropped by groupby


def split_path(split: str, suffix: str = "_cohort_imputed") -> Path:
    return config.DATA_MASTER / f"{split}{suffix}.csv"


def load_split(split: str, suffix: str = "_cohort_imputed") -> pd.DataFrame:
    """Read one partition of the frozen snapshot; `listing_id` stays a string."""
    path = split_path(split, suffix)
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.data_prep.pipeline' first")
    frame = pd.read_csv(path, low_memory=False)
    frame["listing_id"] = frame["listing_id"].astype(str)
    return frame


def _segment_key(frame: pd.DataFrame) -> pd.Series:
    return (frame["brand"].fillna("").astype(str).str.strip().str.casefold() + "|"
            + frame["model"].fillna("").astype(str).str.strip().str.casefold())


def capture_year(frame: pd.DataFrame, fallback: int = 2026) -> int:
    """Latest capture year in the data — an "impossible year" is judged against the snapshot, not today."""
    years = pd.to_numeric(frame["scraped_at"].astype(str).str[:4], errors="coerce").dropna()
    return int(years.max()) if len(years) else fallback



# --------------------------------------------------------------------- rules
def fit_segment_medians(train: pd.DataFrame, min_rows: int = SEGMENT_MIN_ROWS) -> dict[str, float]:
    """Median asking price per `brand|model`, learned on **train only**.

    A segment thinner than `min_rows` is not evidence, so it falls back to the national median at
    lookup time. The table is returned rather than stored: keeping it in memory makes "no statistic
    crosses a partition" visible in the code.
    """
    price = pd.to_numeric(train["price_vnd"], errors="coerce")
    usable = price > 0
    key = _segment_key(train)
    counts = key[usable].value_counts()
    medians = price[usable].groupby(key[usable]).median()
    kept = medians[medians.index.isin(counts[counts >= min_rows].index)]
    table = {str(name): float(value) for name, value in kept.items()}
    table["__national__"] = float(price[usable].median()) if usable.any() else float("nan")
    return table


def deposit_flags(frame: pd.DataFrame, medians: dict[str, float],
                  threshold: float = DEPOSIT_THRESHOLD) -> tuple[pd.Series, pd.Series]:
    """`(flag, ratio)`: asking price below `threshold` of the segment median."""
    price = pd.to_numeric(frame["price_vnd"], errors="coerce")
    national = medians.get("__national__", float("nan"))
    baseline = _segment_key(frame).map(medians).fillna(national)
    ratio = price / baseline.where(baseline > 0)
    flag = (price > 0) & ratio.notna() & (ratio < threshold)
    return flag.fillna(False).astype(bool), ratio


def placeholder_flags(frame: pd.DataFrame) -> pd.Series:
    """Odometer values that are a placeholder, not a distance."""
    mileage = pd.to_numeric(frame["mileage_km"], errors="coerce")
    flag = mileage.notna() & ((mileage <= PLACEHOLDER_LOW) | (mileage >= PLACEHOLDER_HIGH))
    return flag.fillna(False).astype(bool)


def year_flags(frame: pd.DataFrame, year_max: int) -> pd.Series:
    """Model years outside the plausible window (`1980 … capture year`).

    Missing years are counted separately in the report: they are a different defect, and no
    imputation can invent the year of a car.
    """
    year = pd.to_numeric(frame["manufacture_year"], errors="coerce")
    flag = year.notna() & ~year.between(YEAR_MIN, year_max)
    return flag.fillna(False).astype(bool)


def repeat_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """Same car, same price, more than once: `repeat_ad`, `is_duplicate_copy`, `canonical_listing_id`.

    The canonical row is the **lowest `listing_id`** in the group. That is deliberately an
    identifier-only rule: it uses no price, no target and no split, so the choice cannot leak
    validation information into training, and adding rows later does not re-canonicalise a group.
    """
    parts = []
    for column in REPEAT_KEY:
        text = frame[column].map(lambda value: MISSING if pd.isna(value) else str(value).strip())
        parts.append(text.astype(str))
    key = parts[0]
    for part in parts[1:]:
        key = key + "|" + part

    sizes = key.value_counts()
    repeated = key.isin(sizes[sizes > 1].index)

    out = pd.DataFrame(index=frame.index)
    out["listing_id"] = frame["listing_id"].astype(str)
    out["repeat_ad"] = repeated
    out["canonical_listing_id"] = frame["listing_id"].astype(str)
    out["is_duplicate_copy"] = False
    if repeated.any():
        canonical = (frame.loc[repeated, ["listing_id"]].assign(_key=key[repeated])
                     .groupby("_key")["listing_id"].min())
        mapped = key[repeated].map(canonical)
        out.loc[repeated, "canonical_listing_id"] = mapped.to_numpy()
        out.loc[repeated, "is_duplicate_copy"] = (
            frame.loc[repeated, "listing_id"].astype(str).to_numpy() != mapped.to_numpy())
    return out



# ----------------------------------------------------------------- assembly
def build_flags(parts: dict[str, pd.DataFrame], threshold: float = DEPOSIT_THRESHOLD,
                segment_min_rows: int = SEGMENT_MIN_ROWS,
                year_max: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Compute the side table over every partition, plus the report that explains the counts."""
    stacked = pd.concat([frame.assign(split=name) for name, frame in parts.items()], ignore_index=True)
    if year_max is None:
        year_max = capture_year(stacked)
    medians = fit_segment_medians(parts[TRAIN], segment_min_rows)

    deposit, ratio = deposit_flags(stacked, medians, threshold)
    placeholder = placeholder_flags(stacked)
    year = year_flags(stacked, year_max)
    repeats = repeat_flags(stacked)

    flags = pd.DataFrame({
        "listing_id": stacked["listing_id"].astype(str),
        "split": stacked["split"],
        "deposit_suspected": deposit.to_numpy(),
        "deposit_ratio": ratio.round(6).to_numpy(),
        "placeholder_odometer": placeholder.to_numpy(),
        "implausible_year": year.to_numpy(),
        "repeat_ad": repeats["repeat_ad"].to_numpy(),
        "is_duplicate_copy": repeats["is_duplicate_copy"].to_numpy(),
        "canonical_listing_id": repeats["canonical_listing_id"].to_numpy(),
    })
    flags["flag_count"] = flags[list(BOOLEAN_FLAGS)].sum(axis=1).astype(int)
    return flags[list(FLAG_COLUMNS)], report_of(stacked, flags, medians, threshold,
                                                segment_min_rows, year_max)


def report_of(stacked: pd.DataFrame, flags: pd.DataFrame, medians: dict[str, float],
              threshold: float, segment_min_rows: int, year_max: int) -> dict:
    """Counts a reader can re-derive, split by split and by platform."""
    per_split = {}
    for split, group in flags.groupby("split"):
        block = stacked.loc[stacked["split"] == split]
        platform = block["source_platform"].astype(str)
        per_split[str(split)] = {
            "rows": int(len(group)),
            "flags": {name: int(group[name].sum()) for name in BOOLEAN_FLAGS},
            "rates": {name: round(float(group[name].mean()), 4) for name in BOOLEAN_FLAGS},
            "rows_with_any_flag": int((group["flag_count"] > 0).sum()),
            "rows_missing_year": int(pd.to_numeric(block["manufacture_year"],
                                                   errors="coerce").isna().sum()),
            "by_platform": {
                str(name): {flag: int(group.loc[platform == name, flag].sum())
                            for flag in BOOLEAN_FLAGS}
                for name in sorted(platform.unique())
            },
        }

    price = pd.to_numeric(stacked["price_vnd"], errors="coerce")
    deposit_ratios = flags.loc[flags["deposit_suspected"], "deposit_ratio"]
    group_sizes = flags.loc[flags["repeat_ad"], "canonical_listing_id"].value_counts()
    return {
        "generated_at": config.now_iso(),
        "version": "v1-side-table",
        "threshold": threshold,
        "segment_min_rows": segment_min_rows,
        "year_range": [YEAR_MIN, int(year_max)],
        "repeat_key": list(REPEAT_KEY),
        "canonical_rule": "lowest listing_id per repeat group (identifier only)",
        "segments_kept": len([key for key in medians if key != "__national__"]),
        "national_median": medians.get("__national__"),
        "rows": {str(split): int((flags["split"] == split).sum())
                 for split in sorted(flags["split"].unique())},
        "per_split": per_split,
        "repeat": {
            "groups": int(group_sizes.size),
            "rows_in_repeat_groups": int(flags["repeat_ad"].sum()),
            "copies_flagged": int(flags["is_duplicate_copy"].sum()),
            "group_size_histogram": {int(size): int(count) for size, count in
                                     group_sizes.value_counts().head(10).items()},
        },
        "deposit": {
            "flagged": int(flags["deposit_suspected"].sum()),
            "median_ratio_of_flagged": (round(float(deposit_ratios.median()), 4)
                                        if len(deposit_ratios) else None),
            "median_price_of_flagged": (int(price[flags["deposit_suspected"].to_numpy()].median())
                                        if flags["deposit_suspected"].any() else None),
        },
        "note": "side table only — data/master/*_cohort_imputed.csv is never modified",
    }


# --------------------------------------------------------------------- io
def write_outputs(flags: pd.DataFrame, report: dict, out_csv: Path, out_report: Path) -> None:
    """Write the side table and its report with LF endings, so a hash is OS-portable."""
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    flags.to_csv(out_csv, index=False, lineterminator="\n")
    out_report = Path(out_report)
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")


def load_flags(path: Path | None = None) -> pd.DataFrame:
    """Read the side table back; `listing_id` stays a string so joins never mangle it."""
    path = Path(path or (config.DATA_MASTER / "label_flags.csv"))
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.data_prep.quality --write'")
    frame = pd.read_csv(path, low_memory=False)
    frame["listing_id"] = frame["listing_id"].astype(str)
    frame["canonical_listing_id"] = frame["canonical_listing_id"].astype(str)
    return frame


def cleaning_weights(flags: pd.DataFrame, mode: str) -> pd.Series:
    """The training weight per listing for each cleaning mode — the comparison's only input.

    `none`            every row weighs 1
    `drop_deposit`    deposit-style rows weigh 0 (the rest 1)
    `drop_all`        any flagged row weighs 0
    `weight_repeats`  a repeated advertisement weighs `1 / k` (k = rows in its repeat group), so a
                      car posted four times does not count four times
    """
    weights = pd.Series(1.0, index=flags.index)
    if mode == "drop_deposit":
        weights[flags["deposit_suspected"].to_numpy()] = 0.0
    elif mode == "drop_all":
        weights[flags["flag_count"].to_numpy() > 0] = 0.0
    elif mode == "weight_repeats":
        copies = flags["repeat_ad"].to_numpy()
        share = flags.loc[copies, "canonical_listing_id"].map(
            flags.loc[copies, "canonical_listing_id"].value_counts())
        weights[copies] = (1.0 / share.astype(float)).to_numpy()
    elif mode != "none":
        raise ValueError(f"unknown cleaning mode {mode!r}")
    return weights


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label-quality side table for the frozen snapshot")
    parser.add_argument("--suffix", default="_cohort_imputed",
                        help="input files are '{split}{suffix}.csv' (default: the modelling cohort)")
    parser.add_argument("--threshold", type=float, default=DEPOSIT_THRESHOLD,
                        help="deposit rule: price below this share of the brand|model median")
    parser.add_argument("--segment-min-rows", type=int, default=SEGMENT_MIN_ROWS,
                        help="a brand|model thinner than this borrows the national median")
    parser.add_argument("--year-max", type=int, default=None,
                        help="plausible upper model year (default: capture year in the snapshot)")
    parser.add_argument("--out", default=str(config.DATA_MASTER / "label_flags.csv"))
    parser.add_argument("--report", default=str(config.DATA_MASTER / "label_flags_report.json"))
    parser.add_argument("--write", action="store_true", help="write the CSV + JSON (default: dry run)")
    args = parser.parse_args(argv)

    parts = {split: load_split(split, args.suffix) for split in SPLITS}
    flags, report = build_flags(parts, args.threshold, args.segment_min_rows, args.year_max)

    print(f"{'split':6s} {'rows':>7s} {'deposit':>8s} {'odo':>6s} {'year':>5s} "
          f"{'repeat':>7s} {'copies':>7s} {'any':>7s}")
    print("-" * 60)
    for split in SPLITS:
        block = report["per_split"][split]
        copies = int(flags.loc[flags["split"] == split, "is_duplicate_copy"].sum())
        print(f"{split:6s} {block['rows']:>7,} {block['flags']['deposit_suspected']:>8,} "
              f"{block['flags']['placeholder_odometer']:>6,} {block['flags']['implausible_year']:>5,} "
              f"{block['flags']['repeat_ad']:>7,} {copies:>7,} {block['rows_with_any_flag']:>7,}")
    print(f"\nrepeat groups {report['repeat']['groups']:,} · copies flagged "
          f"{report['repeat']['copies_flagged']:,} · segments kept {report['segments_kept']:,}")
    if args.write:
        write_outputs(flags, report, Path(args.out), Path(args.report))
        print(f"  csv    -> {args.out}\n  report -> {args.report}")
    else:
        print("  dry run — pass --write to create the side table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

