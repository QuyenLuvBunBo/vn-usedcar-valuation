"""Kiểm tra: URL trong sitemap nhưng KHÔNG có trong dữ liệu đã cào còn truy cập được không?

Chạy: python -m tools.check_sitemap_live [so_mau]
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src import storage  # noqa: E402
from src.http_client import ScraperSession  # noqa: E402
from src.oto_scraper import parse_detail_page  # noqa: E402

CACHE = "data/raw/sitemap_lastmod.json"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    with open(CACHE, encoding="utf-8") as fh:
        sitemap_urls = list(json.load(fh).keys())

    conn = sqlite3.connect("data/scraped.db")
    ours = {r[0] for r in conn.execute("SELECT url FROM oto_cars")}
    conn.close()

    extra = [u for u in sitemap_urls if u not in ours]
    print(f"Sitemap: {len(sitemap_urls):,} URL | đã cào: {len(ours):,} | chưa cào: {len(extra):,}")
    sample = random.Random(42).sample(extra, min(n, len(extra)))

    live = dead = sold = with_price = 0
    with ScraperSession(delay=1.5) as session:
        for url in sample:
            resp = session.get(url)
            if resp is None:
                dead += 1
                print(f"  [LỖI ] {url[:95]}")
                continue
            ok = resp.status_code == 200 and "/NotFound" not in resp.url
            if not ok:
                dead += 1
                print(f"  [{resp.status_code}] redirect={resp.url[:60]} | {url[:80]}")
                continue
            live += 1
            detail = parse_detail_page(resp.text, url)
            # tin đã bán: site gỡ nút "Gọi ngay" nên không còn data-phone
            has_phone = "data-phone" in resp.text
            if not has_phone:
                sold += 1
            if detail["d_price_vnd"]:
                with_price += 1
            tag = "CÒN BÁN" if has_phone else "đã bán"
            print(f"  [200-{tag}] {detail['d_title']!r} | giá={detail['d_price_vnd']} | "
                  f"seats={detail['d_seats']} | ảnh={detail['d_image_count']} | {url[:65]}")
    print(f"\nKết quả: 200={live}/{len(sample)} | lỗi/404={dead} | "
          f"còn bán={live - sold} | đã bán={sold} | có giá={with_price}")


if __name__ == "__main__":
    main()
