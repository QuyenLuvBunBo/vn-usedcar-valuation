"""Kiểm tra trang chi tiết có ngày đăng / mã tin không (để quyết định có cào thêm)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

HTML = Path("data/raw/recon_detail.html")


def main() -> None:
    text = HTML.read_text(encoding="utf-8")
    tree = html.fromstring(text.encode("utf-8"))

    print("=== JSON-LD blocks ===")
    for i, block in enumerate(tree.xpath('//script[@type="application/ld+json"]/text()')):
        print(f"\n--- block {i} ({len(block)} ký tự) ---")
        print(block.strip()[:900])

    print("\n=== mẫu ngày tháng trong HTML ===")
    dates = re.findall(r"(?:ngày|Ngày)[^<>\n]{0,30}\d{1,2}[/.-]\d{1,2}[/.-]\d{4}", text)
    for d in dates[:10]:
        print("  ", re.sub(r"\s+", " ", d)[:80])
    print("  tổng:", len(dates))

    print("\n=== giờ:phút dd/mm/yyyy ===")
    stamps = re.findall(r"\d{2}:\d{2}\s*\d{1,2}[/-]\d{1,2}[/-]\d{4}", text)
    for s in set(stamps):
        print("  ", s)


if __name__ == "__main__":
    main()
