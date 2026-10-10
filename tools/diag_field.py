"""Tra cứu field của 1 tin trong file HTML thô (offline) theo data-autoid.

Chạy: python -m tools.diag_field <file.html> <data-autoid> [<data-autoid> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.oto_scraper import ITEM_XPATH, parse_item  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1])
    ids = set(sys.argv[2:])
    if not ids:
        print("Cần ít nhất 1 data-autoid")
        return

    text = path.read_text(encoding="utf-8")
    tree = html.fromstring(text.encode("utf-8"))

    for item in tree.xpath(ITEM_XPATH):
        if item.get("data-autoid") not in ids:
            continue
        print("=" * 70)
        print(f"id={item.get('data-autoid')}  class={item.get('class')!r}")
        print(f"data-tinrao = {item.get('data-tinrao')!r}")
        print(f"data-call   = {item.xpath('.//a[contains(@class,\"btn-tel\")]/@data-call')}")
        print(f"price  raw  = {[t.strip() for t in item.xpath('.//p[@class=\"price\"]//text()') if t.strip()]}")
        print(f"tag-list    = {[t.strip() for t in item.xpath('.//ul[@class=\"tag-list\"]/li//text()') if t.strip()]}")
        print(f"car-name    = {item.xpath('.//span[@class=\"car-name\"]/text()')}")
        print("\n-- parse_item() --")
        record = parse_item(item, str(path))
        for key, value in record.items():
            print(f"   {key:13s} = {value!r}")


if __name__ == "__main__":
    main()
