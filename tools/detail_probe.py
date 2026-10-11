"""Probe 1 trang chi tiết tin đăng: JSON-LD, ngày đăng, thông số.

Chạy: python -m tools.detail_probe <url_tin_dang>
"""

from __future__ import annotations

import json
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.common import storage  # noqa: E402
from src.common.http_client import ScraperSession  # noqa: E402


def main() -> None:
    url = sys.argv[1]
    with ScraperSession(delay=0.5) as session:
        text = session.get_text(url)
    if text is None:
        print("không lấy được")
        return

    storage.save_raw(text, "recon_detail")
    tree = html.fromstring(text)
    print("=== title ===")
    print(" ", (tree.xpath("//title/text()") or [""])[0].strip())

    print("\n=== JSON-LD ===")
    for block in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(block)
        except ValueError:
            print("  (JSON-LD không parse được, độ dài %s)" % len(block))
            continue
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2500])
        print("  ---")

    body = re.sub(r"\s+", " ", tree.xpath("//body")[0].text_content())
    print("\n=== text nghi là ngày đăng ===")
    for m in re.finditer(r"(Đăng ngày|Ngày đăng|Tin đăng ngày|Cập nhật)[^|]{0,40}", body):
        print("  ", m.group(0)[:90])

    print("\n=== text nghi là mã tin / lượt xem ===")
    for m in re.finditer(r"(Mã tin|Lượt xem)[^|]{0,30}", body):
        print("  ", m.group(0)[:80])

    print("\n=== bảng thông số (class chứa spec/thong-so) ===")
    for el in tree.xpath('//*[contains(@class,"spec") or contains(@class,"thong-so")]')[:3]:
        print(f"  <{el.tag} class={el.get('class')!r}>")
        for li in el.xpath(".//li")[:14]:
            print("     ", re.sub(r"\s+", " ", li.text_content()).strip()[:90])


if __name__ == "__main__":
    main()
