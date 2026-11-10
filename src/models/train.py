"""Week 3, Team 2: fit one price model, append one row to model_results.json.

Contract (docs/week3_plan.md §4.2, Hiếu — primary deliverable):

    python -m src.models.train --model lgbm --features full --seed 42
    python -m src.models.train --model catboost --features minimal --seed 42
    python -m src.models.train --model lgbm --features full --quantiles      # P10/P50/P90
    python -m src.models.train --model lgbm --features full --split test --write-predictions

* target is ``log1p(price_vnd)``; metrics are reported in log space **and** VND;
* every run appends **exactly one row** to ``data/master/model_results.json``;
* the fitted model is saved as ``models/<model>_<features>.joblib``.

Models: ``median`` (brand|model|year group medians), ``ridge``, ``rf``,
``lgbm``, ``catboost``, ``xgboost``.

Leakage rules this module lives by (AGENTS.md hard rule 3):

* ``ridge`` and ``rf`` encode categoricals with ``sklearn``'s ``TargetEncoder``, which fits its
  mappings on train only *inside 5 inner folds* (out-of-fold encodings while fitting), and maps an
  unseen category to the global mean at transform time — exactly the fallback the plan specifies.
* ``lgbm`` / ``catboost`` / ``xgboost`` take the categorical columns natively; the validation
  categories are aligned to the training ones first so a level val never saw cannot invent
  information (unseen → treated as missing).
* nothing here reads ``test_cohort_imputed.csv`` unless ``--split test`` is passed explicitly, and
  that path refuses to run twice for the same model+features without ``--force`` — the test set is
  evaluated exactly once, at M2.

The predictions file (``--write-predictions``) carries the contract columns —
``listing_id, duplicate_group_id, brand, model, manufacture_year, mileage_km, location_province,
source_platform, price_vnd, y_pred_log, y_pred_vnd, p10_vnd, p90_vnd, residual, abs_pct_error`` —
with ``p10_vnd``/``p90_vnd`` coming from the LightGBM quantile models fitted by ``--quantiles``.
``location_province`` is joined from the frozen cohort by ``listing_id`` because the *full* feature
variant carries ``province_group``, not the raw province.
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

TARGET = "price_vnd"
ID_COLUMNS = ("listing_id", "duplicate_group_id")
MODELS = ("median", "ridge", "rf", "lgbm", "catboost", "xgboost")
SPLITS = ("val", "test")
RESULTS_PATH = config.DATA_MASTER / "model_results.json"
MODELS_DIR = config.ROOT / "models"

# Identity columns the predictions contract asks for; the *full* variant replaced
# location_province with province_group, so they are re-joined from the frozen cohort.
PREDICTION_COLUMNS = ("listing_id", "duplicate_group_id", "brand", "model", "manufacture_year",
                      "mileage_km", "location_province", "source_platform", "price_vnd",
                      "y_pred_log", "y_pred_vnd", "p10_vnd", "p90_vnd", "residual",
                      "abs_pct_error")


# --------------------------------------------------------------------------- data
def load_split(split: str, variant: str) -> pd.DataFrame:
    """Read one feature table; `split` is val or test (train is always read for fitting)."""
    path = config.DATA_MASTER / f"{split}_features_{variant}.csv"
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.features.build_features "
                         f"--features {variant}' first")
    return pd.read_csv(path, low_memory=False)


def load_train(variant: str) -> pd.DataFrame:
    path = config.DATA_MASTER / f"train_features_{variant}.csv"
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.features.build_features "
                         f"--features {variant}' first")
    return pd.read_csv(path, low_memory=False)


def split_xy(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """X = every column except the ids and the target; text columns become `category`.

    Same convention as `tools/baseline_smoke.py`, so the two files' numbers are comparable.
    """
    features = [column for column in frame.columns if column not in (*ID_COLUMNS, TARGET)]
    x = frame[features].copy()
    for column in x.columns:
        if not pd.api.types.is_numeric_dtype(x[column]):
            x[column] = x[column].astype("category")
    return x, frame[TARGET]


def align_categories(x_train: pd.DataFrame, x_other: pd.DataFrame) -> pd.DataFrame:
    """Force val/test category levels to be a subset of train's (unseen level -> NaN)."""
    aligned = x_other.copy()
    for column in x_train.columns:
        if isinstance(x_train[column].dtype, pd.CategoricalDtype):
            aligned[column] = aligned[column].astype("category").cat.set_categories(
                x_train[column].cat.categories)
    return aligned


