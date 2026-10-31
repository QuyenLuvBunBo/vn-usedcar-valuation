"""Unit tests for the week-2 missing-value policy in src/data_prep/missing.py.

Two properties matter and the report claims both:

  * **no leakage** — every statistic is fitted on the train partition and then applied unchanged to
    val/test, so a value that only exists in val cannot influence a fill;
  * **no silent fill** — nothing is ever replaced with 0, and every filled cell carries an
    `imputed` flag (report §4.4 asks for a missingness indicator, not a clean-looking table).

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from src.data_prep.missing import (IMPUTED_COLUMN, MODEL_GROUP_COLUMN, apply_rare, fill_categorical,
                                   fill_engine_from_trim, fill_median_by_age, fill_median_by_group,
                                   fill_seats_from_mapping, fit_categorical, fit_median_by_age,
                                   fit_median_by_group, group_rare_models, measure_missing,
                                   missing_by_source, rare_values)


def row(brand: str = "Toyota", model: str = "Vios", platform: str = "bonbanh", **extra) -> dict:
    """One synthetic record, shaped like the columns the policy touches."""
    base = {"brand": brand, "model": model, "source_platform": platform,
            "body_type": "", "mileage_km": "", "seats": "", "engine_capacity": "",
            "sub_model_trim": "", "manufacture_year": 2018,
            "scraped_at": "2026-10-29T00:00:00Z"}
    base.update(extra)
    return base


class AuditTests(unittest.TestCase):
    """The Milestone 1 numbers: what is absent, and where."""

    def test_blank_and_unknown_both_count_as_missing(self):
        rows = [row(body_type="Sedan"), row(body_type=""), row(body_type="Unknown")]
        stats = measure_missing(rows, ["body_type"])["body_type"]
        self.assertEqual(stats["missing"], 2)
        self.assertAlmostEqual(stats["rate"], 0.6667, places=4)

    def test_rate_is_per_platform_not_average(self):
        rows = [row(platform="oto.com.vn", body_type="SUV"),
                row(platform="carmudi", body_type=""),
                row(platform="carmudi", body_type="")]
        per_source = missing_by_source(rows, ["body_type"])
        self.assertEqual(per_source["oto.com.vn"]["body_type"], 0.0)
        self.assertEqual(per_source["carmudi"]["body_type"], 1.0)


class CategoricalModeTests(unittest.TestCase):
    """Mode within brand+model -> brand -> global, fitted on train only."""

    def test_train_never_sees_the_validation_answer(self):
        train = [row(body_type="Sedan") for _ in range(5)]
        fitted = fit_categorical(train, "body_type", min_group=5)
        # val says SUV five times: a leaky implementation would learn SUV and "confirm" itself
        val = [row(body_type="") for _ in range(5)]
        self.assertEqual(fill_categorical(val, fitted), 5)
        self.assertTrue(all(record["body_type"] == "Sedan" for record in val))

    def test_thin_group_falls_back_to_the_brand(self):
        train = ([row(model="Camry", body_type="Sedan") for _ in range(5)]
                 + [row(model="Vios", body_type="Hatchback") for _ in range(6)])
        fitted = fit_categorical(train, "body_type", group_cols=("brand", "model"), min_group=5)
        # one observation for Corolla: too thin to be evidence, so the brand-level mode wins
        target = [row(model="Corolla", body_type="")]
        fill_categorical(target, fitted)
        self.assertEqual(target[0]["body_type"], "Hatchback")

    def test_unknown_is_replaced_but_flagged(self):
        train = [row(body_type="SUV") for _ in range(5)]
        target = [row(body_type="Unknown")]
        fill_categorical(target, fit_categorical(train, "body_type", min_group=5))
        self.assertEqual(target[0]["body_type"], "SUV")
        self.assertEqual(target[0][IMPUTED_COLUMN], "body_type")

    def test_an_observed_value_is_never_overwritten(self):
        train = [row(body_type="SUV") for _ in range(5)]
        target = [row(body_type="Sedan")]
        self.assertEqual(fill_categorical(target, fit_categorical(train, "body_type", min_group=5)), 0)
        self.assertEqual(target[0]["body_type"], "Sedan")
        self.assertNotIn(IMPUTED_COLUMN, target[0])

    def test_empty_train_fills_nothing(self):
        self.assertEqual(fill_categorical([row(body_type="")], fit_categorical([], "body_type")), 0)


class MedianByAgeTests(unittest.TestCase):
    """An odometer is a function of age: the band matters more than the brand."""

    def setUp(self):
        self.train = ([row(manufacture_year=2022, mileage_km=30_000) for _ in range(4)]
                      + [row(manufacture_year=2010, mileage_km=180_000) for _ in range(4)])
        self.fitted = fit_median_by_age(self.train, "mileage_km", reference_year=2026, min_group=4)

    def test_bands_are_learned_separately(self):
        # age 4 -> bucket 0, age 16 -> bucket 3 (5-year bands)
        self.assertEqual(self.fitted["buckets"][0], 30_000)
        self.assertEqual(self.fitted["buckets"][3], 180_000)

    def test_a_blank_odometer_takes_its_own_age_band(self):
        target = [row(manufacture_year=2009, mileage_km="")]
        self.assertEqual(fill_median_by_age(target, self.fitted, reference_year=2026), 1)
        self.assertEqual(target[0]["mileage_km"], 180_000)
        self.assertEqual(target[0][IMPUTED_COLUMN], "mileage_km")

    def test_thin_band_falls_back_to_the_global_median(self):
        fitted = fit_median_by_age(self.train, "mileage_km", reference_year=2026, min_group=99)
        self.assertEqual(fitted["buckets"], {})
        target = [row(manufacture_year=2011, mileage_km="")]
        fill_median_by_age(target, fitted, reference_year=2026)
        self.assertEqual(target[0]["mileage_km"], 105_000)          # median of the two bands

    def test_never_filled_with_zero(self):
        fitted = {"column": "mileage_km", "buckets": {}, "global": None}
        self.assertEqual(fill_median_by_age([row(mileage_km="")], fitted), 0)

    def test_an_observed_odometer_is_kept(self):
        target = [row(manufacture_year=2010, mileage_km=5_000)]
        self.assertEqual(fill_median_by_age(target, self.fitted, reference_year=2026), 0)
        self.assertEqual(target[0]["mileage_km"], 5_000)


class MedianByGroupTests(unittest.TestCase):
    """An engine displacement belongs to the model, not to the car's age."""

    def setUp(self):
        self.train = ([row(model="Vios", engine_capacity="1.5") for _ in range(5)]
                      + [row(model="Camry", engine_capacity="2.5") for _ in range(5)])

    def test_the_median_is_learned_per_model(self):
        fitted = fit_median_by_group(self.train, "engine_capacity", min_group=5)
        target = [row(model="Vios", engine_capacity=""), row(model="Camry", engine_capacity="")]
        self.assertEqual(fill_median_by_group(target, fitted), 2)
        self.assertEqual([r["engine_capacity"] for r in target], [1.5, 2.5])

    def test_a_model_absent_from_train_takes_the_global_median(self):
        fitted = fit_median_by_group(self.train, "engine_capacity", min_group=5)
        target = [row(model="Unknown Model", engine_capacity="")]
        fill_median_by_group(target, fitted)
        self.assertEqual(target[0]["engine_capacity"], 2.0)     # median of 1.5 x5 and 2.5 x5

    def test_a_thin_model_is_not_learned(self):
        fitted = fit_median_by_group(self.train, "engine_capacity", min_group=99)
        self.assertEqual(fitted["groups"], {})


