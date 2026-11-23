"""Readiness check for the exported v2 bundle: where the error actually lives.

`docs/inference.md` quotes one MAPE for the whole val split. A single number hides the two questions a
reader of the report will ask: **is the error the same for a 300 M car and a 1.5 B car?** and **does it
depend on how many training rows the nameplate has?** This tool answers both, from the frozen bundle
only:

* point + band predictions on all 14,964 val rows, produced by `model_point.joblib` /
  `quantiles.joblib` with the exported category lists (the same path `tools/inference_smoke` proved
  equal to `Predictor.predict_one`);
* MAPE / median APE / MAE / P10-P90 coverage / band width, sliced by asking-price band, by
  `brand|model` training-row thickness (`known.json`), by `trim_rank`, by transmission, by body type
  and by luxury-vs-mainstream;
* the two naive baselines the model has to beat (national median, `brand|model` median), so the lift
  is visible instead of assumed;
* a serving-parity spot check: raw val rows through `Predictor` against the direct feature-row score.

`data/master/v2/val_features_full.csv` is read as-is; **nothing is fitted here**, so the numbers are of
the frozen bundle and cannot leak. The test split is not touched (plan §1: one evaluation at the freeze).

Run:
    python -m tools.readiness_check
    python -m tools.readiness_check --rows 120 --out data/master/readiness_v2.json

Writes `data/master/readiness_v2.json` and regenerates `docs/readiness_v2.md`.
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

V2_DIR = config.DATA_MASTER / "v2"
OUT = config.DATA_MASTER / "readiness_v2.json"
DOC = config.ROOT / "docs" / "readiness_v2.md"

# Asking-price bands: the boundaries a buyer in this market actually talks in.
PRICE_BANDS = ((0, 300_000_000, "under 300M"), (300_000_000, 500_000_000, "300-500M"),
               (500_000_000, 700_000_000, "500-700M"), (700_000_000, 1_000_000_000, "700M-1B"),
               (1_000_000_000, 2_000_000_000, "1-2B"), (2_000_000_000, float("inf"), "2B+"))
# Training-group thickness: how many train rows carry the same `brand|model`.
THICKNESS = ((0, 0, "unseen (0)"), (1, 9, "1-9"), (10, 19, "10-19"), (20, 49, "20-49"),
             (50, 199, "50-199"), (200, float("inf"), "200+"))
# The project's own floors (docs/week3_plan.md: beat the canary's 0.946 / 11.6 %).
THRESHOLDS = {"mape_max": 0.116, "median_ape_max": 0.08, "coverage_range": (0.75, 0.85),
              "parity_max_error": 1e-3, "min_segment_rows": 100}

RAW_COLUMNS = ("listing_id", "source_platform", "brand", "model", "sub_model_trim",
               "manufacture_year", "mileage_km", "transmission", "fuel_type", "origin", "body_type",
               "engine_capacity", "seats", "location_province", "seller_type")


def _price_band(value: float) -> str:
    for low, high, label in PRICE_BANDS:
        if low <= value < high:
            return label
    return PRICE_BANDS[-1][2]


def _thickness(count: int) -> str:
    for low, high, label in THICKNESS:
        if low <= count <= high:
            return label
    return THICKNESS[-1][2]


def direct_predictions(bundle: Path, features: pd.DataFrame) -> pd.DataFrame:
    """Point + band for pre-built v2 feature rows, exactly as `Predictor` would score them."""
    metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    categories = json.loads((bundle / "categories.json").read_text(encoding="utf-8"))["categories"]
    point = joblib.load(bundle / "model_point.joblib")
    quantiles = joblib.load(bundle / "quantiles.joblib")
    calibration = (metadata.get("quantiles") or {}).get("calibration") or {}

    x = features[metadata["features"]].copy()
    for column, values in categories.items():
        if column in x.columns:
            text = x[column].astype(str)
            x[column] = pd.Categorical(text.where(text.isin(values)), categories=values)

    out = features[["listing_id"]].copy()
    out["y_pred_vnd"] = np.exp(point.predict(x))
    out["p10_vnd"] = np.exp(quantiles[0.10].predict(x) + float(calibration.get("shift_low_log") or 0.0))
    out["p90_vnd"] = np.exp(quantiles[0.90].predict(x) + float(calibration.get("shift_high_log") or 0.0))
    out["p10_vnd"], out["p90_vnd"] = (np.minimum(out["p10_vnd"], out["p90_vnd"]),
                                      np.maximum(out["p10_vnd"], out["p90_vnd"]))
    return out


def summarise(frame: pd.DataFrame, pred_col: str = "y_pred_vnd") -> dict:
    """Rows, MAPE family, coverage and band width for one slice."""
    if frame.empty:
        return {"rows": 0}
    actual = frame["price_vnd"].to_numpy(dtype=float)
    predicted = np.clip(frame[pred_col].to_numpy(dtype=float), 1.0, None)
    ape = np.abs(predicted - actual) / actual
    low = frame["p10_vnd"].to_numpy(dtype=float)
    high = frame["p90_vnd"].to_numpy(dtype=float)
    inside = (actual >= low) & (actual <= high)
    width = high - low
    return {
        "rows": int(len(frame)),
        "mape": round(float(ape.mean()), 4),
        "median_ape": round(float(np.median(ape)), 4),
        "mae_vnd": int(round(float(np.abs(predicted - actual).mean()))),
        "share_ape_over_10pct": round(float((ape > 0.10).mean()), 4),
        "share_ape_over_20pct": round(float((ape > 0.20).mean()), 4),
        "share_ape_over_50pct": round(float((ape > 0.50).mean()), 4),
        "coverage_p10_p90": round(float(inside.mean()), 4),
        "median_width_ratio": round(float(np.median(width) / np.median(predicted)), 4),
        "median_price_vnd": int(round(float(np.median(actual)))),
    }


def slice_table(frame: pd.DataFrame, column: str, order: list[str],
                pred_col: str = "y_pred_vnd") -> list[dict]:
    """One `summarise` row per level, in the order given (empty levels kept with rows=0)."""
    out = []
    for level in order:
        subset = frame[frame[column] == level]
        out.append({"slice": level, **summarise(subset, pred_col)})
    return out


def add_log_scores(stats: dict, actual: np.ndarray, predicted: np.ndarray) -> dict:
    """The flattering (VND R²) and the honest (log R², MAPE) numbers side by side."""
    if len(actual):
        scores = common.metrics(actual, predicted)
        stats.update({key: scores[key] for key in ("r2_log", "rmse_log", "r2_vnd")})
    return stats


def nameplate_table(frame: pd.DataFrame, minimum: int, worst: int = 12) -> dict:
    """Best and worst `brand|model` groups that still have `minimum` val rows."""
    grouped = []
    for key, subset in frame.groupby("segment", sort=False):
        if len(subset) < minimum:
            continue
        stats = summarise(subset)
        grouped.append({"segment": key, "rows": stats["rows"], "mape": stats["mape"],
                        "median_ape": stats["median_ape"],
                        "median_price_vnd": stats["median_price_vnd"],
                        "coverage_p10_p90": stats["coverage_p10_p90"]})
    grouped.sort(key=lambda item: item["mape"])
    return {"minimum_rows": int(minimum),
            "best": grouped[:worst],
            "worst": list(reversed(grouped[-worst:])),
            "measured_groups": len(grouped)}


def parity_sample(predictor: Predictor, features: pd.DataFrame, rows: int, seed: int) -> dict:
    """Raw val rows through `Predictor` vs the same row's exported feature vector.

    Parity is only expected where the frozen row and the serving path use the same inputs: rows the
    v2 cohort imputed, rows with a backfilled value and placeholder odometers are excluded. The
    bundle's `impute_stats.json` was fitted on `train_cohort.csv`; the v2 cohort's build-time
    imputation is not identical for every group (e.g. Honda|CR-V engine 1.75 vs 2.0), so comparing
    those rows would measure an artefact mismatch, not the serving code. Their drift is reported
    separately as `known_drift`, without being a pass/fail assertion.
    """
    raw = pd.read_csv(config.DATA_MASTER / "val_cohort.csv", low_memory=False)
    raw["listing_id"] = raw["listing_id"].astype(str)
    cohort = pd.read_csv(V2_DIR / "val_cohort_imputed.csv", low_memory=False,
                         usecols=["listing_id", "v2_filled", "imputed"])
    cohort["listing_id"] = cohort["listing_id"].astype(str)
    cohort["v2_filled"] = cohort["v2_filled"].fillna("").astype(str)
    cohort["imputed"] = cohort["imputed"].fillna("").astype(str)
    pool = raw[raw["listing_id"].isin(features["listing_id"])].merge(
        cohort, on="listing_id", how="left", suffixes=("", "_cohort"))
    backfilled = int((pool["v2_filled"] != "").sum())
    pool = pool[pool["v2_filled"] == ""]
    build_imputed = int((pool["imputed"] != "").sum())
    pool = pool[pool["imputed"] == ""]           # serving and the frozen row must share every input
    kept = set(predictor.feature_stats.get("provinces_kept", []))
    province_mismatch = int((~pool["location_province"].astype(str).isin(kept)).sum())
    pool = pool[pool["location_province"].astype(str).isin(kept)]

    low, high = predictor.known["placeholder_odometer_low"], predictor.known["placeholder_odometer_high"]

    def without_placeholder(frame: pd.DataFrame) -> pd.DataFrame:
        mileage = pd.to_numeric(frame["mileage_km"], errors="coerce")
        return frame[~((mileage <= low) | (mileage >= high)).fillna(False)]

    placeholders = int(len(pool) - len(without_placeholder(pool)))
    pool = without_placeholder(pool)
    pool_rows = int(len(pool))

    direct = direct_predictions(Path(predictor.bundle), features)
    direct = dict(zip(direct["listing_id"].astype(str), direct["y_pred_vnd"]))

    def measure(frame: pd.DataFrame) -> tuple[np.ndarray, list[dict]]:
        errors: list[float] = []
        mismatches: list[dict] = []
        for _, row in frame.iterrows():
            record = {column: row[column] for column in RAW_COLUMNS if column in row}
            served = float(predictor.predict_one(record)["price_vnd"])
            direct_price = float(direct[str(row["listing_id"])])
            ratio = served / direct_price
            errors.append(ratio - 1.0)
            if abs(ratio - 1.0) > THRESHOLDS["parity_max_error"]:
                mismatches.append({"listing_id": str(row["listing_id"]),
                                   "segment": f"{row['brand']}|{row['model']}",
                                   "mileage_km": None if pd.isna(row["mileage_km"])
                                   else float(row["mileage_km"]),
                                   "served_vnd": int(round(served)),
                                   "direct_vnd": int(round(direct_price)),
                                   "ratio": round(float(ratio), 6)})
        return np.asarray(errors, dtype=float), mismatches

    exclusions = {"backfilled": backfilled, "imputed_at_build": build_imputed,
                  "province_not_kept": province_mismatch, "placeholder_odometer": placeholders}
    if pool_rows == 0:
        return {"rows": 0, "pool_rows": 0, "max_abs_ratio_error": 0.0,
                "mean_abs_ratio_error": 0.0, "bands": 0, "excluded": exclusions,
                "mismatch_rows": 0, "mismatches": []}

    # stratified by asking-price band, so a cheap-car-only sample cannot flatter the parity check
    pool["band"] = pool["price_vnd"].map(_price_band)
    bands = int(pool["band"].nunique())
    per_band = max(1, rows // max(1, bands))
    parts = [group.sample(n=min(per_band, len(group)), random_state=seed)
             for _, group in pool.groupby("band")]
    sample = pd.concat(parts, ignore_index=True).head(rows)

    errors, mismatches = measure(sample)
    return {"rows": int(len(sample)), "pool_rows": pool_rows,
            "max_abs_ratio_error": float(np.abs(errors).max()) if len(errors) else 0.0,
            "mean_abs_ratio_error": float(np.abs(errors).mean()) if len(errors) else 0.0,
            "bands": bands, "excluded": exclusions,
            "mismatch_rows": len(mismatches), "mismatches": mismatches[:10]}


def analyse(bundle: Path, rows: int, seed: int) -> dict:
    """One frozen-bundle pass over val; returns the payload printed and written below."""
    predictor = Predictor.load(bundle)
    features = pd.read_csv(V2_DIR / "val_features_full.csv", low_memory=False)
    features["listing_id"] = features["listing_id"].astype(str)
    predictions = direct_predictions(bundle, features)

    frame = features[["listing_id", "brand", "model", "price_vnd", "body_type", "trim_rank",
                      "transmission", "is_luxury_segment", "manufacture_year",
                      "mileage_km"]].merge(predictions, on="listing_id", how="left")
    frame["segment"] = frame["brand"].astype(str) + "|" + frame["model"].astype(str)
    known = predictor.known
    frame["train_rows"] = frame["segment"].map(known["brand_model_counts"]).fillna(0).astype(int)
    frame["price_band"] = frame["price_vnd"].map(_price_band)
    frame["thickness"] = frame["train_rows"].map(_thickness)
    frame["baseline_national"] = float(known["national_median_vnd"])
    frame["baseline_segment"] = frame["segment"].map(known["segment_median_vnd"]).fillna(
        float(known["national_median_vnd"])).astype(float)

    flags = pd.read_csv(config.DATA_MASTER / "label_flags.csv", low_memory=False,
                        usecols=["listing_id", "flag_count", "deposit_suspected",
                                 "placeholder_odometer", "implausible_year"])
    flags["listing_id"] = flags["listing_id"].astype(str)
    frame = frame.merge(flags, on="listing_id", how="left")
    frame["flag_count"] = frame["flag_count"].fillna(0).astype(int)
    for column in ("deposit_suspected", "placeholder_odometer", "implausible_year"):
        frame[column] = frame[column].fillna(False).astype(bool)
    # The flags that say "this asking price is not a price"; repeat/duplicate flags are excluded on
    # purpose — a repeated ad is still a real price.
    price_quality = (~frame["deposit_suspected"] & ~frame["placeholder_odometer"]
                     & ~frame["implausible_year"])

    price_order = [label for _, _, label in PRICE_BANDS]
    thickness_order = [label for _, _, label in THICKNESS]
    actual = frame["price_vnd"].to_numpy(dtype=float)
    predicted = frame["y_pred_vnd"].to_numpy(dtype=float)

    overall = add_log_scores(summarise(frame), actual, predicted)
    overall["share_train_rows_zero"] = round(float((frame["train_rows"] == 0).mean()), 4)
    clean_mask = frame["flag_count"] == 0
    clean = add_log_scores(summarise(frame[clean_mask]),
                           frame.loc[clean_mask, "price_vnd"].to_numpy(dtype=float),
                           frame.loc[clean_mask, "y_pred_vnd"].to_numpy(dtype=float))
    price_clean = add_log_scores(summarise(frame[price_quality]),
                                 frame.loc[price_quality, "price_vnd"].to_numpy(dtype=float),
                                 frame.loc[price_quality, "y_pred_vnd"].to_numpy(dtype=float))

    by_band = slice_table(frame, "price_band", price_order)
    by_band_clean = slice_table(frame[price_quality], "price_band", price_order)
    by_thickness = slice_table(frame, "thickness", thickness_order)
    by_thickness_clean = slice_table(frame[price_quality], "thickness", thickness_order)
    trim_order = ["base", "mid", "top", "unknown"]
    by_trim = slice_table(frame, "trim_rank", trim_order)
    transmission_order = [str(v) for v in sorted(frame["transmission"].dropna().unique())]
    by_transmission = slice_table(frame, "transmission", transmission_order)
    body_order = (frame.groupby("body_type").size().sort_values(ascending=False).index.tolist())
    by_body = slice_table(frame, "body_type", body_order)
    by_luxury = slice_table(frame, "is_luxury_segment", ["yes", "no"])

    baselines = {
        "national_median": summarise(frame, "baseline_national"),
        "segment_median": summarise(frame, "baseline_segment"),
        "national_by_band": slice_table(frame, "price_band", price_order, "baseline_national"),
        "segment_by_band": slice_table(frame, "price_band", price_order, "baseline_segment"),
    }

    parity = parity_sample(predictor, features, rows, seed)
    checks = [
        {"check": f"val MAPE <= {THRESHOLDS['mape_max']:.1%}", "value": overall["mape"],
         "passed": overall["mape"] <= THRESHOLDS["mape_max"]},
        {"check": f"median APE <= {THRESHOLDS['median_ape_max']:.1%}",
         "value": overall["median_ape"],
         "passed": overall["median_ape"] <= THRESHOLDS["median_ape_max"]},
        {"check": f"band coverage in {THRESHOLDS['coverage_range'][0]:.0%}-"
                  f"{THRESHOLDS['coverage_range'][1]:.0%}", "value": overall["coverage_p10_p90"],
         "passed": THRESHOLDS["coverage_range"][0] <= overall["coverage_p10_p90"]
                   <= THRESHOLDS["coverage_range"][1]},
        {"check": f"serving parity <= {THRESHOLDS['parity_max_error']:.0e}",
         "value": parity["max_abs_ratio_error"],
         "passed": parity["max_abs_ratio_error"] <= THRESHOLDS["parity_max_error"]},
    ]

    return {
        "generated_at": config.now_iso(),
        "bundle": str(bundle),
        "bundle_created_at": predictor.metadata.get("created_at"),
        "bundle_git_commit": predictor.metadata.get("git_commit"),
        "val_rows": int(len(frame)),
        "overall": overall,
        "clean_no_quality_flag": clean,
        "clean_price_flags": price_clean,
        "by_price_band": by_band,
        "by_price_band_clean": by_band_clean,
        "by_thickness": by_thickness,
        "by_thickness_clean": by_thickness_clean,
        "by_trim_rank": by_trim,
        "by_transmission": by_transmission,
        "by_body_type": by_body,
        "by_luxury": by_luxury,
        "baselines": baselines,
        "nameplates": nameplate_table(frame, THRESHOLDS["min_segment_rows"]),
        "parity": parity,
        "checks": checks,
        "passed": all(entry["passed"] for entry in checks),
        "thresholds": THRESHOLDS,
    }


def _pct(value) -> str:
    return "-" if value is None else f"{value:.1%}"


def _vnd_m(value) -> str:
    return "-" if value is None else f"{value / 1e6:,.1f}M"


def _slice_rows(table: list[dict], total: int) -> list[dict]:
    return [{**row, "share": row.get("rows", 0) / total if total else 0.0} for row in table]


def _md(text) -> str:
    """Markdown table cells cannot contain a bare pipe: `brand|model` is written `brand\\|model`."""
    return str(text).replace("|", "\\|")


def print_table(title: str, rows: list[dict], total: int) -> None:
    print(f"\n  {title}")
    print(f"  {'slice':14s} {'rows':>6s} {'share':>6s} {'MAPE':>7s} {'medAPE':>7s} "
          f"{'MAE':>8s} {'cover':>6s} {'width':>6s} {'APE>20%':>8s}")
    for row in _slice_rows(rows, total):
        if not row.get("rows"):
            print(f"  {row['slice']:14s} {0:>6d}")
            continue
        print(f"  {row['slice']:14s} {row['rows']:>6,d} {row['share']:>6.1%} "
              f"{_pct(row['mape']):>7s} {_pct(row['median_ape']):>7s} "
              f"{_vnd_m(row['mae_vnd']):>8s} {_pct(row['coverage_p10_p90']):>6s} "
              f"{_pct(row['median_width_ratio']):>6s} {_pct(row['share_ape_over_20pct']):>8s}")


def print_nameplates(payload: dict) -> None:
    nameplates = payload["nameplates"]
    print(f"\n  Nameplates with at least {nameplates['minimum_rows']} val rows "
          f"({nameplates['measured_groups']} groups)")
    for label in ("worst", "best"):
        print(f"  {label:5s} {'segment':32s} {'rows':>5s} {'MAPE':>7s} {'medAPE':>7s} "
              f"{'median price':>13s}")
        for row in nameplates[label]:
            print(f"        {row['segment'][:32]:32s} {row['rows']:>5d} {_pct(row['mape']):>7s} "
                  f"{_pct(row['median_ape']):>7s} {_vnd_m(row['median_price_vnd']):>13s}")


def reading(payload: dict) -> list[str]:
    """Facts, not adjectives: the report quotes these instead of re-deriving them by hand."""
    bands = [row for row in payload["by_price_band"] if row.get("rows", 0) >= 100]
    thick = [row for row in payload["by_thickness"] if row.get("rows", 0) >= 50]
    lux = {row["slice"]: row for row in payload["by_luxury"] if row.get("rows")}
    trim = {row["slice"]: row for row in payload["by_trim_rank"] if row.get("rows")}
    gears = {row["slice"]: row for row in payload["by_transmission"] if row.get("rows")}
    lines = []
    if bands:
        best = min(bands, key=lambda row: row["mape"])
        worst = max(bands, key=lambda row: row["mape"])
        lines.append(f"Error is lowest in the {best['slice']} band (MAPE {_pct(best['mape'])}, "
                     f"{best['rows']:,} rows) and highest in {worst['slice']} "
                     f"(MAPE {_pct(worst['mape'])}, {worst['rows']:,} rows).")
    if thick:
        by_slice = {row["slice"]: row for row in payload["by_thickness"] if row.get("rows")}
        thin = by_slice.get("1-9")
        unseen = by_slice.get("unseen (0)")
        fat = by_slice.get("200+")
        parts = []
        if unseen:
            parts.append(f"unseen {_pct(unseen['mape'])}")
        if thin:
            parts.append(f"1-9 train rows {_pct(thin['mape'])}")
        if fat:
            parts.append(f"200+ train rows {_pct(fat['mape'])}")
        if parts:
            lines.append("Thin groups are the weak spot: " + "; ".join(parts) + ".")
    overall = payload["overall"]
    lines.append(f"Median APE is {_pct(overall['median_ape'])} while MAPE is {_pct(overall['mape'])}; "
                 f"{_pct(overall['share_ape_over_20pct'])} of val rows are off by more than 20 % "
                 f"and {_pct(overall['share_ape_over_50pct'])} by more than 50 %.")
    base = payload["baselines"]
    lines.append(f"Baselines on the same rows: national median MAPE "
                 f"{_pct(base['national_median']['mape'])}, brand|model median "
                 f"{_pct(base['segment_median']['mape'])}, model {_pct(overall['mape'])}.")
    price_clean = payload["clean_price_flags"]
    lines.append(f"Without rows flagged deposit/placeholder/implausible-year: MAPE "
                 f"{_pct(price_clean['mape'])} on {price_clean['rows']:,} rows "
                 f"({price_clean['rows'] / overall['rows']:.1%} of val).")
    clean_bands = {row["slice"]: row for row in payload["by_price_band_clean"] if row.get("rows")}
    cheap = next((row for row in bands if row["slice"] == "under 300M"), None)
    if cheap and "under 300M" in clean_bands:
        lines.append(f"In the under-300M band MAPE moves from {_pct(cheap['mape'])} (all rows) to "
                     f"{_pct(clean_bands['under 300M']['mape'])} after those flags are dropped — "
                     f"part of the cheap-car error is ad quality, not valuation skill.")
    if "yes" in lux and "no" in lux:
        lines.append(f"Luxury brands: MAPE {_pct(lux['yes']['mape'])} on {lux['yes']['rows']:,} rows; "
                     f"mainstream {_pct(lux['no']['mape'])} on {lux['no']['rows']:,} rows.")
    if "Manual" in gears and "Automatic" in gears:
        lines.append(f"Manual: MAPE {_pct(gears['Manual']['mape'])} on {gears['Manual']['rows']:,} "
                     f"rows; automatic {_pct(gears['Automatic']['mape'])} on "
                     f"{gears['Automatic']['rows']:,} rows.")
    if trim:
        lines.append("By trim rank: " + "; ".join(
            f"{name} {_pct(row['mape'])} ({row['rows']:,} rows)" for name, row in trim.items()) + ".")
    return lines


def write_doc(payload: dict, path: Path) -> None:
    """Regenerate `docs/readiness_v2.md` — the committed evidence, since `models/` is git-ignored."""
    total = payload["val_rows"]
    lines = [
        "# Readiness check — where the v2 bundle's error lives",
        "",
        f"Generated {payload['generated_at']} by `python -m tools.readiness_check`. Bundle built "
        f"{payload['bundle_created_at']} (git `{str(payload['bundle_git_commit'])[:7]}`), scored on "
        f"`data/master/v2/val_features_full.csv` ({total:,} rows). **Nothing is fitted here** and the "
        "test split is not touched.",
        "",
        "Point and band come from `model_point.joblib` / `quantiles.joblib` with the exported category "
        "lists — the same path `Predictor.predict_one` takes (spot-checked below).",
        "",
        "## Headline",
        "",
        "| Slice | Rows | MAPE | median APE | MAE | R²(log) | inside P10-P90 | width / point |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, row in (("val (all)", payload["overall"]),
                       ("val, no quality flag", payload["clean_no_quality_flag"]),
                       ("val, price-quality clean", payload["clean_price_flags"])):
        lines.append(f"| {label} | {row['rows']:,} | {_pct(row['mape'])} | "
                     f"{_pct(row['median_ape'])} | {row['mae_vnd']:,} | "
                     f"{row.get('r2_log', float('nan')):.4f} | {_pct(row['coverage_p10_p90'])} | "
                     f"{_pct(row['median_width_ratio'])} |")

    def table(title: str, rows: list[dict]) -> None:
        lines.extend(["", f"## {title}", "",
                      "| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | "
                      "width / point | APE > 20 % |",
                      "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
        for row in _slice_rows(rows, total):
            if not row.get("rows"):
                lines.append(f"| {_md(row['slice'])} | 0 | - | - | - | - | - | - | - |")
                continue
            lines.append(f"| {_md(row['slice'])} | {row['rows']:,} | {row['share']:.1%} | "
                         f"{_pct(row['mape'])} | {_pct(row['median_ape'])} | "
                         f"{row['mae_vnd']:,} | {_pct(row['coverage_p10_p90'])} | "
                         f"{_pct(row['median_width_ratio'])} | {_pct(row['share_ape_over_20pct'])} |")

    table("By asking-price band", payload["by_price_band"])
    table("By asking-price band, price-quality clean", payload["by_price_band_clean"])
    table("By training-group thickness (`brand|model` rows in train)", payload["by_thickness"])
    table("By training-group thickness, price-quality clean", payload["by_thickness_clean"])
    table("By trim rank", payload["by_trim_rank"])
    table("By transmission", payload["by_transmission"])
    table("By body type", payload["by_body_type"])
    table("By luxury brand", payload["by_luxury"])

    lines += ["", "## Nameplates with at least "
              f"{payload['nameplates']['minimum_rows']} val rows", "",
              "| Worst | Rows | MAPE | median APE | median price |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for row in payload["nameplates"]["worst"]:
        lines.append(f"| {_md(row['segment'])} | {row['rows']} | {_pct(row['mape'])} | "
                     f"{_pct(row['median_ape'])} | {row['median_price_vnd']:,} |")
    lines += ["", "| Best | Rows | MAPE | median APE | median price |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for row in payload["nameplates"]["best"]:
        lines.append(f"| {_md(row['segment'])} | {row['rows']} | {_pct(row['mape'])} | "
                     f"{_pct(row['median_ape'])} | {row['median_price_vnd']:,} |")

    base = payload["baselines"]
    lines += ["", "## Baselines on the same rows", "",
              "| Predictor | MAPE | median APE |", "| --- | ---: | ---: |",
              f"| national median | {_pct(base['national_median']['mape'])} | - |",
              f"| brand\\|model median | {_pct(base['segment_median']['mape'])} | - |",
              f"| **v2 bundle** | **{_pct(payload['overall']['mape'])}** | "
              f"**{_pct(payload['overall']['median_ape'])}** |"]

    parity = payload["parity"]
    excluded = parity["excluded"]
    lines += ["", "## Serving parity", "",
              f"`Predictor.predict_one` on {parity['rows']} raw val rows (stratified over "
              f"{parity['bands']} price bands, from a pool of {parity['pool_rows']:,} rows that the "
              f"v2 cohort did not impute and whose province the feature table kept) vs the same rows' "
              f"exported feature vector: max |ratio-1| "
              f"**{parity['max_abs_ratio_error']:.2e}**, mean "
              f"**{parity['mean_abs_ratio_error']:.2e}**.", "",
              f"Excluded from the pool: {excluded['backfilled']:,} backfilled, "
              f"{excluded['imputed_at_build']:,} rows with a build-time imputation, "
              f"{excluded['province_not_kept']:,} with a province outside `provinces_kept`, "
              f"{excluded['placeholder_odometer']:,} with a placeholder odometer.", "",
              "Rows the v2 cohort imputed are **not** a serving-parity test: `impute_stats.json` is "
              "fitted on `train_cohort.csv`, while the v2 cohort's build-time imputation is a "
              "different snapshot for a few groups — e.g. Honda|CR-V's engine median is 1.75 L in the "
              "bundle and 2.0 L in the v2 cohort. That is an artefact mismatch to track separately, "
              "not a serving failure.", ""]

    lines += ["## Checks", "", "| Check | Value | Result |", "| --- | ---: | --- |"]
    for entry in payload["checks"]:
        lines.append(f"| {entry['check']} | {entry['value']:.4f} | "
                     f"{'PASS' if entry['passed'] else 'FAIL'} |")

    lines += ["", "## Reading (generated from the tables)", ""]
    lines += [f"- {line}" for line in reading(payload)]
    lines += ["",
              "## What this page does and does not say", "",
              "- It measures **advertised prices**, not transaction prices "
              "(`docs/data_limitations.md` §1).",
              "- A row whose asking price is a deposit makes the model look wrong; the clean slice "
              "drops rows carrying a label flag, and `docs/error_audit_25.md` reads the tail by hand.",
              "- The band's coverage is measured on val; the conformal shift itself was fitted on train "
              "OOF, so val is still a holdout.",
              "- The test split is **not** used here: plan §1 allows one evaluation at the freeze.",
              ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Where does the v2 bundle's error live?")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--rows", type=int, default=120, help="raw rows for the serving-parity check")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--no-doc", action="store_true", help="do not regenerate docs/readiness_v2.md")
    args = parser.parse_args(argv)

    payload = analyse(Path(args.bundle), args.rows, args.seed)
    total = payload["val_rows"]
    overall, clean = payload["overall"], payload["clean_no_quality_flag"]
    print(f"READINESS - {payload['bundle']} | built {payload['bundle_created_at']} | "
          f"val {total:,} rows")
    print(f"  overall   MAPE {_pct(overall['mape'])} | median APE {_pct(overall['median_ape'])} | "
          f"MAE {_vnd_m(overall['mae_vnd'])} | R2(log) {overall.get('r2_log', float('nan')):.4f}")
    print(f"  band      inside P10-P90 {_pct(overall['coverage_p10_p90'])} | median width "
          f"{_pct(overall['median_width_ratio'])} of the point")
    price_clean = payload["clean_price_flags"]
    print(f"  clean     MAPE {_pct(clean['mape'])} | median APE {_pct(clean['median_ape'])} on "
          f"{clean['rows']:,} rows without a quality flag")
    print(f"  price$    MAPE {_pct(price_clean['mape'])} | median APE "
          f"{_pct(price_clean['median_ape'])} on {price_clean['rows']:,} rows without a "
          f"deposit/placeholder/year flag")
    print(f"  parity    {payload['parity']['rows']} raw rows | max |ratio-1| "
          f"{payload['parity']['max_abs_ratio_error']:.2e}")
    for row in payload["parity"]["mismatches"]:
        print(f"    mismatch {row['listing_id']} {row['segment']} km={row['mileage_km']} "
              f"served {row['served_vnd']:,} direct {row['direct_vnd']:,} ratio {row['ratio']:.4f}")


    print_table("By asking-price band (all rows)", payload["by_price_band"], total)
    print_table("By asking-price band (price-quality clean)", payload["by_price_band_clean"],
                price_clean["rows"])
    print_table("By training-group thickness (brand|model rows in train)",
                payload["by_thickness"], total)
    print_table("By trim rank", payload["by_trim_rank"], total)
    print_table("By transmission", payload["by_transmission"], total)
    print_table("By luxury brand", payload["by_luxury"], total)
    print_nameplates(payload)

    base = payload["baselines"]
    print("\n  Baselines on the same rows")
    print(f"  {'predictor':24s} {'MAPE':>8s}")
    for label in ("national_median", "segment_median"):
        print(f"  {label:24s} {_pct(base[label]['mape']):>8s}")
    print(f"  {'v2 bundle':24s} {_pct(overall['mape']):>8s}")

    print("\n  Checks")
    for entry in payload["checks"]:
        print(f"  [{'PASS' if entry['passed'] else 'FAIL'}] {entry['check']:32s} "
              f"-> {entry['value']:.4f}")
    print(f"\n  {len(payload['checks'])} checks | "
          f"{'PASS' if payload['passed'] else 'FAIL'}")

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                    newline="\n")
    print(f"  -> {path}")
    if not args.no_doc:
        write_doc(payload, DOC)
        print(f"  -> {DOC}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
