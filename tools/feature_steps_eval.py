"""Four cumulative feature steps, each trained once, each scored on `val_full` and `val_clean`.

The steps are cumulative on purpose — the question is not "which column is best" but "does the next
change still pay after the previous one":

    1. baseline                       v1 feature table, every row weight 1
    2. + weight_repeats               v1 features, a repeated advertisement weighs 1/k
    3. + engine parse & trim_rank     v2 table: engine parsed from the badge, trim_rank, trim_missing
    4. + canonical model & variants   v2 table with `model` replaced by `model_canonical`,
                                      plus variant_tokens and variant_count

`val_clean` is the val rows whose `flag_count` is 0 — the identical rows for all four steps, so a
change there is a training effect and not the evaluation set getting easier
(`docs/label_cleaning.md` explains why that distinction mattered).

The estimator and its parameters are fixed: this compares feature sets and weights, not models.

Run:
    python -m tools.feature_steps_eval
    python -m tools.feature_steps_eval --steps 1 2 3
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
from src.data_prep import quality  # noqa: E402
from src.models import common  # noqa: E402

STEPS = (
    (1, "baseline", "v1 table, weight 1"),
    (2, "+ weight_repeats", "v1 table, 1/k for repeated ads"),
    (3, "+ engine parse & trim_rank", "v2 table: engine parsed, trim_rank, trim_missing"),
    (4, "+ canonical model & variants", "v2 table, model_canonical + variant_tokens, variant_count"),
)
PARAMS = dict(n_estimators=300, learning_rate=0.06, num_leaves=63, min_child_samples=40,
              random_state=42, n_jobs=-1, verbose=-1)
V2_DIR = config.DATA_MASTER / "v2"


def load(split: str, step: int) -> pd.DataFrame:
    """Step 1-2 read the frozen v1 table; step 3-4 read the v2 table written beside it."""
    if step <= 2:
        return common.load_split("full", split)
    path = V2_DIR / f"{split}_features_full.csv"
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.features.extend --write'")
    frame = pd.read_csv(path, low_memory=False)
    frame["listing_id"] = frame["listing_id"].astype(str)
    return frame


def columns_for(step: int, frame: pd.DataFrame) -> pd.DataFrame:
    """Step 4 swaps `model` for its canonical form; the raw column stays available in the file."""
    if step < 4:
        return frame
    return frame.drop(columns=["model"])


def fit_score(train: pd.DataFrame, val: pd.DataFrame, clean: np.ndarray, weights: np.ndarray) -> dict:
    import lightgbm as lgb

    xtr, ytr = common.split_xy(train)
    xva, _ = common.split_xy(val)
    xtr, xva = common.align_categories(xtr, xva)
    categorical = [c for c in xtr.columns if isinstance(xtr[c].dtype, pd.CategoricalDtype)]
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(xtr, np.log(ytr.to_numpy(dtype=float)), sample_weight=weights,
              categorical_feature=categorical)
    predicted = np.exp(model.predict(xva))
    return {"full": common.metrics(val["price_vnd"], predicted),
            "clean": common.metrics(val["price_vnd"][clean], predicted[clean]),
            "n_features": int(xtr.shape[1]),
            "train_rows": int(len(xtr))}



def write_doc(doc: Path, payload: dict) -> None:
    lines = [
        "# Feature steps — what each change buys, on two fixed hold-outs",
        "",
        f"Generated {payload['generated_at']} by `python -m tools.feature_steps_eval`.",
        f"Fixed estimator (LightGBM, {PARAMS['n_estimators']} trees); only the feature set and the "
        f"row weights change between rows. `val_full` = {payload['val_full_rows']:,} rows, "
        f"`val_clean` = {payload['val_clean_rows']:,} rows (the same rows for every step).",
        "",
        "| # | Step | Features | Train rows | R² val_full | MAPE val_full | ΔMAPE | "
        "R² val_clean | MAPE val_clean | ΔMAPE |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    previous = None
    for item in payload["results"]:
        full, clean = item["val_full"], item["val_clean"]
        delta_full = "" if previous is None else f"{full['mape'] - previous['val_full']['mape']:+.4f}"
        delta_clean = "" if previous is None else f"{clean['mape'] - previous['val_clean']['mape']:+.4f}"
        lines.append(f"| {item['step']} | {item['label']} | {item['n_features']} | "
                     f"{item['train_rows']:,} | {full['r2_log']:.4f} | {full['mape']:.4f} | "
                     f"{delta_full} | {clean['r2_log']:.4f} | {clean['mape']:.4f} | {delta_clean} |")
        previous = item
    lines += ["", "## Reading", "",
              "- A step pays only if **both** columns improve: `val_full` is the deployment number, "
              "`val_clean` proves the gain is not the evaluation set getting easier.",
              "- Step 3 keeps `engine_capacity` beside `engine_capacity_parsed`, so the delta is purely "
              "additive; step 4 drops `model` in favour of `model_canonical` and keeps `model_group`.",
              "- The raw `model` column still exists in the v2 files — nothing was overwritten.", ""]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cumulative feature steps on val_full and val_clean")
    parser.add_argument("--steps", nargs="+", type=int, default=[step for step, _, _ in STEPS])
    parser.add_argument("--flags", default=str(config.DATA_MASTER / "label_flags.csv"))
    parser.add_argument("--out", default=str(config.DATA_MASTER / "feature_steps.json"))
    parser.add_argument("--doc", default="docs/features_steps.md")
    args = parser.parse_args(argv)

    flags = quality.load_flags(Path(args.flags))
    labels = {step: (label, note) for step, label, note in STEPS}
    fill = {"deposit_suspected": False, "placeholder_odometer": False, "implausible_year": False,
            "repeat_ad": False, "is_duplicate_copy": False, "flag_count": 0}
    results = []
    val_clean_rows = 0
    val_full_rows = 0

    for step in args.steps:
        label, note = labels[step]
        train = columns_for(step, load("train", step))
        val = columns_for(step, load("val", step))
        train_flags = train[["listing_id"]].merge(flags, on="listing_id", how="left").fillna(fill)
        val_flags = val[["listing_id"]].merge(flags, on="listing_id", how="left").fillna(fill)
        clean = val_flags["flag_count"].to_numpy(dtype=int) == 0
        val_clean_rows, val_full_rows = int(clean.sum()), int(len(val))

        weights = (np.ones(len(train)) if step == 1
                   else quality.cleaning_weights(train_flags, "weight_repeats").to_numpy(dtype=float))

        started = time.monotonic()
        scores = fit_score(train, val, clean, weights)
        row = {"step": step, "label": label, "note": note,
               "seconds": round(time.monotonic() - started, 1),
               "n_features": scores["n_features"], "train_rows": scores["train_rows"],
               "val_full": scores["full"], "val_clean": scores["clean"]}
        results.append(row)
        print(f"  {step}. {label:32s} features {row['n_features']:>3} "
              f"val_full R2 {row['val_full']['r2_log']:.4f} MAPE {row['val_full']['mape']:.4f} | "
              f"val_clean R2 {row['val_clean']['r2_log']:.4f} MAPE {row['val_clean']['mape']:.4f}")

    payload = {"generated_at": config.now_iso(), "estimator": "lightgbm fixed", "params": PARAMS,
               "val_full_rows": val_full_rows, "val_clean_rows": val_clean_rows,
               "val_clean_definition": "val rows whose flag_count == 0 (identical for every step)",
               "note": "cumulative steps; fixed estimator, so the comparison is between feature sets",
               "results": results}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    doc = (Path(args.doc) if Path(args.doc).is_absolute()
           else Path(__file__).resolve().parents[1] / args.doc)
    write_doc(doc, payload)
    print(f"\n  json -> {args.out}\n  doc  -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
