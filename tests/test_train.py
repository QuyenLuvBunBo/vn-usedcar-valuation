"""Unit tests for src/models/train.py — the contract, not the training speed."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import train


class MetricsTest(unittest.TestCase):
    def test_metrics_in_log_and_vnd(self):
        y = pd.Series([1_000.0, 2_000.0, 4_000.0])
        perfect = np.log1p(y.to_numpy(dtype=float))
        score = train.metrics(y, perfect)
        self.assertEqual(score["r2_log"], 1.0)
        self.assertEqual(score["mae_vnd"], 0)
        self.assertEqual(score["mape"], 0.0)

    def test_a_bad_prediction_scores_worse(self):
        y = pd.Series([1_000.0, 2_000.0, 4_000.0])
        flat = np.full(3, np.log1p(2_000.0))
        score = train.metrics(y, flat)
        self.assertLess(score["r2_log"], 1.0)
        self.assertGreater(score["mape"], 0.0)


class MedianTest(unittest.TestCase):
    def test_median_predicts_log_space(self):
        frame = pd.DataFrame({
            "brand": ["Toyota", "Toyota", "Kia", "Kia"],
            "model": ["Vios", "Vios", "Morning", "Morning"],
            "manufacture_year": [2020, 2020, 2015, 2015],
            "price_vnd": [500.0, 700.0, 100.0, 150.0],
        })
        _, predict = train.fit_median(frame, None, 42)
        predicted = predict(frame)
        # the predict interface is log1p space — expm1 must return a plausible price
        back = np.expm1(predicted)
        self.assertTrue(np.all(np.isfinite(back)))
        self.assertTrue(np.all(back > 0))
        self.assertAlmostEqual(back[0], 600.0)          # the group median


class ResultsAppendTest(unittest.TestCase):
    def test_append_result_creates_and_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = train.RESULTS_PATH
            try:
                train.RESULTS_PATH = Path(tmp) / "model_results.json"
                train.append_result({"model": "lgbm", "r2_log": 0.94})
                train.append_result({"model": "ridge", "r2_log": 0.86})
                rows = json.loads(train.RESULTS_PATH.read_text(encoding="utf-8"))
                self.assertEqual([r["model"] for r in rows], ["lgbm", "ridge"])
            finally:
                train.RESULTS_PATH = original


class PredictionColumnsTest(unittest.TestCase):
    def test_contract_columns_are_stable(self):
        self.assertEqual(len(train.PREDICTION_COLUMNS), 15)
        for column in ("listing_id", "price_vnd", "y_pred_log", "y_pred_vnd",
                       "p10_vnd", "p90_vnd", "residual", "abs_pct_error"):
            self.assertIn(column, train.PREDICTION_COLUMNS)


if __name__ == "__main__":
    unittest.main()
