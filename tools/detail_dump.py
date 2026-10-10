"""In HTML thô các khối quan trọng của trang chi tiết (offline, đọc từ data/raw).

Chạy: python -m tools.detail_dump [file.html]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

PATH = Path("data/raw/recon_detail2.html")
BLOCKS = [
    "content-detail",
    "list-info",
    "box-price",
    "content-description",
    "seller-info",
    "information-address",
    "title-detail",
    "group-title-detail",
    "info-car",
    "box-tab",
    "titel-tab-detail",
    "box-detail-listing",
    "info-title",
]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else PATH
    tree = html.fromstring(path.read_text(encoding="utf-8"))
    body = re.sub(r"\s+", " ", tree.xpath("//body")[0].text_content())

    for cls in BLOCKS:
        nodes = tree.xpath(f'//*[contains(@class,"{cls}")]')
        if not nodes:
            print(f"\n### {cls}: (không có)")
            continue
        node = nodes[0]
        raw = html.tostring(node, pretty_print=True, encoding="unicode")
        raw = re.sub(r"\n\s*\n+", "\n", raw)
        print(f"\n### {cls} ({len(nodes)} node) — {len(raw)} ký tự")
        print(raw[:1800])

    print("\n### Chuỗi ngày tháng trong trang (nghi ngày đăng)")
    for pattern in (r"\d{2}/\d{2}/\d{4}", r"\d{2}-\d{2}-\d{4}", r"\d{1,2}:\d{2}\s*\d{2}/\d{2}/\d{4}"):
        found = re.findall(pattern, body)
        print(f"  {pattern} -> {found[:8]} ({len(found)} lần)")

    print("\n### Tìm 'Mã tin' và ngữ cảnh")
    for m in re.finditer(r".{0,80}Mã tin.{0,120}", body):
        print("  ...", m.group(0), "...")

    print("\n### data-tragia (chứa màu xe) & data-autohasvoucher")
    for el in tree.xpath('//*[@data-tragia]'):
        print("  ", el.get("data-tragia"))

    print("\n### Ảnh trong trang (unique, có crop/wm = ảnh tin đăng)")
    imgs = [i for i in tree.xpath("//img/@data-src") if "/crop/" in i or "/watermark/" in i]
    print(f"  {len(imgs)} ảnh")
    for i in imgs[:10]:
        print("   ", i)

    print("\n### Link tab / ajax trong khối tab")
    for el in tree.xpath('//*[contains(@class,"box-tab")]//a | //*[contains(@class,"titel-tab-detail")]//a'):
        print(f"  class={el.get('class')!r} href={el.get('href')!r} text={re.sub(chr(92)+'s+', ' ', el.text_content()).strip()[:40]!r}")

    print("\n### Element chứa 'Số chỗ' / 'Động cơ' / 'Công suất' (thông số kỹ thuật)")
    for kw in ("Số chỗ", "Động cơ", "Công suất", "Dẫn động", "Kích thước", "Trang bị"):
        n = tree.xpath(f'//*[contains(text(),"{kw}")]')
        print(f"  {kw}: {len(n)} element")


if __name__ == "__main__":
    main()
