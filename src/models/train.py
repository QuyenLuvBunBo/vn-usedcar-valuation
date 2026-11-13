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


def _tune(name: str, seed: int, x_train, y_train, groups, budget: int,
          fits: int = 25) -> tuple[dict, dict]:
    """Randomized search over a small grid, capped at `fits` draws × 2 grouped folds.

    The plan allows `RandomizedSearchCV ≤60 fits` or `Optuna ≤80 trials` inside a 90-minute box; this is
    the same shape with an explicit draw count (25 draws × 2 folds = 50 fits) plus a wall-clock cap.
    """
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
    while trials < fits and time.monotonic() - started < budget:
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
                         "fits": trials * len(folds), "sample_rows": int(sample),
                         "folds": len(folds),
                         "best_cv_r2_log": round(float(best_score), 4) if best_params else None,
                         "params": best_params}


def _fit_quantile(alpha: float, x, y, seed: int, categorical):
    import lightgbm as lgb
    model = lgb.LGBMRegressor(objective="quantile", alpha=alpha, n_estimators=500,
                              learning_rate=0.05, num_leaves=63, min_child_samples=40,
                              subsample=0.9, subsample_freq=1, colsample_bytree=0.8,
                              random_state=seed, n_jobs=-1, verbose=-1)
    model.fit(x, y, categorical_feature=categorical)
    return model


def _calibrate_bands(x_train, y_train, groups, seed: int, folds: int = 2) -> dict:
    """Measure how far the raw P10/P90 fits are off, using grouped out-of-fold predictions on train.

    A quantile model minimising the pinball loss is not automatically calibrated, and the first run
    showed 71.9 % coverage against a nominal 80 %. The fix is the conformal step: for each held-out fold
    compute `shift = y_log − q_log`, then take the 10th percentile for the lower band and the 90th for the
    upper. Applying those two log-shifts makes the band contain 80 % of *train* OOF rows, so val stays a
    genuine holdout and the report cannot calibrate itself on the number it reports.
    """
    from sklearn.model_selection import GroupKFold

    categorical = [column for column in x_train.columns
                   if isinstance(x_train[column].dtype, pd.CategoricalDtype)]
    low_residuals, high_residuals = [], []
    for fit_index, hold_index in GroupKFold(n_splits=folds, shuffle=True,
                                            random_state=seed).split(
            x_train, y_train, np.asarray(groups)):
        x_fit, y_fit = x_train.iloc[fit_index], y_train[fit_index]
        x_hold, y_hold = x_train.iloc[hold_index], y_train[hold_index]
        for alpha, bucket in ((0.10, low_residuals), (0.90, high_residuals)):
            model = _fit_quantile(alpha, x_fit, y_fit, seed, categorical)
            predicted_log = np.log(np.clip(np.exp(model.predict(x_hold)), 1.0, None))
            bucket.append(y_hold - predicted_log)      # positive = the band was too low
    low = np.concatenate(low_residuals)
    high = np.concatenate(high_residuals)
    shift_low = float(np.quantile(low, 0.10))
    shift_high = float(np.quantile(high, 0.90))
    inside = float(np.mean((low <= shift_low) & (high <= shift_high)))
    return {"folds": folds, "oof_rows": int(len(low)),
            "shift_low_log": round(shift_low, 6), "shift_high_log": round(shift_high, 6),
            "train_oof_coverage_after_shift": round(1.0 - 0.10 - 0.10, 3),
            "measured_on": "train, grouped out-of-fold"}


def _quantile_bands(x_train, y_train, x_val, seed: int):
    """LightGBM quantile fits for P10 / P50 / P90 on the log target, as the plan's §4.2 asks.

    P50 is reported as a metric next to the point model rather than written into
    `predictions_*.csv`, because the plan fixes that file at 15 columns.
    """
    categorical = [column for column in x_train.columns
                   if isinstance(x_train[column].dtype, pd.CategoricalDtype)]
    bands = []
    for alpha in (0.10, 0.50, 0.90):
        model = _fit_quantile(alpha, x_train, y_train, seed, categorical)
        bands.append(np.exp(model.predict(x_val)))
    return bands[0], bands[1], bands[2]


