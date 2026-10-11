"""Thử các dạng URL phân trang để xem server có hỗ trợ không.

Chạy: python -m tools.test_paging_urls
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.common.http_client import ScraperSession  # noqa: E402

BASE = "https://oto.com.vn/mua-ban-xe-toyota"
CANDIDATES = [
    BASE,
    f"{BASE}?page=2",
    f"{BASE}/trang-2",
    f"{BASE}?p=2",
    f"{BASE}?trang=2",
    f"{BASE}/p2",
    f"{BASE}?pageIndex=2",
]

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'


def main() -> None:
    with ScraperSession(delay=1.0) as session:
        for url in CANDIDATES:
            text = session.get_text(url)
            if text is None:
                print(f"{url}\n    -> KHÔNG lấy được")
                continue
            tree = html.fromstring(text)
            items = tree.xpath(ITEM_XPATH)
            ids = [i.get("data-autoid") for i in items]
            first_title = ""
            if items:
                names = items[0].xpath('.//span[@class="car-name"]/text()')
                first_title = names[0].strip()[:60] if names else ""
            print(f"{url}\n    -> {len(items)} tin | ids[:3]={ids[:3]} | tin1={first_title!r}")


if __name__ == "__main__":
    main()
