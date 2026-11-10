"""Unit tests for the week-3 tools — synthetic inputs only, so CI can run them without the snapshot.

Run: python -m unittest tests.test_tools -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.models import benchmark, train as trainer
from tools import check_intervals, eda_summary, error_report, feature_ablation


class ProvinceTests(unittest.TestCase):
    def test_variants_fold_into_one_province(self):
        series = pd.Series(["TP. Hồ Chí Minh", "TP HCM", "TP.HCM", "Đắk Lắk", "Đăk Lăk", "Hà Nội"])
        merged = eda_summary.canonical_province(series)
        self.assertEqual(merged.value_counts()["TP. Hồ Chí Minh"], 3)
        self.assertEqual(merged.value_counts()["Đắk Lắk"], 2)
        self.assertEqual(len(merged.unique()), 3)

    def test_missing_province_becomes_unknown(self):
        merged = eda_summary.canonical_province(pd.Series([None, "Hà Nội"]))
        self.assertEqual(merged.tolist(), ["Unknown", "Hà Nội"])


class ErrorBucketTests(unittest.TestCase):
    def frame(self, **overrides) -> pd.Series:
        base = {"price_vnd": 500_000_000.0, "manufacture_year": 2020, "mileage_km": 50_000.0,
                "origin": "Trong nước", "price_status": "full"}
        base.update(overrides)
        base["km_per_year"] = base["mileage_km"] / max(2026 - base["manufacture_year"], 1)
        return pd.Series(base)

    def test_rules_are_ordered_and_exclusive(self):
        self.assertEqual(error_report.bucket(self.frame(price_vnd=150_000_000.0)), "1_under_200tr")
        self.assertEqual(error_report.bucket(self.frame(mileage_km=400_000.0)), "2_odometer_outlier")
        self.assertEqual(error_report.bucket(self.frame(origin="Nhập khẩu")), "3_import_or_salvage")
        self.assertEqual(error_report.bucket(self.frame(price_status="negotiable")), "4_negotiable_price")
        self.assertEqual(error_report.bucket(self.frame(mileage_km=300_000.0, price_vnd=500_000_000.0,
                                                        manufacture_year=2024)), "2_odometer_outlier")
        self.assertEqual(error_report.bucket(self.frame()), "6_ordinary_but_wrong")


class AblationTests(unittest.TestCase):
    def test_groups_partition_the_feature_set(self):
        columns = [column for group in feature_ablation.GROUPS.values() for column in group]
        self.assertEqual(len(columns), len(set(columns)), "a column is dropped by two groups")
        self.assertEqual(len(columns), 23, "the full variant has 23 feature columns")


class ModelNameTests(unittest.TestCase):
    def test_short_names_resolve(self):
        self.assertEqual(trainer.resolve_model("lgbm"), "lightgbm")
        self.assertEqual(trainer.resolve_model("XGB"), "xgboost")
        self.assertEqual(trainer.resolve_model("cb"), "catboost")
        self.assertEqual(trainer.resolve_model("median"), "median")


class IntervalTests(unittest.TestCase):
    def test_coverage_maths(self):
        frame = pd.DataFrame({"price_vnd": [100.0, 200.0, 300.0, 400.0],
                              "p10_vnd": [150.0, 150.0, 150.0, 150.0],
                              "p90_vnd": [250.0, 250.0, 250.0, 250.0],
                              "y_pred_vnd": [200.0] * 4,
                              "abs_pct_error": [0.0, 0.0, 0.5, 0.5]})
        summary = check_intervals.summarise(frame)
        self.assertEqual(summary["below"], 0.25)      # 100 < P10
        self.assertEqual(summary["above"], 0.50)      # 300 and 400 > P90
        self.assertEqual(summary["inside"], 0.25)     # 200 only


class BenchmarkDocTests(unittest.TestCase):
    def row(self, model: str, r2: float) -> dict:
        return {"model": model, "features": "full", "r2_log": r2, "rmse_log": 0.2, "r2_vnd": 0.9,
                "mae_vnd": 1_000, "mape": 0.11, "clean_mape": 0.09, "median_ape": 0.06,
                "rows_used": 70_244, "rows_tail": 23, "seconds": 1.0,
                "tuning": {"budget_seconds": 0, "trials": 0}, "_abs_errors": np.array([0.1, 0.2])}

    def test_doc_has_the_clean_column_and_a_best_line(self):
        rows = [self.row("lightgbm", 0.95), self.row("ridge", 0.90)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "benchmark.md"
            benchmark.write_doc(rows, path, tuning_budget=0)
            text = path.read_text(encoding="utf-8")
        self.assertIn("MAPE clean", text)
        self.assertIn("Best on val: **lightgbm / full**", text)
        self.assertIn("docs/error_audit_25.md", text)


if __name__ == "__main__":
    unittest.main()
