"""Unit tests for the feature-table leakage gate in tools/model_gate.py.

The gate is the only thing standing between "a model that scores 0.99" and a real result, so each
check gets a test that makes it fail on purpose.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.model_gate import audit, check_siblings


def write_csv(path: Path, columns: list[str], rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    return path


BASE_COLUMNS = ["listing_id", "duplicate_group_id", "price_vnd", "mileage_km", "brand"]
BASE_ROWS = [["A1", "G1", 300_000_000, 40_000, "Toyota"],
             ["A2", "G2", 700_000_000, 20_000, "Ford"],
             ["A3", "G3", 500_000_000, 60_000, "Kia"]]


class CleanTableTests(unittest.TestCase):

    def test_a_clean_table_passes(self):
        with TemporaryDirectory() as folder:
            path = write_csv(Path(folder) / "train_features_full.csv", BASE_COLUMNS, BASE_ROWS)
            report = audit(path)
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["rows"], 3)
        self.assertIn("mileage_km", report["numeric"])

    def test_ids_are_a_note_not_a_problem(self):
        with TemporaryDirectory() as folder:
            path = write_csv(Path(folder) / "train_features_full.csv", BASE_COLUMNS, BASE_ROWS)
            report = audit(path)
        self.assertEqual(len(report["notes"]), 2)          # listing_id + duplicate_group_id


class ForbiddenColumnTests(unittest.TestCase):

    def test_a_price_text_column_is_rejected(self):
        columns = [*BASE_COLUMNS, "raw_price_text"]
        rows = [row + ["1 tỷ 250 tr"] for row in BASE_ROWS]
        with TemporaryDirectory() as folder:
            path = write_csv(Path(folder) / "train_features_full.csv", columns, rows)
            report = audit(path)
        self.assertTrue(any("raw_price_text" in problem for problem in report["problems"]))

    def test_a_review_flag_column_is_rejected(self):
        columns = [*BASE_COLUMNS, "quality_flags"]
        rows = [row + ["missing_mileage"] for row in BASE_ROWS]
        with TemporaryDirectory() as folder:
            path = write_csv(Path(folder) / "train_features_full.csv", columns, rows)
            problems = audit(path)["problems"]
        self.assertTrue(any("quality_flags" in problem for problem in problems))


class TargetCopyTests(unittest.TestCase):

    def test_a_renamed_copy_of_the_target_is_caught(self):
        columns = [*BASE_COLUMNS, "price_smooth"]
        rows = [row + [row[2]] for row in BASE_ROWS]       # same numbers, different name
        with TemporaryDirectory() as folder:
            path = write_csv(Path(folder) / "train_features_full.csv", columns, rows)
            report = audit(path)
        self.assertTrue(any("copy of the target" in problem for problem in report["problems"]))

    def test_a_legitimate_numeric_feature_is_not_flagged(self):
        columns = [*BASE_COLUMNS, "vehicle_age"]
        rows = [[*row, 6] for row in BASE_ROWS]
        with TemporaryDirectory() as folder:
            path = write_csv(Path(folder) / "train_features_full.csv", columns, rows)
            report = audit(path)
        self.assertEqual(report["problems"], [])


class PartitionTests(unittest.TestCase):

    def test_a_group_in_two_partitions_is_reported(self):
        with TemporaryDirectory() as folder:
            folder_path = Path(folder)
            write_csv(folder_path / "train_features_full.csv", BASE_COLUMNS, BASE_ROWS)
            write_csv(folder_path / "val_features_full.csv", BASE_COLUMNS,
                      [["B1", "G1", 400_000_000, 30_000, "Toyota"]])     # G1 also in train
            problems = check_siblings({}, folder_path / "train_features_full.csv")
        self.assertTrue(any("G1" in problem for problem in problems))

    def test_a_drifting_column_set_is_reported(self):
        with TemporaryDirectory() as folder:
            folder_path = Path(folder)
            write_csv(folder_path / "train_features_full.csv", BASE_COLUMNS, BASE_ROWS)
            write_csv(folder_path / "val_features_full.csv",
                      [*BASE_COLUMNS, "seats"], [row + [5] for row in BASE_ROWS])
            problems = check_siblings({}, folder_path / "train_features_full.csv")
        self.assertTrue(any("different column set" in problem for problem in problems))


class MissingTargetTests(unittest.TestCase):

    def test_a_table_without_the_target_is_rejected(self):
        columns = ["listing_id", "mileage_km"]
        with TemporaryDirectory() as folder:
            path = write_csv(Path(folder) / "train_features_full.csv", columns, [["A1", 40_000]])
            report = audit(path)
        self.assertTrue(any("target column" in problem for problem in report["problems"]))


if __name__ == "__main__":
    unittest.main()
