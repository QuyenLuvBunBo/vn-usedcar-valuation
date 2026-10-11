"""Scan sitemap-detail đã tải: đếm tin XE CŨ thật sự, theo hãng.

Chạy: python -m tools.scan_sitemap
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CACHE = "data/raw/sitemap_lastmod.json"
# .../mua-ban-xe-<brand>-<model>-<tinh>/<slug>-aidxc<id>
DETAIL_RE = re.compile(r"/mua-ban-xe-(?P<slug>[^/]+)/(?P<tail>[^?]*)$")


def main() -> None:
    with open(CACHE, encoding="utf-8") as fh:
        urls = list(json.load(fh).keys())
    print(f"Tổng URL trong cache sitemap: {len(urls):,}")

    kinds = Counter()
    suffixes = Counter()
    brand_urls: Counter = Counter()
    detail_urls: list[str] = []

    for url in urls:
        path = url.replace("https://oto.com.vn", "")
        parts = path.strip("/").split("/")
        if len(parts) == 1:  # trang danh mục: /mua-ban-xe-toyota
            kinds["trang danh mục"] += 1
            continue
        kinds["trang chi tiết tin"] += 1
        detail_urls.append(url)

        m = DETAIL_RE.search(url)
        if not m:
            kinds["khác"] += 1
            continue
        slug = m.group("slug")
        # bỏ hậu tố tỉnh/thành (2 từ cuối viết thường, vd -ha-noi, -hcm)
        brand_urls[slug.split("-")[0]] += 1

        tail = m.group("tail")
        found = re.search(r"-aid(?P<code>[a-z]*)(?P<id>\d+)$", tail)
        suffixes[found.group("code") if found else "(không có aid)"] += 1

    print("\n### Loại URL")
    for k, v in kinds.most_common():
        print(f"  {k:22s} {v:7,}")

    print("\n### Hậu tố id trong URL (aidxc = xe cũ?)")
    for k, v in suffixes.most_common(10):
        print(f"  aid{k!r}: {v:7,}")

    print("\n### Số tin theo hãng (top 25) — lấy token đầu của slug")
    for k, v in brand_urls.most_common(25):
        print(f"  {k:16s} {v:6,}")
    print(f"  ... tổng số hãng: {len(brand_urls)}")

    # đối chiếu với dữ liệu đã cào
    conn = sqlite3.connect("data/scraped.db")
    ours = {r[0]: r[1] for r in conn.execute(
        "SELECT lower(brand), COUNT(*) FROM oto_cars GROUP BY lower(brand)")}
    print("\n### Đối chiếu 6 hãng đã cào")
    tot_ours = tot_sitemap = 0
    for brand, n in sorted(ours.items()):
        s = brand_urls.get(brand, 0)
        tot_ours += n
        tot_sitemap += s
        print(f"  {brand:12s} đã cào {n:5,} | sitemap {s:5,}")
    print(f"  6 hãng: đã cào {tot_ours:,} | sitemap {tot_sitemap:,}")

    remaining = len(detail_urls) - tot_sitemap
    print(f"\n### Tin chi tiết trong sitemap: {len(detail_urls):,}")
    print(f"    trừ 6 hãng đã cào            -> còn lại: {remaining:,}")
    print(f"    (bạn Phương cào được ~2.200) -> chênh lệch: {remaining - 2200:,}")
    conn.close()


if __name__ == "__main__":
    main()
