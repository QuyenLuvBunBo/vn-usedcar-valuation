"""Offline tests for src.sources.carmudi (fixtures are RECONSTRUCTED from the recon of 2026-10-20,
not saved site HTML — re-validate with real `--save-raw` pages)."""
from pathlib import Path
from src.sources.carmudi.crawl import parse_list_page, parse_detail_page, parse_total, item_to_row, unpack
from src.sources.carmudi.unified import build_unified, km_from_description, is_used

F = Path(__file__).parent / "fixtures"
def check(label, got, exp):
    ok = got == exp; print(f"[{'PASS' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f" != {exp!r}")); return ok

res = []
page = F.joinpath("list_page.html").read_text(encoding="utf-8")
cards = parse_list_page(page)
res += [check("total", parse_total(page), 807), check("cards", len(cards), 3),
        check("id", cards[0]["id"], "543369"), check("title", cards[0]["title"], "Toyota Yaris 1.3G 2010"),
        check("km_text", cards[0]["km_text"], "Xe mới"), check("price", cards[1]["price_text"], "8 tỷ 590 triệu"),
        check("province", cards[2]["province"], "Hồ Chí Minh - Quận 7")]
det = parse_detail_page(F.joinpath("detail_yaris.html").read_text(encoding="utf-8"), cards[0]["url"])
res += [check("posted", det["d_posted"], "2026-10-20"), check("brand", det["d_brand"], "Toyota"),
        check("body", det["d_body"], "Coupe"), check("desc km", km_from_description(det["d_description"]), 165000)]
rows, dropped = build_unified(cards, {det["url"]: det})
by = {r["listing_id"]: r for r in rows}
res += [check("new 2026 dropped", dropped["new_car"], 1), check("kept", len(rows), 2),
        check("Yaris kept as used (2010)", "CAR_543369" in by, True),
        check("Yaris km from description", by["CAR_543369"]["mileage_km"], 165000.0),
        check("Yaris AT from description (field says MT)", by["CAR_543369"]["transmission"], "Automatic"),
        check("10,000,000 km -> null", by["CAR_543366"]["mileage_km"], None),
        check("Everest 2024 w/o km kept (year<2025)", "CAR_543366" in by, True),
        check("card gearbox 'Tự động' -> Automatic (validator bug)", by["CAR_543366"]["transmission"], "Automatic"),
        check("province normalized", by["CAR_543366"]["location_province"], "TP. Hồ Chí Minh"),
        check("is_used 2026 no km", is_used(2026, None, "Xe mới"), False)]
# JSON API: only id / name / slug / brandName are verified keys; the rest must not crash when absent
api = {"success": True, "data": {"data": {"data": [{"id": 543338, "name": "Kia Sedona 2.2 DAT 2018", "slug": "ban-xe-oto-kia-sedona-543338/", "brandName": "KIA", "mileage": 27000.0, "price": {"name": "800 triệu"}}, {"id": 1, "name": "x"}], "meta": {"current_page": 2, "last_page": 41}}}}
items, last = unpack(api); r0, r1 = item_to_row(items[0]), item_to_row(items[1])
res += [check("api last_page", last, 41), check("api url", r0["url"], "https://www.carmudi.vn/ban-xe-oto-kia-sedona-543338/"),
        check("api brand", r0["brand"], "KIA"), check("api float km -> '27000'", r0["km_text"], "27000"),
        check("api nested price", r0["price_text"], "800 triệu"), check("api missing keys -> ''", r1["price_text"], "")]
rows2, _ = build_unified([r0], {})
res += [check("api row -> unified", (rows2[0]["manufacture_year"], rows2[0]["price_vnd"], rows2[0]["mileage_km"]), (2018, 800_000_000, 27000.0))]
print(f"{sum(res)}/{len(res)} passed"); raise SystemExit(0 if all(res) else 1)
