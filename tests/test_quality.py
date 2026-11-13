"""Unit tests for the label-quality side table (`src/data_prep/quality.py`).

Every rule here decides whether a real listing is "suspect", so each one gets a synthetic frame with
the boundary on both sides. No snapshot needed: CI runs this without `data/master`.

Run: python -m unittest tests.test_quality -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data_prep import quality


def frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal cohort: only the columns the rules read."""
    base = {"brand": "Toyota", "model": "Camry", "manufacture_year": 2022, "mileage_km": 40_000,
            "price_vnd": 800_000_000, "scraped_at": "2026-10-31T00:00:00+00:00",
            "source_platform": "bonbanh"}
    filled = [{**base, **row} for row in rows]
    return pd.DataFrame(filled)


def split(prefix: str, count: int, **overrides) -> pd.DataFrame:
    return frame([{"listing_id": f"{prefix}{index:03d}", **overrides} for index in range(count)])


class DepositRuleTests(unittest.TestCase):

    def setUp(self):
        # 40 train rows at 800 M -> the segment median is 800 M (>= SEGMENT_MIN_ROWS)
        self.train = split("T", 40)

    def test_the_boundary_is_exclusive(self):
        medians = quality.fit_segment_medians(self.train)
        probe = frame([{"listing_id": "A1", "price_vnd": 200_000_000},      # 0.25 -> not below
                       {"listing_id": "A2", "price_vnd": 190_000_000}])     # 0.2375 -> flagged
        flag, ratio = quality.deposit_flags(probe, medians)
        self.assertEqual(flag.tolist(), [False, True])
        self.assertAlmostEqual(float(ratio.iloc[0]), 0.25, places=6)

    def test_a_thin_segment_borrows_the_national_median(self):
        thin = frame([{"listing_id": "T1", "model": "Camry", "price_vnd": 800_000_000},
                      {"listing_id": "T2", "model": "Camry", "price_vnd": 800_000_000},
                      {"listing_id": "T3", "model": "Camry", "price_vnd": 800_000_000},
                      {"listing_id": "T4", "model": "Supra", "price_vnd": 3_000_000_000},
                      {"listing_id": "T5", "model": "Supra", "price_vnd": 3_000_000_000}])
        medians = quality.fit_segment_medians(thin, min_rows=3)
        self.assertNotIn("toyota|supra", medians)              # 2 rows < 3 -> not a level
        self.assertIn("toyota|camry", medians)
        self.assertEqual(medians["__national__"], 800_000_000)

    def test_the_median_never_comes_from_val(self):
        """A flood of cheap val rows must not move the threshold: the table is fitted on train."""
        medians = quality.fit_segment_medians(self.train)
        cheap_val = frame([{"listing_id": f"V{index:03d}", "price_vnd": 40_000_000}
                           for index in range(100)])
        flag, _ = quality.deposit_flags(cheap_val, medians)
        self.assertTrue(flag.all())          # 40 M vs a train median of 800 M
        # and the reverse: the train median is still 800 M, not dragged down by the val rows
        self.assertEqual(medians["toyota|camry"], 800_000_000)

    def test_a_missing_price_is_not_flagged(self):
        medians = quality.fit_segment_medians(self.train)
        flag, ratio = quality.deposit_flags(frame([{"listing_id": "A1", "price_vnd": None}]), medians)
        self.assertFalse(bool(flag.iloc[0]))
        self.assertTrue(pd.isna(ratio.iloc[0]))


class OdometerRuleTests(unittest.TestCase):

    def test_boundaries(self):
        probe = frame([{"listing_id": "A1", "mileage_km": 100},
                       {"listing_id": "A2", "mileage_km": 101},
                       {"listing_id": "A3", "mileage_km": 899_999},
                       {"listing_id": "A4", "mileage_km": 900_000},
                       {"listing_id": "A5", "mileage_km": None}])
        self.assertEqual(quality.placeholder_flags(probe).tolist(),
                         [True, False, False, True, False])


class YearRuleTests(unittest.TestCase):

    def test_boundaries(self):
        probe = frame([{"listing_id": "A1", "manufacture_year": 1025},
                       {"listing_id": "A2", "manufacture_year": 2028},
                       {"listing_id": "A3", "manufacture_year": 1979},
                       {"listing_id": "A4", "manufacture_year": 1980},
                       {"listing_id": "A5", "manufacture_year": 2026},
                       {"listing_id": "A6", "manufacture_year": None}])
        self.assertEqual(quality.year_flags(probe, 2026).tolist(),
                         [True, True, True, False, False, False])

    def test_the_window_comes_from_the_snapshot_not_the_clock(self):
        later = frame([{"listing_id": "A1", "scraped_at": "2030-01-01"}])
        self.assertEqual(quality.capture_year(later), 2030)



