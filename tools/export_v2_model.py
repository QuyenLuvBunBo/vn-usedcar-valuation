"""Export the adopted v2 configuration as a serving bundle under `models/v2/`.

The winning configuration lives in `tools/feature_steps_eval.py` (step 3): the v2 feature table, row
weights `1/k` for repeated ads, LightGBM on the log target. Until now it only existed inside that
script, so nothing could score a new car without rebuilding the data. This tool freezes it:

    models/v2/model_point.joblib    the point model (log target, weights 1/k)
    models/v2/quantiles.joblib      P10/P50/P90 + the conformal log-shifts (skipped by --fast)
    models/v2/categories.json       the category list of every categorical column
    models/v2/impute_stats.json     the train-fitted imputation statistics (modes, medians)
    models/v2/feature_stats.json    a copy of the stats `build_features.apply_stats` applies
    models/v2/known.json            brand|model counts/medians, thresholds, capture year
    models/v2/metadata.json         hashes, feature order, weight mode, val metrics, versions

`models/` is git-ignored (`CONTRIBUTING.md` §2), so the binary files go to Drive and the numbers are
recorded in `docs/inference.md`, which is committed. v1 artefacts are not touched.

Run:
    python -m tools.export_v2_model                # full bundle with the band (~2 min)
    python -m tools.export_v2_model --fast         # point model only (clean_check)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.data_prep import missing, quality  # noqa: E402
from src.models import common, train as trainer  # noqa: E402
from tools.feature_steps_eval import PARAMS  # noqa: E402

SPLITS = ("train", "val")
V2_DIR = config.DATA_MASTER / "v2"
DEFAULT_BUNDLE = config.ROOT / "models" / "v2"
ALPHAS = (0.10, 0.50, 0.90)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonable(value):
    """JSON-safe copy: numpy scalars, nested dicts with integer keys (age buckets), NaN -> None."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    return value


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def train_rows() -> list[dict]:
    """The pre-imputation train rows; a clean checkout only ships the imputed cohort.

    When `train_cohort.csv` is absent (the mandatory snapshot folder carries the imputed file), the
    blanks are reconstructed from the `imputed` column: every cell the pipeline filled is set back to
    empty, which is exactly the state the statistics were fitted on.
    """
    pre = config.DATA_MASTER / "train_cohort.csv"
    if pre.exists():
        return missing.load_split(pre)[0]
    rows, _ = missing.load_split(config.DATA_MASTER / "train_cohort_imputed.csv")
    for row in rows:
        for column in str(row.get("imputed") or "").split(";"):
            if column:
                row[column] = ""
    print("  note: train_cohort.csv absent -> blanks restored from the `imputed` column")
    return rows


def fit_impute_stats() -> dict:
    """The statistics `missing.impute_parts` fits on train — serialised instead of thrown away.

    Fitted on `train_cohort.csv` (before imputation), exactly as the pipeline does, so a raw record
    goes through the same modes and medians it would have met during training.
    """
    rows = train_rows()
    reference = missing.capture_year(rows)
    groups = ("brand", "model")
    return {
        "reference_year": reference,
        "min_group": missing.MIN_GROUP,
        "age_bucket": missing.AGE_BUCKET_YEARS,
        "categorical": {column: missing.fit_categorical(rows, column, groups, missing.MIN_GROUP)
                        for column in ("body_type", "transmission", "fuel_type", "origin",
                                       "seller_type")},
        "seats": missing.fit_categorical(rows, "seats", groups, missing.MIN_GROUP),
        "mileage_by_age": missing.fit_median_by_age(rows, "mileage_km", reference_year=reference,
                                                    min_group=missing.MIN_GROUP),
        "engine_by_model": missing.fit_median_by_group(rows, "engine_capacity",
                                                       min_group=missing.MIN_GROUP),
        "engine_by_age": missing.fit_median_by_age(rows, "engine_capacity",
                                                   reference_year=reference,
                                                   min_group=missing.MIN_GROUP),
        "rare_models": sorted(missing.rare_values(rows, "model", min_count=10)),
        "rare_min": 10,
    }


