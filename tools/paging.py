"""Find the pagination block and the total listing count of a listing page.

Run: python -m tools.paging https://oto.com.vn/mua-ban-xe-toyota
"""

from __future__ import annotations

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
        print("could not fetch", url)
        return
    storage.save_raw(text, "recon_brand")

    tree = html.fromstring(text)

    print("--- <title> ---")
    print(" ", (tree.xpath("//title/text()") or [""])[0].strip())

    print("\n--- text containing 'tin' / 'kết quả' / 'Trang' (site wording) ---")
    body = re.sub(r"\s+", " ", tree.xpath("//body")[0].text_content())
    for kw in ("tin", "kết quả", "Trang", "trang"):
        for m in re.finditer(re.escape(kw), body):
            seg = body[max(0, m.start() - 60) : m.start() + 40]
            if re.search(r"\d", seg):
                print(f"  [{kw}] ...{seg}...")
    print()

    # elements holding several numeric links are usually the pagination block
    print("--- elements with >=2 numeric link texts (pagination candidates) ---")
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

    print("\n--- every href containing 'page=' ---")
    for h in sorted(set(re.findall(r'href="([^"]*page=[^"]*)"', text)))[:20]:
        print("  ", h)

    print("\n--- page navigation links (Next/Prev) ---")
    for a in tree.xpath('//a[contains(@class,"next") or contains(@class,"prev") or contains(@class,"Next")]'):
        print(f"  class={a.get('class')!r} href={a.get('href')!r} text={(a.text or '').strip()!r}")


if __name__ == "__main__":
    main()
