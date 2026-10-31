"""Unit tests for the week-2 normalisation and cohort rules in src/data_prep/normalize.py.

Two claims are tested here:

  * **one brand/model is one string** — the alias table plus the train vote collapse the spellings
    the merge left behind (and only those: a val-only spelling is not learned);
  * **the cohort is a view, with a reason per record** — every excluded row is attributed to exactly
    one §4.3 rule, and kept + excluded always adds up to the rows given.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from src.data_prep.normalize import (BRAND_CANONICALS, COHORT_RULES, alias_report,
                                     apply_brand_and_model, apply_cohort, cohort_reason,
                                     cohort_table, learn_brand_map, learn_model_map, normalize_brand,
                                     repair_body_type, repair_implausible_numbers)


def row(brand: str = "Toyota", model: str = "Vios", price=600_000_000, year=2018,
        km=50_000, **extra) -> dict:
    base = {"brand": brand, "model": model, "price_vnd": price,
            "manufacture_year": year, "mileage_km": km}
    base.update(extra)
    return base


class BrandTests(unittest.TestCase):

    def test_the_explicit_table_wins_over_the_common_spelling(self):
        # 'Mercedes Benz' is written 898 times against 4,040 for the correct spelling; the table is
        # what makes the answer independent of the vote.
        self.assertEqual(normalize_brand("Mercedes Benz"), "Mercedes-Benz")
        self.assertEqual(normalize_brand("KIA"), "Kia")
        self.assertEqual(normalize_brand("LandRover"), "Land Rover")

    def test_the_explicit_table_is_consulted_before_the_learned_map(self):
        learned = learn_brand_map([row(brand="KIA")] * 9)
        self.assertEqual(learned["kia"], BRAND_CANONICALS["kia"])

    def test_a_decoration_is_not_a_brand(self):
        self.assertEqual(normalize_brand(None), "Unknown")
        self.assertEqual(normalize_brand(""), "Unknown")
        self.assertEqual(normalize_brand("🚘"), "Unknown")

    def test_bold_letters_and_spacing_are_normalized(self):
        # '\U0001d405\U0001d40e\U0001d411\U0001d403' is FORD in mathematical bold capitals
        self.assertEqual(normalize_brand("\U0001d405\U0001d40e\U0001d411\U0001d403"), "FORD")
        self.assertEqual(normalize_brand("Land  Rover "), "Land Rover")

    def test_the_train_vote_picks_the_common_spelling(self):
        learned = learn_brand_map([row(brand="Audi")] * 5 + [row(brand="AUDI")] * 2)
        self.assertEqual(normalize_brand("AUDI", learned), "Audi")


class ModelTests(unittest.TestCase):
    """A model map is keyed by brand, so two brands can use the same name differently."""

    def setUp(self):
        self.train = ([row(brand="Mazda", model="CX-5") for _ in range(4)]
                      + [row(brand="Mazda", model="CX 5") for _ in range(1)])
        self.brand_map = learn_brand_map(self.train)
        self.model_map = learn_model_map(self.train, self.brand_map)

    def test_spellings_of_one_model_collapse(self):
        target = [row(brand="Mazda", model="CX 5"), row(brand="Mazda", model="cx-5")]
        apply_brand_and_model(target, self.brand_map, self.model_map)
        self.assertEqual([r["model"] for r in target], ["CX-5", "CX-5"])

    def test_a_spelling_seen_only_outside_train_is_left_alone(self):
        target = [row(brand="Mazda", model="CX 50")]
        apply_brand_and_model(target, self.brand_map, self.model_map)
        self.assertEqual(target[0]["model"], "CX 50")

    def test_alias_report_finds_the_variants(self):
        report = alias_report([row(brand="VinFast"), row(brand="Vinfast")], "brand")
        self.assertEqual(report[0]["variants"], 2)
        self.assertEqual(set(report[0]["spellings"]), {"VinFast", "Vinfast"})


class TemplateDefaultTests(unittest.TestCase):
    """carmudi writes `Coupe` for 528 of its 546 listings — a dropdown default, not a body style."""

    def test_carmudi_coupe_becomes_unknown(self):
        rows = [{"source_platform": "carmudi", "body_type": "Coupe"}]
        self.assertEqual(repair_body_type(rows), {"carmudi": 1})
        self.assertEqual(rows[0]["body_type"], "Unknown")

    def test_the_listing_itself_is_kept(self):
        rows = [{"source_platform": "carmudi", "body_type": "Coupe", "price_vnd": "500000000"}]
        repair_body_type(rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_vnd"], "500000000")

    def test_another_source_may_really_sell_a_coupe(self):
        rows = [{"source_platform": "bonbanh", "body_type": "Coupe"}]
        self.assertEqual(repair_body_type(rows), {})
        self.assertEqual(rows[0]["body_type"], "Coupe")

    def test_a_genuine_carmudi_body_type_is_left_alone(self):
        rows = [{"source_platform": "carmudi", "body_type": "SUV"}]
        self.assertEqual(repair_body_type(rows), {})
        self.assertEqual(rows[0]["body_type"], "SUV")


class ImplausibleNumberTests(unittest.TestCase):
    """A model year in the displacement column, or a 760-seat car."""

    def test_an_engine_capacity_that_is_a_year_is_blanked(self):
        rows = [{"engine_capacity": "2021"}]
        self.assertEqual(repair_implausible_numbers(rows), {"engine_capacity": 1})
        self.assertEqual(rows[0]["engine_capacity"], "")

    def test_a_zero_displacement_is_blanked_too(self):
        rows = [{"engine_capacity": "0"}]
        repair_implausible_numbers(rows)
        self.assertEqual(rows[0]["engine_capacity"], "")

    def test_a_real_displacement_survives(self):
        rows = [{"engine_capacity": "2.0"}, {"engine_capacity": "1.5"}]
        self.assertEqual(repair_implausible_numbers(rows), {})
        self.assertEqual([r["engine_capacity"] for r in rows], ["2.0", "1.5"])

    def test_a_760_seat_car_is_blanked_and_a_16_seat_van_is_not(self):
        rows = [{"seats": "760"}, {"seats": "16"}, {"seats": "1"}]
        self.assertEqual(repair_implausible_numbers(rows), {"seats": 2})
        self.assertEqual([r["seats"] for r in rows], ["", "16", ""])

    def test_the_row_itself_is_never_dropped(self):
        rows = [{"engine_capacity": "2021", "price_vnd": "500000000", "seats": "760"}]
        repair_implausible_numbers(rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_vnd"], "500000000")


class CohortRuleTests(unittest.TestCase):
    """The §4.3 rules, and the precedence that stops a unit error being filed as luxury."""

    reference = 2026

    def test_a_usable_row_has_no_reason(self):
        self.assertEqual(cohort_reason(row(), self.reference), "")

    def test_missing_price(self):
        self.assertEqual(cohort_reason(row(price=None), self.reference), "missing_price")
        self.assertEqual(cohort_reason(row(price=""), self.reference), "missing_price")

    def test_a_trillion_range_price_is_a_unit_error_not_luxury(self):
        self.assertEqual(cohort_reason(row(price=465_000_000_000_000), self.reference),
                         "price_unit_error")
        self.assertEqual(cohort_reason(row(price=30_000_000_000), self.reference),
                         "price_above_luxury_segment")

    def test_the_luxury_ceiling_is_shared_with_build_master(self):
        # exactly 25 billion is not "> 25 billion": the same comparison as the master's flags
        self.assertEqual(cohort_reason(row(price=25_000_000_000), self.reference), "")

    def test_price_floor(self):
        self.assertEqual(cohort_reason(row(price=29_999_999), self.reference), "price_below_floor")
        self.assertEqual(cohort_reason(row(price=30_000_000), self.reference), "")

    def test_a_typo_year_is_out_of_scope(self):
        self.assertEqual(cohort_reason(row(year=1025), self.reference), "year_out_of_scope")
        self.assertEqual(cohort_reason(row(year=2032), self.reference), "year_out_of_scope")
        self.assertEqual(cohort_reason(row(year=1995), self.reference), "")

    def test_a_missing_mileage_is_imputable_so_it_stays(self):
        self.assertEqual(cohort_reason(row(km=None), self.reference), "")
        self.assertEqual(cohort_reason(row(km=1_000_001), self.reference), "mileage_implausible")


class CohortAccountingTests(unittest.TestCase):

    def test_every_row_is_kept_or_counted_once(self):
        rows = [row(), row(price=None), row(price=10_000_000), row(year=1025),
                row(km=2_500_000_000_000_000), row(price=465_000_000_000_000)]
        kept, counts = apply_cohort(rows, 2026)
        self.assertEqual(len(kept), 1)
        self.assertEqual(sum(counts.values()), len(rows) - len(kept))
        self.assertEqual(set(counts), set(COHORT_RULES))   # every rule reported, zero included

    def test_the_table_reports_the_cutoffs_it_used(self):
        kept, counts = apply_cohort([row(), row(price=None)], 2026)
        table = cohort_table(counts, 2)
        self.assertEqual(table["kept"], len(kept))
        self.assertEqual(table["excluded"], 1)
        self.assertEqual(table["reasons"], {"missing_price": 1})
        self.assertEqual(table["cutoffs"]["price_floor_vnd"], 30_000_000)


if __name__ == "__main__":
    unittest.main()

