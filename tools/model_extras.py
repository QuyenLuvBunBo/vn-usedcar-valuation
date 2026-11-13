"""Importance, partial dependence, seed stability and the learning curve (plan §4.2, Duy's items).

Everything is measured on the frozen val split with the same LightGBM configuration used elsewhere,
so the numbers in §4–5 of the report can be reproduced by one command.

    data/master/feature_importance.csv   permutation importance (mean ± sd over 5 shuffles)
    data/master/model_extras.json        PD tables, seed stability, learning curve
    docs/model_extras.md                 the same numbers as tables

Run:
    python -m tools.model_extras
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

REPO = Path(__file__).resolve().parents[1]


def _lightgbm(seed: int = 42, n_estimators: int = 500):
    import lightgbm as lgb
    return lgb.LGBMRegressor(n_estimators=n_estimators, learning_rate=0.05, num_leaves=63,
                             min_child_samples=40, subsample=0.9, subsample_freq=1,
                             colsample_bytree=0.8, random_state=seed, n_jobs=-1, verbose=-1)


def _fit(x_train, y_train, seed: int = 42, n_estimators: int = 500):
    categorical = [column for column in x_train.columns
                   if isinstance(x_train[column].dtype, pd.CategoricalDtype)]
    model = _lightgbm(seed, n_estimators)
    model.fit(x_train, y_train, categorical_feature=categorical)
    return model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importance, PD, seed stability, learning curve")
    parser.add_argument("--features", default="full", choices=common.VARIANTS)
    parser.add_argument("--features-name", default="full")
    parser.add_argument("--doc", default="docs/model_extras.md")
    args = parser.parse_args(argv)

    train_frame = common.load_split(args.features, "train")
    val_frame = common.load_split(args.features, "val")
    x_train, y_train = common.split_xy(train_frame)
    x_val, y_val = common.split_xy(val_frame)
    x_train, x_val = common.align_categories(x_train, x_val)
    y_train_log = np.log(y_train.to_numpy(dtype=float))

    model = _fit(x_train, y_train_log)
    base_pred = np.exp(model.predict(x_val))
    base = common.metrics(y_val, base_pred)
    print(f"baseline lightgbm/{args.features}: R2(log) {base['r2_log']:.4f}  MAPE {base['mape']:.3f}")

    # 1 — permutation importance on a 4,000-row slice, so 23 features x 5 shuffles stays quick
    from sklearn.inspection import permutation_importance
    index = np.random.RandomState(42).choice(len(x_val), min(4000, len(x_val)), replace=False)
    x_slice, y_slice = x_val.iloc[index], np.log(y_val.to_numpy(dtype=float))[index]
    importance = permutation_importance(model, x_slice, y_slice, n_repeats=5,
                                        random_state=42, n_jobs=-1,
                                        scoring="neg_mean_squared_error")
    table = pd.DataFrame({"feature": x_val.columns,
                          "importance": np.sqrt(importance.importances_mean),
                          "std": np.sqrt(np.abs(importance.importances_std))})
    table = table.sort_values("importance", ascending=False)
    table.to_csv(config.DATA_MASTER / "feature_importance.csv", index=False, lineterminator="\n")
    top = table.head(12)

    # 2 — partial dependence for the three strongest features, computed by hand so the axis is readable
    pd_rows = []
    for feature in table["feature"].head(3):
        column = x_val[feature]
        if isinstance(column.dtype, pd.CategoricalDtype):
            levels = column.value_counts().head(5).index.tolist()
            grid = [(str(level), (column == level).mean()) for level in levels]
        else:
            grid = [(float(value), float((column <= value).mean()))
                    for value in column.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(4)]
        for value, support in grid:
            probe = x_val.copy()
            probe[feature] = value
            # keep the column dtype: assigning a scalar turns a categorical into object and LightGBM
            # then rejects the frame ("categorical_feature do not match")
            probe[feature] = probe[feature].astype(x_val[feature].dtype)
            mean_price = float(np.exp(model.predict(probe)).mean())
            pd_rows.append({"feature": feature, "value": value, "mean_prediction_vnd": mean_price,
                            "support_share": round(float(support), 4)})

    # 3 — seed stability: three seeds on a 20k slice, so the spread is about the seed, not the runtime
    sample = np.random.RandomState(42).choice(len(x_train), min(20000, len(x_train)), replace=False)
    seed_scores = []
    for seed in (42, 43, 44):
        fitted = _fit(x_train.iloc[sample], y_train_log[sample], seed=seed, n_estimators=300)
        seed_scores.append(common.metrics(y_val, np.exp(fitted.predict(x_val)))["r2_log"])

    # 4 — learning curve at 10/25/50/100% of train
    learning = []
    for fraction in (0.1, 0.25, 0.5, 1.0):
        rows = int(len(x_train) * fraction)
        fitted = _fit(x_train.iloc[:rows], y_train_log[:rows], n_estimators=300)
        learning.append({"train_rows": rows,
                         "r2_log": common.metrics(y_val, np.exp(fitted.predict(x_val)))["r2_log"]})
        print(f"  learning curve {fraction:>4.0%} ({rows:,} rows) "
              f"R2(log) {learning[-1]['r2_log']:.4f}")

    payload = {"features": args.features, "baseline": base,
               "permutation_importance_top": top.to_dict(orient="records"),
               "partial_dependence": pd_rows,
               "seed_stability": {"seeds": [42, 43, 44], "r2_log": seed_scores,
                                  "mean": round(float(np.mean(seed_scores)), 4),
                                  "sd": round(float(np.std(seed_scores)), 4),
                                  "rows": int(len(sample)), "n_estimators": 300},
               "learning_curve": learning,
               "note": "LightGBM 500 trees for importance/PD; 300 trees for the seed and learning runs"}
    (config.DATA_MASTER / "model_extras.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    doc = Path(args.doc)
    if not doc.is_absolute():
        doc = REPO / doc
    lines = ["# Model extras — importance, partial dependence, seed stability, learning curve", "",
             f"LightGBM on `{args.features}` features. Baseline on val: R²(log) "
             f"{base['r2_log']:.4f}, MAPE {base['mape']:.1%}. Reproduce with "
             "`python -m tools.model_extras`.", "",
             "## Permutation importance (top 12, RMSE in log space)", "",
             "| Feature | Importance | sd |", "| --- | ---: | ---: |"]
    for row in top.to_dict(orient="records"):
        lines.append(f"| `{row['feature']}` | {row['importance']:.4f} | {row['std']:.4f} |")
    lines += ["", "## Partial dependence (mean predicted price while the feature is fixed)", "",
              "| Feature | Value | Mean prediction (VND) | share of val ≤ value |",
              "| --- | ---: | ---: | ---: |"]
    for row in pd_rows:
        lines.append(f"| `{row['feature']}` | {row['value']} | {int(row['mean_prediction_vnd']):,} | "
                     f"{row['support_share']:.2f} |")
    stability = payload["seed_stability"]
    lines += ["", "## Seed stability (3 seeds, 20k rows, 300 trees)", "",
              "| Seed | R²(log) |", "| ---: | ---: |"]
    for seed, score in zip(stability["seeds"], stability["r2_log"]):
        lines.append(f"| {seed} | {score:.4f} |")
    lines += ["", f"Mean {stability['mean']:.4f} ± {stability['sd']:.4f}. A spread above ~0.002 would mean "
              "model comparisons in §5 need the paired Wilcoxon test rather than a ranking by R².", "",
              "## Learning curve", "", "| Train rows | R²(log) |", "| ---: | ---: |"]
    for row in learning:
        lines.append(f"| {row['train_rows']:,} | {row['r2_log']:.4f} |")
    lines += ["", "If the last two points are within noise, more rows will not help and the report should "
              "say the ceiling is the feature set, not the sample size.", ""]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"\n  importance -> {config.DATA_MASTER / 'feature_importance.csv'}")
    print(f"  json -> {config.DATA_MASTER / 'model_extras.json'}\n  doc  -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
