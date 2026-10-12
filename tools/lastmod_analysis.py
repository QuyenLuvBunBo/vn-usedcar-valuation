"""Analyse <lastmod> in sitemap-detail: coverage and meaning (publication vs bump date).

Run: python -m tools.lastmod_analysis
"""

from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.common.http_client import ScraperSession  # noqa: E402

SITEMAPS = ("sitemap-detail-1.xml", "sitemap-detail-2.xml")
ENTRY_RE = re.compile(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>")


def load_lastmods(session: ScraperSession) -> dict[str, str]:
    """Download the detail sitemaps -> dict of url -> lastmod."""
    out: dict[str, str] = {}
    for name in SITEMAPS:
        text = session.get_text(f"https://oto.com.vn/{name}")
        if not text:
            print(f"  {name}: could not fetch")
            continue
        entries = ENTRY_RE.findall(text)
        print(f"  {name}: {len(text)} bytes | {len(entries)} entries")
        for url, lastmod in entries:
            out[url] = lastmod
    return out


def main() -> None:
    with ScraperSession(delay=1.0) as session:
        print("### Downloading sitemaps")
        lastmods = load_lastmods(session)
    print(f"Total URLs with a lastmod: {len(lastmods)}")

    if not lastmods:
        return

    # distribution by day
    days = Counter(v[:10] for v in lastmods.values())
    print("\n### lastmod distribution by day (top 10)")
    for day, n in days.most_common(10):
        print(f"  {day}: {n}")
    dates = sorted(lastmods.values())
    print(f"  earliest: {dates[0]}")
    print(f"  latest  : {dates[-1]}")
    print(f"  distinct days: {len(days)}")

    # compare with the DB: coverage and correlation with the listing page position
    conn = sqlite3.connect("data/scraped.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT url, id, source_page, sold FROM oto_cars").fetchall()
    print(f"\n### Comparison with the {len(rows)} crawled listings")
    hit = 0
    by_page: dict[int, list[str]] = {}
    for r in rows:
        lm = lastmods.get(r["url"])
        if not lm:
            continue
        hit += 1
        m = re.search(r"/p(\d+)", r["source_page"] or "")
        page = int(m.group(1)) if m else 1
        by_page.setdefault((page - 1) // 10 * 10 + 1, []).append(lm[:10])
    print(f"  has a lastmod in the sitemap: {hit}/{len(rows)} ({hit / len(rows) * 100:.1f}%)")

    print("\n### Median lastmod per listing-page bucket (page 1 = newest listings)")
    for bucket in sorted(by_page):
        vals = sorted(by_page[bucket])
        print(f"  pages {bucket:>3}-{bucket + 9:<3}: n={len(vals):5d} | "
              f"median {vals[len(vals) // 2]} | earliest {vals[0]} | latest {vals[-1]}")
    conn.close()

    # compare with the capture date (today)
    today = datetime.now().strftime("%Y-%m-%d")
    same_day = sum(1 for v in lastmods.values() if v.startswith(today))
    print(f"\n  lastmod on the capture day ({today}): {same_day} "
          f"({same_day / len(lastmods) * 100:.1f}%)")


if __name__ == "__main__":
    main()