def metrics(y_true: pd.Series, y_pred_log: np.ndarray) -> dict:
    """Log-space R²/RMSE (what the model optimises) and VND-space MAE/MAPE (what a reader feels).

    `y_pred_log` is already in log1p space; the VND numbers come from `expm1` of it.
    """
    truth = y_true.to_numpy(dtype=float)
    pred_vnd = np.expm1(np.asarray(y_pred_log, dtype=float))
    true_log = np.log1p(truth)
    pred_log = np.asarray(y_pred_log, dtype=float)
    ss_res = float(((true_log - pred_log) ** 2).sum())
    ss_tot = float(((true_log - true_log.mean()) ** 2).sum())
    return {
        "r2_log": round(1 - ss_res / ss_tot, 4) if ss_tot else float("nan"),
        "rmse_log": round(float(np.sqrt(ss_res / len(true_log))), 4),
        "mae_vnd": int(round(float(np.abs(truth - pred_vnd).mean()))),
        "mape": round(float((np.abs(truth - pred_vnd) / truth).mean()), 4),
    }


# ----------------------------------------------------------------------- models
def fit_median(train: pd.DataFrame, _: pd.DataFrame, seed: int):
    """Median asking price of the same brand|model|year, fitted on train, two fallbacks."""
    key = train["brand"].astype(str) + "|" + train["model"].astype(str) + "|" \
        + train["manufacture_year"].astype(str)
    grouped = train.groupby(key)[TARGET].median()
    by_brand = train.groupby("brand")[TARGET].median()
    overall = float(train[TARGET].median())
    artifact = {"grouped": grouped, "by_brand": by_brand, "overall": overall}

    def predict(frame: pd.DataFrame) -> np.ndarray:
        same = (frame["brand"].astype(str) + "|" + frame["model"].astype(str) + "|"
                + frame["manufacture_year"].astype(str))
        price_vnd = (same.map(grouped).fillna(frame["brand"].map(by_brand)).fillna(overall))
        return np.log1p(price_vnd.to_numpy(dtype=float))

    return artifact, predict


def fit_ridge(train: pd.DataFrame, _: pd.DataFrame, seed: int):
    """Ridge on target-encoded categoricals + scaled numerics, all inside one sklearn Pipeline.

    TargetEncoder fits its means on train only, in 5 inner folds (out-of-fold values during fit);
    a category val has never seen falls back to the global mean at transform time.
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler, TargetEncoder

    x_train, y_train = split_xy(train)
    categorical = [c for c in x_train.columns if not pd.api.types.is_numeric_dtype(x_train[c])]
    numeric = [c for c in x_train.columns if c not in categorical]
    pipeline = Pipeline([
        ("encode", ColumnTransformer([
            ("cats", TargetEncoder(target_type="continuous", cv=5, random_state=seed), categorical),
            ("nums", Pipeline([("impute", SimpleImputer(strategy="median")),
                               ("scale", StandardScaler())]), numeric),
        ])),
        ("model", Ridge(alpha=10.0)),
    ])
    pipeline.fit(x_train, np.log1p(y_train.to_numpy(dtype=float)))

    def predict(frame: pd.DataFrame) -> np.ndarray:
        return pipeline.predict(align_categories(x_train, split_xy(frame)[0]))

    return pipeline, predict


def fit_rf(train: pd.DataFrame, _: pd.DataFrame, seed: int):
    """Random Forest on the same encoded matrix as Ridge (trees do not need the scaler, but
    sharing the matrix keeps the two rows exactly comparable)."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler, TargetEncoder

    x_train, y_train = split_xy(train)
    categorical = [c for c in x_train.columns if not pd.api.types.is_numeric_dtype(x_train[c])]
    numeric = [c for c in x_train.columns if c not in categorical]
    pipeline = Pipeline([
        ("encode", ColumnTransformer([
            ("cats", TargetEncoder(target_type="continuous", cv=5, random_state=seed), categorical),
            ("nums", Pipeline([("impute", SimpleImputer(strategy="median")),
                               ("scale", StandardScaler())]), numeric),
        ])),
        ("model", RandomForestRegressor(n_estimators=300, min_samples_leaf=2,
                                         random_state=seed, n_jobs=-1)),
    ])
    pipeline.fit(x_train, np.log1p(y_train.to_numpy(dtype=float)))

    def predict(frame: pd.DataFrame) -> np.ndarray:
        return pipeline.predict(align_categories(x_train, split_xy(frame)[0]))

    return pipeline, predict


