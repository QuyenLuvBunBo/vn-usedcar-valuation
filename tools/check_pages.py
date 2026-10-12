"""Verify the /p{N} pagination rule: compare page ids and find the page/total counters.

Run: python -m tools.check_pages https://oto.com.vn/mua-ban-xe-toyota
"""

from __future__ import annotations

import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.common.http_client import ScraperSession  # noqa: E402

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "https://oto.com.vn/mua-ban-xe-toyota"
    with ScraperSession(delay=1.0) as session:
        for path in ("", "/p2", "/p3", "/p60", "/p61", "/p999"):
            url = base + path
            text = session.get_text(url)
            if text is None:
                print(f"{path or '(page 1)':>10} -> could not fetch / error")
                continue
            tree = html.fromstring(text)
            items = tree.xpath(ITEM_XPATH)
            ids = [i.get("data-autoid") for i in items]

            # page-number block: the /p<N> links
            page_links = sorted(set(re.findall(r'href="[^"]*/p(\d+)"', text)), key=int)
            total = re.findall(r"C[oó]\s*([\d\.]+)\s*tin", re.sub(r"\s+", " ", tree.text_content()))

            print(f"{path or '(page 1)':>10} -> {len(items):2d} listings | ids[:2]={ids[:2]} "
                  f"| page links: {page_links[:6]}...{page_links[-3:] if len(page_links) > 6 else ''} "
                  f"| counter: {total[:2]}")


if __name__ == "__main__":
    main()
