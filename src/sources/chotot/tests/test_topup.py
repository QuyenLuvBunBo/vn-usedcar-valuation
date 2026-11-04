"""Offline tests for src.sources.chotot.topup — no network, no live site.

The properties that matter: the queue never accepts a URL outside the source scope, a member id is
never queued twice, and the budget policy prefers listing fetches over endless enumeration.

Run: python -m unittest discover -s src/sources/chotot/tests -v
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.sources.chotot.topup import (FIELDS, QUEUE, TABLE, _next_pending, api_row_to_contract,
                                      enqueue, init, kind_of, known_ids, seed_urls)


class KindTests(unittest.TestCase):

    def test_a_listing_url_ends_with_an_id(self):
        self.assertEqual(kind_of("https://xe.chotot.com/mua-ban-oto-quan-7-tp-hcm/135556592.htm"),
                         "detail")
        self.assertEqual(kind_of("https://xe.chotot.com/mua-ban-oto"), "index")
        self.assertEqual(kind_of("https://xe.chotot.com/mua-ban-oto-toyota"), "index")


class KnownIdTests(unittest.TestCase):

    def test_ids_come_from_the_listing_id_column(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "chotot_mua_ban_oto.csv"
            path.write_text("listing_id,source_platform\nCHOTOT_135556592,chotot\n"
                            "CHOTOT_135556593,chotot\n", encoding="utf-8-sig")
            self.assertEqual(known_ids(Path(folder)), {"135556592", "135556593"})

    def test_a_missing_file_is_not_an_error(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(known_ids(Path(folder)), set())


class ApiContractTests(unittest.TestCase):
    """The API export is a 24-column working file; the team contract is 21 columns."""

    def test_a_row_is_mapped_and_cleaned(self):
        row = api_row_to_contract({
            "list_id": "135560359", "url": "https://xe.chotot.com/135560359.htm",
            "brand": "Mitsubishi", "model": "Xpander", "trim": "", "year": "2025",
            "body_type": "Minivan (MPV)", "transmission": "Tự động", "fuel": "Xăng",
            "seats": "7", "odo_km": "27.000", "origin": "Nước khác",
            "price_vnd": "515000000", "location": "Phường Hòa Minh, Quận Liên Chiểu, Đà Nẵng",
            "posted_at_utc": "2026-10-30T12:50:08+00:00",
            "scraped_at_utc": "2026-10-30T17:47:35+00:00",
        })
        self.assertEqual(row["listing_id"], "CHOTOT_135560359")
        self.assertEqual(row["source_platform"], "chotot")
        self.assertEqual(row["body_type"], "MPV")
        self.assertEqual(row["transmission"], "Automatic")
        self.assertEqual(row["fuel_type"], "Gasoline")
        self.assertEqual(row["origin"], "CBU")              # "Nước khác" = not domestic
        self.assertEqual(row["mileage_km"], 27000.0)        # "27.000" is thousands, not a decimal
        self.assertEqual(row["location_province"], "Đà Nẵng")
        self.assertEqual(row["listing_date"], "2026-10-30")
        self.assertEqual(row["price_status"], "full")
        self.assertEqual(set(row), set(FIELDS))

    def test_a_monthly_payment_price_stays_a_number(self):
        # 5.15 million for a 2025 car is an instalment, not a price: the cohort rules exclude it later
        row = api_row_to_contract({"list_id": "1", "price_vnd": "5150000", "year": "2025"})
        self.assertEqual(row["price_vnd"], 5_150_000)


class SeedApiTests(unittest.TestCase):
    """The listing API answers with both `ad_id` and `list_id`; only `list_id` opens a detail page.

    Regression: the first version stored `ad_id`, and every detail request then returned 404.
    """

    def test_the_queue_gets_the_listing_id_not_the_ad_id(self):
        from src.sources.chotot import topup as module

        payload = {"total": 1, "ads": [{"ad_id": 178024538, "list_id": 134050772, "subject": "X"}]}
        original = module._api_get
        module._api_get = lambda session, params, rps: payload
        try:
            with TemporaryDirectory() as folder:
                result = module.seed_api(Path(folder), rps=1000, max_cells=2)
                written = (Path(folder) / "listings.jsonl").read_text(encoding="utf-8")
        finally:
            module._api_get = original
        ids = [json.loads(line)["list_id"] for line in written.splitlines() if line.strip()]
        self.assertEqual(ids, ["134050772"])
        self.assertEqual(result["new_ids"], 1)


class QueueTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        init(self.db)

    def tearDown(self):
        self.db.close()

    def test_a_url_outside_the_source_is_refused(self):
        self.assertFalse(enqueue(self.db, "https://www.carmudi.vn/ban-xe-oto-kia-1/"))
        self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {QUEUE}").fetchone()[0], 0)

    def test_the_same_url_is_queued_once(self):
        url = "https://xe.chotot.com/mua-ban-oto-quan-7-tp-hcm/135556592.htm"
        self.assertTrue(enqueue(self.db, url))
        self.assertTrue(enqueue(self.db, url))
        self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {QUEUE}").fetchone()[0], 1)

    def test_the_budget_policy_can_prefer_listings_over_index_pages(self):
        index = "https://xe.chotot.com/mua-ban-oto"
        detail = "https://xe.chotot.com/mua-ban-oto-quan-7-tp-hcm/135556592.htm"
        enqueue(self.db, index)
        enqueue(self.db, detail)
        self.assertEqual(_next_pending(self.db, prefer_detail=True)[1], "detail")
        self.assertEqual(_next_pending(self.db, prefer_detail=False)[1], "index")

    def test_seeds_are_unique_and_in_scope(self):
        seeds = seed_urls()
        self.assertEqual(len(seeds), len(set(seeds)))
        self.assertTrue(all(seed.startswith("https://xe.chotot.com/mua-ban-oto") for seed in seeds))
        self.assertGreater(len(seeds), 20)          # national + provinces + district/brand pages


if __name__ == "__main__":
    unittest.main()
