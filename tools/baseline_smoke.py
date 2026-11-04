"""Day-1 smoke test: can this machine actually train on the feature table?

Not a benchmark — a **canary**. It answers three questions in under a minute, before anyone spends a
day on their own model:

1. do the feature tables load, with the target present and excluded from `X`?
2. does LightGBM fit and predict on this machine (Windows, this Python), with the categoricals passed
   natively and NaN left alone?
3. roughly how good is "no features, just the median of the same car" — the number every model has to
   beat for its extra complexity to be worth anything?

It writes `data/master/baseline_smoke.json`, deliberately **not** `model_results.json`: that file
belongs to the modelling sub-team, and this tool must not look like their work.

Run:
    python -m tools.baseline_smoke                       # minimal features, median + LightGBM
    python -m tools.baseline_smoke --features full
    python -m tools.baseline_smoke --rows 5000           # a 30-second version
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402

TARGET = "price_vnd"
ID_COLUMNS = ("listing_id", "duplicate_group_id")
OUT = "baseline_smoke.json"


def load(variant: str, rows: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    for split in ("train", "val"):
        path = config.DATA_MASTER / f"{split}_features_{variant}.csv"
        if not path.exists():
            raise SystemExit(f"missing {path} -> run 'python -m src.features.build_features "
                             f"--features {variant}'")
        frame = pd.read_csv(path, low_memory=False)
        if rows and split == "train":
            frame = frame.sample(n=min(rows, len(frame)), random_state=42)
        frames.append(frame)
    return frames[0], frames[1]


def split_xy(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Everything except the ids and the target is a feature — the gate enforces that promise."""
    features = [column for column in frame.columns if column not in (*ID_COLUMNS, TARGET)]
    x = frame[features].copy()
    for column in x.columns:
        # pandas 3 gives text columns the `str` dtype, not `object`, so ask "is it numeric?" instead
        if not pd.api.types.is_numeric_dtype(x[column]):
            x[column] = x[column].astype("category")
    return x, frame[TARGET]


def metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict:
    """Log-space R²/RMSE (what the model optimises) and VND-space MAE/MAPE (what a reader feels)."""
    true_log = np.log(y_true.to_numpy(dtype=float))
    pred = np.clip(np.asarray(y_pred, dtype=float), 1.0, None)
    pred_log = np.log(pred)
    ss_res = float(((true_log - pred_log) ** 2).sum())
    ss_tot = float(((true_log - true_log.mean()) ** 2).sum())
    return {
        "r2_log": round(1 - ss_res / ss_tot, 4) if ss_tot else float("nan"),
        "rmse_log": round(math.sqrt(ss_res / len(true_log)), 4),
        "mae_vnd": int(round(float(np.abs(y_true.to_numpy() - pred).mean()))),
        "mape": round(float((np.abs(y_true.to_numpy() - pred) / y_true.to_numpy()).mean()), 4),
    }


def median_baseline(train: pd.DataFrame, val: pd.DataFrame) -> dict:
    """Median asking price of the same brand+model+year, fitted on train, with two fallbacks."""
    keys = ["brand", "model", "manufacture_year"]
    grouped = train.groupby(keys, dropna=False)[TARGET].median()
    by_brand = train.groupby("brand")[TARGET].median()
    overall = float(train[TARGET].median())

    def predict(row: pd.Series) -> float:
        if pd.notna(row["manufacture_year"]):
            key = (row["brand"], row["model"], row["manufacture_year"])
            if key in grouped.index:
                return float(grouped.loc[key])
        return float(by_brand.get(row["brand"], overall))

    started = time.monotonic()
    predicted = val.apply(predict, axis=1).to_numpy()
    return {"model": "median_brand_model_year", "seconds": round(time.monotonic() - started, 2),
            **metrics(val[TARGET], predicted)}


def lightgbm_baseline(train: pd.DataFrame, val: pd.DataFrame, n_estimators: int = 400) -> dict:
    """LightGBM with its own categorical handling — no imputation, no encoding, no tuning."""
    import lightgbm as lgb

    x_train, y_train = split_xy(train)
    x_val, y_val = split_xy(val)
    # align the categorical levels so val cannot introduce a level train never saw (unseen -> NaN)
    for column in x_train.columns:
        if isinstance(x_train[column].dtype, pd.CategoricalDtype):
            x_val[column] = x_val[column].astype("category").cat.set_categories(
                x_train[column].cat.categories)

    categorical = [column for column in x_train.columns if str(x_train[column].dtype) == "category"]
    model = lgb.LGBMRegressor(
        objective="regression", n_estimators=n_estimators, learning_rate=0.06, num_leaves=63,
        min_child_samples=40, subsample=0.9, subsample_freq=1, colsample_bytree=0.8,
        random_state=42, n_jobs=-1, verbose=-1,
    )
    started = time.monotonic()
    model.fit(x_train, np.log(y_train.to_numpy(dtype=float)),
              categorical_feature=categorical)
    predicted = np.exp(model.predict(x_val))
    return {"model": "lightgbm_untuned", "seconds": round(time.monotonic() - started, 2),
            "n_features": int(x_train.shape[1]), "n_categorical": len(categorical),
            **metrics(y_val, predicted)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canary: does training run here, and what beats what")
    parser.add_argument("--features", default="minimal", choices=("minimal", "full"))
    parser.add_argument("--rows", type=int, default=0, help="sample the train rows (0 = all)")
    parser.add_argument("--out", default=str(config.DATA_MASTER / OUT))
    args = parser.parse_args(argv)

    train, val = load(args.features, args.rows)
    print(f"features '{args.features}': train {len(train):,} rows | val {len(val):,} rows | "
          f"{train.shape[1]} columns")
    results = [median_baseline(train, val)]
    try:
        results.append(lightgbm_baseline(train, val))
    except ImportError:
        print("  lightgbm is not installed -> pip install -r requirements.txt")

    header = f"{'model':26s} {'R2(log)':>8s} {'RMSE(log)':>10s} {'MAE (VND)':>13s} {'MAPE':>7s} {'s':>6s}"
    print("\n" + header)
    print("-" * len(header))
    for row in results:
        print(f"{row['model']:26s} {row['r2_log']:>8.4f} {row['rmse_log']:>10.4f} "
              f"{row['mae_vnd']:>13,} {row['mape']:>7.3f} {row['seconds']:>6.1f}")

    payload = {"generated_at": config.now_iso(), "features": args.features,
               "train_rows": int(len(train)), "val_rows": int(len(val)),
               "note": "canary only — the benchmark table is the modelling sub-team's model_results.json",
               "results": results}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  wrote {args.out}")
    print("  next: the modelling sub-team replaces this with src/models/train.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