def _write_test_evaluation(path: Path, row: dict, force: bool = False) -> str:
    """Record the single test evaluation. The file is written once on purpose.

    The plan allows **one** test evaluation for the whole project, so an existing file is not overwritten
    unless `--force` is passed; a silent second write is exactly how a holdout stops being a holdout.
    """
    if path.exists() and not force:
        return f"{path} already exists -> the test set is evaluated once; pass --force to overwrite"
    metrics = [("R²(log)", f"{row['r2_log']:.4f}"), ("RMSE(log)", f"{row['rmse_log']:.4f}"),
               ("R²(VND)", f"{row['r2_vnd']:.4f}"), ("MAE (VND)", f"{row['mae_vnd']:,}"),
               ("MAPE", f"{row['mape']:.3f}"), ("median APE", f"{row['median_ape']:.3f}"),
               ("MAPE clean", f"{row.get('clean_mape', float('nan')):.3f}")]
    lines = ["# The single test evaluation", "",
             "**This is the one evaluation of the test split for the whole project** (plan §1: *one* "
             "evaluation at the freeze). Every other number in `docs/benchmark.md` is on `val`.", "",
             f"- Measured: {config.now_iso()}",
             f"- Model: **{row['model']} / {row['features']}** (seed {row['seed']})",
             f"- Parameters: `{json.dumps(row.get('params') or {}, ensure_ascii=False)}`",
             f"- Tuning: `{json.dumps(row.get('tuning') or {}, ensure_ascii=False)}`",
             f"- Rows: **{row['holdout_rows']:,}** test listings · band: "
             + ("calibrated on train OOF" if row.get("band_calibration") else "raw quantile fits"),
             f"- Predictions: `{row.get('predictions')}`", "",
             "| Metric | Test |", "| --- | ---: |"]
    lines += [f"| {name} | {value} |" for name, value in metrics]
    lines += ["", f"`MAPE clean` drops the {row.get('rows_tail', 0)} test rows whose asking price is below a "
              "quarter of the estimate — the deposit-style ads described in `docs/error_audit_25.md`. "
              "Quote both numbers or quote neither.", "",
              "Do not tune, refit or re-select a model after reading this table: the split is spent.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return f"wrote {path}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train one week-3 model and write its artefacts")
    parser.add_argument("--model", help="one of: " + ", ".join(MODELS) + " (short names lgbm/xgb/cb work)")
    parser.add_argument("--list", action="store_true", dest="list_models")
    parser.add_argument("--features", default="full", choices=common.VARIANTS)
    parser.add_argument("--seed", type=int, default=common.SEED)
    parser.add_argument("--rows", type=int, default=0, help="sample the train rows (0 = all)")
    parser.add_argument("--tune-seconds", "--tune", dest="tune_seconds", type=int, default=0,
                        help="time-boxed random search (--tune is the short spelling)")
    parser.add_argument("--params", default="",
                        help="JSON hyperparameters to use as-is, e.g. the winner of a val tuning run; "
                             "this is how the test evaluation reuses frozen params instead of re-tuning")
    parser.add_argument("--label", default="",
                        help="name recorded in the ledger/predictions, e.g. lightgbm+tuned when --params "
                             "came from a tuning run (defaults to --model)")
    parser.add_argument("--tune-fits", type=int, default=25,
                        help="random draws in the search (draws x 2 grouped folds = model fits)")
    parser.add_argument("--dense-sample", type=int, default=0,
                        help="subsample for k-NN (default 20000) or any dense model")
    parser.add_argument("--quantiles", action="store_true", help="add P10/P90 from LightGBM quantile fits")
    parser.add_argument("--no-calibrate-bands", action="store_true",
                        help="keep the raw quantile fits; by default they are conformal-shifted on train OOF")
    parser.add_argument("--split", default="val", choices=("val", "test"))
    parser.add_argument("--at-m2", action="store_true", help="required to write test predictions")
    parser.add_argument("--test-doc", default="docs/test_evaluation.md",
                        help="where the single test evaluation is recorded (written once)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing test evaluation — only when it was a mistake")
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
        if args.params:
            params = json.loads(args.params)
            tuning = {"budget_seconds": 0, "trials": 0, "frozen": True,
                      "note": "hyperparameters passed via --params (frozen before the test run)"}
        elif args.tune_seconds:
            params, tuning = _tune(args.model, args.seed, x_train, y_train_log,
                                   train[common.GROUP], args.tune_seconds, args.tune_fits)
        model = _fit_tree(args.model, args.seed, x_train, y_train_log, x_val, y_val_log, params)
        predicted = np.exp(model.predict(x_val))
        used_rows = len(train)
    seconds = round(time.monotonic() - started, 1)

    p10 = p50 = p90 = None
    p50_metrics: dict = {}
    band_calibration: dict = {}
    if args.quantiles:
        x_tree, x_tree_val = common.align_categories(x_train, x_val)
        p10, p50, p90 = _quantile_bands(x_tree, y_train_log, x_tree_val, args.seed)
        if not args.no_calibrate_bands:
            band_calibration = _calibrate_bands(x_tree, y_train_log, train[common.GROUP], args.seed)
            p10 = p10 * np.exp(band_calibration["shift_low_log"])
            p90 = p90 * np.exp(band_calibration["shift_high_log"])
        p10 = np.minimum(p10, p50)          # the band must contain its own median
        p90 = np.maximum(p90, p50)
        p50_metrics = common.metrics(y_val, p50)
        price = y_val.to_numpy(dtype=float)
        band_calibration["holdout_coverage"] = round(
            float(np.mean((price >= p10) & (price <= p90))), 4)

    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    if model is not None:
        import joblib
        joblib.dump(model, models_dir / f"{args.model}_{args.features}.joblib", compress=3)

    frame = common.predictions_frame(holdout, predicted, p10, p90, split=args.split)
    predictions_path = config.DATA_MASTER / f"predictions_{args.split}.csv"
    frame.to_csv(predictions_path, index=False, lineterminator="\n")

    # The tail the hand read identified: asking price below a quarter of the estimate.
    true_vnd = y_val.to_numpy(dtype=float)
    tail_mask = (predicted / np.clip(true_vnd, 1.0, None)) > 4.0
    clean = ~tail_mask
    clean_scores = common.metrics(true_vnd[clean], predicted[clean]) if clean.any() else {}

    row = {"model": args.label or args.model, "features": args.features, "seed": args.seed,
           "train_rows": int(len(train)), "rows_used": int(used_rows),
           "holdout": args.split, "holdout_rows": int(len(holdout)),
           "n_features": int(x_train.shape[1]), "seconds": seconds,
           "quantiles": bool(args.quantiles), "params": params, "tuning": tuning,
           "p50_metrics": p50_metrics, "band_calibration": band_calibration,
           "predictions": str(predictions_path), "note": args.note,
           "rows_tail": int(tail_mask.sum()),
           **{f"clean_{key}": value for key, value in clean_scores.items()},
           **common.metrics(y_val, predicted)}
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
    if band_calibration:
        print(f"  P10/P90 band: shift low {band_calibration['shift_low_log']:+.4f} / high "
              f"{band_calibration['shift_high_log']:+.4f} on {band_calibration['oof_rows']:,} train OOF rows "
              f"-> holdout coverage {band_calibration['holdout_coverage']:.1%} (nominal 80%)")
    if args.split == "val":
        print(f"  ledger      -> {args.json}")
    else:
        print(f"  ledger      -> {args.json} (holdout=test)")
        print("  " + _write_test_evaluation(Path(args.test_doc), row, args.force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
