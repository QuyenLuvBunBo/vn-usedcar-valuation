"""Anomaly labelling: Δ = (ŷ − y)/y, an Isolation Forest, and the four labels §4.3 asks for.

Inputs are the artefacts of `src/models/train.py` (`predictions_val.csv` with P10/P90) plus the
frozen feature table. Outputs are the two files the plan names:

    data/master/anomaly_labels.csv        one row per val listing with Δ, score, label, reason
    data/master/anomaly_thresholds.json   the calibrated thresholds and the review rate they imply

Labels: **Bargain** (price below P10), **Overpriced** (above P90), **Fair** (inside), and
**Suspicious** (outside the band *and* top-1% Isolation Forest score) — the plan's rule.

Run:
    python -m src.models.anomaly --rate 0.03
    python -m src.models.anomaly --compare     # also scores LOF / One-Class SVM for §7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402

MIN_RATE, MAX_RATE = 0.02, 0.05


def _matrix(variant: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Codes for categoricals, not one-hot: cheaper and the forest ranks rows the same way."""
    frame = common.load_split(variant, "val")
    x, _ = common.split_xy(frame)
    numeric = x.select_dtypes("number").to_numpy(dtype=float)
    categorical = x.select_dtypes(exclude="number")
    codes = (np.column_stack([categorical[column].cat.codes.to_numpy(dtype=float)
                              for column in categorical.columns])
             if len(categorical.columns) else np.empty((len(x), 0)))
    matrix = np.hstack([numeric, codes])
    return frame[["listing_id"]].copy(), np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)


def _iso_scores(matrix: np.ndarray, seed: int = 42) -> np.ndarray:
    from sklearn.ensemble import IsolationForest
    model = IsolationForest(n_estimators=300, max_samples=4096, contamination="auto",
                            random_state=seed, n_jobs=-1)
    model.fit(matrix)
    return -model.score_samples(matrix)  # higher = more anomalous


def calibrate(scores: np.ndarray, rate: float) -> float:
    """Threshold such that `rate` of val rows get flagged for human review (clamped to 2–5%)."""
    rate = min(max(rate, MIN_RATE), MAX_RATE)
    return float(np.quantile(scores, 1.0 - rate))


def label_rows(predictions: pd.DataFrame, iso_scores: np.ndarray, iso_threshold: float) -> pd.DataFrame:
    frame = predictions.copy()
    frame["delta"] = (frame["y_pred_vnd"] - frame["price_vnd"]) / frame["price_vnd"]
    frame["iso_score"] = iso_scores
    if frame["p10_vnd"].notna().any() and frame["p90_vnd"].notna().any():
        below = frame["price_vnd"] < frame["p10_vnd"]
        above = frame["price_vnd"] > frame["p90_vnd"]
    else:  # fallback before the quantile artifact exists; the thresholds file records which mode ran
        ratio = frame["price_vnd"] / frame["y_pred_vnd"]
        below = ratio < ratio.quantile(0.10)
        above = ratio > ratio.quantile(0.90)
    frame["band"] = np.where(below, "below_p10", np.where(above, "above_p90", "inside"))
    suspicious = (frame["band"] != "inside") & (frame["iso_score"] >= iso_threshold)
    frame["label"] = np.where(suspicious, "Suspicious",
                              np.where(below, "Bargain",
                                       np.where(above, "Overpriced", "Fair")))
    frame["reason"] = [f"{band} + iso {score:.4f}"
                       for band, score in zip(frame["band"], frame["iso_score"])]
    return frame


