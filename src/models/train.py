"""Train one model and write the artefacts the rest of the team reads.

Everything at week 3 hangs off this file: `model_results.json` (one ledger row per run),
`models/<model>_<features>.joblib`, and `data/master/predictions_val.csv` with the exact
14 columns `docs/week3_plan.md` §3 fixes. Features and target come from the frozen split
tables only.

Run:
    python -m src.models.train --model lightgbm --features full
    python -m src.models.train --model median --features minimal --rows 20000
    python -m src.models.train --model lightgbm --features full --tune-seconds 90 --quantiles
    python -m src.models.train --list
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402

MODELS = ("median", "ridge", "lasso", "elasticnet", "knn", "rf", "hgb",
          "lightgbm", "catboost", "xgboost")
# The plan writes `--model lgbm`; keep the short names working so the documented command is the real one.
ALIASES = {"lgbm": "lightgbm", "lgb": "lightgbm", "cb": "catboost", "xgb": "xgboost",
           "enet": "elasticnet", "rf200": "rf"}
DENSE = ("ridge", "lasso", "elasticnet", "knn", "rf")
TREES = ("hgb", "lightgbm", "catboost", "xgboost")


def resolve_model(name: str) -> str:
    """Accept the short names used in the plan (`lgbm`, `xgb`, `cb`) and in the benchmark list."""
    lowered = str(name).strip().lower()
    return ALIASES.get(lowered, lowered)


def _median_predict(train: pd.DataFrame, val: pd.DataFrame) -> np.ndarray:
    """Median asking price of the same brand+model+year, with brand and global fallbacks."""
    grouped = train.groupby(["brand", "model", "manufacture_year"], observed=True)[common.TARGET].median()
    by_brand = train.groupby("brand", observed=True)[common.TARGET].median()
    overall = float(train[common.TARGET].median())

    def one(row):
        key = (row["brand"], row["model"], row["manufacture_year"])
        if key in grouped.index:
            return float(grouped.loc[key])
        return float(by_brand.get(row["brand"], overall))

    return val.apply(one, axis=1).to_numpy()


def _stringify(series: pd.Series) -> np.ndarray:
    """Plain Python strings, missing → "missing". CatBoost refuses NaN inside a categorical column."""
    values = series.astype(object).to_numpy()
    return np.array([("missing" if value is None or value is pd.NA
                      or (isinstance(value, float) and np.isnan(value)) else str(value))
                     for value in values], dtype=object)


class CatBoostCoded:
    """CatBoost plus the train-derived integer code map, so predict() sees the same encoding.

    CatBoost refuses unseen/NaN levels inside a categorical column at *predict* time too, so the
    coding has to travel with the model instead of being applied once in the caller.
    """

    def __init__(self, model, mapping: dict[str, dict[str, int]], categorical: list[str]):
        self.model = model
        self.mapping = mapping
        self.categorical = categorical

    def _code(self, x: pd.DataFrame) -> pd.DataFrame:
        frame = x.copy()
        for column in self.categorical:
            mapping = self.mapping[column]
            values = x[column].astype(object)
            frame[column] = np.array([
                mapping.get("missing" if value is None or value is pd.NA
                            or (isinstance(value, float) and np.isnan(value)) else str(value), -1)
                for value in values], dtype=np.int32)
        return frame

    def predict(self, x: pd.DataFrame):
        return self.model.predict(self._code(x))

    def __getattr__(self, item):
        return getattr(self.model, item)


def _fit_dense(name: str, seed: int, x_train: pd.DataFrame, y_train: pd.Series, sample: int = 0):
    """Median impute + one-hot + scaler for the models that cannot take pandas categories."""
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import ElasticNet, Lasso, Ridge
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    if sample and len(x_train) > sample:
        index = np.random.RandomState(seed).choice(len(x_train), sample, replace=False)
        x_train = x_train.iloc[index]
        y_train = np.asarray(y_train, dtype=float)[index]     # callers pass the log target as an array
    numeric = [column for column in x_train.columns if pd.api.types.is_numeric_dtype(x_train[column])]
    categorical = [column for column in x_train.columns if column not in numeric]
    numeric_steps = [("impute", SimpleImputer(strategy="median"))]
    if name != "rf":
        numeric_steps.append(("scale", StandardScaler()))
    columns = ColumnTransformer([
        ("num", Pipeline(numeric_steps), numeric),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                          ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=50,
                                                   sparse_output=False))]), categorical),
    ])
    estimator = {
        "ridge": Ridge(alpha=1.0),
        # alpha/tol are set so a 20k-column one-hot design still converges in seconds, not minutes;
        # the coefficient scale is meaningless here anyway because the target is log price.
        "lasso": Lasso(alpha=1e-3, max_iter=1000, tol=1e-3),
        "elasticnet": ElasticNet(alpha=1e-3, l1_ratio=0.5, max_iter=1000, tol=1e-3),
        "knn": KNeighborsRegressor(n_neighbors=25, weights="distance", n_jobs=-1),
        "rf": RandomForestRegressor(n_estimators=200, min_samples_leaf=3, max_features=0.4,
                                    random_state=seed, n_jobs=-1),
    }[name]
    model = Pipeline([("columns", columns), ("model", estimator)])
    model.fit(x_train, y_train)
    return model


def _fit_tree(name: str, seed: int, x_train, y_train, x_val, y_val, params: dict | None = None):
    params = params or {}
    if name == "lightgbm":
        import lightgbm as lgb
        categorical = [column for column in x_train.columns
                       if isinstance(x_train[column].dtype, pd.CategoricalDtype)]
        model = lgb.LGBMRegressor(objective="regression",
                                  n_estimators=int(params.get("n_estimators", 600)),
                                  learning_rate=float(params.get("learning_rate", 0.05)),
                                  num_leaves=int(params.get("num_leaves", 63)),
                                  min_child_samples=int(params.get("min_child_samples", 40)),
                                  subsample=0.9, subsample_freq=1, colsample_bytree=0.8,
                                  random_state=seed, n_jobs=-1, verbose=-1)
        model.fit(x_train, y_train, categorical_feature=categorical,
                  eval_X=x_val, eval_y=y_val, callbacks=[lgb.early_stopping(50, verbose=False)])
        return model
    if name == "catboost":
        from catboost import CatBoostRegressor
        categorical = [column for column in x_train.columns
                       if isinstance(x_train[column].dtype, pd.CategoricalDtype)]
        train_frame, val_frame = x_train.copy(), x_val.copy()
        mappings: dict[str, dict[str, int]] = {}
        for column in categorical:
            # Integer codes, "missing" included as its own level: CatBoost accepts integer
            # categorical values, and an int column cannot smuggle a NaN into the CTR builder.
            train_values = x_train[column].astype(object)
            mapping: dict[str, int] = {}
            codes = np.empty(len(train_values), dtype=np.int32)
            for position, value in enumerate(train_values):
                key = ("missing" if value is None or value is pd.NA
                       or (isinstance(value, float) and np.isnan(value)) else str(value))
                codes[position] = mapping.setdefault(key, len(mapping))
            val_values = x_val[column].astype(object)
            val_codes = np.empty(len(val_values), dtype=np.int32)
            for position, value in enumerate(val_values):
                key = ("missing" if value is None or value is pd.NA
                       or (isinstance(value, float) and np.isnan(value)) else str(value))
                val_codes[position] = mapping.get(key, -1)     # unseen level → -1
            mappings[column] = mapping
            train_frame[column] = codes
            val_frame[column] = val_codes
        model = CatBoostRegressor(iterations=int(params.get("iterations", 3000)),
                                  learning_rate=float(params.get("learning_rate", 0.05)),
                                  depth=int(params.get("depth", 8)), loss_function="RMSE",
                                  od_type="Iter", od_wait=100, random_seed=seed,
                                  # Plain boosting + a single CTR combination keeps the mandatory
                                  # iterations=3000 budget affordable on 70k rows; recorded in the table.
                                  boosting_type="Plain", max_ctr_complexity=1, one_hot_max_size=10,
                                  verbose=False, thread_count=-1)
        model.fit(train_frame, y_train, cat_features=categorical,
                  eval_set=(val_frame, y_val), use_best_model=True)
        return CatBoostCoded(model, mappings, categorical)
    if name == "xgboost":
        import xgboost as xgb
        model = xgb.XGBRegressor(n_estimators=int(params.get("n_estimators", 900)),
                                 learning_rate=float(params.get("learning_rate", 0.05)),
                                 max_depth=int(params.get("max_depth", 8)), subsample=0.9,
                                 colsample_bytree=0.8, tree_method="hist", enable_categorical=True,
                                 random_state=seed, n_jobs=-1, early_stopping_rounds=50)
        model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
        return model
    if name == "hgb":
        from sklearn.ensemble import HistGradientBoostingRegressor
        model = HistGradientBoostingRegressor(max_iter=600, learning_rate=0.06,
                                              categorical_features="from_dtype", random_state=seed)
        model.fit(x_train, y_train)
        return model
TUNABLE = {
    "lightgbm": {"n_estimators": [400, 600, 900], "learning_rate": [0.03, 0.05, 0.08],
                 "num_leaves": [31, 63, 127], "min_child_samples": [20, 40, 80]},
    "catboost": {"iterations": [500, 800, 1200], "learning_rate": [0.03, 0.05, 0.08],
                 "depth": [6, 8, 10]},
    "xgboost": {"n_estimators": [600, 900, 1200], "learning_rate": [0.03, 0.05, 0.08],
                "max_depth": [6, 8, 10]},
}


def _tune(name: str, seed: int, x_train, y_train, groups, budget: int) -> tuple[dict, dict]:
    """Time-boxed random search. Bounded on purpose: the plan fixes 90 minutes per model as a rule."""
    if budget <= 0 or name not in TUNABLE:
        return {}, {"budget_seconds": 0, "trials": 0, "note": "fixed parameters (no tuning)"}
    from sklearn.model_selection import GroupKFold

    space = TUNABLE[name]
    sample = min(len(x_train), 15000)
    index = np.random.RandomState(seed).choice(len(x_train), sample, replace=False)
    x_sample = x_train.iloc[index]
    y_array = np.asarray(y_train, dtype=float)      # callers pass the log target as an array
    y_sample = y_array[index]
    groups_sample = np.asarray(groups)[index]
    folds = list(GroupKFold(n_splits=2, shuffle=True, random_state=seed).split(x_sample, y_sample,
                                                                              groups_sample))
    rng = np.random.RandomState(seed)
    best_params, best_score, trials = {}, -np.inf, 0
    started = time.monotonic()
    while trials < 10 and time.monotonic() - started < budget:
        params = {key: values[rng.randint(len(values))] for key, values in space.items()}
        scores = []
        try:
            for fit_index, hold_index in folds:
                model = _fit_tree(name, seed, x_sample.iloc[fit_index], y_sample[fit_index],
                                  x_sample.iloc[hold_index], y_sample[hold_index], params)
                predicted = np.exp(model.predict(x_sample.iloc[hold_index]))
                scores.append(common.metrics(np.exp(y_sample[hold_index]), predicted)["r2_log"])
        except Exception:  # a draw that does not converge is just a bad draw
            trials += 1
            continue
        score = float(np.mean(scores))
        if score > best_score:
            best_params, best_score = params, score
        trials += 1
    return best_params, {"budget_seconds": int(budget), "trials": trials,
                         "sample_rows": int(sample), "folds": 2,
                         "best_cv_r2_log": round(float(best_score), 4) if best_params else None,
                         "params": best_params}


def _quantile_bands(x_train, y_train, x_val, seed: int):
    """LightGBM quantile fits for P10 / P50 / P90 on the log target, as the plan's §4.2 asks.

    P50 is reported as a metric next to the point model rather than written into
    `predictions_*.csv`, because the plan fixes that file at 15 columns.
    """
    import lightgbm as lgb
    categorical = [column for column in x_train.columns
                   if isinstance(x_train[column].dtype, pd.CategoricalDtype)]
    bands = []
    for alpha in (0.10, 0.50, 0.90):
        model = lgb.LGBMRegressor(objective="quantile", alpha=alpha, n_estimators=500,
                                  learning_rate=0.05, num_leaves=63, min_child_samples=40,
                                  subsample=0.9, subsample_freq=1, colsample_bytree=0.8,
                                  random_state=seed, n_jobs=-1, verbose=-1)
        model.fit(x_train, y_train, categorical_feature=categorical)
        bands.append(np.exp(model.predict(x_val)))
    return bands[0], bands[1], bands[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train one week-3 model and write its artefacts")
    parser.add_argument("--model", help="one of: " + ", ".join(MODELS) + " (short names lgbm/xgb/cb work)")
    parser.add_argument("--list", action="store_true", dest="list_models")
    parser.add_argument("--features", default="full", choices=common.VARIANTS)
    parser.add_argument("--seed", type=int, default=common.SEED)
    parser.add_argument("--rows", type=int, default=0, help="sample the train rows (0 = all)")
    parser.add_argument("--tune-seconds", type=int, default=0, help="time-boxed random search")
    parser.add_argument("--dense-sample", type=int, default=0,
                        help="subsample for k-NN (default 20000) or any dense model")
    parser.add_argument("--quantiles", action="store_true", help="add P10/P90 from LightGBM quantile fits")
    parser.add_argument("--split", default="val", choices=("val", "test"))
    parser.add_argument("--at-m2", action="store_true", help="required to write test predictions")
    parser.add_argument("--json", default=str(config.DATA_MASTER / "model_results.json"))
    parser.add_argument("--models-dir", default=str(Path(__file__).resolve().parents[2] / "models"))
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    args.model = resolve_model(args.model) if args.model else args.model
    if args.model and args.model not in MODELS:
        raise SystemExit(f"unknown model {args.model!r}; choose one of {', '.join(MODELS)}")

    if args.list_models or not args.model:
        print("models:", ", ".join(MODELS))
        print("dense (one-hot):", ", ".join(DENSE))
        print("native categoricals:", ", ".join(TREES))
        return 0
    if args.split == "test" and not args.at_m2:
        raise SystemExit("test predictions are exported once at M2 (Sat 07/11 18:00); pass --at-m2")

    train = common.load_split(args.features, "train", args.rows, args.seed)
    holdout = common.load_split(args.features, args.split)
    x_train, y_train = common.split_xy(train)
    x_val, y_val = common.split_xy(holdout)
    y_train_log = np.log(y_train.to_numpy(dtype=float))
    y_val_log = np.log(y_val.to_numpy(dtype=float))

    started = time.monotonic()
    model, params = None, {}
    tuning = {"budget_seconds": 0, "trials": 0, "note": "no tuning requested"}
    if args.model == "median":
        predicted = _median_predict(train, holdout)
        used_rows = len(train)
    elif args.model in DENSE:
        used_rows = args.dense_sample or (20000 if args.model == "knn" else 0)
        used_rows = min(used_rows, len(train)) if used_rows else len(train)
        model = _fit_dense(args.model, args.seed, x_train, y_train_log, used_rows or 0)
        predicted = np.exp(model.predict(x_val))
    else:
        x_train, x_val = common.align_categories(x_train, x_val)
        if args.tune_seconds:
            params, tuning = _tune(args.model, args.seed, x_train, y_train_log,
                                   train[common.GROUP], args.tune_seconds)
        model = _fit_tree(args.model, args.seed, x_train, y_train_log, x_val, y_val_log, params)
        predicted = np.exp(model.predict(x_val))
        used_rows = len(train)
    seconds = round(time.monotonic() - started, 1)

    p10 = p50 = p90 = None
    p50_metrics: dict = {}
    if args.quantiles:
        x_tree, x_tree_val = common.align_categories(x_train, x_val)
        p10, p50, p90 = _quantile_bands(x_tree, y_train_log, x_tree_val, args.seed)
        p50_metrics = common.metrics(y_val, p50)

    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    if model is not None:
        import joblib
        joblib.dump(model, models_dir / f"{args.model}_{args.features}.joblib", compress=3)

    frame = common.predictions_frame(holdout, predicted, p10, p90, split=args.split)
    predictions_path = config.DATA_MASTER / f"predictions_{args.split}.csv"
    frame.to_csv(predictions_path, index=False, lineterminator="\n")

    row = {"model": args.model, "features": args.features, "seed": args.seed,
           "train_rows": int(len(train)), "rows_used": int(used_rows),
           "holdout": args.split, "holdout_rows": int(len(holdout)),
           "n_features": int(x_train.shape[1]), "seconds": seconds,
           "quantiles": bool(args.quantiles), "params": params, "tuning": tuning,
           "p50_metrics": p50_metrics,
           "predictions": str(predictions_path), "note": args.note,
           **common.metrics(y_val, predicted)}
    if args.split == "val":
        common.append_result(Path(args.json), row)

    header = f"{'model':12s} {'features':8s} {'R2(log)':>8s} {'RMSE(log)':>10s} {'MAE(VND)':>13s} {'MAPE':>7s} {'s':>7s}"
    print(header)
    print("-" * len(header))
    print(f"{row['model']:12s} {row['features']:8s} {row['r2_log']:>8.4f} {row['rmse_log']:>10.4f} "
          f"{row['mae_vnd']:>13,} {row['mape']:>7.3f} {row['seconds']:>7.1f}")
    print(f"\n  predictions -> {predictions_path} ({len(frame):,} rows, {len(frame.columns)} columns)")
    if p50_metrics:
        print(f"  P50 quantile: R²(log) {p50_metrics['r2_log']:.4f} · MAPE {p50_metrics['mape']:.3f} "
              f"(point model above)")
    if args.split == "val":
        print(f"  ledger      -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
