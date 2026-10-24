"""Offline tests for the muaban.net parsers (no network: the fixtures are inline JSON payloads)."""

from __future__ import annotations

import json
import unittest

from src.sources.muaban.crawl import (
    brand_candidates,
    facets,
    parse_detail_page,
    parse_list_page,
    slugify,
)
from src.sources.muaban.unified import (
    _body_type,
    _brand,
    _engine_capacity,
    _is_new_car,
    _model,
    _origin,
    _province,
    _to_row,
    _trim,
    is_excluded,
)

LISTING_ITEM = {
    "id": 71297868,
    "title": "Honda Civic 5 chỗ Xăng Số sàn 106.985 km",
    "price": 185_000_000,
    "price_display": "185 triệu",
    "url": "/o-to/ban-o-to-honda-civic-tp-nha-trang-khanh-hoa/civic-5-cho-id71297868",
    "location": "TP. Nha Trang, Khánh Hòa",
    "publish_at": "2026-10-24T00:00:05.895184+07:00",
    "is_company": False,
    "category_name": "Bán Ô tô Civic",
    "covers": ["https://cloud.muaban.net/images/a.jpg"],
}

DETAIL_CLASSIFIED = {
    "id": 71297868,
    "title": "Honda Civic 5 chỗ Xăng Số sàn 106.985 km",
    "body": "Xe nhà dùng <br />chính chủ, bao tess",
    "address": "TP. Nha Trang, Khánh Hòa",
    "price": 185_000_000,
    "price_display": "185 triệu",
    "publish_at": "2026-10-24T00:00:05.895184+07:00",
    "created_at": "2026-10-21T19:12:40.591548+07:00",
    "total_images": 5,
    "contact_name": "NGUYỄN THÀNH CHÍ",
    "is_company": False,
    "parameters": [
        {"label": "Hãng xe", "value": "Honda"},
        {"label": "Dòng xe", "value": "Civic"},
        {"label": "Năm sản xuất", "value": "2007"},
        {"label": "Số km đã đi", "value": "106,985"},
        {"label": "Hộp số", "value": "Số sàn"},
        {"label": "Nhiên liệu", "value": "Xăng"},
        {"label": "Số chỗ", "value": "5"},
        {"label": "Xuất xứ", "value": "Việt nam"},
    ],
}


def page(payload: dict) -> str:
    """Build a minimal Next.js page around a props.pageProps payload."""
    data = {"props": {"pageProps": payload}}
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data, ensure_ascii=False) + "</script></body></html>")


class PartitionTests(unittest.TestCase):
    """The category pager stops at ~1,000 ads, so the crawl partitions by brand."""

    def test_slugify(self):
        self.assertEqual(slugify("Mercedes Benz"), "mercedes-benz")
        self.assertEqual(slugify("Vinfast"), "vinfast")
        self.assertEqual(slugify("Các hãng khác"), "cac-hang-khac")
        self.assertEqual(slugify("Peugeot"), "peugeot")

    def test_brand_candidates_fall_back_to_the_first_word(self):
        self.assertEqual(brand_candidates("Mercedes Benz"), ["mercedes-benz", "mercedes"])
        self.assertEqual(brand_candidates("Honda"), ["honda"])
        self.assertEqual(brand_candidates("Land Rover"), ["land-rover", "land"])

    def test_facets_read_brand_names_and_fuels(self):
        html = page({"filterConfig": {"filters": {
            "52": {"items": [{"id": 420, "name": "Honda"}, {"id": 650, "name": "Kia"}]},
            "61": {"items": [{"id": 540, "name": "Xăng"}]},
        }}})
        brands, fuels = facets(html)
        self.assertEqual(brands, ["Honda", "Kia"])
        self.assertEqual([f["id"] for f in fuels], [540])


class ParseListPageTests(unittest.TestCase):
    def test_absolute_url_and_total(self):
        html = page({"classified": {"total": 7500, "items": [LISTING_ITEM]}})
        records, total = parse_list_page(html)
        self.assertEqual(total, 7500)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["url"].startswith("https://muaban.net/o-to/"))
        self.assertEqual(records[0]["price_vnd"], 185_000_000)
        self.assertEqual(records[0]["category_name"], "Bán Ô tô Civic")

    def test_page_without_payload_is_empty(self):
        records, total = parse_list_page("<html>no payload</html>")
        self.assertEqual(records, [])
        self.assertEqual(total, 0)


class ParseDetailPageTests(unittest.TestCase):
    def test_parameters_are_mapped_to_columns(self):
        html = page({"classified": DETAIL_CLASSIFIED})
        row = parse_detail_page(html, "https://muaban.net/x-id71297868")
        self.assertEqual(row["id"], 71297868)
        self.assertEqual(row["brand"], "Honda")
        self.assertEqual(row["model"], "Civic")
        self.assertEqual(row["year"], "2007")
        self.assertEqual(row["km"], "106,985")
        self.assertEqual(row["gearbox"], "Số sàn")
        self.assertEqual(row["seats"], "5")
        self.assertEqual(row["price_vnd"], 185_000_000)
        self.assertIn("chính chủ", row["description"])
        self.assertNotIn("<br", row["description"])

    def test_removed_ad_returns_empty_dict(self):
        self.assertEqual(parse_detail_page(page({}), "https://muaban.net/x-id1"), {})


