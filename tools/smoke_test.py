"""Smoke test offline cho parser oto.com.vn (assert thuần, không cần pytest).

Chạy: python -m tools.smoke_test
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.oto_scraper import (  # noqa: E402
    coerce_numeric,
    dedupe_rows,
    parse_data_call,
    parse_detail_page,
    parse_km,
    parse_list_page,
    parse_price,
    parse_year,
)

PASSED = FAILED = 0


def check(label: str, got, expected) -> None:
    global PASSED, FAILED
    ok = got == expected
    PASSED += ok
    FAILED += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f" != {expected!r}"))


def main() -> int:
    print("### parse_price")
    check("335 triệu", parse_price("335 triệu"), 335_000_000)
    check("1 tỷ 045 triệu", parse_price("1 tỷ 045 triệu"), 1_045_000_000)
    check("1 tỉ 450 triệu (site ghi 'tỉ')", parse_price("1 tỉ 450 triệu"), 1_450_000_000)
    check("2 tỷ 439 triệu", parse_price("2 tỷ 439 triệu"), 2_439_000_000)
    check("1,2 tỷ", parse_price("1,2 tỷ"), 1_200_000_000)
    check("rỗng -> None", parse_price(""), None)
    check("Thỏa thuận -> None", parse_price("Thỏa thuận"), None)

    print("\n### parse_km / parse_year")
    check("140.000 km", parse_km("140.000 km"), 140_000)
    check("01 km", parse_km("01 km"), 1)
    check("12.000.000 km", parse_km("12.000.000 km"), 12_000_000)
    check("không có km", parse_km(""), None)
    check("2014 - Toyota", parse_year("2014 - Toyota Corolla Altis"), 2014)
    check("không có năm", parse_year("Toyota Corolla"), None)

    print("\n### parse_data_call")
    good = ("Toyota.Corolla Altis.Xe cũ.Trong nước.2014.335 triệu.Sedan.Màu khác.F0.V5.23444795.")
    info = parse_data_call(good)
    check("brand", info.get("brand"), "Toyota")
    check("model", info.get("model"), "Corolla Altis")
    check("origin", info.get("origin"), "Trong nước")
    check("year", info.get("year"), "2014")
    check("price", info.get("price_text"), "335 triệu")
    check("body_type", info.get("body_type"), "Sedan")
    check("listing_type", info.get("listing_type"), "F0")
    check("id", info.get("id"), "23444795")
    check("rỗng -> {}", parse_data_call(""), {})
    check("sai năm -> {}", parse_data_call("X.Y.Z.Trong nước.20..A.B.F0.V0.1."), {})
    check("sai xuất xứ -> {}", parse_data_call("X.Y.Z.Không rõ.2014.1 triệu.A.B.F0.V0.1."), {})

    print("\n### dedupe_rows / coerce_numeric")
    rows = [{"url": "a", "id": "1"}, {"url": "a", "id": "1"}, {"url": "b", "id": "2"}]
    check("loại trùng url", len(dedupe_rows(rows)), 2)
    coerced = coerce_numeric([{"year": "2014", "price_vnd": "335000000", "km": "", "sold": "1"}])
    check("year int", coerced[0]["year"], 2014)
    check("price int", coerced[0]["price_vnd"], 335_000_000)
    check("km rỗng -> None", coerced[0]["km"], None)
    check("sold int", coerced[0]["sold"], 1)

    print("\n### parse_list_page trên HTML thô")
    samples = {
        "data/raw/recon_brand.html": (15, 0),          # tin đang bán
        "data/raw/diag_23442802.html": (15, 14),       # trang có nhiều tin đã bán
    }
    for path, (n_items, n_sold) in samples.items():
        p = Path(path)
        if not p.exists():
            print(f"  [SKIP] {path} không tồn tại")
            continue
        records = parse_list_page(p.read_text(encoding="utf-8"), p.name)
        check(f"{p.name} số record", len(records), n_items)
        check(f"{p.name} số tin đã bán", sum(r["sold"] for r in records), n_sold)
        check(f"{p.name} lọc --exclude-sold", len([r for r in records if not r["sold"]]), n_items - n_sold)
        check(f"{p.name} url tuyệt đối", all(r["url"].startswith("https://oto.com.vn/") for r in records), True)

    print("\n### parse_detail_page (trang chi tiết)")
    detail_path = Path("data/raw/recon_detail2.html")
    if detail_path.exists():
        detail = parse_detail_page(detail_path.read_text(encoding="utf-8"), "https://oto.com.vn/x")
        check("d_title", detail["d_title"], "Honda CR-V 1.5 G 2021")
        check("d_price_vnd", detail["d_price_vnd"], 745_000_000)
        check("d_price_text", detail["d_price_text"], "745 triệu")
        check("d_color", detail["d_color"], "Đỏ")
        check("d_seats", detail["d_seats"], 5)
        check("d_city_code", detail["d_city_code"], "SG")
        check("d_make_id", detail["d_make_id"], 28)
        check("d_model_id", detail["d_model_id"], 541)
        check("d_seller_id", detail["d_seller_id"], 21004)
        check("d_image_count", detail["d_image_count"], 22)
        check("d_seller_name", detail["d_seller_name"], "Auto 9X")
        check("d_seller_url", detail["d_seller_url"], "https://auto9x.oto.com.vn")
        check("có địa chỉ salon", detail["d_seller_address"].startswith("792 "), True)
        check("có mô tả", len(detail["d_description"]) > 20, True)
        check("d_image_1 là ảnh crop", "/crop/640x480/" in detail["d_image_1"], True)
        specs = json.loads(detail["d_specs"] or "{}")
        check("specs có 8 mục", len(specs), 8)
        check("specs Năm SX", specs.get("Năm SX"), "2021")
        check("specs Tình trạng", specs.get("Tình trạng"), "Xe cũ")
        check("specs Km đã đi", specs.get("Km đã đi"), "30.000 km")
    else:
        print("  [SKIP] data/raw/recon_detail2.html không tồn tại")

    print(f"\n{'=' * 40}\nPASS {PASSED} | FAIL {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
