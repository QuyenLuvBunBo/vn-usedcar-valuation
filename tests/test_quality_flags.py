"""Unit tests for the report §4.3 quality flags in src/merge/build_master.py.

The flags decide which records the report calls "excluded from the regression cohort, with a reason", so
their precedence matters: a 465-billion Mazda must not be filed as a luxury car.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from src.merge.build_master import (PRICE_IMPLAUSIBLE_HIGH, PRICE_REVIEW_LOW, PRICE_SEPARATE_SEGMENT,
                                    quality_flags)

CAPTURE_YEAR = 2026


def row(price=None, km=50_000, year=2018, **extra) -> dict:
    base = {"price_vnd": price, "mileage_km": km, "manufacture_year": year}
    base.update(extra)
    return base


class PriceFlagTests(unittest.TestCase):
    """The three price cutoffs of §4.3, and their order."""

    def test_normal_price_has_no_price_flag(self):
        flags = quality_flags(row(600_000_000), CAPTURE_YEAR)
        self.assertNotIn("implausible_price_low", flags)
        self.assertNotIn("implausible_price_high", flags)
        self.assertNotIn("luxury_segment", flags)

    def test_below_thirty_million_is_a_low_review_candidate(self):
        self.assertIn("implausible_price_low", quality_flags(row(PRICE_REVIEW_LOW - 1), CAPTURE_YEAR))
        self.assertNotIn("implausible_price_low", quality_flags(row(PRICE_REVIEW_LOW), CAPTURE_YEAR))

    def test_a_real_supercar_is_a_separate_segment_not_an_error(self):
        # a Phantom at 66 billion is a genuine listing: flagged for review, never as implausible
        flags = quality_flags(row(66_000_000_000), CAPTURE_YEAR)
        self.assertIn("luxury_segment", flags)
        self.assertNotIn("implausible_price_high", flags)

    def test_a_unit_error_is_flagged_high_not_luxury(self):
        # "465000 Tỷ" on a 2017 CX5 — the two flags must not be confused
        flags = quality_flags(row(465_000_000_000_000), CAPTURE_YEAR)
        self.assertIn("implausible_price_high", flags)
        self.assertNotIn("luxury_segment", flags)

    def test_the_high_ceiling_sits_above_the_segment_ceiling(self):
        self.assertGreater(PRICE_IMPLAUSIBLE_HIGH, PRICE_SEPARATE_SEGMENT)

    def test_missing_price_is_its_own_flag(self):
        self.assertIn("missing_price", quality_flags(row(None), CAPTURE_YEAR))


class MileageFlagTests(unittest.TestCase):
    """Mileage rules are about inspection, never a deletion."""

    def test_over_one_million_km(self):
        self.assertIn("implausible_mileage_high", quality_flags(row(600_000_000, km=1_000_001),
                                                                CAPTURE_YEAR))

    def test_low_reading_on_an_old_car(self):
        flags = quality_flags(row(600_000_000, km=50, year=2010), CAPTURE_YEAR)
        self.assertIn("low_mileage_older_car", flags)

    def test_low_reading_on_a_new_car_is_normal(self):
        flags = quality_flags(row(600_000_000, km=50, year=CAPTURE_YEAR), CAPTURE_YEAR)
        self.assertNotIn("low_mileage_older_car", flags)


class YearFlagTests(unittest.TestCase):

    def test_out_of_scope_year(self):
        self.assertIn("year_out_of_scope", quality_flags(row(600_000_000, year=1990), CAPTURE_YEAR))
        self.assertIn("year_out_of_scope", quality_flags(row(600_000_000, year=2032), CAPTURE_YEAR))

    def test_missing_year(self):
        self.assertIn("missing_year", quality_flags(row(600_000_000, year=None), CAPTURE_YEAR))


if __name__ == "__main__":
    unittest.main()