class SeatsAndEngineTests(unittest.TestCase):

    def test_seats_come_from_the_brand_model_mapping(self):
        train = [row(brand="Mitsubishi", model="Xpander", seats="7") for _ in range(5)]
        target = [row(brand="Mitsubishi", model="Xpander", seats="")]
        _, filled = fill_seats_from_mapping(target, train_rows=train, min_group=5)
        self.assertEqual(filled, 1)
        self.assertEqual(target[0]["seats"], 7)

    def test_no_seats_evidence_leaves_the_cell_empty(self):
        _, filled = fill_seats_from_mapping([row(seats="")], train_rows=[], min_group=5)
        self.assertEqual(filled, 0)

    def test_engine_is_read_from_the_trim_badge(self):
        rows = [row(sub_model_trim="2.5Q"), row(sub_model_trim="1.5G CVT"),
                row(sub_model_trim="2.0L 4x4 AT")]
        self.assertEqual(fill_engine_from_trim(rows), 3)
        self.assertEqual([r["engine_capacity"] for r in rows], [2.5, 1.5, 2.0])

    def test_a_badge_without_a_displacement_is_left_alone(self):
        rows = [row(sub_model_trim="V6"), row(sub_model_trim="RX 300"),
                row(sub_model_trim=""), row(sub_model_trim=None)]
        self.assertEqual(fill_engine_from_trim(rows), 0)
        self.assertTrue(all(not r["engine_capacity"] for r in rows))

    def test_an_existing_displacement_is_kept(self):
        rows = [row(sub_model_trim="2.5Q", engine_capacity=3.0)]
        self.assertEqual(fill_engine_from_trim(rows), 0)
        self.assertEqual(rows[0]["engine_capacity"], 3.0)


class ModelGroupTests(unittest.TestCase):
    """The plan's "<10 listings -> Other", written as a column instead of an overwrite."""

    def test_a_thin_model_becomes_other_and_keeps_its_raw_name(self):
        rows = [row(model="Roadster")]
        self.assertEqual(group_rare_models(rows, {"Roadster"}), 1)
        self.assertEqual(rows[0][MODEL_GROUP_COLUMN], "Other")
        self.assertEqual(rows[0]["model"], "Roadster")      # target encoding still has the model

    def test_a_common_model_keeps_its_own_group(self):
        rows = [row(model="Vios")]
        self.assertEqual(group_rare_models(rows, {"Roadster"}), 0)
        self.assertEqual(rows[0][MODEL_GROUP_COLUMN], "Vios")

    def test_an_empty_model_is_other(self):
        rows = [row(model="")]
        group_rare_models(rows, set())
        self.assertEqual(rows[0][MODEL_GROUP_COLUMN], "Other")


class RareCardinalityTests(unittest.TestCase):
    """`collapse_rare` must be split into fit and apply, or val-only categories survive."""

    def test_rare_values_are_fitted_on_train_only(self):
        train = [row(model="Vios") for _ in range(12)] + [row(model="Roadster") for _ in range(3)]
        rare = rare_values(train, "model", min_count=10)
        self.assertEqual(rare, {"Roadster"})

        target = [row(model="Roadster"), row(model="Vios"), row(model="ValOnly")]
        collapsed = apply_rare(target, "model", rare)
        self.assertEqual(collapsed, 1)                    # ValOnly is unknown, not "rare"
        self.assertEqual([r["model"] for r in target], ["Other", "Vios", "ValOnly"])


if __name__ == "__main__":
    unittest.main()

