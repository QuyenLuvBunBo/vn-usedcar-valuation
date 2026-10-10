"""Kiểm tra tin 'đã bán' (class sold): tỷ lệ, phân bố theo trang, mất field nào.

Chạy: python -m tools.diag_sold toyota 14 15 16 17
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.http_client import ScraperSession  # noqa: E402

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'


def main() -> None:
    brand = sys.argv[1] if len(sys.argv) > 1 else "toyota"
    pages = [int(p) for p in sys.argv[2:]] or [1, 2, 14, 15, 16, 17]

    with ScraperSession(delay=0.8) as session:
        print(f"{'trang':>6} | {'tin':>4} | {'sold':>4} | {'có btn-tel':>10} | {'có phone':>8} | {'có price':>8}")
        print("-" * 62)
        for page in pages:
            base = f"https://oto.com.vn/mua-ban-xe-{brand}"
            url = base if page == 1 else f"{base}/p{page}"
            text = session.get_text(url)
            if text is None:
                print(f"{page:>6} | KHÔNG lấy được")
                continue
            tree = html.fromstring(text)
            items = tree.xpath(ITEM_XPATH)

            sold = sum(1 for i in items if "sold" in (i.get("class") or "").split())
            tel = sum(1 for i in items if i.xpath('.//a[contains(@class,"btn-tel")]'))
            phone = sum(1 for i in items if i.xpath('.//a[contains(@class,"btn-tel")]/@data-phone'))
            price = sum(1 for i in items if "".join(i.xpath('.//p[@class="price"]//text()')).strip())
            print(f"{page:>6} | {len(items):>4} | {sold:>4} | {tel:>10} | {phone:>8} | {price:>8}")

            # đối chiếu: tin sold có luôn thiếu btn-tel?
            mism = [i.get("data-autoid") for i in items
                    if ("sold" in (i.get("class") or "").split()) != (not i.xpath('.//a[contains(@class,"btn-tel")]'))]
            if mism:
                print(f"        lệch giả thuyết ở các id: {mism[:5]}")


if __name__ == "__main__":
    main()