class UnifiedMappingTests(unittest.TestCase):
    def test_row_lands_in_the_contract(self):
        detail = parse_detail_page(page({"classified": DETAIL_CLASSIFIED}),
                                   "https://m/x-id71297868")
        listing = {"url": "https://m/x-id71297868", "id": 71297868,
                   "title": DETAIL_CLASSIFIED["title"], "price_vnd": 185_000_000,
                   "price_text": "185 triệu", "location": "TP. Nha Trang, Khánh Hòa",
                   "publish_at": "2026-10-24T00:00:05+07:00", "is_company": 0,
                   "scraped_at": "2026-10-24T01:00:00+00:00"}
        row = _to_row(listing, detail)
        self.assertEqual(row["listing_id"], "MUA_71297868")
        self.assertEqual(row["source_platform"], "muaban.net")
        self.assertEqual(row["mileage_km"], 106_985)          # '106,985' -> 106985
        self.assertEqual(row["manufacture_year"], 2007)
        self.assertEqual(row["transmission"], "Manual")        # 'Số sàn'
        self.assertEqual(row["fuel_type"], "Gasoline")         # 'Xăng'
        self.assertEqual(row["origin"], "CKD")                 # 'Việt nam'
        self.assertEqual(row["location_province"], "Khánh Hòa")
        self.assertEqual(row["seats"], 5)
        self.assertEqual(row["seller_type"], "Private Individual")
        self.assertEqual(row["price_status"], "full")

    def test_negotiable_price(self):
        listing = {"url": "https://m/x-id2", "id": 2, "title": "Kia Morning 2012",
                   "price_vnd": 0, "price_text": "Thỏa thuận", "location": "Hà Nội",
                   "publish_at": "2026-10-24T00:00:05+07:00", "is_company": 1}
        row = _to_row(listing, {})
        self.assertIsNone(row["price_vnd"])
        self.assertEqual(row["price_status"], "negotiable")
        self.assertEqual(row["seller_type"], "Dealership/Salon")
        self.assertIsNone(row["mileage_km"])


class HelperTests(unittest.TestCase):
    def test_origin(self):
        self.assertEqual(_origin("Việt nam"), "CKD")
        self.assertEqual(_origin("Nhập khẩu"), "CBU")
        self.assertEqual(_origin("Nhật Bản"), "CBU")
        self.assertEqual(_origin(""), "Unknown")

    def test_province_is_the_last_part(self):
        self.assertEqual(_province("Quận Hà Đông, Hà Nội"), "Hà Nội")
        self.assertEqual(_province("TP. Nha Trang, Khánh Hòa"), "Khánh Hòa")

    def test_body_type_keywords(self):
        self.assertEqual(_body_type("Ford Ranger Wildtrak bán tải 2023"), "Pickup")
        self.assertEqual(_body_type("Hyundai Tucson SUV 2022"), "SUV")
        self.assertEqual(_body_type("Honda Civic 2007"), "Unknown")

    def test_body_type_prefers_the_site_field(self):
        self.assertEqual(_body_type("Xe gia đình", "Sedan"), "Sedan")
        self.assertEqual(_body_type("Xe gia đình", "SUV/Crossover"), "SUV")
        self.assertEqual(_body_type("Xe gia đình", "Pick Up"), "Pickup")
        self.assertEqual(_body_type("Xe gia đình", "Van/Mini Van"), "Van")
        self.assertEqual(_body_type("Xe gia đình", "Không rõ"), "Unknown")

    def test_engine_capacity_ignores_odometer(self):
        self.assertEqual(_engine_capacity("Mazda CX5 2.0 Deluxe 2024"), 2.0)
        self.assertIsNone(_engine_capacity("Honda Civic 106.985 km"))

    def test_trim_after_brand_and_model(self):
        self.assertEqual(_trim("Toyota Vios 1.5G CVT 2019", "Toyota", "Vios"), "1.5G CVT")

    def test_brand_and_model_aliases(self):
        self.assertEqual(_brand("Mercedes Benz"), "Mercedes-Benz")
        self.assertEqual(_brand("Các hãng khác"), "Unknown")
        self.assertEqual(_brand("Xe tải, đầu kéo…"), "Unknown")
        self.assertEqual(_model("CRV"), "CR-V")
        self.assertEqual(_model("Dòng khác"), "Unknown")

    def test_new_car_filter(self):
        self.assertTrue(_is_new_car("Xe mới"))
        self.assertTrue(_is_new_car("xe mới nguyên seal"))
        self.assertFalse(_is_new_car("Đã sử dụng"))
        self.assertFalse(_is_new_car(""))          # unknown -> treated as used

    def test_scope_filter(self):
        self.assertEqual(is_excluded("https://muaban.net/o-to/cho-thue-o-to-quan-1/x-id1"),
                         "not_for_sale")
        self.assertEqual(is_excluded("https://muaban.net/o-to/ban-o-to-xe-tai-dau-keo/x-id2"),
                         "commercial")
        self.assertEqual(is_excluded("https://muaban.net/o-to/ban-o-to-honda-civic/x-id3"), "")


if __name__ == "__main__":
    unittest.main()
