"""Unit tests for tools/audit_master.py (the "kiểm tra kiểu dữ liệu" gate of week 2).

The tool guards the merged dataset, so it must fail on the shapes that actually reached us: a numeric
column holding text, a categorical outside the enum, a duplicated key, and — the subtle one — a date that
pandas can parse but that is not ISO 8601 ("10/2026" is read as October 2026).

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.common import schema
from tools.audit_master import audit, diagnostics

HEADER = [*schema.SCHEMA_COLUMNS, "tier", "duplicate_group_id", "quality_flags"]


def row(**overrides) -> dict:
    base = dict.fromkeys(HEADER, "")
    base.update({
        "listing_id": "OTO_1", "source_url": "https://oto.com.vn/1", "price_vnd": "600000000",
        "manufacture_year": "2020", "mileage_km": "50000", "engine_capacity": "2.0", "seats": "5",
        "transmission": "Automatic", "fuel_type": "Gasoline", "origin": "CKD", "body_type": "SUV",
        "seller_type": "Unknown", "price_status": "full", "tier": "listed",
        "listing_date": "2026-01-01", "scraped_at": "2026-01-01T00:00:00+00:00",
    })
    base.update(overrides)
    return base


def write(rows: list[dict]) -> Path:
    path = Path(tempfile.mkdtemp()) / "master.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return path


class CleanFileTests(unittest.TestCase):
    def test_a_clean_row_has_no_problems(self):
        self.assertEqual(audit(write([row()])), 0)

    def test_empty_optional_columns_are_allowed(self):
        # nulls stay null: an absent odometer or date is not a defect
        self.assertEqual(audit(write([row(mileage_km="", listing_date="", engine_capacity="")])), 0)


class DetectsProblemsTests(unittest.TestCase):
    def test_text_in_a_numeric_column(self):
        self.assertGreater(audit(write([row(price_vnd="khong biet")])), 0)

    def test_a_value_outside_the_enum(self):
        self.assertGreater(audit(write([row(fuel_type="Xang")])), 0)

    def test_a_date_that_is_not_iso_8601(self):
        # pandas parses "10/2026" as October 2026, so parseability alone would miss this
        self.assertGreater(audit(write([row(listing_date="10/2026")])), 0)

    def test_an_impossible_date(self):
        self.assertGreater(audit(write([row(listing_date="2026-13-45")])), 0)

    def test_a_duplicated_listing_id(self):
        self.assertGreater(audit(write([row(), row()])), 0)

    def test_an_empty_listing_id(self):
        self.assertGreater(audit(write([row(listing_id="")])), 0)


class DiagnosticsTests(unittest.TestCase):
    def test_a_deposit_style_price_is_diagnosed_but_never_a_problem(self):
        # Same car, one plausible price and one 42 M placeholder: the pair must not fail the gate.
        rows = [row(price_vnd="600000000"), row(listing_id="OTO_2", source_url="https://oto.com.vn/2",
                                               price_vnd="42000000")]
        self.assertEqual(audit(write(rows)), 0)

    def test_a_placeholder_odometer_is_diagnosed_but_never_a_problem(self):
        self.assertEqual(audit(write([row(mileage_km="999998")])), 0)
        self.assertEqual(audit(write([row(mileage_km="1")])), 0)

    def test_an_impossible_model_year_is_diagnosed_but_never_a_problem(self):
        self.assertEqual(audit(write([row(manufacture_year="1025")])), 0)

    def test_the_diagnostic_block_reports_counts(self):
        frame = pd.DataFrame([row(price_vnd="600000000"), row(price_vnd="42000000"),
                              row(mileage_km="999998"), row(manufacture_year="2032")])
        text = "\n".join(diagnostics(frame))
        self.assertIn("deposit-style price", text)
        self.assertIn("placeholder odometer", text)
        self.assertIn("impossible model year", text)


if __name__ == "__main__":
    unittest.main()