def compare_models(matrix: np.ndarray, iso_scores: np.ndarray) -> dict:
    """Plan §4.3 S-item: the same review rate under LOF and One-Class SVM, next to the forest."""
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.svm import OneClassSVM

    sample = np.random.RandomState(42).choice(len(matrix), min(12000, len(matrix)), replace=False)
    subset = matrix[sample]
    out = {"isolation_forest": {"flagged_rate": float((iso_scores >= np.quantile(iso_scores, 0.97)).mean())}}
    try:
        out["lof"] = {"flagged_rate": float((LocalOutlierFactor(n_neighbors=35).fit_predict(subset) == -1).mean())}
    except Exception as error:
        out["lof"] = {"error": type(error).__name__}
    try:
        out["one_class_svm"] = {"flagged_rate": float((OneClassSVM(nu=0.03, gamma="scale")
                                                       .fit_predict(subset) == -1).mean())}
    except Exception as error:
        out["one_class_svm"] = {"error": type(error).__name__}
    return out


def proxy_matrix(labels: pd.DataFrame) -> pd.DataFrame:
    """quality_flags × label — a **proxy**, exactly as the plan insists it must be called."""
    raw = pd.read_csv(common.raw_path("val"), usecols=["listing_id", "quality_flags"], low_memory=False)
    merged = labels.merge(raw, on="listing_id", how="left")
    merged["flag_count"] = merged["quality_flags"].fillna("").apply(
        lambda text: 0 if not str(text).strip() else len(str(text).split(";")))
    merged["has_quality_flag"] = merged["flag_count"] > 0
    return (merged.groupby(["has_quality_flag", "label"]).size().unstack(fill_value=0)
            .rename_axis(index="has_quality_flag", columns="label"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label anomalies on the val split")
    parser.add_argument("--rate", type=float, default=0.03, help="review rate, clamped to 2-5%%")
    parser.add_argument("--features", default="full", choices=common.VARIANTS)
    parser.add_argument("--predictions", default=str(config.DATA_MASTER / "predictions_val.csv"))
    parser.add_argument("--compare", action="store_true", help="also score LOF and One-Class SVM")
    args = parser.parse_args(argv)

    predictions = pd.read_csv(args.predictions, low_memory=False)
    ids, matrix = _matrix(args.features)
    predictions = predictions.merge(ids, on="listing_id", how="inner").reset_index(drop=True)
    scores = _iso_scores(matrix)
    threshold = calibrate(scores, args.rate)
    labelled = label_rows(predictions, scores, threshold)
    achieved = float((scores >= threshold).mean())

    columns = ["listing_id", "brand", "model", "price_vnd", "y_pred_vnd", "p10_vnd", "p90_vnd",
               "delta", "abs_pct_error", "iso_score", "band", "label", "reason"]
    labels_path = config.DATA_MASTER / "anomaly_labels.csv"
    labelled[columns].to_csv(labels_path, index=False, lineterminator="\n")

    thresholds = {
        "calibrated_at": config.now_iso(), "rate_requested": args.rate,
        "rate_achieved": round(achieved, 4), "iso_threshold": round(threshold, 6),
        "isolation_forest": {"n_estimators": 300, "max_samples": 4096,
                             "note": "numeric as-is, categoricals as codes; fitted on the val rows"},
        "bands": "Bargain < P10, Overpriced > P90, Suspicious = outside band AND iso >= threshold",
        "quantile_source": ("predictions_val.csv P10/P90" if labelled["p10_vnd"].notna().any()
                            else "fallback: empirical P10/P90 of price/prediction — rebuild with --quantiles"),
        "label_counts": labelled["label"].value_counts().to_dict(),
    }
    if args.compare:
        thresholds["comparison"] = compare_models(matrix, scores)
    (config.DATA_MASTER / "anomaly_thresholds.json").write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proxy_matrix(labelled).to_csv(config.DATA_MASTER / "anomaly_proxy_matrix.csv", lineterminator="\n")

    print(f"rows {len(labelled):,} | review rate {achieved:.2%} (asked {args.rate:.2%}) | "
          f"iso threshold {threshold:.4f}")
    print(labelled["label"].value_counts().to_string())
    print(f"\n  labels -> {labels_path}")
    print(f"  thresholds -> {config.DATA_MASTER / 'anomaly_thresholds.json'}")
    print(f"  proxy matrix -> {config.DATA_MASTER / 'anomaly_proxy_matrix.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
