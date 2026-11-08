"""Shared plumbing for the week-3 models: loading, metrics, the prediction contract.

One place decides which columns are features (the same rule `tools/model_gate` enforces),
one place turns a prediction vector into the 14 columns `docs/week3_plan.md` §3 asks for,
and one place computes every metric in **both** log and VND space so no model can report
only the flattering one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from src.common import config

TARGET = "price_vnd"
ID_COLUMNS = ("listing_id", "duplicate_group_id")
GROUP = "duplicate_group_id"
SEED = 42
VARIANTS = ("minimal", "full")
PREDICTION_COLUMNS = (
    "listing_id", "duplicate_group_id", "brand", "model", "manufacture_year", "mileage_km",
    "location_province", "source_platform", "price_vnd", "y_pred_log", "y_pred_vnd",
    "p10_vnd", "p90_vnd", "residual", "abs_pct_error",
)


def features_path(variant: str, split: str) -> Path:
    return config.DATA_MASTER / f"{split}_features_{variant}.csv"


def raw_path(split: str) -> Path:
    return config.DATA_MASTER / f"{split}.csv"


def load_split(variant: str, split: str, rows: int = 0, seed: int = SEED) -> pd.DataFrame:
    """Load a feature table; `rows > 0` takes a seeded sample (for 20k-row ablations)."""
    path = features_path(variant, split)
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.features.build_features "
                         f"--features {variant}'")
    frame = pd.read_csv(path, low_memory=False)
    if rows and split == "train" and rows < len(frame):
        frame = frame.sample(n=rows, random_state=seed).reset_index(drop=True)
    return frame


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """Everything except the trace ids and the target — the gate's promise, applied here."""
    return [column for column in frame.columns if column not in (*ID_COLUMNS, TARGET)]


def split_xy(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    x = frame[feature_columns(frame)].copy()
    for column in x.columns:
        # pandas 3 uses the `str` dtype for text, so ask "is it numeric?" instead of "is it object?"
        if not pd.api.types.is_numeric_dtype(x[column]):
            x[column] = x[column].astype("category")
    return x, frame[TARGET]


def align_categories(x_train: pd.DataFrame, x_other: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Never let val introduce a category train never saw: unseen values become NaN for trees."""
    x_other = x_other.copy()
    for column in x_train.columns:
        if isinstance(x_train[column].dtype, pd.CategoricalDtype):
            x_other[column] = x_other[column].astype("category").cat.set_categories(
                x_train[column].cat.categories)
    return x_train, x_other


def metrics(y_true: Iterable[float], y_pred: Iterable[float]) -> dict:
    """R²/RMSE in log space (what models optimise) and MAE/MAPE/R² in VND space (what a reader feels)."""
    true_vnd = np.asarray(y_true, dtype=float)
    pred_vnd = np.clip(np.asarray(y_pred, dtype=float), 1.0, None)
    true_log, pred_log = np.log(true_vnd), np.log(pred_vnd)
    ss_res = float(((true_log - pred_log) ** 2).sum())
    ss_tot = float(((true_log - true_log.mean()) ** 2).sum())
    vnd_res = float(((true_vnd - pred_vnd) ** 2).sum())
    vnd_tot = float(((true_vnd - true_vnd.mean()) ** 2).sum())
    return {
        "r2_log": round(1 - ss_res / ss_tot, 4) if ss_tot else float("nan"),
        "rmse_log": round(float(np.sqrt(ss_res / len(true_log))), 4),
        "r2_vnd": round(1 - vnd_res / vnd_tot, 4) if vnd_tot else float("nan"),
        "mae_vnd": int(round(float(np.abs(true_vnd - pred_vnd).mean()))),
        "mape": round(float((np.abs(true_vnd - pred_vnd) / true_vnd).mean()), 4),
        "median_ape": round(float(np.median(np.abs(true_vnd - pred_vnd) / true_vnd)), 4),
    }


def predictions_frame(split_frame: pd.DataFrame, y_pred_vnd, p10=None, p90=None,
                      split: str = "val") -> pd.DataFrame:
    """The 14-column contract; `location_province` is not in the feature table, so join the raw split."""
    raw = pd.read_csv(raw_path(split), usecols=["listing_id", "location_province"], low_memory=False)
    frame = split_frame[[*ID_COLUMNS, "brand", "model", "manufacture_year", "mileage_km",
                         "source_platform", TARGET]].copy()
    frame = frame.merge(raw, on="listing_id", how="left")
    pred = np.clip(np.asarray(y_pred_vnd, dtype=float), 1.0, None)
    frame["y_pred_log"] = np.log(pred)
    frame["y_pred_vnd"] = pred
    frame["p10_vnd"] = np.asarray(p10, dtype=float) if p10 is not None else np.nan
    frame["p90_vnd"] = np.asarray(p90, dtype=float) if p90 is not None else np.nan
    frame["residual"] = frame[TARGET] - pred
    frame["abs_pct_error"] = (frame["residual"].abs() / frame[TARGET])
    return frame[list(PREDICTION_COLUMNS)]


def append_result(path: Path, row: dict) -> dict:
    """`model_results.json` is an append-only ledger: one row per (model, features, seed) run."""
    payload = {"generated_at": config.now_iso(), "results": []}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.setdefault("results", [])
        except json.JSONDecodeError:
            pass
    frozen = bool((row.get("tuning") or {}).get("frozen"))
    key = (row.get("model"), row.get("features"), row.get("seed"), row.get("holdout", "val"), frozen)
    payload["results"] = [existing for existing in payload["results"]
                          if (existing.get("model"), existing.get("features"), existing.get("seed"),
                              existing.get("holdout", "val"),
                              bool((existing.get("tuning") or {}).get("frozen"))) != key]
    payload["results"].append(row)
    payload["results"].sort(key=lambda item: (item.get("features", ""), -float(item.get("r2_log") or 0)))
    payload["generated_at"] = config.now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
