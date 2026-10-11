"""So sánh: số URL sitemap theo HÃNG vs độ mới lastmod vs số tin listing thực tế.

Chạy: python -m tools.lastmod_recency
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CACHE = "data/raw/sitemap_lastmod.json"
SIX = {"toyota", "hyundai", "kia", "mazda", "honda", "mitsubishi"}


def brand_of(url: str) -> str:
    """Token đầu sau /mua-ban-xe- (đủ tốt cho các hãng phổ biến)."""
    m = re.search(r"/mua-ban-xe-([a-z0-9]+)", url)
    return m.group(1) if m else "?"


def main() -> None:
    with open(CACHE, encoding="utf-8") as fh:
        mapping = json.load(fh)

    newest = max(mapping.values())
    newest_dt = datetime.fromisoformat(newest)
    print(f"lastmod mới nhất: {newest}")

    brands: dict[str, list[str]] = {}
    for url, lm in mapping.items():
        brands.setdefault(brand_of(url), []).append(lm)

    conn = sqlite3.connect("data/scraped.db")
    listed = {r[0]: r[1] for r in conn.execute(
        "SELECT lower(brand), COUNT(*) FROM oto_cars GROUP BY lower(brand)")}
    conn.close()

    print(f"\n{'hãng':14s} {'sitemap':>8s} {'≤7 ngày':>8s} {'≤30 ngày':>9s} "
          f"{'≤90 ngày':>9s} {'≤365 ngày':>10s} {'listing':>8s}")
    print("-" * 74)
    for brand in sorted(brands, key=lambda b: -len(brands[b]))[:12]:
        times = sorted(brands[brand], reverse=True)
        row = [sum(1 for t in times if datetime.fromisoformat(t) >= newest_dt - timedelta(days=d))
               for d in (7, 30, 90, 365)]
        print(f"{brand:14s} {len(times):8,} {row[0]:8,} {row[1]:9,} {row[2]:9,} {row[3]:10,} "
              f"{listed.get(brand, 0):8,}")

    total = sum(len(v) for v in brands.values())
    six_sitemap = sum(len(brands.get(b, [])) for b in SIX)
    six_listed = sum(listed.get(b, 0) for b in SIX)
    print("-" * 74)
    print(f"{'TỔNG':14s} {total:8,}")
    print(f"{'6 hãng':14s} sitemap {six_sitemap:,} | listing đã cào {six_listed:,}")

    # phân bố độ mới toàn bộ
    days = Counter()
    for lm in mapping.values():
        delta = (newest_dt - datetime.fromisoformat(lm)).days
        bucket = "0-7 ngày" if delta <= 7 else "8-30 ngày" if delta <= 30 else \
            "31-90 ngày" if delta <= 90 else "91-365 ngày" if delta <= 365 else ">365 ngày"
        days[bucket] += 1
    print("\nToàn bộ sitemap theo độ mới của lastmod:")
    for k in ("0-7 ngày", "8-30 ngày", "31-90 ngày", "91-365 ngày", ">365 ngày"):
        print(f"  {k:12s} {days[k]:7,}")


if __name__ == "__main__":
    main()
