"""Does cleaning the labels actually help, or does it only make the validation set easier?

The label-quality side table (`src/data_prep/quality.py`) can be used four ways. This tool trains the
same fixed LightGBM under each of them and scores it on **two identical hold-outs**:

    val_full    all val rows — what a deployment would meet
    val_clean   the val rows with no flag at all — the same rows for every mode

The second column is the whole point. If a mode improves `val_clean` too, the training set really got
better. If it only improves `val_full`, the improvement is the *evaluation set* getting easier, not the
model getting smarter — and the report must say which of the two happened.

Modes (`src/data_prep/quality.py::cleaning_weights`):

    none              every train row weighs 1
    drop_deposit      deposit-style rows weigh 0
    drop_all          any flagged row weighs 0
    weight_repeats    a repeated advertisement weighs 1/k (k rows in its group)

Run:
    python -m tools.label_cleaning_eval
    python -m tools.label_cleaning_eval --rows 20000 --modes none drop_deposit
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

MODES = ("none", "drop_deposit", "drop_all", "weight_repeats")
PARAMS = dict(n_estimators=300, learning_rate=0.06, num_leaves=63, min_child_samples=40,
              random_state=42, n_jobs=-1, verbose=-1)
FILL = {"deposit_suspected": False, "placeholder_odometer": False, "implausible_year": False,
        "repeat_ad": False, "is_duplicate_copy": False, "flag_count": 0}


def _fit(xtr: pd.DataFrame, ytr: pd.Series, weights: np.ndarray):
    import lightgbm as lgb

    categorical = [c for c in xtr.columns if isinstance(xtr[c].dtype, pd.CategoricalDtype)]
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(xtr, np.log(ytr.to_numpy(dtype=float)), sample_weight=weights,
              categorical_feature=categorical)
    return model


def _score(model, frame: pd.DataFrame, x: pd.DataFrame) -> dict:
    return common.metrics(frame["price_vnd"], np.exp(model.predict(x)))



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label cleaning vs an easier validation set")
    parser.add_argument("--features", default="full", choices=common.VARIANTS)
    parser.add_argument("--rows", type=int, default=0, help="sample the train rows (0 = all)")
    parser.add_argument("--flags", default=str(config.DATA_MASTER / "label_flags.csv"))
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    parser.add_argument("--out", default=str(config.DATA_MASTER / "label_cleaning.json"))
    parser.add_argument("--doc", default="docs/label_cleaning.md")
    args = parser.parse_args(argv)

    train = common.load_split(args.features, "train", args.rows)
    val = common.load_split(args.features, "val")
    flags = quality.load_flags(Path(args.flags))

    train_flags = train[["listing_id"]].merge(flags, on="listing_id", how="left")
    val_flags = val[["listing_id"]].merge(flags, on="listing_id", how="left")
    for name, frame in (("train", train_flags), ("val", val_flags)):
        missing = int(frame["flag_count"].isna().sum())
        if missing:
            print(f"  note: {missing:,} {name} rows have no flag entry -> treated as unflagged")
    train_flags = train_flags.fillna(FILL)
    val_flags = val_flags.fillna(FILL)

    clean = val_flags["flag_count"].to_numpy(dtype=int) == 0
    print(f"val_full {len(val):,} rows · val_clean {int(clean.sum()):,} rows "
          f"({clean.mean():.1%}) — the same rows for every mode")

    xtr, ytr = common.split_xy(train)
    xva, _ = common.split_xy(val)
    xtr, xva = common.align_categories(xtr, xva)

    results = []
    for mode in args.modes:
        started = time.monotonic()
        weights = quality.cleaning_weights(train_flags, mode).to_numpy(dtype=float)
        keep = weights > 0
        model = _fit(xtr[keep], ytr[keep], weights[keep])
        full = _score(model, val, xva)
        clean_scores = _score(model, val[clean], xva[clean])
        row = {"mode": mode, "train_rows": int(keep.sum()), "rows_dropped": int((~keep).sum()),
               "seconds": round(time.monotonic() - started, 1),
               "val_full": full, "val_clean": clean_scores}
        results.append(row)
        print(f"  {mode:15s} train {row['train_rows']:>6,}  "
              f"val_full R2 {full['r2_log']:.4f} MAPE {full['mape']:.4f} | "
              f"val_clean R2 {clean_scores['r2_log']:.4f} MAPE {clean_scores['mape']:.4f}")

    baseline = next((item for item in results if item["mode"] == "none"), None)
    payload = {
        "generated_at": config.now_iso(),
        "features": args.features,
        "estimator": "lightgbm fixed",
        "params": PARAMS,
        "val_full_rows": int(len(val)),
        "val_clean_rows": int(clean.sum()),
        "val_clean_definition": "val rows whose flag_count == 0 in label_flags.csv "
                                "(identical for every mode, so a difference is a training effect)",
        "flags_file": str(args.flags),
        "results": results,
        "deltas_vs_none": [
            {"mode": item["mode"],
             "val_full_mape": round(item["val_full"]["mape"] - baseline["val_full"]["mape"], 4),
             "val_clean_mape": round(item["val_clean"]["mape"] - baseline["val_clean"]["mape"], 4)}
            for item in results if baseline is not None],
        "note": "fixed estimator on purpose: the comparison is between training sets, not models",
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    doc = Path(args.doc) if Path(args.doc).is_absolute() else Path(__file__).resolve().parents[1] / args.doc
    _write_doc(doc, payload)
    print(f"\n  json -> {args.out}\n  doc  -> {args.doc}")
    return 0



def _verdict_lines(payload: dict) -> list[str]:
    """One sentence per mode: did it improve the *model* or only the *evaluation set*?"""
    base = next((item for item in payload["results"] if item["mode"] == "none"), None)
    if base is None:
        return ["- `none` was not run, so there is no baseline to compare against."]
    lines = []
    for item in payload["results"]:
        if item["mode"] == "none":
            continue
        delta_full = item["val_full"]["mape"] - base["val_full"]["mape"]
        delta_clean = item["val_clean"]["mape"] - base["val_clean"]["mape"]
        if delta_clean <= -0.002 and delta_full <= 0.0:
            verdict = "improves **both** hold-outs: a genuinely better training set"
        elif delta_clean <= -0.002 and delta_full > 0.002:
            verdict = ("better on the clean rows but **worse on val_full**: the gain comes from the "
                       "rows it removed, so it must not be quoted as a deployment improvement")
        elif delta_clean > 0.002 and delta_full > 0.002:
            verdict = "worse on both: the rows it removes carried signal the model still needs"
        elif abs(delta_clean) <= 0.002 and abs(delta_full) <= 0.002:
            verdict = "within noise on both hold-outs"
        else:
            verdict = "mixed: read the two columns separately before quoting either"
        lines.append(f"- `{item['mode']}` (train {item['train_rows']:,} rows): "
                     f"MAPE val_full {delta_full:+.4f}, val_clean {delta_clean:+.4f} — {verdict}.")
    return lines


def _write_doc(doc: Path, payload: dict) -> None:
    """A table a reader can act on: both hold-outs side by side."""
    def cell(scores: dict, key: str) -> str:
        value = scores[key]
        return f"{value:.4f}" if isinstance(value, float) else f"{value:,}"

    lines = [
        "# Label cleaning — does it help the model or only the validation set?",
        "",
        f"Generated {payload['generated_at']} by `python -m tools.label_cleaning_eval`.",
        f"Fixed estimator (LightGBM, {payload['params']['n_estimators']} trees) on the "
        f"`{payload['features']}` feature set; only the **training set** changes between rows.",
        "",
        f"`val_full` = {payload['val_full_rows']:,} rows · "
        f"`val_clean` = {payload['val_clean_rows']:,} rows — {payload['val_clean_definition']}.",
        "",
        "| Training mode | Train rows | R²(log) val_full | MAPE val_full | "
        "R²(log) val_clean | MAPE val_clean |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in payload["results"]:
        lines.append(f"| {item['mode']} | {item['train_rows']:,} | "
                     f"{cell(item['val_full'], 'r2_log')} | {cell(item['val_full'], 'mape')} | "
                     f"{cell(item['val_clean'], 'r2_log')} | {cell(item['val_clean'], 'mape')} |")
    lines += ["", "## What this run says", "", *_verdict_lines(payload), "",
              "## Reading it", "",
              "- **val_full** is what a deployment meets; **val_clean** is the same rows for every mode.",
              "- An improvement that appears on **both** columns is a better training set.",
              "- An improvement that appears **only on val_full** means the flagged rows left the "
              "*evaluation* too: that is an easier test, not a better model, and quoting it alone "
              "would be dishonest.",
              "- The estimator and its parameters are fixed on purpose: this compares training sets, "
              "not models."]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
