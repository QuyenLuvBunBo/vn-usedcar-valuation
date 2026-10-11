"""Đối chiếu marker 'còn bán' với độ mới lastmod: dấu hiệu Trả giá có đáng tin không?

Chạy: python -m tools.onsale_vs_recency
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOG = "logs/_onsale40.txt"
CACHE = "data/raw/sitemap_lastmod.json"


def main() -> None:
    with open(CACHE, encoding="utf-8") as fh:
        mapping = json.load(fh)
    newest = datetime.fromisoformat(max(mapping.values()))

    text = open(LOG, encoding="utf-8", errors="replace").read()
    # log bị redirect qua PowerShell có thể bị double-encode -> chỉ dựa vào phần ASCII
    pairs = re.findall(r"marker=(\w+)[^|]*\| (\d+) \| (\S+)", text)
    if not pairs:
        pairs = re.findall(r"n b\S*=(\w+)[^|]*\| (\d+) \| (\S+)", text)
    pairs = [(v, u) for v, _id, u in pairs]
    print(f"Đọc được {len(pairs)} mẫu từ {LOG}\n")

    table = {"True": Counter(), "False": Counter()}
    for verdict, url in pairs:
        lm = mapping.get(url)
        if not lm:
            print("  (không có lastmod trong cache):", url[:80])
            continue
        age = (newest - datetime.fromisoformat(lm)).days
        bucket = "0-7 ngày" if age <= 7 else "8-30 ngày" if age <= 30 else \
            "31-90 ngày" if age <= 90 else "91-365 ngày" if age <= 365 else ">365 ngày"
        table[verdict][bucket] += 1

    print(f"{'verdict':10s} " + " ".join(f"{b:>12s}" for b in
          ("0-7 ngày", "8-30 ngày", "31-90 ngày", "91-365 ngày")))
    for verdict in ("True", "False"):
        row = table[verdict]
        print(f"{verdict:10s} " + " ".join(f"{row.get(b, 0):12d}" for b in
              ("0-7 ngày", "8-30 ngày", "31-90 ngày", "91-365 ngày")))

    # đối chiếu: tin TRONG listing của chúng ta có lastmod thế nào
    import sqlite3
    conn = sqlite3.connect("data/scraped.db")
    listed = [r[0] for r in conn.execute("SELECT url FROM oto_cars")]
    conn.close()
    buckets = Counter()
    for url in listed:
        lm = mapping.get(url)
        if not lm:
            continue
        age = (newest - datetime.fromisoformat(lm)).days
        buckets["0-7 ngày" if age <= 7 else "8-30 ngày" if age <= 30 else
                "31-90 ngày" if age <= 90 else "91-365 ngày" if age <= 365 else ">365 ngày"] += 1
    print("\nTin ĐANG TRONG LISTING (2.706 tin đã cào) theo độ mới lastmod:")
    for b in ("0-7 ngày", "8-30 ngày", "31-90 ngày", "91-365 ngày", ">365 ngày"):
        print(f"  {b:12s} {buckets.get(b, 0):6,}")


if __name__ == "__main__":
    main()
