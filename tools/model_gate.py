"""Gate before any model is trained: does the feature table leak the target?

`tools/audit_master` guards the merged dataset and `tools.validate_source_csv` guards a source
hand-over. This guards the *feature* table, which is where a leak actually does damage — a model that
scores 0.99 because a copy of the price is sitting in `X` looks like a success and is worthless.

Four checks, each of which has bitten projects like this one:

1. **A column that must not be there** — the price as text, the listing date, the capture time, the
   URL, the review flags, the imputation log, or anything produced from the prediction.
2. **A numeric feature that is a copy of the target** — caught even when renamed (`price_smooth`,
   `target_norm`, …) by looking at |Pearson| against `price_vnd`.
3. **The partitions do not share the same columns** — a per-split build can drift, and a model trained
   on one shape cannot predict another.
4. **A `duplicate_group_id` in more than one partition** — the same physical car on both sides of the
   split, which is the leak the grouped split exists to prevent.

`listing_id` and `duplicate_group_id` are allowed in the table (they are how a prediction is traced
back to a listing) and are reported separately: they must never be passed to the model.

Run:
    python -m tools.model_gate                                   # data/master/train_features_full.csv
    python -m tools.model_gate --features data/master/val_features_full.csv
    python -m tools.model_gate --quiet

Exit code 1 when anything fails, so it can be a PR gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402

TARGET = "price_vnd"
# Allowed in the table as a trace, never as a feature.
ID_COLUMNS = ("listing_id", "duplicate_group_id")
# Must not appear at all: any of these turns the model into a lookup.
FORBIDDEN = (
    "raw_price_text", "price_status", "listing_date", "scraped_at", "source_url",
    "quality_flags", "imputed", "tier",
    "y_pred", "y_pred_log", "y_pred_vnd", "residual", "abs_pct_error", "delta", "label", "reason",
    # label-quality side table (src/data_prep/quality.py): a flag computed from the price, or a row
    # whose *weight* the model is supposed to feel, must never travel as a feature.
    "deposit_suspected", "deposit_ratio", "placeholder_odometer", "implausible_year",
    "repeat_ad", "is_duplicate_copy", "canonical_listing_id", "flag_count",
    # the partition label itself: a table that knows which split it is in can memorise the split
    "split",
)
MAX_TARGET_CORRELATION = 0.999
GROUP_COLUMN = "duplicate_group_id"


def audit(path: Path, target: str = TARGET) -> dict:
    """Return a report dict; `problems` is empty when the table is clean."""
    problems: list[str] = []
    notes: list[str] = []
    if not path.exists():
        return {"file": str(path), "problems": [f"missing file: {path}"], "rows": 0,
                "columns": [], "numeric": [], "notes": []}

    frame = pd.read_csv(path, low_memory=False)
    columns = list(frame.columns)
    if target not in columns:
        problems.append(f"target column {target!r} is absent — is this a feature table?")
    for column in FORBIDDEN:
        if column in columns:
            problems.append(f"forbidden column in the table: {column!r}")
    for column in ID_COLUMNS:
        if column in columns:
            notes.append(f"{column}: trace only, keep it out of X")

    numeric = frame.select_dtypes("number")
    if target in numeric.columns and len(frame) > 1:
        # a constant column has no correlation to report (and numpy warns about dividing by 0)
        varying = [column for column in numeric.columns if numeric[column].nunique(dropna=True) > 1]
        if target in varying and len(varying) > 1:
            correlations = numeric[varying].corrwith(numeric[target])
            correlations = correlations.drop(labels=[target], errors="ignore")
            for column, value in correlations.items():
                if pd.notna(value) and abs(value) > MAX_TARGET_CORRELATION:
                    problems.append(f"{column!r} is a copy of the target (|r| = {abs(value):.4f})")

    return {
        "file": str(path),
        "rows": int(len(frame)),
        "columns": columns,
        "numeric": sorted(numeric.columns),
        "notes": notes,
        "problems": problems,
    }


def check_siblings(report: dict, path: Path) -> list[str]:
    """Compare the other partitions of the same variant, when they exist."""
    problems: list[str] = []
    variant = "_".join(part for part in path.stem.split("_") if part not in ("train", "val", "test"))
    siblings = {split: path.parent / f"{split}_{variant}.csv" for split in ("train", "val", "test")}
    present = {split: file for split, file in siblings.items() if file.exists()}
    if len(present) < 2:
        return problems

    frames = {split: pd.read_csv(file, low_memory=False) for split, file in present.items()}
    reference = set(frames.get("train", next(iter(frames.values()))).columns)
    for split, frame in frames.items():
        if set(frame.columns) != reference:
            problems.append(f"{split} has a different column set than train")

    if GROUP_COLUMN in reference:
        seen: dict[str, str] = {}
        for split, frame in frames.items():
            for group in frame[GROUP_COLUMN].dropna().unique():
                first = seen.setdefault(str(group), split)
                if first != split:
                    problems.append(f"group {group} appears in {first} and {split}")
                    break
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leakage gate for a feature table")
    parser.add_argument("--features", default=str(config.DATA_MASTER / "train_features_full.csv"))
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--no-siblings", action="store_true", help="skip the cross-partition checks")
    parser.add_argument("--json", default="", help="write the report to this path")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.features)
    report = audit(path, args.target)
    problems = list(report["problems"])
    if not args.no_siblings:
        problems += check_siblings(report, path)
    report["problems"] = problems

    if not args.quiet:
        print(f"FEATURE GATE: {path.name}")
        print(f"  rows {report['rows']:,} | {len(report['columns'])} columns | "
              f"{len(report['numeric'])} numeric")
        if report.get("notes"):
            for note in report["notes"]:
                print(f"  note: {note}")
        if problems:
            print("\n  PROBLEMS:")
            for problem in problems:
                print(f"    - {problem}")
        else:
            print("  no forbidden column, no copy of the target, partitions consistent")
        print(f"\n  RESULT: {'FAIL' if problems else 'PASS'}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

