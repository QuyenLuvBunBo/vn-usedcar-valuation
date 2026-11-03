"""Week 3: turn the frozen cohort into a feature table.

Two kinds of transformation live here, and the difference is the whole point of the module:

* **stateless** — a value computed from the row itself (`vehicle_age`, `km_per_year`, `age_band`,
  `engine_per_seat`, `is_luxury_segment`). Running it on train or on test gives the same answer.
* **fitted** — a value that depends on other rows (`brand_retention_rate`, `province_price_index`,
  `province_group`). These are **learned on train only** and then applied unchanged to val/test; the
  learned statistics are written to `data/master/feature_stats.json` so the report can quote them and
  so a re-run is reproducible.

What is deliberately **not** here: encoding. One-hot, ordinal and target encoding all have to be fitted
inside the training fold (`src/features/pipeline.py`), so baking them into a CSV would leak the
validation set into the features. This module emits typed columns; the pipeline decides how to encode
them, per model.

Run:
    python -m src.features.build_features --features minimal     # raw columns only (day-1 baseline)
    python -m src.features.build_features --features full        # + derived and fitted features
    python -m src.features.build_features --features full --split train   # one partition

Writes: `data/master/{train,val,test}_features_<variant>.csv`, `data/master/feature_stats.json`,
`data/master/features_manifest.json`.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..common import config

log = logging.getLogger("features")

SPLITS = ("train", "val", "test")
TARGET = "price_vnd"
ID_COLUMNS = ("listing_id", "duplicate_group_id")

# Raw columns a model may use, exactly as the cohort provides them.
BASE_CATEGORICAL = ("brand", "model", "model_group", "transmission", "fuel_type", "origin",
                    "body_type", "seller_type", "source_platform")
BASE_NUMERIC = ("manufacture_year", "mileage_km", "engine_capacity", "seats")

# `is_luxury_segment` is a rule, not a learned statistic: a brand list, never a price threshold.
# Using the price to define "luxury" would put the target on both sides of the model.
LUXURY_BRANDS = ("Mercedes-Benz", "BMW", "Audi", "Lexus", "Porsche", "Land Rover", "Jaguar",
                 "Volvo", "Infiniti", "Acura", "Cadillac", "Tesla", "Maserati", "Bentley",
                 "Rolls-Royce", "Ferrari", "Lamborghini", "McLaren", "Genesis", "MINI")

AGE_BANDS = ((0, 2, "0-2"), (3, 5, "3-5"), (6, 9, "6-9"), (10, 14, "10-14"), (15, 99, "15+"))
MIN_PROVINCE_ROWS = 50        # a province thinner than this joins "Other"
MIN_BRAND_ROWS = 20           # a brand thinner than this in either age band uses the global rate
SHRINK_K = 50                 # how far a province median is pulled toward the global median


def load(split: str) -> pd.DataFrame:
    """Read one cohort partition, with the numeric columns actually numeric."""
    path = config.DATA_MASTER / f"{split}_cohort_imputed.csv"
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.data_prep.pipeline' first")
    frame = pd.read_csv(path, low_memory=False)
    missing = [column for column in (TARGET, "manufacture_year", "mileage_km")
               if column not in frame.columns]
    if missing:
        raise SystemExit(f"{path.name} lacks {missing}")
    return frame


def capture_year(frame: pd.DataFrame) -> int:
    """Latest capture year in the data — vehicle age is measured against it, not against today."""
    years = pd.to_numeric(frame["scraped_at"].astype(str).str[:4], errors="coerce").dropna()
    return int(years.max()) if len(years) else 2026


def add_stateless(frame: pd.DataFrame, reference_year: int) -> pd.DataFrame:
    """Derived columns that depend only on the row (safe to compute per split)."""
    out = frame.copy()
    age = reference_year - pd.to_numeric(out["manufacture_year"], errors="coerce")
    out["vehicle_age"] = age.clip(lower=0)
    out["km_per_year"] = (pd.to_numeric(out["mileage_km"], errors="coerce")
                          / out["vehicle_age"].clip(lower=1))
    out["engine_per_seat"] = (pd.to_numeric(out["engine_capacity"], errors="coerce")
                              / pd.to_numeric(out["seats"], errors="coerce").replace(0, pd.NA))
    out["is_luxury_segment"] = out["brand"].isin(LUXURY_BRANDS).map({True: "yes", False: "no"})

    bands = pd.Series("unknown", index=out.index, dtype="object")
    for low, high, label in AGE_BANDS:
        bands[(age >= low) & (age <= high)] = label
    out["age_band"] = bands
    out["brand_age_band"] = out["brand"].astype(str) + "|" + out["age_band"]

    imputed = out["imputed"].fillna("").astype(str)
    out["n_imputed"] = imputed.apply(lambda cell: len([part for part in cell.split(";") if part]))
    return out


def fit_stats(train: pd.DataFrame, reference_year: int) -> dict:
    """Learn the row-independent statistics **on train only**.

    Three things are learned, and each is a place where a leak would hide:
      * `province_group` — provinces with enough train rows keep their own label, the rest share
        "Other" (the cut is a train frequency, not a property of the test row);
      * `brand_retention_rate` — how much of its price a brand keeps between age 1-2 and 5-6;
      * `province_price_index` — the median price of a province relative to the national median,
        shrunk toward the national value when the province is thin.
    """
    frame = train.copy()
    price = pd.to_numeric(frame[TARGET], errors="coerce")
    frame["_price"] = price
    frame["_age"] = reference_year - pd.to_numeric(frame["manufacture_year"], errors="coerce")
    frame["_log_price"] = np.log(price.where(price > 0))

    counts = frame["location_province"].fillna("Unknown").value_counts()
    keep = [name for name, count in counts.items() if count >= MIN_PROVINCE_ROWS]

    young = frame[frame["_age"].between(1, 2)]
    older = frame[frame["_age"].between(5, 6)]
    young_median = young.groupby("brand")["_price"].agg(["size", "median"])
    older_median = older.groupby("brand")["_price"].agg(["size", "median"])
    retention: dict[str, float] = {}
    for brand, row in young_median.iterrows():
        if brand not in older_median.index or row["size"] < MIN_BRAND_ROWS:
            continue
        old = older_median.loc[brand]
        if old["size"] < MIN_BRAND_ROWS or not row["median"] > 0:
            continue
        retention[str(brand)] = round(min(max(float(old["median"] / row["median"]), 0.05), 1.0), 4)

    global_retention = 0.7
    if len(young) and len(older) and young["_price"].median() > 0:
        global_retention = float(older["_price"].median() / young["_price"].median())
    global_retention = round(min(max(global_retention, 0.05), 1.0), 4)

    global_log = float(frame["_log_price"].median()) if frame["_log_price"].notna().any() else 0.0
    index: dict[str, float] = {}
    for province in keep:
        rows = frame.loc[frame["location_province"] == province, "_log_price"].dropna()
        if not len(rows):
            continue
        shrunk = (float(rows.median()) * len(rows) + global_log * SHRINK_K) / (len(rows) + SHRINK_K)
        index[province] = round(float(np.exp(shrunk - global_log)), 4)

    return {
        "reference_year": reference_year,
        "province_rows_min": MIN_PROVINCE_ROWS,
        "brand_rows_min": MIN_BRAND_ROWS,
        "shrink_k": SHRINK_K,
        "provinces_kept": keep,
        "brand_retention_rate": retention,
        "brand_retention_default": global_retention,
        "province_price_index": index,
        "province_price_index_default": 1.0,
        "fitted_on": "train",
        "train_rows": int(len(frame)),
    }



def apply_stats(frame: pd.DataFrame, stats: dict) -> pd.DataFrame:
    """Apply the train-fitted statistics unchanged (no fitting happens here)."""
    out = frame.copy()
    kept = set(stats["provinces_kept"])
    out["province_group"] = out["location_province"].where(
        out["location_province"].isin(kept), "Other")
    out["brand_retention_rate"] = (out["brand"].map(stats["brand_retention_rate"])
                                   .fillna(stats["brand_retention_default"]))
    out["province_price_index"] = (out["location_province"]
                                   .map(stats["province_price_index"])
                                   .fillna(stats["province_price_index_default"]))
    return out


VARIANT_COLUMNS = {
    "minimal": {
        "categorical": (*BASE_CATEGORICAL, "location_province"),
        "numeric": BASE_NUMERIC,
    },
    "full": {
        "categorical": (*BASE_CATEGORICAL, "province_group", "age_band", "brand_age_band",
                        "is_luxury_segment"),
        "numeric": (*BASE_NUMERIC, "vehicle_age", "km_per_year", "engine_per_seat", "n_imputed",
                    "brand_retention_rate", "province_price_index"),
    },
}

# Which group each feature belongs to, for the drop-one ablation study (report §4). Sorted by the
# question each group answers: does the model need the car's identity, its specs, its age, or the
# market aggregates derived from train?
ABLATION_GROUPS = {
    "cat_identity": ("brand", "model", "model_group"),
    "cat_spec": ("transmission", "fuel_type", "origin", "body_type", "seller_type",
                 "source_platform"),
    "raw_numeric": ("manufacture_year", "mileage_km", "engine_capacity", "seats"),
    "derived_age": ("vehicle_age", "km_per_year", "age_band"),
    "derived_engine_per_seat": ("engine_per_seat",),
    "derived_missing": ("n_imputed",),
    "derived_luxury": ("is_luxury_segment",),
    "derived_brand_age": ("brand_age_band",),
    "derived_geo": ("province_group", "province_price_index"),
    "derived_retention": ("brand_retention_rate",),
}


def as_features(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Select `columns` and give the text ones the `category` dtype LightGBM expects."""
    x = frame[columns].copy()
    for column in x.columns:
        if not pd.api.types.is_numeric_dtype(x[column]):
            x[column] = x[column].astype("category")
    return x


