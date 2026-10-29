"""Week 2: the train/validation/test split, grouped by `duplicate_group_id` (no data leakage).

Why a grouped split, and not a plain `train_test_split`:

    the same physical car is advertised on several marketplaces at once, so it appears as two or three
    rows which `build_master` already tied together into one `duplicate_group_id`. A random row-level
    split would put one copy in train and another in test: the model then "recognizes" the car and the
    test score stops measuring anything. Every record of a group must therefore travel together, so
    the split is made **on groups** and the rows follow their group.

Why stratified, on top of that:

    the price distribution is heavy-tailed (docs/unified_schema.md, report §4). A plain grouped split
    on this data moves the share of luxury cars between partitions by several points, so validation and
    test stop being comparable with train. Each group is therefore placed in a **price decile** (the
    group's median asking price), and the 70/15/15 ratio is applied *inside* every decile. That keeps
    all three partitions on the same price mix while keeping groups intact.

Report rule (docs/unified_schema.md): every statistic that is later learned from the data — the
imputation modes and medians in `src/data_prep/missing.py`, the encoders and scalers of week 3 — must be
fitted on `train` only and then applied unchanged to `val`/`test`. This module is what makes that
possible: it writes the three files and nothing else touches the split.

Rows whose asking price is missing are **not** part of the split: `price_vnd` is the regression target,
so such a row cannot be a training or an evaluation example. They are written to `unlabelled.csv`
instead of being deleted (the report's rule: flag, never silently drop).

Run:
    python -m src.data_prep.split                        # 70/15/15, seed 42
    python -m src.data_prep.split --seed 7 --ratios 0.8 0.1 0.1

Writes: data/master/train.csv · val.csv · test.csv · unlabelled.csv · split_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from ..common import config, storage

log = logging.getLogger("split")

SPLITS = ("train", "val", "test")
DEFAULT_RATIOS = (0.70, 0.15, 0.15)
DEFAULT_SEED = 42
DECILES = 10
NO_PRICE_STRATUM = "no_price"


# ------------------------------------------------------------------ reading
def load_master(path: Path) -> tuple[list[dict], list[str]]:
    """Read the Master Dataset back, keeping every value as a string (no dtype surprises)."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "duplicate_group_id" not in fieldnames:
        raise SystemExit(f"{path} has no duplicate_group_id column — run "
                         f"'python -m src.merge.build_master' first")
    return rows, fieldnames


def _is_unlabelled(row: dict) -> bool:
    """True when the row has no usable asking price, so it cannot be a regression example."""
    price = str(row.get("price_vnd") or "").strip()
    if not price or price.lower() in ("none", "nan", "null"):
        return True
    try:
        return float(price) <= 0
    except ValueError:
        return True


