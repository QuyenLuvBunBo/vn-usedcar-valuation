"""Unit tests for the shared parsing helpers in src/common/parsing.py.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from src.common import schema
from src.common.parsing import parse_km_text, parse_vnd_price, parse_year_text


class ParseKmTextTests(unittest.TestCase):
    """The odometer is a model feature, so every spelling the sites use must land exactly."""

    def test_plain_thousands_separator(self):
        self.assertEqual(parse_km_text("140.000 km"), 140_000)
        self.assertEqual(parse_km_text("106,985"), 106_985)
        self.assertEqual(parse_km_text("58.279 km"), 58_279)
        self.assertEqual(parse_km_text("12000"), 12_000)

    def test_van_is_ten_thousand(self):
        # the bug this test was written for: '5 vạn' used to become 5 km
        self.assertEqual(parse_km_text("5 vạn"), 50_000)
        self.assertEqual(parse_km_text("1 vạn km"), 10_000)
        self.assertEqual(parse_km_text("10 vạn"), 100_000)
        self.assertEqual(parse_km_text("1,2 vạn"), 12_000)

    def test_van_with_a_thousand_tail(self):
        self.assertEqual(parse_km_text("5v8km"), 58_000)
        self.assertEqual(parse_km_text("12 vạn 5"), 125_000)

    def test_k_is_one_thousand_string(self):
        self.assertEqual(parse_km_text("34k km"), 34_000)
        self.assertEqual(parse_km_text("1.7k km"), 1_700)

    def test_km_is_not_a_thousand(self):
        self.assertEqual(parse_km_text("5km"), 5)
        self.assertEqual(parse_km_text("0 km"), 0)

    def test_empty_and_junk(self):
        self.assertIsNone(parse_km_text(""))
        self.assertIsNone(parse_km_text(None))
        self.assertIsNone(parse_km_text("không rõ"))
        self.assertEqual(parse_km_text("140.000\u00a0km"), 140_000)  # non-breaking space


class ParseVndPriceTests(unittest.TestCase):
    """Regression guard: the price parser must keep working for every source."""

    def test_million_and_billion(self):
        self.assertEqual(parse_vnd_price("550 triệu"), 550_000_000)
        self.assertEqual(parse_vnd_price("1 tỷ 250 tr"), 1_250_000_000)
        self.assertEqual(parse_vnd_price("1,15 tỷ"), 1_150_000_000)
        self.assertEqual(parse_vnd_price("2 tỉ 450 triệu"), 2_450_000_000)

    def test_negotiable_is_not_a_number(self):
        self.assertIsNone(parse_vnd_price("Thỏa thuận"))
        self.assertIsNone(parse_vnd_price("Liên hệ"))
        self.assertIsNone(parse_vnd_price(""))


class NormalizerTests(unittest.TestCase):
    """The contract maps must cover the labels the marketplaces actually print."""

    def test_transmission(self):
        self.assertEqual(schema.normalize_transmission("Số tự động"), "Automatic")
        self.assertEqual(schema.normalize_transmission("Số sàn"), "Manual")
        self.assertEqual(schema.normalize_transmission("Bán tự động"), "Other")
        self.assertEqual(schema.normalize_transmission(""), "Unknown")

    def test_fuel_and_origin(self):
        self.assertEqual(schema.normalize_fuel("Xăng"), "Gasoline")
        self.assertEqual(schema.normalize_fuel("Dầu"), "Diesel")
        self.assertEqual(schema.normalize_origin("Trong nước"), "CKD")
        self.assertEqual(schema.normalize_origin("Nhập khẩu"), "CBU")


class ParseYearTextTests(unittest.TestCase):
    def test_first_plausible_year(self):
        self.assertEqual(parse_year_text("Toyota Zace 2003-GL chính chủ"), 2003)
        self.assertEqual(parse_year_text("đời 2015, 1.5 AT"), 2015)
        self.assertEqual(parse_year_text("Honda Civic", "2019"), 2019)

    def test_no_year(self):
        self.assertIsNone(parse_year_text("xe đẹp"))
        self.assertIsNone(parse_year_text(""))


if __name__ == "__main__":
    unittest.main()
