"""Unit tests for the week-4 tools: generalisation hold-out, recon classification, feature steps.

Synthetic inputs only — CI runs this without the snapshot and without the network.

Run: python -m unittest tests.test_week4_tools -v
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from tools import feature_steps_eval, generalisation_check, recon_detail_fields


def frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame({"brand": [r[0] for r in rows], "model": [r[1] for r in rows],
                         "price_vnd": [r[2] for r in rows]})


class HoldoutSelectionTests(unittest.TestCase):

    def test_the_same_seed_gives_the_same_levels(self):
        data = frame([("Toyota", "Camry", 8e8)] * 4 + [("Kia", "Morning", 3e8)] * 3)
        self.assertEqual(generalisation_check.select_holdout(data, 0.5, 42),
                         generalisation_check.select_holdout(data, 0.5, 42))

    def test_the_choice_does_not_read_the_price(self):
        cheap = frame([("Toyota", "Camry", 8e8)] * 4 + [("Kia", "Morning", 3e8)] * 3)
        expensive = cheap.assign(price_vnd=cheap["price_vnd"] * 10)
        self.assertEqual(generalisation_check.select_holdout(cheap, 0.5, 42),
                         generalisation_check.select_holdout(expensive, 0.5, 42))

    def test_a_different_seed_can_pick_another_level(self):
        data = frame([(f"Brand{index}", "Model", 5e8) for index in range(12)])
        picks = {frozenset(generalisation_check.select_holdout(data, 0.3, seed))
                 for seed in (1, 2, 3, 4, 5)}
        self.assertGreater(len(picks), 1)

    def test_the_share_is_a_floor_not_an_overshoot(self):
        data = frame([(f"Brand{index}", "Model", 5e8) for index in range(10)])
        held = generalisation_check.select_holdout(data, 0.30, 7)
        held_rows = data[generalisation_check.combo_key(data).isin(held)].shape[0]
        self.assertGreaterEqual(held_rows, 3)
        self.assertLessEqual(held_rows, 4)          # whole levels only, never fractional

    def test_a_zero_share_holds_nothing(self):
        data = frame([("Toyota", "Camry", 8e8), ("Kia", "Morning", 3e8)])
        self.assertEqual(generalisation_check.select_holdout(data, 0.0, 42), set())


class ReconTests(unittest.TestCase):

    def test_the_apex_bonbanh_host_is_switched_to_www(self):
        self.assertEqual(recon_detail_fields.prepare_url("https://bonbanh.com/xe-a-id,1.html"),
                         "https://www.bonbanh.com/xe-a-id,1.html")

    def test_other_hosts_are_left_alone(self):
        url = "https://xe.chotot.com/134989809.htm"
        self.assertEqual(recon_detail_fields.prepare_url(url), url)
        self.assertEqual(recon_detail_fields.prepare_url("https://www.bonbanh.com/x.html"),
                         "https://www.bonbanh.com/x.html")

    def resp(self, status: int = 200, history: list | None = None, url: str = "https://x/a"):
        return SimpleNamespace(status_code=status, history=history or [], url=url)

    def test_404_is_dead(self):
        state, _ = recon_detail_fields.classify(self.resp(404), "", "https://x/a")
        self.assertEqual(state, "dead_404")

    def test_a_200_page_that_says_the_listing_is_gone_is_dead(self):
        state, reason = recon_detail_fields.classify(self.resp(), "Tin đăng không tồn tại", "https://x/a")
        self.assertEqual(state, "dead_removed")
        self.assertIn("không tồn tại", reason)

    def test_a_redirect_to_another_path_is_dead(self):
        redirect = SimpleNamespace(status_code=200, history=[object()], url="https://x/oto")
        state, _ = recon_detail_fields.classify(redirect, "<html>list</html>", "https://x/a")
        self.assertEqual(state, "dead_redirect")

    def test_a_live_page_with_the_same_path_is_alive(self):
        same = SimpleNamespace(status_code=200, history=[object()], url="https://x/a?ref=1")
        self.assertEqual(recon_detail_fields.classify(same, "<html>xe</html>", "https://x/a")[0], "alive")

    def test_engine_needs_a_label_and_a_value(self):
        self.assertTrue(recon_detail_fields.has_field("Dung tích: 2.0L", "engine_capacity"))
        self.assertFalse(recon_detail_fields.has_field("Xe Toyota 2.0", "engine_capacity"))
        self.assertFalse(recon_detail_fields.has_field("Động cơ xăng", "engine_capacity"))

    def test_body_type_is_a_word_match(self):
        self.assertTrue(recon_detail_fields.has_field("Kiểu dáng: SUV", "body_type"))
        self.assertFalse(recon_detail_fields.has_field("Liên hệ để biết thêm", "body_type"))


class FeatureStepTests(unittest.TestCase):

    def test_step_four_swaps_the_raw_model_column(self):
        data = pd.DataFrame({"model": ["Camry"], "model_canonical": ["camry"], "price_vnd": [1]})
        self.assertIn("model", feature_steps_eval.columns_for(3, data).columns)
        self.assertNotIn("model", feature_steps_eval.columns_for(4, data).columns)
        self.assertIn("model_canonical", feature_steps_eval.columns_for(4, data).columns)

    def test_the_steps_are_cumulative_and_uniquely_labelled(self):
        numbers = [step for step, _, _ in feature_steps_eval.STEPS]
        labels = [label for _, label, _ in feature_steps_eval.STEPS]
        self.assertEqual(numbers, [1, 2, 3, 4])
        self.assertEqual(len(labels), len(set(labels)))


if __name__ == "__main__":
    unittest.main()