def score_r2(train: pd.DataFrame, val: pd.DataFrame, columns: list[str], seed: int = 42,
             n_estimators: int = 200) -> float:
    """R² in log space from one small LightGBM fit.

    A **relative** diagnostic, not a benchmark: the parameters are fixed and small on purpose, so the
    comparison between "with" and "without" a feature group is fair while the absolute number is not
    quotable as a result.
    """
    import lightgbm as lgb

    x_train = as_features(train, columns)
    x_val = as_features(val, columns)
    for column in x_train.columns:            # a level only val has must not break the fit
        if isinstance(x_train[column].dtype, pd.CategoricalDtype):
            x_val[column] = x_val[column].astype("category").cat.set_categories(
                x_train[column].cat.categories)

    y_train = np.log(train[TARGET].to_numpy(dtype=float))
    y_val = np.log(val[TARGET].to_numpy(dtype=float))
    model = lgb.LGBMRegressor(n_estimators=n_estimators, learning_rate=0.08, num_leaves=31,
                              min_child_samples=20, subsample=0.9, subsample_freq=1,
                              colsample_bytree=0.9, random_state=seed, n_jobs=-1, verbose=-1)
    model.fit(x_train, y_train,
              categorical_feature=[c for c in x_train.columns
                                   if isinstance(x_train[c].dtype, pd.CategoricalDtype)])
    predicted = model.predict(x_val)
    ss_res = float(((y_val - predicted) ** 2).sum())
    ss_tot = float(((y_val - y_val.mean()) ** 2).sum())
    return 1 - ss_res / ss_tot if ss_tot else float("nan")


