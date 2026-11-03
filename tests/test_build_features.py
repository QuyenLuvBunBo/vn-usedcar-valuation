"""Unit tests for the feature builder and its ablation study (src/features/build_features.py).

Two things matter and both are cheap to get wrong:

  * the ablation groups must cover **exactly** the feature columns of the variant — a typo silently
    drops nothing and reports ΔR² = 0, which reads like "the feature is useless";
  * `ablate_tables` must always return one row per group, even when a drop would leave no feature.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.features.build_features import (ABLATION_GROUPS, VARIANT_COLUMNS, ablate_tables, as_features)


def synthetic(rows: int = 120, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A tiny frame with the columns the `full` variant needs, price driven by age and mileage."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        "brand": rng.choice(["Toyota", "Ford", "Kia"], rows),
        "model": rng.choice(["Vios", "Ranger", "Morning"], rows),
        "model_group": rng.choice(["Vios", "Ranger", "Other"], rows),
        "transmission": rng.choice(["Automatic", "Manual"], rows),
        "fuel_type": rng.choice(["Gasoline", "Diesel"], rows),
        "origin": rng.choice(["CKD", "CBU"], rows),
        "body_type": rng.choice(["Sedan", "Pickup"], rows),
        "seller_type": rng.choice(["Private Individual", "Dealership/Salon"], rows),
        "source_platform": rng.choice(["bonbanh", "chotot"], rows),
        "manufacture_year": rng.integers(2012, 2025, rows),
        "mileage_km": rng.integers(10_000, 200_000, rows),
        "engine_capacity": rng.choice([1.5, 2.0, 2.4], rows),
        "seats": rng.choice([5, 7], rows),
        "vehicle_age": rng.integers(0, 14, rows),
        "km_per_year": rng.integers(2_000, 40_000, rows),
        "engine_per_seat": rng.choice([0.3, 0.4, 0.5], rows),
        "n_imputed": rng.integers(0, 5, rows),
        "brand_retention_rate": rng.choice([0.7, 0.8, 0.9], rows),
        "province_price_index": rng.choice([0.9, 1.0, 1.1], rows),
        "province_group": rng.choice(["Hà Nội", "TP. Hồ Chí Minh", "Other"], rows),
        "age_band": rng.choice(["0-2", "3-5", "6-9"], rows),
        "brand_age_band": rng.choice(["Toyota|0-2", "Ford|6-9"], rows),
        "is_luxury_segment": rng.choice(["yes", "no"], rows),
    })
    frame.loc[:, "price_vnd"] = np.exp(
        20.0 - 0.04 * frame["vehicle_age"] - 0.000004 * frame["mileage_km"]
        + rng.normal(0, 0.05, rows)).round().astype(int)
    split = rows * 2 // 3
    return frame.iloc[:split].copy(), frame.iloc[split:].copy()


class AblationGroupTests(unittest.TestCase):

    def test_the_groups_cover_the_feature_columns_exactly_once(self):
        columns = [*VARIANT_COLUMNS["full"]["categorical"], *VARIANT_COLUMNS["full"]["numeric"]]
        grouped = [column for members in ABLATION_GROUPS.values() for column in members]
        self.assertEqual(len(grouped), len(set(grouped)), "a column is listed in two groups")
        self.assertEqual(set(grouped), set(columns), "a feature is in no group, or in a group but not "
                                                    "in the variant")

    def test_every_group_is_non_empty(self):
        for name, members in ABLATION_GROUPS.items():
            self.assertTrue(members, f"{name} is empty")


class AblateTablesTests(unittest.TestCase):

    def test_one_row_per_group_and_a_baseline(self):
        train, val = synthetic()
        report = ablate_tables(train, val, groups={"cat_identity": ("brand", "model", "model_group")},
                               rows=0)
        self.assertIn("baseline_r2", report)
        self.assertEqual(len(report["groups"]), 1)
        row = report["groups"][0]
        self.assertEqual(row["group"], "cat_identity")
        self.assertEqual(row["dropped"], ["brand", "model", "model_group"])
        self.assertIsInstance(row["r2"], float)
        self.assertIsInstance(row["delta_r2"], float)

    def test_dropping_everything_is_reported_not_crashed(self):
        train, val = synthetic(60)
        everything = {"all": tuple([*VARIANT_COLUMNS["full"]["categorical"],
                                    *VARIANT_COLUMNS["full"]["numeric"]])}
        report = ablate_tables(train, val, groups=everything, rows=0)
        self.assertIsNone(report["groups"][0]["r2"])
        self.assertIsNone(report["groups"][0]["delta_r2"])

    def test_delta_is_baseline_minus_without(self):
        train, val = synthetic()
        report = ablate_tables(train, val, groups={}, rows=0)
        self.assertEqual(report["groups"], [])          # no groups -> nothing to compare
        self.assertGreaterEqual(report["baseline_r2"], -1.0)


class AsFeaturesTests(unittest.TestCase):

    def test_text_becomes_category_and_numbers_stay_numeric(self):
        train, _ = synthetic(30)
        x = as_features(train, ["brand", "mileage_km"])
        self.assertTrue(isinstance(x["brand"].dtype, pd.CategoricalDtype))
        self.assertTrue(pd.api.types.is_numeric_dtype(x["mileage_km"]))


if __name__ == "__main__":
    unittest.main()
