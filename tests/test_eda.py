"""Unit tests for the week-2 EDA tables in src/data_prep/eda.py.

The tables are what the report quotes, so the tests pin the arithmetic: a median is a median, the
depreciation ratio is measured between the age bands it claims, and the platform comparison is
leave-one-out (otherwise two-cell groups would always look neutral).

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

import pandas as pd

from src.data_prep.eda import (by_brand, by_mileage, by_year, depreciation_by_brand,
                               platform_gap, price_overview, summary_stats)


def frame(*rows) -> pd.DataFrame:
    """Build the minimum columns the EDA functions touch."""
    base = {"scraped_at": "2026-10-29T00:00:00Z", "manufacture_year": 2018, "mileage_km": 50_000,
            "brand": "Toyota", "model": "Vios", "source_platform": "bonbanh"}
    return pd.DataFrame([{**base, **row} for row in rows])


class SummaryStatsTests(unittest.TestCase):
    """The descriptive-statistics table of the week-2 plan."""

    def test_count_median_and_missing_rate(self):
        data = frame({"price_vnd": 100, "mileage_km": 10_000},
                     {"price_vnd": 200, "mileage_km": None},
                     {"price_vnd": 300, "mileage_km": 30_000})
        stats = summary_stats(data, columns=("price_vnd", "mileage_km"))
        self.assertEqual(stats.loc["price_vnd", "count"], 3)
        self.assertEqual(stats.loc["price_vnd", "median"], 200)
        self.assertEqual(stats.loc["price_vnd", "min"], 100)
        self.assertAlmostEqual(stats.loc["mileage_km", "missing_rate"], 1 / 3, places=4)

    def test_an_empty_column_is_skipped_rather_than_dividing_by_zero(self):
        stats = summary_stats(frame({"price_vnd": 100}), columns=("price_vnd", "engine_capacity"))
        self.assertNotIn("engine_capacity", stats.index)


class PriceOverviewTests(unittest.TestCase):

    def test_median_p10_p90_and_share(self):
        data = frame(*[{"price_vnd": price} for price in (100, 200, 300, 400, 500)])
        table = price_overview(data)
        self.assertEqual(table.loc["bonbanh", "rows"], 5)
        self.assertEqual(table.loc["bonbanh", "median"], 300)
        self.assertEqual(table.loc["bonbanh", "share"], 1.0)
        self.assertGreater(table.loc["bonbanh", "p90_over_p10"], 1)

    def test_brands_and_years_keep_only_well_populated_rows(self):
        data = frame({"brand": "Toyota", "price_vnd": 300},
                     *[{"brand": "Lexus", "price_vnd": 900} for _ in range(3)])
        table = by_brand(data, top=5)
        self.assertEqual(table.index[0], "Lexus")          # sorted by listing count
        self.assertEqual(table.loc["Lexus", "median"], 900)

        years = frame(*[{"manufacture_year": 2020, "price_vnd": 500} for _ in range(5)],
                      *[{"manufacture_year": 1998, "price_vnd": 90} for _ in range(2)])
        self.assertNotIn(1998, by_year(years).index)        # 2 listings < the 5-row floor


class MileageAndDepreciationTests(unittest.TestCase):

    def test_deciles_report_the_median_price_of_each_band(self):
        data = frame(*[{"mileage_km": km, "price_vnd": 1_000_000_000 - km}
                       for km in range(10_000, 210_000, 10_000)])
        table = by_mileage(data, bins=5)
        self.assertEqual(len(table), 5)
        # price falls as the odometer rises, which is the shape the report claims
        self.assertGreater(table["median"].iloc[0], table["median"].iloc[-1])

    def test_depreciation_is_measured_between_the_two_age_bands(self):
        rows = ([{"manufacture_year": 2025, "price_vnd": 800} for _ in range(30)]      # age 1
                + [{"manufacture_year": 2021, "price_vnd": 400} for _ in range(30)])   # age 5
        table = depreciation_by_brand(frame(*rows), min_rows=30)
        self.assertAlmostEqual(table.loc["Toyota", "value_lost_by_age5"], 0.5)

    def test_a_thin_brand_is_dropped_rather_than_shown(self):
        rows = ([{"manufacture_year": 2025, "price_vnd": 800} for _ in range(4)]
                + [{"manufacture_year": 2021, "price_vnd": 400} for _ in range(4)])
        self.assertTrue(depreciation_by_brand(frame(*rows), min_rows=30).empty)


class PlatformGapTests(unittest.TestCase):
    """Leave-one-out, so a two-platform group still reports the real difference."""

    def test_the_cheaper_platform_gets_a_ratio_below_one(self):
        rows = ([{"source_platform": "bonbanh", "price_vnd": 1_000} for _ in range(3)]
                + [{"source_platform": "chotot", "price_vnd": 900} for _ in range(3)])
        table = platform_gap(frame(*rows), min_rows=3)
        self.assertAlmostEqual(table.loc["chotot", "median_ratio"], 0.9)
        self.assertAlmostEqual(table.loc["bonbanh", "median_ratio"], 1 / 0.9)

    def test_a_platform_alone_in_its_group_is_ignored(self):
        rows = [{"source_platform": "bonbanh", "price_vnd": 1_000} for _ in range(3)]
        self.assertTrue(platform_gap(frame(*rows), min_rows=3).empty)


if __name__ == "__main__":
    unittest.main()
