"""Probe 1 URL listing: đếm tin, dò thanh phân trang, in mẫu dữ liệu.

Chạy: python -m tools.probe https://oto.com.vn/mua-ban-xe-toyota
"""

from __future__ import annotations

import re
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.http_client import ScraperSession  # noqa: E402

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'


def probe(session: ScraperSession, url: str) -> None:
    print("=" * 78)
    print("URL:", url)
    text = session.get_text(url)
    if text is None:
        print("  !! không lấy được")
        return

    tree = html.fromstring(text)
    items = tree.xpath(ITEM_XPATH)
    print(f"  bytes={len(text)} | so tin = {len(items)}")

    brands, conds = Counter(), Counter()
    for it in items:
        tinrao = it.get("data-tinrao", "")
        parts = tinrao.split(".")
        if len(parts) >= 3:
            brands[parts[0]] += 1
            conds[parts[2]] += 1
    print("  brand:", dict(brands))
    print("  tình trạng:", dict(conds))

    # khối phân trang
    print("  --- khối phân trang ---")
    found = False
    for el in tree.xpath('//*[contains(@class,"pag") or contains(@class,"Pag")]'):
        cls = el.get("class", "")
        if "pag" in cls.lower():
            found = True
            print(f"  <{el.tag} class={cls!r}>")
            for a in el.xpath(".//a"):
                print(f"      a class={a.get('class')!r} href={a.get('href')!r} text={(a.text or '').strip()!r}")
    if not found:
        print("  (không tìm thấy khối có class chứa 'pag')")

    # các link phân trang dạng khác
    hrefs = set(re.findall(r'href="([^"]+)"', text))
    cand = sorted(h for h in hrefs if re.search(r"(page=|trang-|/p\d|\?p=)", h))
    print("  --- link nghi là phân trang ---")
    for h in cand[:25]:
        print("      ", h)

    # tổng số tin
    m = re.findall(r"([\d\.]+)\s*(?:tin|kết quả)", text, re.I)
    print("  --- text 'N tin/kết quả' ---", m[:8])

    # in mẫu 3 tin đầu
    print("  --- mẫu dữ liệu 3 tin đầu ---")
    for it in items[:3]:
        name = it.xpath('.//span[@class="car-name"]/text()')
        price = it.xpath('.//p[@class="price"]/text()')
        tags = [t.strip() for t in it.xpath('.//ul[@class="tag-list"]/li//text()') if t.strip()]
        loc = [t.strip() for t in it.xpath('.//li[@class="seller-location"]//text()') if t.strip()]
        seller = [t.strip() for t in it.xpath('.//li[@class="seller-name"]//text()') if t.strip()]
        phone = it.xpath('.//a[contains(@class,"btn-tel")]/@data-phone')
        print(f"    name={(name[0][:70] if name else None)!r}")
        print(f"    price={(price[0].strip() if price else None)!r} tags={tags}")
        print(f"    seller={seller} loc={loc} phone={phone}")
        print(f"    data-call={it.xpath('.//a[contains(@class,\"btn-tel\")]/@data-call')}")


def main() -> None:
    urls = sys.argv[1:] or ["https://oto.com.vn/mua-ban-xe-tennis"]
    with ScraperSession(delay=1.0) as session:
        for url in urls:
            probe(session, url)


if __name__ == "__main__":
    main()