class RepeatRuleTests(unittest.TestCase):

    def probe(self):
        return frame([
            {"listing_id": "B2", "price_vnd": 500_000_000},      # same car, same price (3 copies)
            {"listing_id": "B1", "price_vnd": 500_000_000},
            {"listing_id": "B3", "price_vnd": 500_000_000},
            {"listing_id": "C1", "price_vnd": 700_000_000},      # a different price
            {"listing_id": "D1", "price_vnd": 500_000_000, "mileage_km": 41_000},
        ])

    def test_the_canonical_row_is_the_lowest_id_and_the_rest_are_copies(self):
        out = quality.repeat_flags(self.probe())
        self.assertEqual(out.loc[out["listing_id"] == "B1", "canonical_listing_id"].item(), "B1")
        self.assertFalse(bool(out.loc[out["listing_id"] == "B1", "is_duplicate_copy"].item()))
        copies = out.loc[out["is_duplicate_copy"], "listing_id"].tolist()
        self.assertEqual(sorted(copies), ["B2", "B3"])
        self.assertEqual(int(out["repeat_ad"].sum()), 3)        # B1..B3, not C1/D1

    def test_two_rows_missing_a_price_group_together(self):
        out = quality.repeat_flags(frame([{"listing_id": "A1", "price_vnd": None},
                                          {"listing_id": "A2", "price_vnd": None}]))
        self.assertEqual(int(out["repeat_ad"].sum()), 2)
        self.assertEqual(int(out["is_duplicate_copy"].sum()), 1)

    def test_a_clean_frame_has_no_copies(self):
        out = quality.repeat_flags(frame([{"listing_id": "A1", "price_vnd": 1},
                                          {"listing_id": "A2", "price_vnd": 2}]))
        self.assertEqual(int(out["repeat_ad"].sum()), 0)
        self.assertEqual(int(out["is_duplicate_copy"].sum()), 0)


class BuildFlagsTests(unittest.TestCase):

    def parts(self):
        train = frame([{"listing_id": f"T{index:03d}", "price_vnd": 800_000_000,
                        "mileage_km": 40_000 + index} for index in range(40)])
        val = frame([{"listing_id": "V1", "price_vnd": 100_000_000},                   # deposit
                     {"listing_id": "V2", "price_vnd": 800_000_000, "mileage_km": 1},  # placeholder
                     {"listing_id": "V3", "price_vnd": 800_000_000, "manufacture_year": 1025},
                     {"listing_id": "V4", "price_vnd": 800_000_000, "mileage_km": 55_000},
                     {"listing_id": "V5", "price_vnd": 800_000_000, "mileage_km": 55_000}])  # repeat
        return {"train": train, "val": val}

    def test_the_side_table_has_the_contract_columns(self):
        flags, _ = quality.build_flags(self.parts())
        self.assertEqual(list(flags.columns), list(quality.FLAG_COLUMNS))
        self.assertEqual(flags["listing_id"].is_unique, True)

    def test_flag_count_sums_the_four_flags(self):
        flags, _ = quality.build_flags(self.parts())
        self.assertEqual(flags["flag_count"].tolist(),
                         flags[list(quality.BOOLEAN_FLAGS)].sum(axis=1).tolist())
        self.assertTrue((flags["flag_count"] <= 4).all())

    def test_building_twice_gives_the_same_table(self):
        first, _ = quality.build_flags(self.parts())
        second, _ = quality.build_flags(self.parts())
        pd.testing.assert_frame_equal(first, second)

    def test_the_input_frames_are_not_mutated(self):
        parts = self.parts()
        before = {name: part.copy() for name, part in parts.items()}
        quality.build_flags(parts)
        for name, snapshot in before.items():
            pd.testing.assert_frame_equal(parts[name], snapshot)

    def test_the_report_counts_match_the_table(self):
        flags, report = quality.build_flags(self.parts())
        self.assertEqual(report["rows"], {"train": 40, "val": 5})
        self.assertEqual(report["per_split"]["val"]["flags"]["deposit_suspected"],
                         int(flags.loc[flags["split"] == "val", "deposit_suspected"].sum()))
        self.assertEqual(report["repeat"]["copies_flagged"], 1)


class WeightTests(unittest.TestCase):

    def flags(self) -> pd.DataFrame:
        return pd.DataFrame({"listing_id": ["A1", "A2", "A3", "A4"],
                             "deposit_suspected": [True, False, False, False],
                             "placeholder_odometer": [False, True, False, False],
                             "implausible_year": [False, False, False, False],
                             "repeat_ad": [False, False, True, True],
                             "is_duplicate_copy": [False, False, False, True],
                             "canonical_listing_id": ["A1", "A2", "A3", "A3"],
                             "flag_count": [1, 1, 1, 2]})

    def test_none_keeps_every_row_at_unit_weight(self):
        self.assertEqual(quality.cleaning_weights(self.flags(), "none").tolist(), [1.0] * 4)

    def test_drop_deposit_zeroes_only_the_deposit_rows(self):
        self.assertEqual(quality.cleaning_weights(self.flags(), "drop_deposit").tolist(),
                         [0.0, 1.0, 1.0, 1.0])

    def test_drop_all_zeroes_every_flagged_row(self):
        self.assertEqual(quality.cleaning_weights(self.flags(), "drop_all").tolist(),
                         [0.0, 0.0, 0.0, 0.0])

    def test_weight_repeats_keeps_one_car_of_mass_per_group(self):
        weights = quality.cleaning_weights(self.flags(), "weight_repeats")
        self.assertEqual(weights.tolist(), [1.0, 1.0, 0.5, 0.5])   # A3+A4 = one car

    def test_an_unknown_mode_is_an_error_not_a_silent_one(self):
        with self.assertRaises(ValueError):
            quality.cleaning_weights(self.flags(), "drop_everything")


if __name__ == "__main__":
    unittest.main()
