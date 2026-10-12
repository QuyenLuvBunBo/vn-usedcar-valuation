"""Verify the 'still for sale' marker on detail pages: the price-proposal button
(its data-tragia attribute contains the listing id).

Run: python -m tools.check_onsale_marker [sample_size]
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.common.http_client import ScraperSession  # noqa: E402

CACHE = "data/raw/sitemap_lastmod.json"


def ad_id_of(url: str) -> str:
    """Extract the listing id from a URL such as ...-aidxc23444795."""
    m = re.search(r"-aidx?[a-z]*(\d+)$", url)
    return m.group(1) if m else ""


def is_onsale(session: ScraperSession, url: str) -> tuple[str, bool | None]:
    """True when the page still shows the price-proposal button of that very listing."""
    resp = session.get(url)
    if resp is None:
        return "error", None
    if "/NotFound" in resp.url:
        return "404", None
    ad_id = ad_id_of(url)
    if not ad_id:
        return "?", None
    marker = re.search(rf'data-tragia="[^"]*\.{re.escape(ad_id)}\."', resp.text)
    return "200", marker is not None


def main() -> None:
    n_extra = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    conn = sqlite3.connect("data/scraped.db")
    conn.row_factory = sqlite3.Row
    avail = [r[0] for r in conn.execute("SELECT url FROM oto_cars WHERE sold=0 LIMIT 5")]
    sold = [r[0] for r in conn.execute("SELECT url FROM oto_cars WHERE sold=1 LIMIT 5")]
    ours = {r[0] for r in conn.execute("SELECT url FROM oto_cars")}

    with open(CACHE, encoding="utf-8") as fh:
        sitemap_urls = list(json.load(fh).keys())
    conn.close()
    extra = random.Random(7).sample([u for u in sitemap_urls if u not in ours], n_extra)

    with ScraperSession(delay=1.2) as session:
        print("### CONTROL — 'sold' label taken from the listing pages (ground truth)")
        for label, urls, expect in (("ON SALE", avail, True), ("SOLD", sold, False)):
            for url in urls:
                status, onsale = is_onsale(session, url)
                verdict = "OK " if onsale is expect else "BAD"
                print(f"  [{verdict}] {label:8s} -> marker={onsale} | {ad_id_of(url)}")

        print("\n### LISTINGS THAT EXIST ONLY IN THE SITEMAP (never seen in a listing)")
        onsale_count = 0
        for url in extra:
            status, onsale = is_onsale(session, url)
            onsale_count += bool(onsale)
            print(f"  [{status}] onsale={onsale} | {ad_id_of(url)} | {url[:88]}")
        print(f"\n  => of {len(extra)} sitemap-only listings: onsale {onsale_count}, "
              f"sold/unknown {len(extra) - onsale_count}")


if __name__ == "__main__":
    main()