def load_training() -> dict:
    """The v2 feature tables, the row weights, and the label flags used by the two hold-outs."""
    train = pd.read_csv(V2_DIR / "train_features_full.csv", low_memory=False)
    val = pd.read_csv(V2_DIR / "val_features_full.csv", low_memory=False)
    train["listing_id"] = train["listing_id"].astype(str)
    val["listing_id"] = val["listing_id"].astype(str)

    flags = None
    try:
        flags = quality.load_flags()
    except SystemExit:
        print("  note: label_flags.csv is absent -> every row weighs 1 (a clean checkout has no flags)")
    if flags is None:
        flags = pd.DataFrame({"listing_id": train["listing_id"], "deposit_suspected": False,
                              "placeholder_odometer": False, "implausible_year": False,
                              "repeat_ad": False, "is_duplicate_copy": False, "flag_count": 0})
    train_flags = train[["listing_id"]].merge(flags, on="listing_id", how="left").fillna(
        {"deposit_suspected": False, "placeholder_odometer": False, "implausible_year": False,
         "repeat_ad": False, "is_duplicate_copy": False, "flag_count": 0})
    val_flags = val[["listing_id"]].merge(flags, on="listing_id", how="left").fillna(
        {"deposit_suspected": False, "placeholder_odometer": False, "implausible_year": False,
         "repeat_ad": False, "is_duplicate_copy": False, "flag_count": 0})

    weights = quality.cleaning_weights(train_flags, "weight_repeats").to_numpy(dtype=float)
    x_train, y_train = common.split_xy(train)
    x_val, y_val = common.split_xy(val)
    x_train, x_val = common.align_categories(x_train, x_val)
    return {"train": train, "val": val, "x_train": x_train, "x_val": x_val,
            "y_train": y_train, "y_val": y_val, "weights": weights,
            "clean": val_flags["flag_count"].to_numpy(dtype=int) == 0,
            "groups": train[common.GROUP].to_numpy()}


def fit_point(data: dict) -> tuple:
    import lightgbm as lgb

    categorical = [c for c in data["x_train"].columns
                   if isinstance(data["x_train"][c].dtype, pd.CategoricalDtype)]
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(data["x_train"], np.log(data["y_train"].to_numpy(dtype=float)),
              sample_weight=data["weights"], categorical_feature=categorical)
    predicted = np.exp(model.predict(data["x_val"]))
    full = common.metrics(data["y_val"], predicted)
    clean = common.metrics(data["y_val"][data["clean"]], predicted[data["clean"]])
    return model, {"val_full": full, "val_clean": clean,
                   "train_rows": int(len(data["x_train"])),
                   "weighted_rows": int((data["weights"] < 1).sum())}


def fit_quantiles(data: dict, seed: int = 42, calibrate_on: str = "train-oof") -> dict:
    """Three quantile fits for serving plus the conformal log-shifts that make the band cover 80 %."""
    categorical = [c for c in data["x_train"].columns
                   if isinstance(data["x_train"][c].dtype, pd.CategoricalDtype)]
    y_log = np.log(data["y_train"].to_numpy(dtype=float))
    models = {alpha: trainer._fit_quantile(alpha, data["x_train"], y_log, seed, categorical)
              for alpha in ALPHAS}

    if calibrate_on == "val":
        y_val_log = np.log(data["y_val"].to_numpy(dtype=float))
        low = y_val_log - models[0.10].predict(data["x_val"])
        high = y_val_log - models[0.90].predict(data["x_val"])
        calibration = {"measured_on": "val (holdout; the band is calibrated on the same rows it is "
                                      "checked on — use train-oof for an honest coverage number)",
                       "shift_low_log": round(float(np.quantile(low, 0.10)), 6),
                       "shift_high_log": round(float(np.quantile(high, 0.90)), 6)}
    else:
        calibration = trainer._calibrate_bands(data["x_train"], y_log, data["groups"], seed)

    p10 = np.exp(models[0.10].predict(data["x_val"]) + calibration["shift_low_log"])
    p50 = np.exp(models[0.50].predict(data["x_val"]))
    p90 = np.exp(models[0.90].predict(data["x_val"]) + calibration["shift_high_log"])
    price = data["y_val"].to_numpy(dtype=float)
    coverage = float(np.mean((price >= p10) & (price <= p90)))
    return {"models": models, "alphas": list(ALPHAS), "calibration": calibration,
            "val_coverage": round(coverage, 4),
            "val_band_median_width_vnd": int(np.median(p90 - p10))}


def known_table(data: dict) -> dict:
    """What the serving path needs to warn: which cars it has seen, and what 'too cheap' means."""
    train = data["train"]
    key = train["brand"].astype(str) + "|" + train["model"].astype(str)
    counts = key.value_counts()
    price = pd.to_numeric(train["price_vnd"], errors="coerce")
    segment = price.groupby(key).median()
    return {
        "brand_model_counts": {str(name): int(count) for name, count in counts.items()},
        "segment_median_vnd": {str(name): int(value) for name, value in segment.items()},
        "national_median_vnd": int(price.median()),
        "deposit_ratio_threshold": quality.DEPOSIT_THRESHOLD,
        "segment_min_rows": quality.SEGMENT_MIN_ROWS,
        "placeholder_odometer_low": quality.PLACEHOLDER_LOW,
        "placeholder_odometer_high": quality.PLACEHOLDER_HIGH,
        "year_min": quality.YEAR_MIN,
        "capture_year": int(missing.capture_year(train_rows())),
        "engine_range": [0.6, 8.0],
    }