def ablate_tables(train: pd.DataFrame, val: pd.DataFrame, variant: str = "full",
                  groups: dict[str, tuple[str, ...]] | None = None,
                  rows: int = 20_000, seed: int = 42) -> dict:
    """Drop one feature group at a time and report what R² it was worth.

    `delta_r2 = baseline − without_group`, so a **positive** number means the group earns its place and
    a number near zero means the model already has that information from another column (which is what
    `brand_age_band` vs `brand` is there to reveal). The fits use a sample of the train rows and a fixed
    small booster: this is a diagnostic for report §4, not the benchmark table.
    """
    groups = ABLATION_GROUPS if groups is None else groups
    columns = [*VARIANT_COLUMNS[variant]["categorical"], *VARIANT_COLUMNS[variant]["numeric"]]
    if rows and len(train) > rows:
        train = train.sample(n=rows, random_state=seed)

    started = time.monotonic()
    baseline = score_r2(train, val, columns, seed)
    results: list[dict] = []
    for name, members in groups.items():
        kept = [column for column in columns if column not in members]
        if not kept:
            results.append({"group": name, "dropped": list(members), "r2": None, "delta_r2": None})
            continue
        score = score_r2(train, val, kept, seed)
        results.append({"group": name, "dropped": list(members), "r2": round(score, 4),
                        "delta_r2": round(baseline - score, 4)})
    results.sort(key=lambda row: (row["delta_r2"] is None, -(row["delta_r2"] or 0)))
    return {
        "variant": variant,
        "train_rows": int(len(train)),
        "val_rows": int(len(val)),
        "n_features": len(columns),
        "baseline_r2": round(baseline, 4),
        "seconds": round(time.monotonic() - started, 1),
        "note": "drop-one at a time with a fixed small LightGBM — relative value, not the benchmark",
        "groups": results,
    }


