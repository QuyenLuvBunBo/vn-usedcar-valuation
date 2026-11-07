"""Feature-group ablation: what does each group of columns actually buy?

The plan (§4.1) assigns this to team 1: *"drop-one at a time → a ΔR² table for report §4"*. It is a
**relative** measurement — one fixed estimator, one group removed at a time — not a benchmark, and the
JSON says so. The default is the plan's own configuration: a fixed small LightGBM on the full 70k train
rows (Ridge is kept as an option, but it would need a one-hot of the 3,212-level `brand|model`, which is
exactly what `src/features/pipeline.py` exists for).

Run:
    python -m tools.feature_ablation
    python -m tools.feature_ablation --estimator ridge --rows 20000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402

# All 23 feature columns, partitioned into ten groups so every column is dropped exactly once.
GROUPS = {
    "cat_identity": ["brand", "model", "model_group"],
    "cat_spec": ["transmission", "fuel_type", "origin", "body_type", "seller_type"],
    "geo": ["province_group"],
    "price_stats": ["brand_retention_rate", "province_price_index"],
    "timing": ["manufacture_year", "vehicle_age", "age_band", "brand_age_band"],
    "usage": ["mileage_km", "km_per_year"],
    "size": ["engine_capacity", "engine_per_seat", "seats"],
    "flags": ["n_imputed"],
    "luxury": ["is_luxury_segment"],
    "source": ["source_platform"],
}


def _fit_predict(x_train, y_train, x_val, y_val, estimator: str) -> float:
    """One fit, one R²(log). Small and fixed on purpose: the comparison is between column sets."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    if estimator == "ridge":
        from sklearn.linear_model import Ridge

        numeric = [c for c in x_train.columns if pd.api.types.is_numeric_dtype(x_train[c])]
        categorical = [c for c in x_train.columns if c not in numeric]
        columns = ColumnTransformer([
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")),
                              ("scale", StandardScaler())]), numeric),
            ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                              ("onehot", OneHotEncoder(handle_unknown="ignore",
                                                       sparse_output=False))]), categorical)])
        model = Pipeline([("columns", columns), ("model", Ridge(alpha=1.0))])
        model.fit(x_train, np.log(y_train.to_numpy(dtype=float)))
        return common.metrics(y_val, np.exp(model.predict(x_val)))["r2_log"]

    import lightgbm as lgb

    categorical = [c for c in x_train.columns if isinstance(x_train[c].dtype, pd.CategoricalDtype)]
    model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.06, num_leaves=63,
                              min_child_samples=40, random_state=42, n_jobs=-1, verbose=-1)
    model.fit(x_train, np.log(y_train.to_numpy(dtype=float)), categorical_feature=categorical)
    return common.metrics(y_val, np.exp(model.predict(x_val)))["r2_log"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drop-one feature-group ablation")
    parser.add_argument("--features", default="full", choices=common.VARIANTS)
    parser.add_argument("--estimator", default="lgbm", choices=("lgbm", "ridge"))
    parser.add_argument("--rows", type=int, default=0,
                        help="train rows (0 = all; the plan asks for a fixed small LightGBM on all 70k)")
    parser.add_argument("--out", default=str(config.DATA_MASTER / "feature_ablation.json"))
    parser.add_argument("--doc", default="docs/features_ablation.md")
    args = parser.parse_args(argv)

    train_frame = common.load_split(args.features, "train", args.rows)
    val_frame = common.load_split(args.features, "val")
    x_train_all, y_train = common.split_xy(train_frame)
    x_val_all, y_val = common.split_xy(val_frame)
    x_train_all, x_val_all = common.align_categories(x_train_all, x_val_all)

    started = time.monotonic()
    baseline = _fit_predict(x_train_all, y_train, x_val_all, y_val, args.estimator)
    print(f"baseline: R2(log) {baseline:.4f}  ({x_train_all.shape[1]} features, "
          f"{len(x_train_all):,} rows, {args.estimator})")

    groups = []
    for name, columns in GROUPS.items():
        present = [column for column in columns if column in x_train_all.columns]
        if not present:
            continue
        score = _fit_predict(x_train_all.drop(columns=present), y_train,
                             x_val_all.drop(columns=present), y_val, args.estimator)
        delta = round(baseline - score, 4)
        groups.append({"group": name, "dropped": present, "r2": round(score, 4), "delta_r2": delta})
        print(f"  -{name:12s} R2(log) {score:.4f}   dR2 {delta:+.4f}")

    payload = {"variant": args.features, "estimator": args.estimator,
               "train_rows": int(len(x_train_all)), "val_rows": int(len(x_val_all)),
               "n_features": int(x_train_all.shape[1]), "baseline_r2": round(baseline, 4),
               "seconds": round(time.monotonic() - started, 1),
               "note": "drop-one at a time with a fixed estimator — relative value, not the benchmark",
               "groups": sorted(groups, key=lambda item: item["delta_r2"], reverse=True)}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    doc = Path(args.doc)
    if not doc.is_absolute():
        doc = Path(__file__).resolve().parents[1] / doc
    doc.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Feature-group ablation", "",
             f"Baseline R²(log) **{baseline:.4f}** with {x_train_all.shape[1]} features, "
             f"{len(x_train_all):,} train rows, estimator **{args.estimator}** "
             f"({payload['seconds']}s total).", "",
             "Relative value only: a fixed estimator, one group removed at a time. This is not the "
             "benchmark table and does not replace it.", "",
             "| Group dropped | Columns | R²(log) without it | ΔR² |", "| --- | --- | ---: | ---: |"]
    for item in payload["groups"]:
        lines.append(f"| {item['group']} | `{'`, `'.join(item['dropped'])}` | {item['r2']:.4f} | "
                     f"{item['delta_r2']:+.4f} |")
    lines += ["", "ΔR² is the drop in R²(log) when the group is removed: a large ΔR² means the group "
              "carries weight, a near-zero or negative ΔR² means this estimator does not need it.", ""]
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"\n  json -> {args.out}\n  doc  -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
