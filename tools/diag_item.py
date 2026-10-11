"""In HTML thô của 1 tin theo id để soi khác biệt cấu trúc (vd tin không có btn-tel).

Chạy: python -m tools.diag_item <url_trang_listing> <data-autoid>
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.common import storage  # noqa: E402
from src.common.http_client import ScraperSession  # noqa: E402

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'


def main() -> None:
    url, target = sys.argv[1], sys.argv[2]
    with ScraperSession(delay=0.5) as session:
        text = session.get_text(url)
    if text is None:
        print("không lấy được", url)
        return
    storage.save_raw(text, f"diag_{target}")

    tree = html.fromstring(text)
    items = [i for i in tree.xpath(ITEM_XPATH) if i.get("data-autoid") == target]
    print(f"Tìm thấy {len(items)} tin có data-autoid={target}\n")
    if not items:
        return

    item = items[0]
    print("=== TOÀN BỘ <a> trong tin (class, data-*, text) ===")
    for a in item.xpath(".//a"):
        attrs = {k: v for k, v in a.attrib.items() if k.startswith("data-")}
        print(f"  class={a.get('class')!r}")
        print(f"      href={a.get('href')!r}")
        print(f"      text={(a.text or '').strip()[:60]!r} attrs={attrs}")

    print("\n=== Các phần tử chứa 'phone'/'tel'/'call' trong class ===")
    for el in item.iter():
        if not isinstance(el.tag, str):
            continue
        cls = el.get("class") or ""
        if any(k in cls.lower() for k in ("phone", "tel", "call")):
            attrs = {k: v for k, v in el.attrib.items() if k.startswith("data-")}
            print(f"  <{el.tag}> class={cls!r} attrs={attrs} text={(el.text or '').strip()[:50]!r}")

    print("\n=== HTML thô của tin (2000 ký tự đầu) ===")
    print(html.tostring(item, pretty_print=True, encoding="unicode")[:2000])


if __name__ == "__main__":
    main()
