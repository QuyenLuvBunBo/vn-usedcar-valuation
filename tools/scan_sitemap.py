"""Scan the downloaded sitemap-detail: count the real USED-CAR listings per brand.

Run: python -m tools.scan_sitemap
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
    print(f"Total URLs in the sitemap cache: {len(urls):,}")

    kinds = Counter()
    suffixes = Counter()
    brand_urls: Counter = Counter()
    detail_urls: list[str] = []

    for url in urls:
        path = url.replace("https://oto.com.vn", "")
        parts = path.strip("/").split("/")
        if len(parts) == 1:  # category page: /mua-ban-xe-toyota
            kinds["category page"] += 1
            continue
        kinds["listing detail page"] += 1
        detail_urls.append(url)

        m = DETAIL_RE.search(url)
        if not m:
            kinds["other"] += 1
            continue
        slug = m.group("slug")
        # drop the province/city suffix (brand = first token)
        brand_urls[slug.split("-")[0]] += 1

        tail = m.group("tail")
        found = re.search(r"-aid(?P<code>[a-z]*)(?P<id>\d+)$", tail)
        suffixes[found.group("code") if found else "(no aid suffix)"] += 1

    print("\n### URL kinds")
    for k, v in kinds.most_common():
        print(f"  {k:22s} {v:7,}")

    print("\n### Id suffix in the URL (aidxc = used car?)")
    for k, v in suffixes.most_common(10):
        print(f"  aid{k!r}: {v:7,}")

    print("\n### Listings per brand (top 25) — first token of the slug")
    for k, v in brand_urls.most_common(25):
        print(f"  {k:16s} {v:6,}")
    print(f"  ... total brands: {len(brand_urls)}")

    # compare with the data we crawled
    conn = sqlite3.connect("data/scraped.db")
    ours = {r[0]: r[1] for r in conn.execute(
        "SELECT lower(brand), COUNT(*) FROM oto_cars GROUP BY lower(brand)")}
    print("\n### Comparison for the six crawled brands")
    tot_ours = tot_sitemap = 0
    for brand, n in sorted(ours.items()):
        s = brand_urls.get(brand, 0)
        tot_ours += n
        tot_sitemap += s
        print(f"  {brand:12s} crawled {n:5,} | sitemap {s:5,}")
    print(f"  six brands: crawled {tot_ours:,} | sitemap {tot_sitemap:,}")

    remaining = len(detail_urls) - tot_sitemap
    print(f"\n### Detail pages in the sitemap: {len(detail_urls):,}")
    print(f"    minus the six crawled brands -> remaining: {remaining:,}")
    print(f"    (Phương crawled ~2,200)      -> difference: {remaining - 2200:,}")
    conn.close()


if __name__ == "__main__":
    main()
