"""Dò khối phân trang + tổng số tin của 1 trang listing.

Chạy: python -m tools.paging https://oto.com.vn/mua-ban-xe-toyota
"""

from __future__ import annotations

import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src import storage  # noqa: E402
from src.http_client import ScraperSession  # noqa: E402


def main() -> None:
    url = sys.argv[1]
    with ScraperSession(delay=0.5) as session:
        text = session.get_text(url)
    if text is None:
        print("không lấy được", url)
        return
    storage.save_raw(text, "recon_brand")

    tree = html.fromstring(text)

    print("--- <title> ---")
    print(" ", (tree.xpath("//title/text()") or [""])[0].strip())

    print("\n--- text có 'tin' / 'kết quả' / 'Trang' ---")
    body = re.sub(r"\s+", " ", tree.xpath("//body")[0].text_content())
    for kw in ("tin", "kết quả", "Trang", "trang"):
        for m in re.finditer(re.escape(kw), body):
            seg = body[max(0, m.start() - 60) : m.start() + 40]
            if re.search(r"\d", seg):
                print(f"  [{kw}] ...{seg}...")
    print()

    # tìm phần tử chứa nhiều link có text là số -> thường là pagination
    print("--- phần tử chứa >=2 link text là số (nghi phân trang) ---")
    seen = set()
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        anchors = el.xpath(".//a")
        numeric = [a for a in anchors if re.fullmatch(r"\d{1,4}", (a.text or "").strip())]
        if len(numeric) >= 2 and id(el) not in seen:
            seen.add(id(el))
            print(f"  <{el.tag}> class={el.get('class')!r}")
            for a in anchors[:12]:
                print(f"      href={a.get('href')!r} text={(a.text or '').strip()!r} class={a.get('class')!r}")

    print("\n--- mọi href chứa 'page=' ---")
    for h in sorted(set(re.findall(r'href="([^"]*page=[^"]*)"', text)))[:20]:
        print("  ", h)

    print("\n--- các link điều hướng trang (Next/Prev/Trang) ---")
    for a in tree.xpath('//a[contains(@class,"next") or contains(@class,"prev") or contains(@class,"Next")]'):
        print(f"  class={a.get('class')!r} href={a.get('href')!r} text={(a.text or '').strip()!r}")


if __name__ == "__main__":
    main()
