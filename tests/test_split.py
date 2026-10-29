"""Unit tests for the train/val/test split in src/data_prep/split.py.

The property that matters is **no leakage**: every record of one candidate vehicle must land in the
same partition, and the price mix must stay comparable across partitions.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from src.data_prep.split import (DEFAULT_RATIOS, assign_splits, assign_strata, group_rows,
                                 split_rows)


def row(listing_id: str, group: str, price, platform: str = "oto.com.vn") -> dict:
    return {"listing_id": listing_id, "duplicate_group_id": group,
            "price_vnd": "" if price is None else str(price),
            "source_platform": platform, "quality_flags": ""}


class GroupRowsTests(unittest.TestCase):
    """A group is one candidate vehicle; a broken export must not glue cars together."""

    def test_groups_by_duplicate_group_id(self):
        groups = group_rows([row("A", "DUP_1", 100), row("B", "DUP_1", 100), row("C", "DUP_2", 200)])
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups["DUP_1"]), 2)

    def test_missing_group_id_becomes_its_own_group(self):
        groups = group_rows([row("A", "", 100), row("B", "", 200)])
        self.assertEqual(len(groups), 2)
        self.assertIn("SOLO_A", groups)


class SplitIntegrityTests(unittest.TestCase):
    """The leakage guarantee: a group never appears in two partitions."""

    def setUp(self):
        # 200 groups x 2 rows each: the same car advertised on two marketplaces.
        self.rows = []
        for index in range(200):
            price = 100_000_000 + index * 5_000_000
            self.rows.append(row(f"A{index}", f"DUP_{index:03d}", price, "oto.com.vn"))
            self.rows.append(row(f"B{index}", f"DUP_{index:03d}", price, "bonbanh"))

    def test_no_group_crosses_partitions(self):
        parts, unlabelled, _ = split_rows(self.rows)
        seen: dict[str, str] = {}
        for name, rows in parts.items():
            for record in rows:
                key = record["duplicate_group_id"]
                seen.setdefault(key, name)
                self.assertEqual(seen[key], name, f"group {key} leaked into {name}")
        self.assertEqual(unlabelled, [])

    def test_every_row_is_placed_exactly_once(self):
        parts, unlabelled, _ = split_rows(self.rows)
        placed = [record["listing_id"] for rows in parts.values() for record in rows]
        self.assertEqual(len(placed), len(self.rows))
        self.assertEqual(len(set(placed)), len(self.rows))

    def test_ratios_are_close(self):
        parts, _, _ = split_rows(self.rows)
        total = sum(len(rows) for rows in parts.values())
        for name, target in zip(("train", "val", "test"), DEFAULT_RATIOS):
            self.assertAlmostEqual(len(parts[name]) / total, target, delta=0.03)

    def test_deterministic_for_the_same_seed(self):
        first, _, _ = split_rows(self.rows, seed=42)
        second, _, _ = split_rows(self.rows, seed=42)
        for name in first:
            self.assertEqual([r["listing_id"] for r in first[name]],
                             [r["listing_id"] for r in second[name]])

    def test_a_different_seed_changes_the_assignment(self):
        first, _, _ = split_rows(self.rows, seed=42)
        second, _, _ = split_rows(self.rows, seed=7)
        self.assertNotEqual([r["listing_id"] for r in first["train"]],
                            [r["listing_id"] for r in second["train"]])


class UnlabelledTests(unittest.TestCase):
    """price_vnd is the target: a row without one cannot be a regression example."""

    def test_rows_without_price_are_set_aside(self):
        rows = [row("A", "DUP_1", 500_000_000), row("B", "DUP_2", None), row("C", "DUP_3", "")]
        parts, unlabelled, _ = split_rows(rows)
        self.assertEqual([record["listing_id"] for record in unlabelled], ["B", "C"])
        self.assertEqual(sum(len(value) for value in parts.values()), 1)


class StratificationTests(unittest.TestCase):
    """The heavy tail must not move between partitions: the split is made inside every decile."""

    def test_deciles_are_assigned_by_price(self):
        # distinct prices, otherwise half the groups share one value and the deciles collapse into ties
        groups = group_rows([row(f"X{i}", f"DUP_{i}", 100_000_000 + i * 400_000_000)
                             for i in range(20)])
        strata = assign_strata(groups)
        self.assertEqual(strata["DUP_0"], "decile 00")     # cheapest
        self.assertEqual(strata["DUP_19"], "decile 09")    # most expensive
        self.assertEqual(len(set(strata.values())), 10)    # every decile is in use

    def test_price_strata_are_balanced_across_partitions(self):
        rows = []
        for index in range(300):
            price = 50_000_000 * (index + 1)          # a wide, skewed range
            rows.append(row(f"X{index}", f"DUP_{index}", price))
        parts, _, _ = split_rows(rows)

        def median_price(rows_here):
            prices = sorted(int(r["price_vnd"]) for r in rows_here)
            return prices[len(prices) // 2]

        train_median = median_price(parts["train"])
        for name in ("val", "test"):
            self.assertLess(abs(median_price(parts[name]) - train_median) / train_median, 0.10)


class AssignSplitsTests(unittest.TestCase):
    """Small strata still get a group in every partition, and one group never fills two."""

    def test_three_groups_give_one_partition_each(self):
        groups = {f"DUP_{i}": [row(f"L{i}", f"DUP_{i}", 100_000_000)] for i in range(3)}
        assignment = assign_splits(groups, DEFAULT_RATIOS, seed=1)
        self.assertEqual(sorted(assignment.values()), ["test", "train", "val"])


if __name__ == "__main__":
    unittest.main()