def fit_lgbm(train: pd.DataFrame, _: pd.DataFrame, seed: int):
    """LightGBM with native categorical handling — no imputation, no one-hot."""
    import lightgbm as lgb

    x_train, y_train = split_xy(train)
    categorical = [c for c in x_train.columns if not pd.api.types.is_numeric_dtype(x_train[c])]
    model = lgb.LGBMRegressor(
        objective="regression", n_estimators=600, learning_rate=0.06, num_leaves=63,
        min_child_samples=40, subsample=0.9, subsample_freq=1, colsample_bytree=0.8,
        random_state=seed, n_jobs=-1, verbose=-1,
    )
    model.fit(x_train, np.log1p(y_train.to_numpy(dtype=float)), categorical_feature=categorical)
    artifact = {"model": model, "categorical": categorical, "seed": seed}

    def predict(frame: pd.DataFrame) -> np.ndarray:
        return model.predict(align_categories(x_train, split_xy(frame)[0]))

    return artifact, predict


def fit_catboost(train: pd.DataFrame, val: pd.DataFrame | None, seed: int):
    """CatBoost — the required row with native handling of the 3,212-level brand|model.

    `iterations=3000, od_type="Iter", od_wait=100` are the plan's fixed settings. Early stopping
    watches the **validation** set when one is given (that is what val is for); on the test split it
    watches a tail slice of train instead — the test set must never steer training.
    """
    from catboost import CatBoostRegressor, Pool

    x_train, y_train = split_xy(train)
    x_val, y_val = (None, None)
    if val is not None:
        x_val, y_val = split_xy(val)
    else:
        x_val, y_val = x_train.iloc[-5000:], y_train.iloc[-5000:]
        x_train, y_train = x_train.iloc[:-5000], y_train.iloc[:-5000]
    categorical = [c for c in x_train.columns if not pd.api.types.is_numeric_dtype(x_train[c])]
    # CatBoost wants plain strings; NaN becomes the same "nan" string on every split
    def as_pool(x: pd.DataFrame, y: pd.Series | None) -> Pool:
        data = x.copy()
        for column in categorical:
            # pandas 3 keeps NaN when casting a categorical column, and CatBoost refuses real
            # NaN in cat_features — go through object dtype and make missing an explicit "NA"
            data[column] = data[column].astype(object).fillna("NA").astype(str)
        return Pool(data, label=None if y is None else np.log1p(y.to_numpy(dtype=float)),
                    cat_features=categorical)

    model = CatBoostRegressor(
        iterations=3000, learning_rate=0.1, depth=8, loss_function="RMSE",
        od_type="Iter", od_wait=100, random_seed=seed, thread_count=-1, verbose=0,
        allow_writing_files=False,
    )
    model.fit(as_pool(x_train, y_train), eval_set=as_pool(x_val, y_val))
    artifact = {"model": model, "categorical": categorical, "seed": seed}

    def predict(frame: pd.DataFrame) -> np.ndarray:
        return model.predict(as_pool(align_categories(x_train, split_xy(frame)[0]), None))

    return artifact, predict


def fit_xgboost(train: pd.DataFrame, _: pd.DataFrame, seed: int):
    """XGBoost with native categoricals (`enable_categorical`), first on the cut list."""
    from xgboost import XGBRegressor

    x_train, y_train = split_xy(train)
    model = XGBRegressor(
        n_estimators=600, learning_rate=0.06, max_depth=8, subsample=0.9, colsample_bytree=0.8,
        enable_categorical=True, tree_method="hist", random_state=seed, n_jobs=-1,
    )
    model.fit(x_train, np.log1p(y_train.to_numpy(dtype=float)))

    def predict(frame: pd.DataFrame) -> np.ndarray:
        return model.predict(align_categories(x_train, split_xy(frame)[0]))

    return model, predict


