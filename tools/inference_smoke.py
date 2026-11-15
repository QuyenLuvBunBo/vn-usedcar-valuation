"""Train-serving parity: does `Predictor` reproduce the model's own prediction from a raw row?

The bundle scores a raw listing; the training table scores a row that already went through the
pipeline. If those two disagree, the serving path is wrong even when both "work". This tool measures
the difference on real val rows:

    raw record      -> Predictor.predict_one            -> log(price_serving)
    v2 feature row  -> model_point.joblib directly      -> log(price_direct)
    assert |price_serving - price_direct| / price_direct is ~0

Rows whose v2 cohort was **backfilled** (`v2_filled` not empty) are skipped: their feature row contains
a value the raw cohort does not have, so the two paths are *supposed* to differ there.

Run:
    python -m tools.inference_smoke
    python -m tools.inference_smoke --rows 40 --bundle models/v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402
from src.models.predict import DEFAULT_BUNDLE, Predictor  # noqa: E402

RAW_COLUMNS = ("listing_id", "source_platform", "brand", "model", "sub_model_trim",
               "manufacture_year", "mileage_km", "transmission", "fuel_type", "origin", "body_type",
               "engine_capacity", "seats", "location_province", "seller_type")


def sample(raw: pd.DataFrame, features: pd.DataFrame, rows: int,
           seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Half complete rows, half rows that still have blanks — the second half exercises imputation."""
    usable = features["v2_filled"].fillna("").astype(str) == ""
    features = features[usable]
    raw = raw.copy()
    raw["listing_id"] = raw["listing_id"].astype(str)
    merged = raw.merge(features[["listing_id"]], on="listing_id")

    blank = (merged["sub_model_trim"].isna() | merged["engine_capacity"].isna()
             | merged["mileage_km"].isna()
             | merged["seller_type"].astype(str).str.casefold().eq("unknown"))
    complete = merged[~blank].sample(n=min(rows // 2, int((~blank).sum())), random_state=seed)
    blanks = merged[blank].sample(n=min(rows - len(complete), int(blank.sum())), random_state=seed)
    return complete, blanks


def direct_predictions(features: pd.DataFrame, bundle: Path, ids: list[str]) -> dict[str, float]:
    """The training-side prediction for the same rows, from the exported point model."""
    model = joblib.load(bundle / "model_point.joblib")
    table = features[features["listing_id"].astype(str).isin(set(ids))].copy()
    table["listing_id"] = table["listing_id"].astype(str)
    x, _ = common.split_xy(table)
    categories = json.loads((bundle / "categories.json").read_text(encoding="utf-8"))["categories"]
    for column, values in categories.items():
        if column in x.columns:
            text = x[column].astype(str)
            x[column] = pd.Categorical(text.where(text.isin(values)), categories=values)
    meta = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    predicted = np.exp(model.predict(x[meta["features"]]))
    return dict(zip(table["listing_id"], predicted))



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train-serving parity check")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--rows", type=int, default=30, help="rows to check (half complete, half blank)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(config.DATA_MASTER / "inference_smoke.json"))
    args = parser.parse_args(argv)

    bundle = Path(args.bundle)
    predictor = Predictor.load(bundle)
    features = pd.read_csv(config.DATA_MASTER / "v2" / "val_features_full.csv", low_memory=False)
    features["listing_id"] = features["listing_id"].astype(str)
    v2_cohort = pd.read_csv(config.DATA_MASTER / "v2" / "val_cohort_imputed.csv", low_memory=False,
                            usecols=["listing_id", "v2_filled"])
    v2_cohort["listing_id"] = v2_cohort["listing_id"].astype(str)
    features = features.merge(v2_cohort, on="listing_id", how="left")
    raw = pd.read_csv(config.DATA_MASTER / "val_cohort.csv", low_memory=False)

    complete, blank = sample(raw, features, args.rows, args.seed)
    results = []
    for label, frame in (("complete", complete), ("with-blanks", blank)):
        ids = frame["listing_id"].astype(str).tolist()
        direct = direct_predictions(features, bundle, ids)
        for _, row in frame.iterrows():
            record = {column: row[column] for column in RAW_COLUMNS if column in row}
            served = predictor.predict_one(record)
            served_price = float(served["price_vnd"])
            direct_price = float(direct[str(row["listing_id"])])
            results.append({"listing_id": str(row["listing_id"]), "kind": label,
                            "served_vnd": int(served_price), "direct_vnd": int(direct_price),
                            "ratio": round(served_price / direct_price, 6),
                            "imputed": served["trace"]["imputed"]})
            print(f"  {label:11s} {row['listing_id']:22s} served {served_price:>13,.0f} "
                  f"direct {direct_price:>13,.0f} ratio {served_price / direct_price:.6f}")

    frame = pd.DataFrame(results)
    for label, group in frame.groupby("kind"):
        worst = float((group["ratio"] - 1).abs().max())
        print(f"{label:12s} rows {len(group):>3} · max |ratio-1| {worst:.2e}")

    tolerance = 1e-3
    worst = float((frame["ratio"] - 1).abs().max())
    passed = worst <= tolerance
    payload = {"checked": int(len(frame)), "max_abs_ratio_error": worst, "tolerance": tolerance,
               "passed": passed,
               "note": "serving = raw row through Predictor; direct = the same row's v2 features "
                       "through model_point.joblib; backfilled rows are excluded by design",
               "rows": results}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    print(f"\n  {'PASS' if passed else 'FAIL'} — max error {worst:.2e} "
          f"(tolerance {tolerance:.0e}) -> {args.out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
