"""Chẩn đoán các tin bị parse_data_call từ chối: in data-call thô của chúng.

Chạy: python -m tools.diag_data_call
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.sources.oto.crawl import ITEM_XPATH, parse_data_call  # noqa: E402


def main() -> None:
    files = sorted(Path("data/raw").glob("oto_*_p*.html"))
    if not files:
        print("Chưa có file data/raw/oto_*_p*.html — chạy scraper với --save-raw trước.")
        return

    total = ok = 0
    fails = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        tree = html.fromstring(text.encode("utf-8"))
        for item in tree.xpath(ITEM_XPATH):
            total += 1
            dc = item.xpath('.//a[contains(@class,"btn-tel")]/@data-call')
            dc = dc[0] if dc else ""
            if parse_data_call(dc):
                ok += 1
            else:
                fails.append((path.name, dc))

    print(f"Tổng {total} tin | parse OK {ok} | FAIL {len(fails)} "
          f"({len(fails) / total * 100:.1f}%)\n")

    print("### Số field (đếm theo dấu '.') của các tin FAIL")
    counts = Counter(len(dc.split(".")) for _, dc in fails)
    for n, c in counts.most_common():
        print(f"  {n} phần: {c} tin")

    print("\n### 15 tin FAIL đầu tiên")
    for name, dc in fails[:15]:
        parts = dc.split(".")
        print(f"\n  [{name}] len(parts)={len(parts)}")
        print(f"    raw: {dc}")
        for i, p in enumerate(parts):
            print(f"      [{i:2d}] {p!r}")


if __name__ == "__main__":
    main()