FITTERS = {"median": fit_median, "ridge": fit_ridge, "rf": fit_rf, "lgbm": fit_lgbm,
           "catboost": fit_catboost, "xgboost": fit_xgboost}


def fit_quantile_lgbm(train: pd.DataFrame, seed: int, variant: str) -> dict:
    """P10 / P50 / P90 LightGBM models → the interval columns of predictions_*.csv.

    Same feature handling and near-identical parameters as the point model, so the interval and
    the point prediction describe one model family, not two.
    """
    import lightgbm as lgb

    x_train, y_train = split_xy(train)
    categorical = [c for c in x_train.columns if not pd.api.types.is_numeric_dtype(x_train[c])]
    # remember train's category levels: predictions align to them so an unseen level stays unseen
    categories = {c: list(x_train[c].cat.categories) for c in categorical}
    trio: dict[str, object] = {}
    for alpha in (0.1, 0.5, 0.9):
        model = lgb.LGBMRegressor(
            objective="quantile", alpha=alpha, n_estimators=600, learning_rate=0.06,
            num_leaves=63, min_child_samples=40, subsample=0.9, subsample_freq=1,
            colsample_bytree=0.8, random_state=seed, n_jobs=-1, verbose=-1,
        )
        model.fit(x_train, np.log1p(y_train.to_numpy(dtype=float)), categorical_feature=categorical)
        trio[f"p{int(alpha * 100)}"] = model
    return {"models": trio, "categorical": categorical, "categories": categories,
            "seed": seed, "variant": variant}