def ablate(variant: str = "full", rows: int = 20_000, out: Path | None = None) -> dict:
    """Load the cohort, build the features, run the study, write `feature_ablation.json`."""
    train, val = load("train"), load("val")
    reference = capture_year(train)
    stats = fit_stats(train, reference)
    train = apply_stats(add_stateless(train, reference), stats)
    val = apply_stats(add_stateless(val, reference), stats)

    report = ablate_tables(train, val, variant, rows=rows)
    path = out or (config.DATA_MASTER / "feature_ablation.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ABLATION ({variant}): baseline R²(log) {report['baseline_r2']:.4f} on "
          f"{report['train_rows']:,} train rows / {report['val_rows']:,} val rows "
          f"({report['seconds']} s)")
    print(f"  {'dropped group':26s} {'R² without':>11s} {'ΔR²':>8s}  columns")
    for row in report["groups"]:
        delta = "  n/a" if row["delta_r2"] is None else f"{row['delta_r2']:+.4f}"
        score = "n/a" if row["r2"] is None else f"{row['r2']:.4f}"
        print(f"  {row['group']:26s} {score:>11s} {delta:>8s}  {', '.join(row['dropped'])}")
    print(f"\n  wrote {path}")
    print("  ΔR² > 0: the group earns its place · ΔR² ≈ 0: the model already has that information")
    return report




def build(variant: str, splits: tuple[str, ...] = SPLITS) -> dict:
    """Build the feature table(s); the statistics are always fitted on `train`."""
    if variant not in VARIANT_COLUMNS:
        raise SystemExit(f"unknown variant {variant!r}; choose from {sorted(VARIANT_COLUMNS)}")
    frames = {split: load(split) for split in splits}
    if "train" not in frames:
        raise SystemExit("the statistics are fitted on train only — include the train split")

    reference_year = capture_year(frames["train"])
    stats = fit_stats(frames["train"], reference_year)
    columns = VARIANT_COLUMNS[variant]
    kept = [*ID_COLUMNS, TARGET, *columns["categorical"], *columns["numeric"]]

    out_dir = config.DATA_MASTER
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for split, frame in frames.items():
        prepared = apply_stats(add_stateless(frame, reference_year), stats)
        missing = [column for column in kept if column not in prepared.columns]
        if missing:
            raise SystemExit(f"{split}: the cohort lacks {missing}; cannot build '{variant}'")
        table = prepared[kept]
        path = out_dir / f"{split}_features_{variant}.csv"
        table.to_csv(path, index=False, encoding="utf-8-sig")
        written[split] = {"path": str(path), "rows": int(len(table)),
                          "missing_rate": {c: round(float(table[c].isna().mean()), 4)
                                           for c in columns["numeric"]}}
        print(f"  {split:5s} {len(table):>7,} rows x {len(table.columns):>2} cols -> {path.name}")

    (out_dir / "feature_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
    manifest = {
        "variant": variant,
        "reference_year": reference_year,
        "target": TARGET,
        "ids": list(ID_COLUMNS),
        "categorical": list(columns["categorical"]),
        "numeric": list(columns["numeric"]),
        "fitted_on": "train",
        "stats_file": str(out_dir / "feature_stats.json"),
        "splits": written,
    }
    (out_dir / "features_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the week-3 feature tables from the frozen cohort")
    parser.add_argument("--features", choices=sorted(VARIANT_COLUMNS), default="full",
                        help="minimal = raw columns only; full = raw + derived and fitted features")
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="all")
    parser.add_argument("--ablate", action="store_true",
                        help="drop one feature group at a time and report ΔR² (needs lightgbm)")
    parser.add_argument("--ablate-rows", type=int, default=20_000,
                        help="train rows sampled for the ablation fits (0 = all rows)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.ablate:
        ablate(args.features, rows=args.ablate_rows)
        return 0
    splits = SPLITS if args.split == "all" else ("train",) if args.split == "train" \
        else ("train", args.split)
    splits = tuple(dict.fromkeys(splits))          # the stats come from train, always
    manifest = build(args.features, splits)

    categorical = manifest["categorical"]
    numeric = manifest["numeric"]
    print(f"\n  variant '{manifest['variant']}': target={manifest['target']}, "
          f"{len(categorical)} categorical + {len(numeric)} numeric features")
    print(f"  statistics fitted on train only -> {Path(manifest['stats_file']).name}")
    print(f"  manifest: {Path(manifest['stats_file']).parent / 'features_manifest.json'}")
    print("\n  next: python -m tools.model_gate --features data/master/train_features_"
          f"{manifest['variant']}.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


