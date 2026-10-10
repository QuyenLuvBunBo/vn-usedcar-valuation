"""Thống kê đa dạng dữ liệu của 6 hãng: định dạng giá, tag, độ phủ field.

Chạy: python -m tools.field_stats [so_trang_moi_hang]
"""

from __future__ import annotations

import re
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.http_client import ScraperSession  # noqa: E402

BRANDS = ["toyota", "hyundai", "kia", "mazda", "honda", "mitsubishi"]
ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'


def main() -> None:
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 2

    prices: Counter = Counter()
    tags: Counter = Counter()
    calls: list[str] = []
    coverage: Counter = Counter()
    totals: dict[str, int] = {}
    total_items = 0

    with ScraperSession(delay=1.0) as session:
        for brand in BRANDS:
            base = f"https://oto.com.vn/mua-ban-xe-{brand}"
            print(f"\n===== {brand} =====")
            for page in range(1, pages + 1):
                url = base if page == 1 else f"{base}/p{page}"
                text = session.get_text(url)
                if text is None:
                    print(f"  p{page}: KHÔNG lấy được")
                    continue
                tree = html.fromstring(text)
                items = tree.xpath(ITEM_XPATH)
                total_items += len(items)

                if page == 1:
                    body = re.sub(r"\s+", " ", tree.text_content())
                    m = re.search(r"C[oó]\s*([\d\.]+)\s*tin", body)
                    totals[brand] = int(m.group(1).replace(".", "")) if m else -1
                print(f"  p{page}: {len(items)} tin | tổng hãng = {totals.get(brand)}")

                for it in items:
                    for tag in it.xpath('.//ul[@class="tag-list"]/li//text()'):
                        if tag.strip():
                            tags[tag.strip()] += 1
                    p = " ".join(t.strip() for t in it.xpath('.//p[@class="price"]//text()') if t.strip())
                    prices[p] += 1

                    checks = {
                        "car-name": it.xpath('.//span[@class="car-name"]'),
                        "href": it.xpath('.//h3/a/@href'),
                        "price": it.xpath('.//p[@class="price"]//text()'),
                        "img": it.xpath('.//img[@class="lozad"]/@data-src'),
                        "seller-name": it.xpath('.//li[@class="seller-name"]//span[@class="txt"]//text()'),
                        "seller-location": it.xpath('.//li[@class="seller-location"]//text()'),
                        "phone": it.xpath('.//a[contains(@class,"btn-tel")]/@data-phone'),
                        "data-call": it.xpath('.//a[contains(@class,"btn-tel")]/@data-call'),
                        "data-tinrao": [it.get("data-tinrao")],
                        "data-listtype": [it.get("data-listtype")],
                    }
                    for key, val in checks.items():
                        if any(str(v).strip() for v in val if v is not None):
                            coverage[key] += 1
                    if len(calls) < 25 and it.get("data-autoid"):
                        dc = it.xpath('.//a[contains(@class,"btn-tel")]/@data-call')
                        if dc:
                            calls.append(f"{it.get('data-tinrao')}   ||   {dc[0]}")

    print("\n\n############ TỔNG SỐ TIN THEO HÃNG ############")
    for b, n in totals.items():
        print(f"  {b:12s} {n:5d} tin -> ~{(n + 14) // 15} trang")

    print("\n############ ĐỘ PHỦ FIELD ############")
    for k, v in coverage.most_common():
        print(f"  {k:18s} {v}/{total_items} = {v / total_items * 100:.1f}%")

    print("\n############ ĐỊNH DẠNG GIÁ (top 30) ############")
    for p, n in prices.most_common(30):
        print(f"  [{n:4d}x] {p!r}")

    print("\n############ TAG-LIST (top 40) ############")
    for t, n in tags.most_common(40):
        print(f"  [{n:4d}x] {t!r}")

    print("\n############ MẪU data-tinrao || data-call ############")
    for c in calls:
        print("  ", c)


if __name__ == "__main__":
    main()