def quantile_predict(quantiles: dict, frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """expm1 of each quantile model's log-space prediction, in VND."""
    x, _ = split_xy(frame)
    for column in quantiles.get("categorical", []):
        levels = quantiles.get("categories", {}).get(column)
        if levels is not None:
            x[column] = x[column].astype("category").cat.set_categories(levels)
    return {f"{name}_vnd": np.expm1(model.predict(x))
            for name, model in quantiles["models"].items()}


# ------------------------------------------------------------------- artefacts
def append_result(row: dict) -> Path:
    """Append exactly one row to data/master/model_results.json (created if absent)."""
    rows: list[dict] = []
    if RESULTS_PATH.exists():
        try:
            rows = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = RESULTS_PATH.with_suffix(".corrupt.json")
            backup.write_text(RESULTS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            raise SystemExit(f"{RESULTS_PATH} is not valid JSON -> backed up to {backup}")
    rows.append(row)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return RESULTS_PATH


def write_predictions(split: str, variant: str, y_pred_log: np.ndarray,
                      quantiles: dict | None) -> Path:
    """Write data/master/predictions_{split}.csv with the 15 contract columns."""
    frame = load_split(split, variant)
    cohort = pd.read_csv(config.DATA_MASTER / f"{split}_cohort_imputed.csv", low_memory=False)
    identity = frame[list(frame.columns.intersection(PREDICTION_COLUMNS))].copy()
    for column in ("location_province", "brand", "model", "manufacture_year", "mileage_km",
                   "source_platform", "duplicate_group_id"):
        if column not in identity.columns:
            joined = cohort.set_index("listing_id")[column]
            identity[column] = identity["listing_id"].map(joined)

    price = frame[TARGET].to_numpy(dtype=float)
    pred_vnd = np.expm1(np.asarray(y_pred_log, dtype=float))
    out = identity
    out["y_pred_log"] = np.asarray(y_pred_log, dtype=float)
    out["y_pred_vnd"] = pred_vnd
    if quantiles is not None:
        intervals = quantile_predict(quantiles, frame)
        out["p10_vnd"] = intervals["p10_vnd"]
        out["p90_vnd"] = intervals["p90_vnd"]
    else:
        out["p10_vnd"] = np.nan
        out["p90_vnd"] = np.nan
    out["residual"] = out["y_pred_log"] - np.log1p(price)
    out["abs_pct_error"] = np.abs(pred_vnd - price) / price

    out = out[list(PREDICTION_COLUMNS)]
    path = config.DATA_MASTER / f"predictions_{split}.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return path


# ------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Team 2: fit one model, one results row")
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--features", choices=("minimal", "full"), default="full")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--split", choices=SPLITS, default="val",
                        help="val = choose models; test = the single M2 evaluation")
    parser.add_argument("--quantiles", action="store_true",
                        help="also fit LightGBM P10/P50/P90 and save models/lgbm_quantiles_<f>.joblib")
    parser.add_argument("--write-predictions", action="store_true",
                        help="write data/master/predictions_<split>.csv from this run's model")
    parser.add_argument("--force", action="store_true",
                        help="allow a second test-split row for the same model+features")
    parser.add_argument("--note", default="", help="free-text note stored with the row")
    args = parser.parse_args(argv)

    # the test set is evaluated exactly once — refuse a duplicate row for the same setup
    if args.split == "test" and RESULTS_PATH.exists():
        existing = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        clash = [r for r in existing if r.get("split") == "test" and r["model"] == args.model
                 and r["features"] == args.features and not r.get("quantile_run")]
        if clash and not args.force:
            raise SystemExit(f"test split already evaluated for {args.model}/{args.features} "
                             f"(row at {clash[0].get('timestamp')}); pass --force to override — "
                             "the test set is a one-shot")

    train = load_train(args.features)
    frame = load_split(args.split, args.features)
    x, y = split_xy(frame)
    print(f"model {args.model} on '{args.features}': train {len(train):,} rows, "
          f"{args.split} {len(frame):,} rows, {x.shape[1]} features, seed {args.seed}")

    fitter = FITTERS[args.model]
    started = time.monotonic()
    artifact, predict = fitter(train, frame if args.split == "val" else None, args.seed)
    fit_seconds = round(time.monotonic() - started, 1)
    y_pred_log = predict(frame)
    score = metrics(y, y_pred_log)
    print(f"  fitted in {fit_seconds}s -> R²(log) {score['r2_log']}, RMSE(log) {score['rmse_log']}, "
          f"MAE {score['mae_vnd']:,} VND, MAPE {score['mape']:.3f}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{args.model}_{args.features}.joblib"
    import joblib
    joblib.dump(artifact, model_path)

    row = {
        "model": args.model, "features": args.features, "seed": args.seed, "split": args.split,
        "rows": {"train": int(len(train)), args.split: int(len(frame))},
        "n_features": int(x.shape[1]),
        "timestamp": config.now_iso(),
        "seconds": fit_seconds,
        **score,
        "note": args.note,
    }

    quantiles = None
    if args.quantiles:
        started_q = time.monotonic()
        quantiles = fit_quantile_lgbm(train, args.seed, args.features)
        quantile_path = MODELS_DIR / f"lgbm_quantiles_{args.features}.joblib"
        joblib.dump(quantiles, quantile_path)
        # how many truths actually fall inside the interval — the number the report quotes
        intervals = quantile_predict(quantiles, frame)
        inside = ((y.to_numpy(dtype=float) >= intervals["p10_vnd"])
                  & (y.to_numpy(dtype=float) <= intervals["p90_vnd"])).mean()
        row["interval_coverage_80"] = round(float(inside), 4)
        row["quantile_seconds"] = round(time.monotonic() - started_q, 1)
        print(f"  quantiles P10/P50/P90 in {row['quantile_seconds']}s -> 80% interval "
              f"coverage {row['interval_coverage_80']}")
        row["quantile_model"] = str(quantile_path.name)

    results_path = append_result(row)
    print(f"  row appended -> {results_path}")
    print(f"  model saved  -> {model_path}")

    if args.write_predictions:
        if quantiles is None:
            quantile_file = MODELS_DIR / f"lgbm_quantiles_{args.features}.joblib"
            if quantile_file.exists():
                quantiles = joblib.load(quantile_file)
                print(f"  intervals from {quantile_file.name} (fitted by an earlier --quantiles run)")
        path = write_predictions(args.split, args.features, y_pred_log, quantiles)
        print(f"  predictions  -> {path} ({len(PREDICTION_COLUMNS)} contract columns)")
        if quantiles is None:
            print("  note: p10_vnd/p90_vnd are empty — run '--model lgbm --quantiles' first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
