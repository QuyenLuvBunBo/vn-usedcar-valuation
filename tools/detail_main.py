"""Dump khối người bán của TIN CHÍNH + số điện thoại + địa chỉ showroom.

Chạy: python -m tools.detail_main [file.html]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402


def outer(el, limit: int = 1500) -> str:
    raw = html.tostring(el, pretty_print=True, encoding="unicode")
    return re.sub(r"\n\s*\n+", "\n", raw)[:limit]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/recon_detail2.html")
    tree = html.fromstring(path.read_text(encoding="utf-8"))

    names = tree.xpath('//h3[contains(@class,"name")]')
    print(f"### h3.name: {len(names)} node")
    if names:
        node = names[0]
        print("  text:", re.sub(r"\s+", " ", node.text_content()).strip())
        chain = []
        cur = node
        for _ in range(5):
            cur = cur.getparent()
            if cur is None:
                break
            chain.append(f"{cur.tag}.{cur.get('class')}")
        print("  tổ tiên:", " <- ".join(chain))
        # khối cha cấp 2 nghi là box tin đăng
        for up in (2, 3):
            cur = node
            for _ in range(up):
                cur = cur.getparent()
            if cur is not None:
                print(f"\n  --- outerHTML tổ tiên cấp {up} (<{cur.tag} class={cur.get('class')!r}>) ---")
                print(outer(cur, 1200))

    print("\n### Các số điện thoại dạng 0xxxxxxxxx trong trang (kèm ngữ cảnh)")
    body = re.sub(r"\s+", " ", tree.xpath("//body")[0].text_content())
    seen = set()
    for m in re.finditer(r"(?:\+84|0)\d[\d\.\s]{7,12}\d", body):
        phone = re.sub(r"\D", "", m.group(0))
        if phone in seen or not (9 <= len(phone) <= 11):
            continue
        seen.add(phone)
        start = max(0, m.start() - 70)
        print(f"  {phone}: ...{body[start:m.end() + 30]}...")

    print("\n### Khối showroom/salon (info-title + map/address)")
    for el in tree.xpath('//*[contains(@class,"info-title")]'):
        print(f"  <{el.tag} class={el.get('class')!r}> {re.sub(chr(92) + 's+', ' ', el.text_content()).strip()[:80]!r}")
    for cls in ("box-detail-listing", "detail-listing", "box-seller", "seller-detail", "showroom"):
        nodes = tree.xpath(f'//*[contains(@class,"{cls}")]')
        if nodes:
            print(f"\n  --- {cls} ({len(nodes)} node) ---")
            print(outer(nodes[0], 1000))


if __name__ == "__main__":
    main()
