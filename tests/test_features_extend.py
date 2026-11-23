"""Unit tests for the v2 feature extension (`src/features/extend.py`).

The module is stateless by design — every column is a function of its own row — so these tests can use
tiny synthetic frames and still prove the property that matters: no group statistic is fitted.

Run: python -m unittest tests.test_features_extend -v
"""

from __future__ import annotations

import unittest

import pandas as pd

from src.features import extend


class EngineParseTests(unittest.TestCase):

    def test_a_badge_yields_a_displacement(self):
        self.assertEqual(extend.parse_engine("2.0T"), 2.0)
        self.assertEqual(extend.parse_engine("1.5 AT"), 1.5)
        self.assertEqual(extend.parse_engine("Camry 2.5Q"), 2.5)
        self.assertEqual(extend.parse_engine("2,2 Diesel"), 2.2)

    def test_numbers_that_are_not_litres_are_ignored(self):
        self.assertIsNone(extend.parse_engine("RX 300"))
        self.assertIsNone(extend.parse_engine("2021"))
        self.assertIsNone(extend.parse_engine("4x4"))
        self.assertIsNone(extend.parse_engine(""))
        self.assertIsNone(extend.parse_engine(None))
        self.assertIsNone(extend.parse_engine("9.0"))          # outside 0.6 .. 8.0

    def test_the_site_value_wins_over_the_badge(self):
        self.assertEqual(extend.fill_engine(2.4, "2.0T"), (2.4, False))
        self.assertEqual(extend.fill_engine(None, "2.0T"), (2.0, True))
        self.assertEqual(extend.fill_engine(None, None, "Custin 1.5"), (1.5, True))
        self.assertEqual(extend.fill_engine(None, "RX 300"), (None, False))


class TrimRankTests(unittest.TestCase):

    def test_top_words(self):
        self.assertEqual(extend.trim_rank("2.5Q Cao Cấp"), "top")
        self.assertEqual(extend.trim_rank("Bản Đặc Biệt"), "top")
        self.assertEqual(extend.trim_rank("Signature"), "top")

    def test_mid_and_base_words(self):
        self.assertEqual(extend.trim_rank("Plus"), "mid")
        self.assertEqual(extend.trim_rank("Sport"), "mid")
        self.assertEqual(extend.trim_rank("Tiêu chuẩn"), "base")

    def test_unknown_stays_unknown(self):
        self.assertEqual(extend.trim_rank(None), "unknown")
        self.assertEqual(extend.trim_rank(""), "unknown")
        self.assertEqual(extend.trim_rank("1.5G"), "unknown")      # a code, not a tier word

    def test_the_model_string_is_a_fallback_when_the_trim_is_empty(self):
        self.assertEqual(extend.trim_rank(None, "Custin Cao Cấp 2.0T"), "top")
        self.assertEqual(extend.trim_rank("", "Carnival Luxury 2.2D"), "top")


class CanonicalModelTests(unittest.TestCase):

    def test_variant_tokens_are_stripped(self):
        self.assertEqual(extend.canonical_model("Custin Cao Cấp 2.0T"), "custin")
        self.assertEqual(extend.canonical_model("Accent Cao cấp 1.5 AT"), "accent")
        self.assertEqual(extend.canonical_model("Carnival Luxury 2.2D"), "carnival")

    def test_a_real_name_survives(self):
        self.assertEqual(extend.canonical_model("CX-5"), "cx-5")
        self.assertEqual(extend.canonical_model("VF 8"), "vf 8")
        self.assertEqual(extend.canonical_model("S Class"), "s class")
        self.assertEqual(extend.canonical_model(""), "unknown")

    def test_tokens_that_were_removed_are_kept_elsewhere(self):
        self.assertEqual(extend.variant_tokens("Accent Cao cấp 1.5 AT"), "1.5;at")
        self.assertEqual(extend.variant_tokens("Carnival Luxury 2.2D"), "2.2d")
        self.assertEqual(extend.variant_tokens("Xpander"), "")



class ExtendSplitTests(unittest.TestCase):

    def frames(self):
        cohort = pd.DataFrame({
            "listing_id": ["A1", "A2", "A3"],
            "model": ["Custin Cao Cấp 2.0T", "Accent", "Camry 2.5Q"],
            "sub_model_trim": [None, "Tiêu chuẩn", None],
            # engine values: site value / imputed value / missing
            "engine_capacity": [2.0, 1.4, None],
            "imputed": ["", "engine_capacity;seats", ""],
        })
        features = pd.DataFrame({
            "listing_id": ["A1", "A2", "A3"],
            "model": cohort["model"],
            "price_vnd": [900_000_000, 500_000_000, 800_000_000],
        })
        return cohort, features

    def test_the_v1_columns_are_untouched_and_the_new_ones_are_appended(self):
        cohort, features = self.frames()
        out = extend.extend_split(cohort, features)
        self.assertEqual(list(out.columns)[:3], list(features.columns))
        for column in extend.NEW_COLUMNS:
            self.assertIn(column, out.columns)

    def test_an_imputed_engine_is_re_parsed_but_a_site_value_is_not(self):
        cohort, features = self.frames()
        out = extend.extend_split(cohort, features).set_index("listing_id")
        self.assertEqual(out.loc["A1", "engine_capacity_parsed"], 2.0)    # site value kept
        self.assertFalse(bool(out.loc["A1", "engine_parsed"]))
        self.assertEqual(out.loc["A2", "engine_capacity_parsed"], 1.4)    # no badge -> keep imputed
        self.assertFalse(bool(out.loc["A2", "engine_parsed"]))
        self.assertEqual(out.loc["A3", "engine_capacity_parsed"], 2.5)    # parsed from "2.5Q"
        self.assertTrue(bool(out.loc["A3", "engine_parsed"]))

    def test_trim_missing_is_an_indicator(self):
        cohort, features = self.frames()
        out = extend.extend_split(cohort, features).set_index("listing_id")
        self.assertTrue(bool(out.loc["A1", "trim_missing"]))
        self.assertFalse(bool(out.loc["A2", "trim_missing"]))

    def test_the_input_frames_are_not_mutated_and_order_is_kept(self):
        cohort, features = self.frames()
        cohort_before, features_before = cohort.copy(), features.copy()
        out = extend.extend_split(cohort, features)
        pd.testing.assert_frame_equal(cohort, cohort_before)
        pd.testing.assert_frame_equal(features, features_before)
        self.assertEqual(out["listing_id"].tolist(), ["A1", "A2", "A3"])

    def test_building_twice_gives_the_same_table(self):
        cohort, features = self.frames()
        pd.testing.assert_frame_equal(extend.extend_split(cohort, features),
                                      extend.extend_split(cohort, features))

    def test_a_feature_row_missing_from_the_cohort_fails_loudly(self):
        cohort, features = self.frames()
        features = pd.concat([features, pd.DataFrame({"listing_id": ["ZZ"], "model": ["X"],
                                                      "price_vnd": [1]})], ignore_index=True)
        with self.assertRaises(SystemExit):
            extend.extend_split(cohort, features)


if __name__ == "__main__":
    unittest.main()