def group_rows(rows: list[dict]) -> dict[str, list[dict]]:
    """Split the records into candidate vehicles (`duplicate_group_id` -> its records).

    A row without a group id gets a group of its own, so one broken export cannot merge unrelated cars
    into a single mega-group (which would land in one partition and silently shrink the other two).
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = str(row.get("duplicate_group_id") or "").strip()
        groups[key or f"SOLO_{row.get('listing_id')}"].append(row)
    return dict(groups)


# ------------------------------------------------------------------ strata
def _quantile(values: list[float], q: float) -> float:
    """Linear-interpolation quantile (numpy's default), without pulling numpy into the pipeline."""
    if not values:
        return 0.0
    position = q * (len(values) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(values) - 1)
    return values[low] * (1 - (position - low)) + values[high] * (position - low)


def _group_price(records: list[dict]) -> float | None:
    """Representative price of a group: the median of its usable asking prices."""
    prices = []
    for record in records:
        try:
            value = float(str(record.get("price_vnd")).strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            prices.append(value)
    return median(prices) if prices else None


def assign_strata(groups: dict[str, list[dict]]) -> dict[str, str]:
    """Put every group in a price decile (`decile 00` = cheapest … `decile 09` = most expensive)."""
    prices = {key: _group_price(records) for key, records in groups.items()}
    known = sorted(price for price in prices.values() if price is not None)
    cuts = [_quantile(known, step / DECILES) for step in range(1, DECILES)]
    strata: dict[str, str] = {}
    for key, price in prices.items():
        if price is None:
            strata[key] = NO_PRICE_STRATUM
            continue
        index = sum(1 for cut in cuts if price > cut)          # how many cuts the price clears
        strata[key] = f"decile {min(index, DECILES - 1):02d}"
    return strata


# ------------------------------------------------------------------ splitting
def _shares(count: int, ratios: tuple[float, float, float]) -> tuple[int, int, int]:
    """Turn a ratio into whole groups; the remainder always goes to train."""
    val = int(round(count * ratios[1]))
    test = int(round(count * ratios[2]))
    if count >= 3:                       # keep at least one group per partition once there are enough
        val, test = max(val, 1), max(test, 1)
    while val + test >= count:
        if val > test:
            val -= 1
        else:
            test -= 1
    return count - val - test, val, test


def assign_splits(groups: dict[str, list[dict]], ratios: tuple[float, float, float],
                  seed: int) -> dict[str, str]:
    """Give every group one partition, applying the ratio inside each price decile.

    The groups are sorted before shuffling, so the same input and seed always produce the same split —
    a split that changes between runs would make two people's accuracy figures incomparable.
    """
    strata = assign_strata(groups)
    by_stratum: dict[str, list[str]] = defaultdict(list)
    for key in sorted(groups):
        by_stratum[strata[key]].append(key)

    assignment: dict[str, str] = {}
    for stratum in sorted(by_stratum):
        members = by_stratum[stratum]
        # a stratum-local random stream, so adding a source later leaves the other strata untouched
        random.Random(f"{seed}|{stratum}").shuffle(members)
        n_train, n_val, _ = _shares(len(members), ratios)
        for position, key in enumerate(members):
            assignment[key] = ("train" if position < n_train
                               else ("val" if position < n_train + n_val else "test"))
    return assignment


def split_rows(rows: list[dict], ratios: tuple[float, float, float] = DEFAULT_RATIOS,
               seed: int = DEFAULT_SEED) -> tuple[dict[str, list[dict]], list[dict], dict[str, str]]:
    """Return ({split: rows}, unlabelled rows, {group: split})."""
    labelled = [row for row in rows if not _is_unlabelled(row)]
    unlabelled = [row for row in rows if _is_unlabelled(row)]

    groups = group_rows(labelled)
    assignment = assign_splits(groups, ratios, seed)

    parts: dict[str, list[dict]] = {name: [] for name in SPLITS}
    for key, records in groups.items():
        parts[assignment[key]].extend(records)
    for name in SPLITS:
        parts[name].sort(key=lambda row: str(row.get("listing_id")))   # stable file, readable diffs
    return parts, unlabelled, assignment


# ------------------------------------------------------------------ reporting
def summarise(parts: dict[str, list[dict]], unlabelled: list[dict], assignment: dict[str, str],
              master_rows: int, ratios: tuple[float, float, float], seed: int) -> dict:
    """The numbers the report has to quote: shares, group integrity, price mix, platforms, flags."""
    def price_stats(rows: list[dict]) -> dict:
        prices = []
        for row in rows:
            try:
                value = float(str(row.get("price_vnd")).strip())
            except (TypeError, ValueError):
                continue
            if value > 0:
                prices.append(value)
        if not prices:
            return {"count": 0}
        prices.sort()
        return {"count": len(prices), "median": int(median(prices)),
                "p10": int(_quantile(prices, 0.10)), "p90": int(_quantile(prices, 0.90))}

    total = sum(len(rows) for rows in parts.values())
    summary = {
        "master_rows": master_rows,
        "labelled_rows": total,
        "unlabelled_rows": len(unlabelled),
        "groups": len(assignment),
        "seed": seed,
        "ratios_requested": dict(zip(SPLITS, ratios)),
        "ratios_achieved": {name: round(len(rows) / total, 4) if total else 0
                            for name, rows in parts.items()},
    }
    for name in SPLITS:
        rows = parts[name]
        groups_here = {str(row.get("duplicate_group_id")) for row in rows}
        summary[name] = {
            "rows": len(rows),
            "groups": len(groups_here),
            "platforms": dict(Counter(str(row.get("source_platform")) for row in rows).most_common()),
            "price": price_stats(rows),
            "flagged_rows": sum(1 for row in rows if str(row.get("quality_flags") or "").strip()),
        }
    return summary


def print_summary(summary: dict) -> None:
    total = summary["labelled_rows"] or 1
    print(f"\n{'=' * 78}")
    print("TRAIN / VAL / TEST — grouped by duplicate_group_id, stratified by price decile")
    print("=" * 78)
    print(f"  master rows      {summary['master_rows']:>7,}")
    print(f"  labelled         {summary['labelled_rows']:>7,}   (regression rows with a definite price)")
    print(f"  unlabelled       {summary['unlabelled_rows']:>7,}   -> unlabelled.csv (no target)")
    print(f"  groups           {summary['groups']:>7,}   (a group never crosses partitions)")
    print(f"  seed             {summary['seed']}")
    print(f"\n  {'split':6s} {'rows':>7s} {'share':>7s} {'groups':>7s} {'median':>13s} "
          f"{'p10':>12s} {'p90':>13s}")
    for name in SPLITS:
        info = summary[name]
        price = info["price"]
        print(f"  {name:6s} {info['rows']:>7,} {info['rows'] / total * 100:6.1f}% {info['groups']:>7,} "
              f"{price.get('median', 0):>13,} {price.get('p10', 0):>12,} {price.get('p90', 0):>13,}")
    print("\n  Platform mix (should look alike across the three partitions):")
    for name in SPLITS:
        mix = summary[name]["platforms"]
        count = summary[name]["rows"] or 1
        shown = ", ".join(f"{key} {value / count * 100:.0f}%" for key, value in list(mix.items())[:5])
        print(f"    {name:6s} {shown}")
    print("\n  Next: fit every imputation/encoding statistic on train only, then apply it to val/test.")


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Split the Master Dataset into train/val/test (grouped)")
    parser.add_argument("--master", default=str(config.DATA_MASTER / "master_clean_dataset.csv"))
    parser.add_argument("--out-dir", default=str(config.DATA_MASTER))
    parser.add_argument("--ratios", nargs=3, type=float, default=list(DEFAULT_RATIOS),
                        metavar=("TRAIN", "VAL", "TEST"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    ratios = tuple(args.ratios)
    if abs(sum(ratios) - 1.0) > 1e-6:
        parser.error(f"--ratios must sum to 1.0 (got {sum(ratios):.3f})")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    master = Path(args.master)
    if not master.exists():
        log.error("master dataset not found: %s -> run 'python -m src.merge.build_master'", master)
        return 1

    rows, fieldnames = load_master(master)
    parts, unlabelled, assignment = split_rows(rows, ratios, args.seed)
    if not parts["train"]:
        log.error("train partition is empty — check the master file")
        return 1

    # Integrity gate: the whole point of the split, checked rather than assumed.
    seen: dict[str, str] = {}
    for name in SPLITS:
        for row in parts[name]:
            key = str(row.get("duplicate_group_id"))
            if seen.setdefault(key, name) != name:
                log.error("group %s appears in both %s and %s — refusing to write a leaking split",
                          key, seen[key], name)
                return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: storage.save_csv(parts[name], name, fieldnames, directory=out_dir)
             for name in SPLITS}
    paths["unlabelled"] = storage.save_csv(unlabelled, "unlabelled", fieldnames, directory=out_dir)

    summary = summarise(parts, unlabelled, assignment, len(rows), ratios, args.seed)
    summary["files"] = {name: str(path) for name, path in paths.items()}
    summary_path = out_dir / "split_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print_summary(summary)
    print(f"\n  files: {', '.join(p.name for p in paths.values())} + {summary_path.name}")
    print(f"  dir  : {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
