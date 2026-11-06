"""Cardinality study (plan §4.1): which encoding of the brand/model signal actually wins?

Three encodings of the same information, everything else held fixed, scored on the frozen val split:

1. `model` as a native categorical — the highest-cardinality column we have.
2. `model_group` as a native categorical — the coarse bucket.
3. `brand|model` target encoding computed **out-of-fold on train only** (smoothed, unseen → train mean).

Writes `data/master/cardinality_study.json` and `docs/cardinality_research.md`.

Run:
    python -m tools.cardinality_study
    python -m tools.cardinality_study --rows 20000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402

SMOOTHING = 20.0


def target_encode(train: pd.DataFrame, other: pd.DataFrame,
                  folds: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """Smoothed out-of-fold encoding of brand|model; the val side uses the full-train map."""
    from sklearn.model_selection import GroupKFold

    keys = train["brand"].astype(str) + "|" + train["model"].astype(str)
    y = np.log(train[common.TARGET].to_numpy(dtype=float))
    prior, encoded = float(y.mean()), np.full(len(train), np.nan)
    groups = train[common.GROUP].astype(str).to_numpy()
    for fit_index, hold_index in GroupKFold(n_splits=folds, shuffle=True, random_state=42).split(
            keys, y, groups):
        sums = pd.Series(y[fit_index]).groupby(keys.iloc[fit_index]).sum()
        counts = pd.Series(y[fit_index]).groupby(keys.iloc[fit_index]).size()
        means = (sums + SMOOTHING * prior) / (counts + SMOOTHING)
        encoded[hold_index] = keys.iloc[hold_index].map(means).fillna(prior).to_numpy()
    sums = pd.Series(y).groupby(keys).sum()
    counts = pd.Series(y).groupby(keys).size()
    full_map = (sums + SMOOTHING * prior) / (counts + SMOOTHING)
    other_keys = other["brand"].astype(str) + "|" + other["model"].astype(str)
    return encoded, other_keys.map(full_map).fillna(prior).to_numpy()


def score(train: pd.DataFrame, val: pd.DataFrame, columns: list[str], seed: int = 42) -> dict:
    """One LightGBM fit on the given columns; the remaining features are identical across encodings."""
    import lightgbm as lgb

    x_train, x_val = train[columns].copy(), val[columns].copy()
    for column in columns:
        if not pd.api.types.is_numeric_dtype(x_train[column]):
            x_train[column] = x_train[column].astype("category")
            x_val[column] = x_val[column].astype("category").cat.set_categories(
                x_train[column].cat.categories)
    categorical = [column for column in columns if str(x_train[column].dtype) == "category"]
    model = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.05, num_leaves=63,
                              min_child_samples=40, random_state=seed, n_jobs=-1, verbose=-1)
    model.fit(x_train, np.log(train[common.TARGET].to_numpy(dtype=float)),
              categorical_feature=categorical)
    return common.metrics(val[common.TARGET], np.exp(model.predict(x_val)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brand/model encoding study on the val split")
    parser.add_argument("--features", default="full", choices=common.VARIANTS)
    parser.add_argument("--rows", type=int, default=20000)
    parser.add_argument("--out", default=str(config.DATA_MASTER / "cardinality_study.json"))
    parser.add_argument("--doc", default="docs/cardinality_research.md")
    args = parser.parse_args(argv)

    train = common.load_split(args.features, "train", args.rows)
    val = common.load_split(args.features, "val")
    keep = [column for column in train.columns
            if column not in (*common.ID_COLUMNS, common.TARGET, "brand", "model", "model_group")]
    train_oof, val_encoded = target_encode(train, val)
    results = {
        "target_encoded_brand_model": score(
            train.assign(target_brand_model=train_oof),
            val.assign(target_brand_model=val_encoded), keep + ["target_brand_model"]),
        "model_categorical": score(train, val, keep + ["model"]),
        "model_group_categorical": score(train, val, keep + ["model_group"]),
        "brand_and_model_categorical": score(train, val, keep + ["brand", "model"]),
    }
    cardinality = {"brand": int(train["brand"].nunique()), "model": int(train["model"].nunique()),
                   "model_group": int(train["model_group"].nunique()),
                   "brand|model": int((train["brand"].astype(str) + "|"
                                       + train["model"].astype(str)).nunique())}
    best = max(results, key=lambda key: results[key]["r2_log"])
    payload = {"variant": args.features, "train_rows": int(len(train)), "val_rows": int(len(val)),
               "cardinality": cardinality, "smoothing": SMOOTHING,
               "note": "identical remaining features; only the brand/model encoding changes",
               "results": results, "best": best}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    doc = Path(args.doc)
    if not doc.is_absolute():
        doc = Path(__file__).resolve().parents[1] / doc
    doc.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Brand/model cardinality study", "",
             f"{len(train):,} train rows, {len(val):,} val rows, LightGBM with identical remaining "
             "features. Only the brand/model encoding changes.", "",
             f"Cardinality on train: `brand` {cardinality['brand']:,} · `model` {cardinality['model']:,} · "
             f"`model_group` {cardinality['model_group']:,} · "
             f"`brand|model` {cardinality['brand|model']:,}.", "",
             "| Encoding | R²(log) | RMSE(log) | MAE (VND) | MAPE | median APE |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, metrics in sorted(results.items(), key=lambda item: -item[1]["r2_log"]):
        lines.append(f"| {name} | {metrics['r2_log']:.4f} | {metrics['rmse_log']:.4f} | "
                     f"{metrics['mae_vnd']:,} | {metrics['mape']:.3f} | {metrics['median_ape']:.3f} |")
    lines += ["", f"**Conclusion: `{best}` wins on val.** "
              + ("The smoothed out-of-fold target encoding is the strongest option, which is why the "
                 "preprocessor keeps it as `target__brand_model_log`."
                 if best == "target_encoded_brand_model" else
                 "The plain categorical wins at this cardinality, so the report must not claim the "
                 "target encoding is improving accuracy — it is a variance-control choice."),
              "", "The encoding is fitted inside each of 5 grouped folds on train only, so the val "
              "number is not inflated by a row's own target.", ""]
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"best: {best}  R2(log) {results[best]['r2_log']:.4f}")
    for name, metrics in sorted(results.items(), key=lambda item: -item[1]["r2_log"]):
        print(f"  {name:28s} R2(log) {metrics['r2_log']:.4f}  MAPE {metrics['mape']:.3f}")
    print(f"\n  json -> {args.out}\n  doc  -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
