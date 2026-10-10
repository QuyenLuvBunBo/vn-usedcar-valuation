"""Soi cấu trúc 1 tin đăng + các link lọc/phân trang. Chạy: python -m tools.inspect_items"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

HTML_PATH = Path("data/raw/recon_muabanxe.html")


def main() -> None:
    tree = html.fromstring(HTML_PATH.read_bytes())

    items = tree.xpath('//*[contains(@class, "dev-item-car")]')
    print(f"### Số tin tìm thấy (dev-item-car): {len(items)}\n")

    if items:
        print("### HTML của tin đầu tiên")
        print(html.tostring(items[0], pretty_print=True, encoding="unicode")[:4000])

        print("\n### Các thẻ/thuộc tính bên trong tin đầu tiên")
        for el in items[0].iter():
            if not isinstance(el.tag, str):
                continue
            cls = el.get("class")
            attrs = {k: v for k, v in el.attrib.items() if k not in ("class", "style")}
            text = (el.text or "").strip()
            print(f"  <{el.tag}> class={cls!r} attrs={attrs} text={text[:70]!r}")

    print("\n### Link dạng /mua-ban-xe/... trên trang (mẫu)")
    links = set(re.findall(r'href="(/mua-ban-xe[^"]{0,80})"', HTML_PATH.read_text(encoding="utf-8")))
    for link in sorted(links)[:40]:
        print("  ", link)

    print("\n### Link phân trang (?page / trang-)")
    paging = sorted(
        set(re.findall(r'href="([^"]*(?:\?page=|/p\d+|/trang-)[^"]*)"', HTML_PATH.read_text(encoding="utf-8")))
    )
    for link in paging[:20]:
        print("  ", link)

    print("\n### Từ khóa lọc tình trạng xe trên trang")
    text = tree.text_content()
    for kw in ("Xe cũ", "Xe mới", "Đã qua sử dụng", "Số km đã đi", "Hộp số", "Năm SX", "Tin rao"):
        print(f"  {kw!r}: {text.count(kw)} lần")


if __name__ == "__main__":
    main()
