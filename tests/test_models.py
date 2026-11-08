"""Unit tests for the week-3 model layer — small synthetic frames, no frozen data needed.

Run: python -m unittest tests.test_models -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.models import anomaly, common
from src.models import train as trainer


def tiny_predictions() -> pd.DataFrame:
    """Four rows: inside the band, above it, below it twice — the four labels §4.3 defines."""
    return pd.DataFrame({
        "listing_id": ["A", "B", "C", "D"],
        "price_vnd": [100.0, 200.0, 300.0, 400.0],
        "y_pred_vnd": [100.0, 175.0, 330.0, 375.0],
        "p10_vnd": [90.0, 100.0, 350.0, 300.0],
        "p90_vnd": [110.0, 150.0, 400.0, 350.0],
    })


class ContractTests(unittest.TestCase):
    def test_prediction_columns_match_the_plan(self):
        # docs/week3_plan.md §3 fixes this list; a silent column rename breaks the anomaly labeller.
        self.assertEqual(list(common.PREDICTION_COLUMNS), [
            "listing_id", "duplicate_group_id", "brand", "model", "manufacture_year", "mileage_km",
            "location_province", "source_platform", "price_vnd", "y_pred_log", "y_pred_vnd",
            "p10_vnd", "p90_vnd", "residual", "abs_pct_error"])

    def test_feature_columns_drop_ids_and_target(self):
        frame = pd.DataFrame({"listing_id": ["a"], "duplicate_group_id": ["g"],
                              "price_vnd": [1.0], "brand": ["Ford"]})
        self.assertEqual(common.feature_columns(frame), ["brand"])

    def test_metrics_identity_and_scale(self):
        y = np.array([100.0, 200.0])
        perfect = common.metrics(y, y)
        self.assertAlmostEqual(perfect["r2_log"], 1.0)
        self.assertEqual(perfect["mape"], 0.0)
        doubled = common.metrics(y, y * 2)
        self.assertAlmostEqual(doubled["mape"], 1.0)
        self.assertLess(doubled["r2_log"], 0.0)


class MedianBaselineTests(unittest.TestCase):
    def test_falls_back_from_brand_model_year_to_brand_then_overall(self):
        from src.models import train as trainer

        train = pd.DataFrame({
            "brand": ["Ford", "Ford", "Ford", "Kia"],
            "model": ["Focus", "Focus", "Ranger", "Morning"],
            "manufacture_year": [2018, 2018, 2020, 2019],
            common.TARGET: [300.0, 400.0, 900.0, 200.0],
        })
        val = pd.DataFrame({
            "brand": ["Ford", "Kia", "Unknown"],
            "model": ["Focus", "Morning", "Nothing"],
            "manufacture_year": [2018, 2019, 2019],
        })
        predicted = trainer._median_predict(train, val)
        self.assertEqual(predicted[0], 350.0)          # same brand+model+year -> median of two
        self.assertEqual(predicted[1], 200.0)          # brand fallback
        self.assertEqual(predicted[2], 350.0)          # global median of [200, 300, 400, 900]


class AnomalyTests(unittest.TestCase):
    def test_labels_follow_the_band_and_the_forest_score(self):
        scores = np.array([0.0, 0.0, 0.9, 0.9])
        labelled = anomaly.label_rows(tiny_predictions(), scores, iso_threshold=0.5)
        self.assertEqual(labelled.loc[0, "label"], "Fair")            # inside the band
        self.assertEqual(labelled.loc[1, "label"], "Overpriced")      # above P90, quiet forest
        self.assertEqual(labelled.loc[2, "label"], "Suspicious")      # below P10 + noisy forest
        self.assertEqual(labelled.loc[3, "label"], "Suspicious")      # above P90 + noisy forest
        self.assertIn("iso", labelled.loc[2, "reason"])
        self.assertAlmostEqual(labelled.loc[0, "delta"], 0.0)

    def test_calibrate_hits_the_requested_review_rate(self):
        scores = np.linspace(0, 1, 1000)
        threshold = anomaly.calibrate(scores, 0.03)
        self.assertAlmostEqual(float((scores >= threshold).mean()), 0.03, places=2)
        # a larger review rate must lower the threshold, and the rate is clamped to 2–5%
        self.assertLessEqual(anomaly.calibrate(scores, 0.5), anomaly.calibrate(scores, 0.02))
        self.assertAlmostEqual(float((scores >= anomaly.calibrate(scores, 0.5)).mean()), 0.05, places=2)


class TestEvaluationTests(unittest.TestCase):
    """The single test evaluation is recorded once — the file must refuse a silent overwrite."""

    def row(self) -> dict:
        return {"model": "lightgbm", "features": "full", "seed": 42, "holdout": "test",
                "holdout_rows": 14_980, "r2_log": 0.94, "rmse_log": 0.2, "r2_vnd": 0.9,
                "mae_vnd": 1_000, "mape": 0.11, "median_ape": 0.06, "clean_mape": 0.1,
                "rows_tail": 12, "params": {}, "tuning": {}, "predictions": "predictions_test.csv",
                "band_calibration": {"folds": 2}}

    def test_written_once_then_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test_evaluation.md"
            self.assertIn("wrote", trainer._write_test_evaluation(path, self.row()))
            text = path.read_text(encoding="utf-8")
            self.assertIn("single test evaluation", text)
            self.assertIn("MAPE clean", text)
            second = trainer._write_test_evaluation(path, self.row())
            self.assertIn("evaluated once", second)
            forced = trainer._write_test_evaluation(path, self.row(), force=True)
            self.assertIn("wrote", forced)


if __name__ == "__main__":
    unittest.main()
