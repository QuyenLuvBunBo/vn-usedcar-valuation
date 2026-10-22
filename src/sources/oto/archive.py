"""Archive tier: crawl used-car URLs that are in the sitemap but no longer in the listings.

Why this exists
---------------
oto.com.vn keeps an archive of listing pages that are no longer shown in the public listings
(renewed under a new id, expired, or sold). `sitemap-detail-*.xml` lists ~30,900 URLs, of which
~29,400 are used-car pages (`-aidxc<id>`) — far more than the ~5,000 currently listed. The sitemap
is sorted by `lastmod` descending, so the first URLs are the newest.

Every archived page is a normal listing detail page and therefore carries all 21 unified columns,
but the car is **not currently advertised**. Rows are marked `in_listing = 0` and exported to a
separate file, never mixed into the week-1 deliverable. See docs/sources/oto.md.

Run:
    python -m src.sources.oto.archive --limit 50     # quick sample
    python -m src.sources.oto.archive                # everything (resumable, ~16-18h)
    python -m src.sources.oto.archive --summary      # stats of what has been crawled so far
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta

from tqdm import tqdm

from ...common import config, storage
from ...common.http_client import ScraperSession
from .crawl import ARCHIVE_COLUMNS, ARCHIVE_TABLE, TABLE, parse_detail_page
from .unified import load_lastmod_map

RELIST_AFTER_DAYS = 30  # ignore URLs bumped so recently that they are probably still listed
BATCH = 25

USED_CAR_URL_RE = re.compile(r"-aidxc(\d+)$")
NEW_CAR_URL_RE = re.compile(r"-aidxm(\d+)$")

log = logging.getLogger("oto_archive")


def ad_id_of(url: str) -> str:
    """Listing id inside a detail URL (...-aidxc23444795)."""
    match = re.search(r"-aidx?[a-z]*(\d+)$", url)
    return match.group(1) if match else ""


def classify(urls: list[str]) -> tuple[list[str], int, int]:
    """Split sitemap URLs into (used-car URLs, new-car count, other count)."""
    used, new, other = [], 0, 0
    for url in urls:
        if USED_CAR_URL_RE.search(url):
            used.append(url)
        elif NEW_CAR_URL_RE.search(url):
            new += 1
        else:
            other += 1
    return used, new, other


def pending_urls(conn, lastmods: dict[str, str], limit: int | None = None,
                 refresh: bool = False, skip_recent_days: int = RELIST_AFTER_DAYS) -> list[str]:
    """Archive URLs still to crawl, newest first.

    URLs already in the listing table are skipped (that is the live inventory, already crawled).
    Already-crawled archive URLs are skipped too, unless `refresh` is set.
    """
    if not lastmods:
        log.warning("empty sitemap cache -> nothing to crawl (run the sitemap fetch first)")
        return []

    known = {r[0] for r in conn.execute(f'SELECT url FROM "{TABLE}"')}
    done = set() if refresh else {r[0] for r in conn.execute(f'SELECT url FROM "{ARCHIVE_TABLE}"')}

    # the sitemap is already sorted newest-first; keep that order
    urls = [u for u in lastmods if USED_CAR_URL_RE.search(u)]

    if skip_recent_days:
        cutoff = (datetime.fromisoformat(max(lastmods.values()))
                  - timedelta(days=skip_recent_days)).isoformat()
        urls = [u for u in urls if lastmods[u] < cutoff]

    todo = [u for u in urls if u not in known and u not in done]
    return todo[:limit] if limit else todo


def sold_marker(html_text: str, ad_id: str) -> int:
    """1 when the page still shows this listing's price-proposal button, else 0.

    Verified against ground-truth 'sold' labels: the site removes that button once a car is sold
    (control test documented in docs/sources/oto.md). It does NOT prove the car is still listed.
    """
    return 1 if re.search(rf'data-tragia="[^"]*\.{re.escape(ad_id)}\."', html_text) else 0


def crawl(limit: int | None = None, refresh: bool = False, save_raw: bool = False,
          skip_recent_days: int = RELIST_AFTER_DAYS,
          session: ScraperSession | None = None) -> int:
    """Crawl archive pages into the oto_archive table (resumable)."""
    config.ensure_dirs()
    lastmods = load_lastmod_map()
    used, new, other = classify(list(lastmods))
    log.info("Sitemap: %s URLs -> %s used-car, %s new-car, %s other",
             len(lastmods), len(used), new, other)

    conn = storage.open_db()
    storage.create_table(conn, ARCHIVE_TABLE, ARCHIVE_COLUMNS)
    storage.ensure_columns(conn, ARCHIVE_TABLE, ARCHIVE_COLUMNS)

    todo = pending_urls(conn, lastmods, limit=limit, refresh=refresh,
                        skip_recent_days=skip_recent_days)
    log.info("Archive pages to crawl: %s (already stored: %s)",
             len(todo), storage.count_rows(conn, ARCHIVE_TABLE))
    if not todo:
        conn.close()
        return 0

    own_session = session is None
    session = session or ScraperSession()
    buffer: list[dict] = []
    ok = fail = 0
    try:
        for url in tqdm(todo, desc="Archive", unit="page"):
            html_text = session.get_text(url, headers={"Referer": "https://oto.com.vn/mua-ban-xe"})
            if html_text is None:
                fail += 1
                continue
            if save_raw:
                storage.save_raw(html_text, f"archive_{ad_id_of(url)}")

            record = parse_detail_page(html_text, url)
            ad_id = ad_id_of(url)
            record.update({
                "ad_id": ad_id,
                "in_listing": 0,
                "listing_date": lastmods.get(url, ""),
                "sold_marker": sold_marker(html_text, ad_id),
            })
            buffer.append(record)
            ok += 1
            if len(buffer) >= BATCH:
                storage.upsert_rows(conn, ARCHIVE_TABLE, buffer)
                buffer.clear()
        if buffer:
            storage.upsert_rows(conn, ARCHIVE_TABLE, buffer)
    finally:
        if own_session:
            session.close()

    log.info("Archive crawl finished: %s pages saved, %s failed, %s rows in the table",
             ok, fail, storage.count_rows(conn, ARCHIVE_TABLE))
    conn.close()
    return ok



def summary() -> None:
    """Print what the archive tier currently holds (field coverage + distributions)."""
    conn = storage.open_db()
    if not any(r[0] == ARCHIVE_TABLE
               for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        print("No archive data yet — run: python -m src.sources.oto.archive --limit 50")
        conn.close()
        return

    total = storage.count_rows(conn, ARCHIVE_TABLE)
    print("=" * 74)
    print(f"OTO ARCHIVE TIER — {total} pages crawled")
    print("=" * 74)
    if not total:
        print("No rows yet — run: python -m src.sources.oto.archive --limit 50")
        conn.close()
        return

    print("\nField coverage (rows with a value):")
    for col in ("d_title", "d_price_vnd", "d_price_text", "d_color", "d_seats", "d_city_code",
                "d_seller_name", "d_seller_url", "d_seller_address", "d_description",
                "d_image_count", "d_specs"):
        filled = conn.execute(
            f'SELECT COUNT(*) FROM "{ARCHIVE_TABLE}" WHERE "{col}" IS NOT NULL AND "{col}" != ""'
        ).fetchone()[0]
        print(f"  {col:18s} {filled:6d} ({filled / total * 100:5.1f}%)")

    marker = conn.execute(
        f'SELECT COUNT(*) FROM "{ARCHIVE_TABLE}" WHERE sold_marker = 1').fetchone()[0]
    print(f"\nPrice-proposal button still present (not marked sold): {marker} "
          f"({marker / total * 100:.1f}%)")

    rows = conn.execute(
        f'SELECT d_price_vnd, d_seats, d_city_code, d_seller_url, listing_date, d_specs '
        f'FROM "{ARCHIVE_TABLE}"'
    ).fetchall()

    prices = sorted(int(r[0]) for r in rows if r[0] not in (None, ""))
    if prices:
        print(f"Price: {len(prices)} with a value | min {prices[0] / 1e6:.0f}M | "
              f"median {prices[len(prices) // 2] / 1e6:.0f}M | max {prices[-1] / 1e9:.2f}B VND")

    from collections import Counter

    seats = Counter(r[1] for r in rows)
    print("Seats:", dict(seats.most_common(6)))
    city = Counter(r[2] for r in rows)
    print("city_code:", dict(city.most_common(6)))
    salon = sum(1 for r in rows if (r[3] or "").strip())
    print(f"Seller with own subdomain (dealership): {salon} ({salon / total * 100:.1f}%)")

    conditions = Counter()
    for r in rows:
        try:
            conditions[json.loads(r[5] or "{}").get("Tình trạng", "?")] += 1
        except ValueError:
            conditions["?"] += 1
    print("Condition (spec field):", dict(conditions.most_common(4)))

    dates = sorted(r[4] for r in rows if r[4])
    if dates:
        print(f"listing_date (from sitemap): {dates[0][:10]} .. {dates[-1][:10]}")

    print("\nNext: python -m src.sources.oto.unified --include-archive   "
          "(exports the archive tier as a separate 21-column CSV)")
    conn.close()


def build_parser() -> argparse.ArgumentParser:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Crawl the oto.com.vn archive tier (sitemap URLs that are no longer listed)",
    )
    parser.add_argument("--limit", type=int, default=None, help="crawl at most this many pages")
    parser.add_argument("--refresh", action="store_true", help="re-crawl pages already stored")
    parser.add_argument("--save-raw", action="store_true",
                        help="also save the raw HTML (about 6 GB for the whole archive)")
    parser.add_argument("--skip-recent-days", type=int, default=RELIST_AFTER_DAYS,
                        help="ignore URLs bumped within the last N days (probably still listed)")
    parser.add_argument("--summary", action="store_true", help="only print what has been crawled")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config.ensure_dirs()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler()])

    if not args.summary:
        crawl(limit=args.limit, refresh=args.refresh, save_raw=args.save_raw,
              skip_recent_days=args.skip_recent_days)
    summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())

