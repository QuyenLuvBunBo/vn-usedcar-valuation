"""Unit tests for the fuzzy pass of src/merge/dedupe.py (report §4.2: "Composite Hashing + Fuzzy match").

The property under test is asymmetric on purpose: merging two different cars only makes them travel
together in the split (harmless), while leaving one car in two groups can put it in both train and test.
The rules therefore lean towards merging, but only on evidence — and the tests pin down exactly which
evidence counts.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from src.merge import dedupe

CAPTURE_YEAR = 2026


def row(listing_id: str, trim="2.0E", km=50_000, price=600_000_000, year=2020,
        province="Hà Nội", **extra) -> dict:
    base = {
        "listing_id": listing_id, "brand": "Toyota", "model": "Innova", "sub_model_trim": trim,
        "manufacture_year": str(year), "mileage_km": "" if km is None else str(km),
        "price_vnd": "" if price is None else str(price),
        "location_province": province, "seats": "", "source_platform": "oto.com.vn",
    }
    base.update(extra)
    return base


def groups_of(rows: list[dict]) -> dict[str, str]:
    """listing_id -> duplicate_group_id, after the fuzzy merge."""
    dedupe.duplicate_groups(rows, capture_year=CAPTURE_YEAR, fuzzy=True)
    return {r["listing_id"]: r["duplicate_group_id"] for r in rows}


class MergeOnEvidenceTests(unittest.TestCase):
    """Pairs whose exact keys differ but which describe one car.

    The exact key already joins identical trim + identical odometer bucket, so a case here must differ in
    something the key uses — otherwise the test would pass without fuzzy doing anything. 50,000 km and
    54,000 km sit in different buckets (10 and 11) yet inside the 5,000 km tolerance, which is exactly the
    gap fuzzy matching exists to close.
    """

    def test_a_moved_odometer_inside_the_tolerance_merges(self):
        rows = [row("A", km=50_000), row("B", km=54_000)]
        merged = groups_of(rows)
        self.assertEqual(merged["A"], merged["B"])

    def test_a_repost_with_a_lower_price_still_merges(self):
        rows = [row("A", km=50_000, price=650_000_000), row("B", km=54_000, price=630_000_000)]
        merged = groups_of(rows)
        self.assertEqual(merged["A"], merged["B"])

    def test_a_grade_of_the_same_shape_merges(self):
        rows = [row("A", trim="2.7 V 4X4 AT", km=50_000), row("B", trim="2.7L 4x4 AT", km=54_000)]
        merged = groups_of(rows)
        self.assertEqual(merged["A"], merged["B"])


class RefuseOnContradictionTests(unittest.TestCase):
    """Same block, different cars. Each pair differs in its exact key, so only fuzzy could join them."""

    def test_a_far_apart_odometer_does_not_merge(self):
        merged = groups_of([row("A", km=50_000), row("B", km=90_000)])
        self.assertNotEqual(merged["A"], merged["B"])

    def test_a_missing_odometer_is_not_evidence(self):
        merged = groups_of([row("A", km=None), row("B", km=50_000)])
        self.assertNotEqual(merged["A"], merged["B"])

    def test_an_empty_grade_is_not_evidence(self):
        # a chain of "no grade at all" matches once merged 181 ads of one model into a single group
        merged = groups_of([row("A", trim="", km=50_000), row("B", trim="", km=54_000)])
        self.assertNotEqual(merged["A"], merged["B"])

    def test_a_different_grade_does_not_merge(self):
        merged = groups_of([row("A", trim="2.0E", km=50_000), row("B", trim="2.5Q", km=54_000)])
        self.assertNotEqual(merged["A"], merged["B"])

    def test_a_different_engine_does_not_merge(self):
        merged = groups_of([row("A", trim="2.7 V 4X4 AT", km=50_000),
                            row("B", trim="2.8L 4x4 AT", km=54_000)])
        self.assertNotEqual(merged["A"], merged["B"])

    def test_a_different_seat_count_does_not_merge(self):
        merged = groups_of([row("A", trim="2.0E", seats="7", km=50_000),
                            row("B", trim="2.0E", seats="8", km=54_000)])
        self.assertNotEqual(merged["A"], merged["B"])

    def test_a_different_year_is_outside_the_block(self):
        merged = groups_of([row("A", year=2020), row("B", year=2021)])
        self.assertNotEqual(merged["A"], merged["B"])

    def test_a_different_province_is_outside_the_block(self):
        merged = groups_of([row("A", province="Hà Nội"), row("B", province="TP. Hồ Chí Minh")])
        self.assertNotEqual(merged["A"], merged["B"])


class BookkeepingTests(unittest.TestCase):
    """The numbers the report quotes must add up."""

    def test_stats_agree_with_the_assigned_ids(self):
        rows = [row("A", km=50_000), row("B", km=54_000), row("C", trim="2.5Q")]
        stats = dedupe.fuzzy_groups(rows, capture_year=CAPTURE_YEAR)
        merged = groups_of(rows)
        self.assertEqual(stats["records"], 3)
        self.assertEqual(stats["exact_groups"], 3)
        self.assertEqual(stats["groups"], 2)             # A and B joined by the odometer tolerance
        self.assertEqual(stats["merged_groups"], 1)
        self.assertEqual(len(set(merged.values())), 2)

    def test_fuzzy_never_increases_the_group_count(self):
        rows = [row(f"X{i}", km=50_000 + i * 1_000) for i in range(5)]
        stats = dedupe.fuzzy_groups(rows, capture_year=CAPTURE_YEAR)
        self.assertLessEqual(stats["groups"], stats["exact_groups"])

    def test_a_single_row_keeps_its_own_group(self):
        self.assertEqual(len(set(groups_of([row("A")]).values())), 1)


if __name__ == "__main__":
    unittest.main()
