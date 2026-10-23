"""Crawl used cars from muaban.net/o-to — the replacement for anycar.vn (that site is offline).

Recon 2026-10-23 (full notes in docs/sources/muaban.md):

    * robots.txt allows everything except /dashboard/ and /8zr2/, and publishes a sitemap index.
    * The site is Next.js: every page embeds its whole payload in
      ``<script id="__NEXT_DATA__" type="application/json">``, so this source parses JSON instead of
      HTML (much more stable than XPath on a JS site).
    * Listing pages ``https://muaban.net/o-to?page=N`` carry 20 ads each (~7,500 ads in total).
    * ``props.pageProps.classified.items`` -> one dict per ad (id, title, price, price_display,
      url, location, publish_at, is_company, category_name, cover).
    * ``props.pageProps.classified`` on a detail page -> the same object plus the car specs in
      ``parameters``: Hãng xe / Dòng xe / Năm sản xuất / Số km đã đi / Hộp số / Nhiên liệu /
      Số chỗ / Xuất xứ.

Two tables, both keyed on url so a re-run never duplicates a row:

    muaban_cars          one row per ad from the listing pages
    muaban_car_details   one row per ad from its detail page (the crawl is resumable)

Run:

    python -m src.sources.muaban --pages 2                 # quick sample: 2 listing pages
    python -m src.sources.muaban --pages 2 --details       # + fetch the detail page of those ads
    python -m src.sources.muaban --details                 # every stored ad that lacks a detail row
    python -m src.sources.muaban.unified                   # export data/processed/muaban.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from typing import Any, Iterable, Sequence

from tqdm import tqdm

from ...common import config, storage
from ...common.http_client import ScraperSession
from ...common.parsing import clean_text as _clean

BASE_URL = "https://muaban.net"
START_URL = f"{BASE_URL}/o-to"
SOURCE_PLATFORM = "muaban.net"
PER_PAGE = 20
TABLE = "muaban_cars"
DETAIL_TABLE = "muaban_car_details"
BATCH = 25

COLUMNS = [
    "url", "id", "title", "price_vnd", "price_text", "location", "publish_at",
    "is_company", "category_name", "cover",
]
DETAIL_COLUMNS = [
    "url", "id", "title", "description", "price_vnd", "price_text", "address",
    "publish_at", "created_at", "image_count", "contact_name", "is_company",
    "brand", "model", "year", "km", "gearbox", "fuel", "seats", "origin", "body_style",
    "parameters",
]

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
DETAIL_ID_RE = re.compile(r"-id(\d+)$")

log = logging.getLogger("muaban")


# ------------------------------------------------------------------ parsing
def next_data(html_text: str) -> dict[str, Any] | None:
    """Return the JSON payload Next.js embeds in the page (None when the page has no payload)."""
    match = NEXT_DATA_RE.search(html_text or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        log.error("__NEXT_DATA__ is not valid JSON (page layout changed?)")
        return None


def _page_props(html_text: str) -> dict[str, Any]:
    """props.pageProps of a muaban page ({} when the payload is missing)."""
    data = next_data(html_text) or {}
    return ((data.get("props") or {}).get("pageProps") or {})


def parse_list_page(html_text: str) -> tuple[list[dict], int]:
    """Parse one listing page -> (records, total ads in this category)."""
    classified = _page_props(html_text).get("classified") or {}
    items = classified.get("items") or []
    total = int(classified.get("total") or 0)
    records: list[dict] = []
    for item in items:
        url = item.get("url") or ""
        covers = item.get("covers") or []
        records.append({
            "url": f"{BASE_URL}{url}" if url.startswith("/") else url,
            "id": item.get("id"),
            "title": _clean(item.get("title")),
            "price_vnd": item.get("price"),
            "price_text": _clean(item.get("price_display")),
            "location": _clean(item.get("location")),
            "publish_at": item.get("publish_at"),
            "is_company": int(bool(item.get("is_company"))),
            "category_name": _clean(item.get("category_name")),
            "cover": covers[0] if covers else "",
        })
    return records, total


def _parameter_map(parameters: Iterable[dict] | None) -> dict[str, str]:
    """[{label, value}] -> {'Hãng xe': 'Honda', ...} (empty values dropped)."""
    mapping: dict[str, str] = {}
    for param in parameters or []:
        label = _clean(param.get("label"))
        value = _clean(param.get("value"))
        if label and value:
            mapping[label] = value
    return mapping


def ad_id_of(url: str) -> str:
    """Ad id inside a detail URL (...-id71297868)."""
    match = DETAIL_ID_RE.search(url or "")
    return match.group(1) if match else ""
def parse_detail_page(html_text: str, url: str) -> dict:
    """Parse a detail page -> one row for muaban_car_details ({} when the ad was removed)."""
    classified = _page_props(html_text).get("classified") or {}
    if not classified:
        return {}
    params = _parameter_map(classified.get("parameters"))
    body = re.sub(r"<br\s*/?>", "\n", classified.get("body") or "")
    description = _clean(re.sub(r"<[^>]+>", " ", body))
    return {
        "url": url,
        "id": classified.get("id") or ad_id_of(url),
        "title": _clean(classified.get("title")),
        "description": description,
        "price_vnd": classified.get("price"),
        "price_text": _clean(classified.get("price_display")),
        "address": _clean(classified.get("address") or classified.get("location")),
        "publish_at": classified.get("publish_at"),
        "created_at": classified.get("created_at"),
        "image_count": classified.get("total_images"),
        "contact_name": _clean(classified.get("contact_name")),
        "is_company": int(bool(classified.get("is_company"))),
        "brand": params.get("Hãng xe", ""),
        "model": params.get("Dòng xe", ""),
        "year": params.get("Năm sản xuất", ""),
        "km": params.get("Số km đã đi", ""),
        "gearbox": params.get("Hộp số", ""),
        "fuel": params.get("Nhiên liệu", ""),
        "seats": params.get("Số chỗ", ""),
        "origin": params.get("Xuất xứ", ""),
        "body_style": params.get("Kiểu dáng", ""),
        "parameters": json.dumps(params, ensure_ascii=False),
    }


# ------------------------------------------------------------------ crawling
def crawl_pages(pages: int | None = None, save_raw: bool = False,
                session: ScraperSession | None = None) -> int:
    """Crawl the listing pages into muaban_cars (page 1..N; stop early when the ads run out)."""
    config.ensure_dirs()
    conn = storage.open_db()
    storage.create_table(conn, TABLE, COLUMNS)
    storage.ensure_columns(conn, TABLE, COLUMNS)

    own_session = session is None
    session = session or ScraperSession()
    page, total, saved = 1, 0, 0
    try:
        while pages is None or page <= pages:
            html_text = session.get_text(f"{START_URL}?page={page}")
            if html_text is None:
                log.error("page %s could not be fetched -> stopping", page)
                break
            if save_raw:
                storage.save_raw(html_text, f"muaban_list_{page:04d}")
            records, total = parse_list_page(html_text)
            if not records:
                log.info("page %s is empty -> done", page)
                break
            storage.upsert_rows(conn, TABLE, records)
            saved += len(records)
            log.info("page %s/%s: %s ads (category total %s, stored %s)",
                     page, (total + PER_PAGE - 1) // PER_PAGE, len(records), total, saved)
            if total and page * PER_PAGE >= total:
                log.info("reached the end of the category (%s ads)", total)
                break
            page += 1
    finally:
        if own_session:
            session.close()

    log.info("listing pages done: %s ads stored (%s rows in %s)",
             saved, storage.count_rows(conn, TABLE), TABLE)
    conn.close()
    return saved


def pending_detail_urls(conn, refresh: bool = False, limit: int | None = None) -> list[str]:
    """URLs that still need a detail page (resumable: already-parsed rows are skipped)."""
    if refresh:
        urls = [row["url"] for row in storage.read_rows(conn, TABLE)]
    else:
        done = {row[0] for row in conn.execute(f'SELECT url FROM "{DETAIL_TABLE}"')}
        urls = [row["url"] for row in storage.read_rows(conn, TABLE) if row["url"] not in done]
    return urls[:limit] if limit else urls
def crawl_details(limit: int | None = None, refresh: bool = False, save_raw: bool = False,
                  session: ScraperSession | None = None) -> int:
    """Fetch the detail page of every ad that does not have one yet (resumable)."""
    config.ensure_dirs()
    conn = storage.open_db()
    storage.create_table(conn, DETAIL_TABLE, DETAIL_COLUMNS)
    storage.ensure_columns(conn, DETAIL_TABLE, DETAIL_COLUMNS)

    todo = pending_detail_urls(conn, refresh=refresh, limit=limit)
    log.info("detail pages to fetch: %s (stored: %s)", len(todo),
             storage.count_rows(conn, DETAIL_TABLE))
    if not todo:
        conn.close()
        return 0

    own_session = session is None
    session = session or ScraperSession()
    buffer: list[dict] = []
    ok = fail = 0
    try:
        for url in tqdm(todo, desc="muaban details", unit="page"):
            html_text = session.get_text(url)
            if html_text is None:
                fail += 1
                continue
            if save_raw:
                storage.save_raw(html_text, f"muaban_detail_{ad_id_of(url)}")
            record = parse_detail_page(html_text, url)
            if not record:
                fail += 1
                continue
            buffer.append(record)
            ok += 1
            if len(buffer) >= BATCH:
                storage.upsert_rows(conn, DETAIL_TABLE, buffer)
                buffer.clear()
        if buffer:
            storage.upsert_rows(conn, DETAIL_TABLE, buffer)
    finally:
        if own_session:
            session.close()

    log.info("detail crawl finished: %s saved, %s failed, %s rows in %s",
             ok, fail, storage.count_rows(conn, DETAIL_TABLE), DETAIL_TABLE)
    conn.close()
    return ok


def crawl(pages: int | None = None, details: bool = False, limit: int | None = None,
          refresh: bool = False, save_raw: bool = False) -> int:
    """Crawl listing pages, then (optionally) the detail page of each ad."""
    stored = crawl_pages(pages=pages, save_raw=save_raw)
    if details:
        stored += crawl_details(limit=limit, refresh=refresh, save_raw=save_raw)
    return stored


# ---------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl muaban.net/o-to (replacement for anycar.vn) into SQLite")
    parser.add_argument("--pages", type=int, default=None,
                        help="how many listing pages to crawl (20 ads each); default: all ~375")
    parser.add_argument("--details", action="store_true",
                        help="also fetch each ad's detail page (resumable)")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of detail pages")
    parser.add_argument("--refresh", action="store_true", help="re-fetch detail pages already stored")
    parser.add_argument("--save-raw", action="store_true", help="also save the raw HTML of each page")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    crawl(pages=args.pages, details=args.details, limit=args.limit,
          refresh=args.refresh, save_raw=args.save_raw)
    print("\nNext: python -m src.sources.muaban.unified   (export the 21-column CSV)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
