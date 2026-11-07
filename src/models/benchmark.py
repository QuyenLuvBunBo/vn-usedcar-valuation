"""Benchmark several models on the same frozen split and write the report table.

The plan (§4.2, §7) asks for ≥5 models × 2 feature sets on **val**, a tuning budget in the
table, and a Wilcoxon test on absolute errors. This runner reuses the exact fitting code in
`src/models/train.py`, so the benchmark and the single-run CLI can never drift apart.

Run:
    python -m src.models.benchmark --models median,ridge,lightgbm,catboost,rf
    python -m src.models.benchmark --features full --models median,ridge,lasso,elasticnet
    python -m src.models.benchmark --all --tune-seconds 60
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402
from src.models import train as trainer  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MODELS = ("median", "ridge", "lightgbm", "catboost", "rf")
DOC = REPO / "docs" / "benchmark.md"


def run_one(model: str, features: str, seed: int, tune_seconds: int, rows: int,
            knn_sample: int = 20000, tune_fits: int = 25) -> dict:
    """Fit once, return the ledger row plus the per-row absolute percentage error."""
    train_frame = common.load_split(features, "train", rows, seed)
    val_frame = common.load_split(features, "val")
    x_train, y_train = common.split_xy(train_frame)
    x_val, y_val = common.split_xy(val_frame)
    y_train_log = np.log(y_train.to_numpy(dtype=float))
    y_val_log = np.log(y_val.to_numpy(dtype=float))

    started = time.monotonic()
    params: dict = {}
    tuning = {"budget_seconds": 0, "trials": 0, "note": "no tuning requested"}
    if model == "median":
        predicted = trainer._median_predict(train_frame, val_frame)
        rows_used = len(train_frame)
    elif model in trainer.DENSE:
        sample = knn_sample if model == "knn" else 0
        rows_used = min(sample, len(train_frame)) if sample else len(train_frame)
        fitted = trainer._fit_dense(model, seed, x_train, y_train_log, rows_used)
        predicted = np.exp(fitted.predict(x_val))
    else:
        x_train, x_val = common.align_categories(x_train, x_val)
        if tune_seconds:
            params, tuning = trainer._tune(model, seed, x_train, y_train_log,
                                           train_frame[common.GROUP], tune_seconds, tune_fits)
        fitted = trainer._fit_tree(model, seed, x_train, y_train_log, x_val, y_val_log, params)
        predicted = np.exp(fitted.predict(x_val))
        rows_used = len(train_frame)

    scores = common.metrics(y_val, predicted)
    true_vnd = y_val.to_numpy(dtype=float)
    return {"model": model, "features": features, "seed": seed, "train_rows": int(len(train_frame)),
            "rows_used": int(rows_used), "holdout": "val", "holdout_rows": int(len(val_frame)),
            "n_features": int(x_train.shape[1]), "seconds": round(time.monotonic() - started, 1),
            "quantiles": False, "params": params, "tuning": tuning,
            "note": "benchmark runner", **scores,
            "_abs_errors": np.abs(predicted - true_vnd) / true_vnd}


def wilcoxon(best: np.ndarray, other: np.ndarray) -> float:
    """Paired signed-rank test on absolute percentage errors; NaN when it cannot be computed."""
    try:
        from scipy.stats import wilcoxon as scipy_wilcoxon
        return float(scipy_wilcoxon(best, other, zero_method="wilcox").pvalue)
    except Exception:
        return float("nan")


def write_doc(rows: list[dict], path: Path, tuning_budget: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    best = max(rows, key=lambda row: row["r2_log"])
    lines = [
        "# Benchmark — week-3 models on the val split",
        "",
        f"Generated {config.now_iso()} by `python -m src.models.benchmark`. Every number is on the "
        "frozen `val` split (14,964 rows); the test split is evaluated exactly once at M2 and is "
        "**not** part of this table.",
        "",
        "Feature tables: `data/master/{train,val}_features_{minimal,full}.csv`. "
        f"Tuning budget: **{tuning_budget}s per model** (random search, 2 grouped folds, 15k sample). "
        "Models without a budget entry use fixed parameters.",
        "",
        "| Features | Model | R²(log) | RMSE(log) | R²(VND) | MAE (VND) | MAPE | median APE | rows | s | tuning |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in sorted(rows, key=lambda item: (item["features"], -item["r2_log"])):
        tuning = row.get("tuning") or {}
        budget = (f"{tuning.get('budget_seconds')}s/{tuning.get('trials')} trials"
                  if tuning.get("trials") else "fixed")
        lines.append(
            f"| {row['features']} | {row['model']} | {row['r2_log']:.4f} | {row['rmse_log']:.4f} | "
            f"{row['r2_vnd']:.4f} | {row['mae_vnd']:,} | {row['mape']:.3f} | {row['median_ape']:.3f} | "
            f"{row['rows_used']:,} | {row['seconds']:.1f} | {budget} |")
    reached = best["r2_log"] > 0.946
    lines += [
        "",
        f"Best on val: **{best['model']} / {best['features']}** — R²(log) {best['r2_log']:.4f}, "
        f"MAPE {best['mape']:.1%}.",
        "",
        "## Wilcoxon signed-rank vs the best model (absolute percentage error, same rows)",
        "",
        "| Model | p-value | reading |",
        "| --- | ---: | --- |",
    ]
    for row in sorted(rows, key=lambda item: item["r2_log"]):
        if row is best:
            continue
        p_value = wilcoxon(best["_abs_errors"], row["_abs_errors"])
        if p_value != p_value:
            reading = "not computed"
        elif p_value >= 0.05:
            reading = "not distinguishable (p ≥ 0.05)"
        elif row["r2_log"] <= best["r2_log"]:
            reading = "worse (p < 0.05)"
        else:
            reading = "better (p < 0.05)"
        lines.append(f"| {row['model']} / {row['features']} | {p_value:.3g} | {reading} |")
    lines += [
        "",
        "## Reading the table",
        "",
        "- Canary floor from `tools/baseline_smoke`: R²(log) 0.946 / MAPE 11.6%. "
        + (f"This benchmark's best is {best['r2_log']:.4f} / {best['mape']:.1%}, above the floor, so the "
           "extra complexity is justified."
           if reached else
           f"This benchmark's best is {best['r2_log']:.4f} / {best['mape']:.1%} — **at or below the floor**. "
           "§5 of the report must say so instead of presenting the best number as progress."),
        "- R²(VND) is dominated by the price spread, so it always looks better than R²(log); MAPE and "
        "median APE are the honest per-listing numbers.",
        "- A `rows` value below 70,244 means the model was subsampled for runtime (k-NN by design); "
        "the column makes that visible instead of hiding it.",
        "- No test-set number appears here on purpose (plan §1: one evaluation at M2).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark models on the frozen val split")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--all", action="store_true", help="every model in src.models.train")
    parser.add_argument("--features", default="minimal,full")
    parser.add_argument("--seed", type=int, default=common.SEED)
    parser.add_argument("--rows", type=int, default=0)
    parser.add_argument("--tune-seconds", type=int, default=0,
                        help="time-boxed random search; tuned runs appear as <model>+tuned rows")
    parser.add_argument("--knn-sample", type=int, default=20000)
    parser.add_argument("--tune-fits", type=int, default=25,
                        help="random draws per tuned model (draws x 2 folds = fits; the plan caps at 60)")
    parser.add_argument("--tune-models", default="lightgbm,xgboost,catboost",
                        help="which models get a tuned row; a CatBoost trial alone can exceed a small budget")
    parser.add_argument("--doc", default=str(DOC))
    parser.add_argument("--json", default=str(config.DATA_MASTER / "model_results.json"))
    parser.add_argument("--copy-to", default=str(REPO / "docs" / "model_results.json"),
                        help="also write the ledger here so a clean clone can read the numbers")
    args = parser.parse_args(argv)

    models = (list(trainer.MODELS) if args.all
              else [trainer.resolve_model(item) for item in args.models.split(",") if item.strip()])
    tunable = {item.strip() for item in args.tune_models.split(",") if item.strip()}
    features = [item.strip() for item in args.features.split(",") if item.strip()]
    rows: list[dict] = []
    ledger = Path(args.json)

    def record(row: dict, label: str) -> None:
        print(f" R2(log) {row['r2_log']:.4f}  MAPE {row['mape']:.3f}  {row['seconds']:.0f}s")
        common.append_result(ledger, {key: value for key, value in row.items() if not key.startswith("_")})
        rows.append(row)

    for variant in features:
        for model in models:
            print(f"  {variant:7s} {model} ...", end="", flush=True)
            try:
                record(run_one(model, variant, args.seed, 0, args.rows, args.knn_sample), model)
            except Exception as error:  # one model failing must not kill the table
                print(f" SKIP ({type(error).__name__}: {error})")
            if args.tune_seconds and model in trainer.TUNABLE and model in tunable:
                print(f"  {variant:7s} {model}+tuned ...", end="", flush=True)
                try:
                    tuned = run_one(model, variant, args.seed, args.tune_seconds, args.rows,
                                    args.knn_sample, args.tune_fits)
                except Exception as error:
                    print(f" SKIP ({type(error).__name__}: {error})")
                    continue
                tuned["model"] = f"{model}+tuned"
                tuned["note"] = (f"random search {args.tune_fits} draws x 2 grouped folds "
                                 f"= {args.tune_fits * 2} fits, {args.tune_seconds}s cap")
                record(tuned, f"{model}+tuned")

    if not rows:
        raise SystemExit("no model ran")
    doc_path = Path(args.doc)
    if not doc_path.is_absolute():
        doc_path = REPO / doc_path
    write_doc(rows, doc_path, args.tune_seconds)
    if args.copy_to:
        target = Path(args.copy_to)
        if not target.is_absolute():
            target = REPO / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ledger.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        print(f"  ledger copy -> {target}")
    best = max(rows, key=lambda row: row["r2_log"])
    print(f"\nbest: {best['model']} / {best['features']}  R2(log) {best['r2_log']:.4f}  MAPE {best['mape']:.3f}")
    print(f"  table -> {doc_path}")
    print(f"  ledger -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
