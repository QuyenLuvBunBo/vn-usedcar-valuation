"""TEMPLATE for a new data source: COPY this folder to `src/sources/<source>/` and edit it.

What you have to do for a new source (details in README.md in this folder):
  1. crawl.py  : write `parse_*` for your site + a `crawl()` that returns list[dict]
  2. unified.py: map the raw fields to the 21 unified columns (see src/common/schema.py)
  3. Before opening a PR:  python -m tools.validate_source_csv data/processed/<source>.csv
"""

from __future__ import annotations

import logging

from lxml import html
from tqdm import tqdm

from ...common import config, storage
from ...common.http_client import ScraperSession
from ...common.parsing import clean_text, first, parse_vnd_price
from ...common.schema import SCHEMA_COLUMNS

SOURCE = "example_books"
BASE_URL = "https://books.toscrape.com"
START_URL = "https://books.toscrape.com/catalogue/page-1.html"
MAX_PAGES = 2
TABLE = "example_books"

log = logging.getLogger(SOURCE)


def parse_list_page(page_html: str, base_url: str) -> tuple[list[dict], str | None]:
    """Parse one listing page -> (records, next_page_url).

    THIS IS THE ONLY FUNCTION YOU HAVE TO REWRITE for each website.
    """
    tree = html.fromstring(page_html)
    rows: list[dict] = []
    for card in tree.xpath('//article[@class="product_pod"]'):
        href = first(card, ".//h3/a/@href")
        price_text = first(card, './/p[@class="price_color"]/text()')
        if not href:
            continue
        url = href.split("/", 3)[-1] if href.startswith("../../") else href
        rows.append({
            "source_url": url if url.startswith("http") else f"{BASE_URL}/catalogue/{url}",
            "title": clean_text(first(card, ".//h3/a/@title")),
            "price_raw": price_text,
            "price_vnd": parse_vnd_price(price_text),
        })
    next_href = first(tree, '//li[@class="next"]/a/@href')
    return rows, (f"{BASE_URL}/catalogue/{next_href}" if next_href else None)


def to_unified(raw: dict) -> dict:
    """Map a raw record to the 21 unified columns — see src/common/schema.py."""
    record = dict.fromkeys(SCHEMA_COLUMNS)
    record.update({
        "listing_id": f"BOOK_{abs(hash(raw['source_url'])) % 10**8}",
        "source_platform": SOURCE,
        "brand": "Unknown",
        "model": raw.get("title") or "Unknown",
        "price_vnd": raw.get("price_vnd"),
        "source_url": raw.get("source_url"),
        "scraped_at": config.now_iso(),
        "raw_price_text": raw.get("price_raw"),
        "price_status": "full" if raw.get("price_vnd") else "invalid",
    })
    return record


def crawl(max_pages: int | None = MAX_PAGES) -> list[dict]:
    """Crawl listings, map them to the 21 columns, and write this source's CSV."""
    config.ensure_dirs()
    conn = storage.open_db()
    storage.create_table(conn, TABLE, ["source_url", "title", "price_raw", "price_vnd"])

    rows: list[dict] = []
    url: str | None = START_URL
    page = 0
    with ScraperSession() as session:
        with tqdm(desc=SOURCE, unit="trang") as bar:
            while url and (max_pages is None or page < max_pages):
                page += 1
                page_html = session.get_text(url)
                if page_html is None:
                    break
                page_rows, url = parse_list_page(page_html, url)
                rows.extend(page_rows)
                bar.update(1)

    storage.upsert_rows(conn, TABLE, rows)
    unified_rows = [to_unified(r) for r in rows]
    csv_path = storage.save_csv(unified_rows, SOURCE, SCHEMA_COLUMNS)
    conn.close()
    log.info("Xong %s tin -> %s", len(unified_rows), csv_path)
    return unified_rows


if __name__ == "__main__":
    crawl()
