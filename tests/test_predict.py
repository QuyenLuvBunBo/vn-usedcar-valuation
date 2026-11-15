"""Unit tests for the serving path (`src/models/predict.py`) and the v2 bundle contract.

A tiny synthetic bundle is built in a temp directory, so the tests run without `data/master` and
without LightGBM: `DummyRegressor` reproduces the log-space contract of the real model.

Run: python -m unittest tests.test_predict -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor

from src.features import build_features, extend
from src.models import predict as serving

FEATURES = [*build_features.VARIANT_COLUMNS["full"]["categorical"],
            *build_features.VARIANT_COLUMNS["full"]["numeric"], *extend.NEW_COLUMNS]

IMPUTE = {
    "reference_year": 2026, "min_group": 5, "age_bucket": 5, "rare_min": 10,
    "rare_models": ["Rare One"],
    "categorical": {column: {"column": column, "levels": [{"cols": ["brand", "model"], "map": {}}],
                             "global": "Unknown"}
                    for column in ("body_type", "transmission", "fuel_type", "origin", "seller_type")},
    "seats": {"column": "seats", "levels": [{"cols": ["brand", "model"], "map": {"toyota|camry": "5"}}],
              "global": "5"},
    "mileage_by_age": {"column": "mileage_km", "unit": "5-year age band", "buckets": {"1": 40_000.0},
                       "global": 60_000.0},
    "engine_by_model": {"column": "engine_capacity", "group_cols": ["brand", "model"],
                        "groups": {"toyota|camry": 2.5}, "global": 2.0},
    "engine_by_age": {"column": "engine_capacity", "unit": "5-year age band",
                      "buckets": {"1": 2.0}, "global": 2.0},
}

FEATURE_STATS = {
    "reference_year": 2026, "provinces_kept": ["Hà Nội"], "brand_rows_min": 20, "province_rows_min": 50,
    "shrink_k": 50, "brand_retention_rate": {"Toyota": 0.8}, "brand_retention_default": 0.75,
    "province_price_index": {"Hà Nội": 1.0}, "province_price_index_default": 1.0,
}

KNOWN = {
    "brand_model_counts": {"Toyota|Camry": 500},
    "segment_median_vnd": {"Toyota|Camry": 800_000_000},
    "national_median_vnd": 520_000_000,
    "deposit_ratio_threshold": 0.25, "segment_min_rows": 30,
    "placeholder_odometer_low": 100, "placeholder_odometer_high": 900_000,
    "year_min": 1980, "capture_year": 2026, "engine_range": [0.6, 8.0],
}


def make_bundle(folder: Path, with_band: bool = True) -> Path:
    bundle = folder / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "impute_stats.json").write_text(json.dumps(IMPUTE), encoding="utf-8")
    (bundle / "feature_stats.json").write_text(json.dumps(FEATURE_STATS), encoding="utf-8")
    (bundle / "known.json").write_text(json.dumps(KNOWN), encoding="utf-8")
    (bundle / "categories.json").write_text(json.dumps({
        "columns": ["brand", "model", "model_group", "transmission", "fuel_type", "origin",
                    "body_type", "seller_type", "source_platform", "province_group", "age_band",
                    "brand_age_band", "is_luxury_segment", "trim_rank", "model_canonical",
                    "variant_tokens"],
        "categories": {"brand": ["Toyota", "Honda"], "model": ["Camry"], "model_group": ["Camry"],
                       "transmission": ["Automatic", "Manual", "Other", "Unknown"],
                       "fuel_type": ["Gasoline", "Diesel", "Hybrid", "Electric", "Unknown"],
                       "origin": ["CKD", "CBU", "Unknown"],
                       "body_type": ["Sedan", "SUV", "Unknown"],
                       "seller_type": ["Dealership/Salon", "Private Individual", "Unknown"],
                       "source_platform": ["Unknown"], "province_group": ["Hà Nội", "Other"],
                       "age_band": ["0-2", "3-5", "6-9", "10-14", "15+", "unknown"],
                       "brand_age_band": ["Toyota|3-5"], "is_luxury_segment": ["yes", "no"],
                       "trim_rank": ["base", "mid", "top", "unknown"],
                       "model_canonical": ["camry"], "variant_tokens": ["2.5"]},
    }), encoding="utf-8")

    x = pd.DataFrame(0.0, index=range(3), columns=FEATURES)
    target = np.log([500_000_000, 600_000_000, 700_000_000])
    model = DummyRegressor(strategy="mean").fit(x, target)
    joblib.dump(model, bundle / "model_point.joblib")
    quantiles = None
    if with_band:
        quantiles = {0.10: DummyRegressor().fit(x, target - 0.2),
                     0.50: DummyRegressor().fit(x, target),
                     0.90: DummyRegressor().fit(x, target + 0.2)}
        joblib.dump(quantiles, bundle / "quantiles.joblib")
    metadata = {"features": FEATURES, "rows": {"train": 3, "val": 2},
                "quantiles": {"calibration": {"shift_low_log": 0.0, "shift_high_log": 0.0}}
                if with_band else {"present": False}}
    (bundle / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return bundle


RECORD = {"brand": "Toyota", "model": "Camry", "manufacture_year": 2020, "mileage_km": 45_000,
          "transmission": "Số tự động", "fuel_type": "Xăng", "body_type": "Sedan",
          "location_province": "Hà Nội", "sub_model_trim": "2.5Q"}


class PredictorTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = make_bundle(Path(self.tmp.name))
        self.predictor = serving.Predictor.load(self.bundle)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_price_and_a_band_are_returned(self):
        result = self.predictor.predict_one(RECORD)
        self.assertGreater(result["price_vnd"], 0)
        self.assertLessEqual(result["p10_vnd"], result["p90_vnd"])
        self.assertEqual(set(result), {"price_vnd", "p10_vnd", "p50_vnd", "p90_vnd",
                                       "warnings", "trace"})

    def test_the_trace_says_what_was_parsed_or_imputed(self):
        trace = self.predictor.predict_one(RECORD)["trace"]
        self.assertIn("engine_parsed", trace)
        self.assertIn("trim_rank", trace)
        self.assertEqual(trace["trim_rank"], "unknown")     # "2.5Q" is a code, not a tier word
        self.assertIsInstance(trace["imputed"], list)

    def test_a_fast_bundle_reports_no_band(self):
        fast = serving.Predictor.load(make_bundle(Path(self.tmp.name) / "fast", with_band=False))
        result = fast.predict_one(RECORD)
        self.assertIsNone(result["p10_vnd"])
        self.assertIn("no_band", {warning["code"] for warning in result["warnings"]})

    def test_an_unseen_combo_is_flagged(self):
        codes = {w["code"] for w in self.predictor.predict_one({**RECORD, "model": "Ghost"})["warnings"]}
        self.assertIn("unseen_brand_model", codes)

    def test_a_placeholder_odometer_is_flagged(self):
        codes = {w["code"] for w in self.predictor.predict_one({**RECORD, "mileage_km": 1})["warnings"]}
        self.assertIn("placeholder_odometer", codes)

    def test_an_absurd_year_is_flagged(self):
        codes = {w["code"] for w in self.predictor.predict_one({**RECORD, "manufacture_year": 1025})["warnings"]}
        self.assertIn("implausible_year", codes)

    def test_a_deposit_price_is_flagged_only_when_an_asking_price_is_given(self):
        without = {w["code"] for w in self.predictor.predict_one(RECORD)["warnings"]}
        self.assertNotIn("deposit_suspect", without)
        with_price = self.predictor.predict_one({**RECORD, "price_vnd": 100_000_000})["warnings"]
        self.assertIn("deposit_suspect", {w["code"] for w in with_price})

    def test_missing_required_fields_raise(self):
        with self.assertRaises(ValueError):
            self.predictor.predict_one({"model": "Camry", "manufacture_year": 2020})

    def test_predict_frame_keeps_a_bad_row_and_prices_the_rest(self):
        frame = pd.DataFrame([RECORD, {**RECORD, "brand": ""}])
        out = self.predictor.predict_frame(frame)
        self.assertEqual(len(out), 2)
        self.assertIsNotNone(out.loc[0, "price_vnd"])
        self.assertIn("invalid_record", out.loc[1, "warnings"])

    def test_a_bundle_whose_features_do_not_match_the_code_fails_loudly(self):
        metadata = json.loads((self.bundle / "metadata.json").read_text(encoding="utf-8"))
        metadata["features"] = [*metadata["features"], "column_that_does_not_exist"]
        (self.bundle / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(ValueError):
            serving.Predictor.load(self.bundle).predict_one(RECORD)


class ZeroLeakageTests(unittest.TestCase):
    """The serving path must not read the training data; only the bundle."""

    def test_prediction_does_not_read_any_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = make_bundle(Path(folder))
            predictor = serving.Predictor.load(bundle)
            original = pd.read_csv

            def explode(*args, **kwargs):
                raise AssertionError(f"predict() tried to read {args[0] if args else kwargs}")

            pd.read_csv = explode
            try:
                result = predictor.predict_one(RECORD)
            finally:
                pd.read_csv = original
        self.assertGreater(result["price_vnd"], 0)

    def test_the_bundle_carries_every_file_the_predictor_needs(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = make_bundle(Path(folder))
            required = {"metadata.json", "categories.json", "known.json", "feature_stats.json",
                        "impute_stats.json", "model_point.joblib"}
            self.assertLessEqual(required, {path.name for path in bundle.iterdir()})


if __name__ == "__main__":
    unittest.main()