def write_bundle(bundle: Path, data: dict, impute_stats: dict, point, point_metrics: dict,
                 quantiles: dict | None, known: dict) -> dict:
    import joblib
    import lightgbm

    bundle.mkdir(parents=True, exist_ok=True)
    joblib.dump(point, bundle / "model_point.joblib", compress=3)
    if quantiles:
        joblib.dump(quantiles["models"], bundle / "quantiles.joblib", compress=3)

    categorical = [c for c in data["x_train"].columns
                   if isinstance(data["x_train"][c].dtype, pd.CategoricalDtype)]
    categories = {column: [str(value) for value in data["x_train"][column].cat.categories]
                  for column in categorical}
    (bundle / "categories.json").write_text(json.dumps({"columns": categorical,
                                                        "categories": categories},
                                                       ensure_ascii=False, indent=1) + "\n",
                                            encoding="utf-8", newline="\n")
    (bundle / "impute_stats.json").write_text(json.dumps(jsonable(impute_stats), ensure_ascii=False,
                                                         indent=1) + "\n",
                                              encoding="utf-8", newline="\n")
    (bundle / "known.json").write_text(json.dumps(known, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8", newline="\n")
    (bundle / "feature_stats.json").write_text(
        (config.DATA_MASTER / "feature_stats.json").read_text(encoding="utf-8"),
        encoding="utf-8", newline="\n")

    sources = {
        "train_features": V2_DIR / "train_features_full.csv",
        "val_features": V2_DIR / "val_features_full.csv",
        "train_cohort": config.DATA_MASTER / "train_cohort.csv",
        "label_flags": config.DATA_MASTER / "label_flags.csv",
    }
    metadata = {
        "created_at": config.now_iso(),
        "git_commit": git_commit(),
        "config": "v2 step 3 — weight_repeats (1/k) + engine_parsed + trim_rank, LightGBM on log price",
        "params": jsonable(PARAMS),
        "features": list(data["x_train"].columns),
        "target": "log1p(price_vnd)",
        "weights": "1/k for repeated ads (quality.cleaning_weights('weight_repeats'))",
        "rows": {"train": int(len(data["x_train"])), "val": int(len(data["x_val"]))},
        "metrics": point_metrics,
        "quantiles": ({"alphas": quantiles["alphas"], "calibration": quantiles["calibration"],
                       "val_coverage": quantiles["val_coverage"],
                       "val_band_median_width_vnd": quantiles["val_band_median_width_vnd"]}
                      if quantiles else {"present": False, "note": "built with --fast"}),
        "sources": {name: {"path": str(path), "sha256": sha256(path)}
                    for name, path in sources.items() if path.exists()},
        "versions": {"python": sys.version.split()[0], "pandas": pd.__version__,
                     "numpy": np.__version__, "lightgbm": lightgbm.__version__},
    }
    (bundle / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=1) + "\n",
                                          encoding="utf-8", newline="\n")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the adopted v2 model as a serving bundle")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--fast", action="store_true", help="point model only (no P10/P90)")
    parser.add_argument("--calibrate-on", choices=("train-oof", "val"), default="train-oof",
                        help="where the conformal shift is measured; train-oof keeps val a holdout")
    parser.add_argument("--no-write", action="store_true", help="fit and report, write nothing")
    args = parser.parse_args(argv)

    if not (V2_DIR / "train_features_full.csv").exists():
        raise SystemExit(f"missing {V2_DIR}/train_features_full.csv -> run "
                         f"'python -m src.features.extend --write --cohort-dir data/master/v2'")
    started = time.monotonic()
    print("fitting the imputation statistics on train_cohort.csv ...", flush=True)
    impute_stats = fit_impute_stats()

    data = load_training()
    print(f"features {data['x_train'].shape[1]} · train {len(data['x_train']):,} rows "
          f"({int((data['weights'] < 1).sum()):,} down-weighted) · val {len(data['x_val']):,}",
          flush=True)

    point, point_metrics = fit_point(data)
    print(f"point model: val_full R2 {point_metrics['val_full']['r2_log']:.4f} "
          f"MAPE {point_metrics['val_full']['mape']:.4f} · val_clean MAPE "
          f"{point_metrics['val_clean']['mape']:.4f}", flush=True)

    quantiles = None
    if args.fast:
        print("  --fast: no quantile models, predict() will report the band as unavailable", flush=True)
    else:
        quantiles = fit_quantiles(data, calibrate_on=args.calibrate_on)
        print(f"quantiles: val coverage {quantiles['val_coverage']:.2%} "
              f"(nominal 80 %) · median width {quantiles['val_band_median_width_vnd']:,} VND · "
              f"calibrated on {quantiles['calibration']['measured_on']}", flush=True)

    known = known_table(data)
    bundle = Path(args.bundle)
    if args.no_write:
        print("  --no-write: bundle not written")
        return 0
    metadata = write_bundle(bundle, data, impute_stats, point, point_metrics, quantiles, known)
    elapsed = time.monotonic() - started
    print(f"\n  bundle -> {bundle} ({elapsed:.0f}s)")
    print(f"  files: {', '.join(sorted(path.name for path in bundle.iterdir()))}")
    print(f"  v2 train sha256 {metadata['sources']['train_features']['sha256'][:16]}…")
    print("  record these numbers in docs/inference.md (models/ is git-ignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
