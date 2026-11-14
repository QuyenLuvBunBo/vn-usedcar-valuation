"""Unit tests for the bonbanh backfill and the v2 build — no network, no snapshot.

Run: python -m unittest tests.test_backfill -v
"""

from __future__ import annotations

import unittest

import pandas as pd

from tools import apply_backfill, backfill_bonbanh

DETAIL_HTML = """
<html><body>
<div class="box_car_detail">
  <div class="row"><div class="label">Động cơ:</div><div class="txt_input">Xăng 2.0 L</div></div>
  <div class="row"><div class="label">Kiểu dáng:</div><div class="txt_input">SUV</div></div>
  <div class="row_last"><div class="label">Xuất xứ:</div><div class="txt_input">Nhập khẩu</div></div>
</div>
<a class="cname" href="https://salon.bonbanh.com">Salon A</a>
</body></html>
"""


class ParseTests(unittest.TestCase):

    def test_the_three_fields_are_read_from_a_detail_page(self):
        parsed = backfill_bonbanh.parse_fields(DETAIL_HTML)
        self.assertEqual(parsed["engine_capacity"], 2.0)
        self.assertEqual(parsed["body_type"], "SUV")
        self.assertEqual(parsed["seller_type"], "Dealership/Salon")

    def test_a_private_seller_lists_nothing_to_classify(self):
        page = DETAIL_HTML.replace('<a class="cname" href="https://salon.bonbanh.com">Salon A</a>', "")
        self.assertNotIn("seller_type", backfill_bonbanh.parse_fields(page))

    def test_a_page_without_a_spec_table_yields_nothing(self):
        self.assertEqual(backfill_bonbanh.parse_fields("<html><body>x</body></html>"), {})


class SoftBlockTests(unittest.TestCase):

    def test_the_captcha_page_is_a_block(self):
        page = ('<html><head><title>Thông báo !!!</title>'
                '<script src="/captcha.js"></script></head><body>...</body></html>')
        self.assertTrue(backfill_bonbanh.is_soft_block(page))

    def test_a_real_page_is_not_a_block(self):
        self.assertFalse(backfill_bonbanh.is_soft_block(DETAIL_HTML))

    def test_no_page_is_a_block(self):
        self.assertTrue(backfill_bonbanh.is_soft_block(None))


class FillOnlyTests(unittest.TestCase):

    def row(self, **overrides) -> pd.Series:
        base = {"listing_id": "BAN_1", "engine_capacity": 2.0, "seller_type": "Private Individual",
                "body_type": "SUV", "imputed": ""}
        base.update(overrides)
        return pd.Series(base)

    def test_a_blank_is_filled(self):
        kept = backfill_bonbanh.keep_only_blanks(self.row(body_type=None), {"body_type": "Sedan"})
        self.assertEqual(kept, {"body_type": "Sedan"})

    def test_an_observed_value_is_never_overwritten(self):
        kept = backfill_bonbanh.keep_only_blanks(self.row(body_type="SUV"), {"body_type": "Sedan"})
        self.assertEqual(kept, {})

    def test_a_statistic_is_replaced(self):
        """`imputed` says the value came from a median, so the page is a better source."""
        kept = backfill_bonbanh.keep_only_blanks(self.row(imputed="seller_type;seats"),
                                                 {"seller_type": "Dealership/Salon"})
        self.assertEqual(kept, {"seller_type": "Dealership/Salon"})

    def test_unknown_counts_as_blank(self):
        kept = backfill_bonbanh.keep_only_blanks(self.row(body_type="Unknown"), {"body_type": "MPV"})
        self.assertEqual(kept, {"body_type": "MPV"})



class DeriveTrimTests(unittest.TestCase):

    def test_a_tier_word_in_the_model_becomes_the_trim(self):
        self.assertEqual(apply_backfill.derive_trim("Custin Cao Cấp 2.0T"), "cao cấp 2.0t")
        self.assertEqual(apply_backfill.derive_trim("Accent Cao cấp 1.5 AT"), "cao cấp 1.5 at")

    def test_a_model_without_a_tier_word_stays_blank(self):
        self.assertIsNone(apply_backfill.derive_trim("GLC 300 4Matic"))
        self.assertIsNone(apply_backfill.derive_trim(None))


class PatchTests(unittest.TestCase):

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({
            "listing_id": ["BAN_1", "BAN_2"], "source_platform": ["bonbanh", "bonbanh"],
            "model": ["Custin Cao Cấp 2.0T", "GLC 300 4Matic"],
            "sub_model_trim": [None, None],
            "engine_capacity": [1.5, 2.0], "seller_type": ["Private Individual", "Dealership/Salon"],
            "body_type": ["SUV", "SUV"], "imputed": ["engine_capacity", ""],
            "price_vnd": [900_000_000, 2_000_000_000],
        })

    def test_the_patch_fills_only_the_listed_blank_and_records_provenance(self):
        patch = {"BAN_1": {"engine_capacity": 1.5, "seller_type": "Dealership/Salon"}}
        after, counts = apply_backfill.apply_patch(self.frame(), patch)
        self.assertEqual(after.loc[0, "engine_capacity"], 1.5)
        # seller was observed on BAN_1 and carries no imputed marker -> the patch must not touch it
        self.assertEqual(after.loc[0, "seller_type"], "Private Individual")
        self.assertEqual(after.loc[0, "imputed"], "")          # engine is now observed
        self.assertIn("bonbanh_detail:engine_capacity", after.loc[0, "v2_filled"])
        self.assertEqual(counts["engine_capacity"], 1)
        self.assertEqual(counts["seller_type"], 0)

    def test_an_observed_value_is_untouched_even_if_the_patch_has_one(self):
        patch = {"BAN_2": {"engine_capacity": 3.0}}
        after, _ = apply_backfill.apply_patch(self.frame(), patch)
        self.assertEqual(after.loc[1, "engine_capacity"], 2.0)   # no imputed marker -> untouched
        self.assertEqual(after.loc[1, "v2_filled"], "")

    def test_the_trim_is_derived_when_the_model_carries_a_tier(self):
        after, counts = apply_backfill.apply_patch(self.frame(), {})
        self.assertEqual(after.loc[0, "sub_model_trim"], "cao cấp 2.0t")
        self.assertTrue(pd.isna(after.loc[1, "sub_model_trim"]))
        self.assertEqual(counts["sub_model_trim"], 1)

    def test_invariants_reject_a_changed_price(self):
        before = self.frame()
        after = before.copy()
        after.loc[0, "price_vnd"] = 1
        with self.assertRaises(SystemExit):
            apply_backfill.assert_invariants(before, after, "train")

    def test_invariants_accept_a_fill(self):
        before = self.frame()
        after, _ = apply_backfill.apply_patch(before, {"BAN_1": {"engine_capacity": 1.5}})
        apply_backfill.assert_invariants(before, after, "train")     # must not raise


if __name__ == "__main__":
    unittest.main()
