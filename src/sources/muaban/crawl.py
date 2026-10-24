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
import unicodedata
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
    "condition", "parameters",
]

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
DETAIL_ID_RE = re.compile(r"-id(\d+)$")

# --- Partitioning -----------------------------------------------------------------------------
# muaban stops advancing `?page=N` after roughly 50-60 pages (~1,000-1,200 ads), so a single query
# can never return the ~7,500 ads of the category. Every ad, however, belongs to exactly one brand
# category (/o-to/ban-o-to-<brand>), which pages further — e.g. /o-to/ban-o-to-toyota holds 1,768 ads —
# and a brand bigger than the cap is split again by condition and fuel.
SALE_PATH = f"{BASE_URL}/o-to/ban-o-to"
USED_STATUS_ID = 526          # filter 'Tình trạng' = Đã qua sử dụng
# The site's facet ids (see docs/sources/muaban.md); used to split a partition that is still
# bigger than the pager cap.
SPLIT_FACETS = (("car_fuels", "61"), ("car_types", "59"), ("car_seat_ids", "62"),
                ("vehicle_origins", "60"))
PARTITION_CAP = 1200          # stop paging a partition above this many ads (site truncates anyway)
MAX_PAGES_PER_PARTITION = 70  # hard stop, the site repeats the last page beyond it

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
        "condition": params.get("Tình trạng", ""),
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
    before = storage.count_rows(conn, TABLE)
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

    after = storage.count_rows(conn, TABLE)
    log.info("listing pages done: %s ads seen, %s new rows (%s rows in %s)",
             saved, after - before, after, TABLE)
    if saved > 2 * max(after - before, 1):
        log.warning("%s of those were repeats: the site stops advancing its pager after ~1,000 ads. "
                    "Use --by-brand (optionally --used-only) for full coverage.",
                    saved - (after - before))
    conn.close()
    return saved


# --------------------------------------------------------------- partitioning
def slugify(name: str) -> str:
    """'Mercedes Benz' -> 'mercedes-benz' (the site's brand URLs are ASCII slugs)."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def brand_candidates(name: str) -> list[str]:
    """Slugs to try for a brand: the full one first, then its first word.

    The site is not consistent: 'Mercedes Benz' lives at /ban-o-to-mercedes (366 ads), while
    /ban-o-to-mercedes-benz is a 404, and 'Land Rover' does live at /ban-o-to-land-rover.
    """
    slug = slugify(name)
    candidates = [slug]
    first = slug.split("-")[0]
    if first and first != slug:
        candidates.append(first)
    return candidates


def facets(html_text: str) -> tuple[list[str], list[dict]]:
    """Brand names and fuel options from a listing page's filterConfig."""
    config_block = _page_props(html_text).get("filterConfig") or {}
    filters = config_block.get("filters") or {}
    brands = [item.get("name", "") for item in (filters.get("52") or {}).get("items") or []]
    fuels = (filters.get("61") or {}).get("items") or []
    return [b for b in brands if b], fuels


def _with_params(base: str, params: Sequence[str]) -> str:
    """Append query params (skipping empties) to a base URL, reusing '?' or '&' as needed."""
    clean = [p for p in params if p]
    if not clean:
        return base
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{'&'.join(clean)}"


def crawl_partition(session: ScraperSession, conn, url: str, total_hint: int | None = None,
                    save_raw: bool = False, tag: str = "") -> tuple[int, int]:
    """Page one partition until the site repeats a page. Returns (ads seen, ads in the partition)."""
    page, prev, seen, total = 1, None, 0, total_hint or 0
    while page <= MAX_PAGES_PER_PARTITION:
        target = _with_params(url, [f"page={page}"])
        html_text = session.get_text(target)
        if html_text is None:
            break
        if save_raw:
            storage.save_raw(html_text, f"muaban_{tag}_{page:03d}")
        records, total = parse_list_page(html_text)
        ids = tuple(r["id"] for r in records)
        if not records or ids == prev:      # the site repeats the last page past its cap
            break
        prev = ids
        storage.upsert_rows(conn, TABLE, records)
        seen += len(records)
        if total and page * PER_PAGE >= total:
            break
        page += 1
    return seen, total


def _facet_items(html_text: str) -> dict[str, list[dict]]:
    """The option lists used for splitting (fuels, car types, seats, origins)."""
    config_block = _page_props(html_text).get("filterConfig") or {}
    filters = config_block.get("filters") or {}
    return {field: (filters.get(key) or {}).get("items") or [] for field, key in SPLIT_FACETS}


def _crawl_split(session: ScraperSession, conn, base: str, params: Sequence[str], depth: int,
                 facet_cache: dict[str, list[dict]], save_raw: bool) -> int:
    """Crawl one partition, splitting it by the next facet while it stays above the pager cap.

    Toyota holds ~1,780 ads: one query stops at ~1,200, petrol is still ~1,300, so the chain goes
    brand -> car_fuels -> car_types -> car_seat_ids -> vehicle_origins until every partition fits.
    """
    _, total = parse_list_page(session.get_text(_with_params(base, [*params, "page=1"])) or "")
    if not total:
        return 0
    field = SPLIT_FACETS[depth][0] if depth < len(SPLIT_FACETS) else ""
    items = facet_cache.get(field) or []
    if total <= PARTITION_CAP or not items:
        seen, _ = crawl_partition(session, conn, _with_params(base, params), total_hint=total,
                                  save_raw=save_raw, tag=f"p{depth}")
        return seen
    seen = 0
    for item in items:
        if not item.get("id"):
            continue
        seen += _crawl_split(session, conn, base, [*params, f"{field}={item['id']}"], depth + 1,
                             facet_cache, save_raw)
    return seen


def crawl_by_brand(used_only: bool = True, brands: Sequence[str] | None = None,
                   save_raw: bool = False, session: ScraperSession | None = None) -> int:
    """Crawl brand partitions (optionally split by fuel) so the whole catalogue is reachable."""
    config.ensure_dirs()
    conn = storage.open_db()
    storage.create_table(conn, TABLE, COLUMNS)
    storage.ensure_columns(conn, TABLE, COLUMNS)
    before = storage.count_rows(conn, TABLE)

    own_session = session is None
    session = session or ScraperSession()
    try:
        first = session.get_text(SALE_PATH) or ""
        brand_names, fuels = facets(first)
        facet_cache = _facet_items(first)
        wanted = [b for b in brand_names if not brands or slugify(b) in set(brands)]
        log.info("partitions: %s brands%s", len(wanted), " (used cars only)" if used_only else "")
        status = [f"vehicle_status_ids={USED_STATUS_ID}"] if used_only else []

        done = skipped = 0
        for name in tqdm(wanted, desc="muaban brands", unit="brand"):
            # the site's slug is not always slugify(name) — try the first word as a fallback
            base, total = "", 0
            for slug in brand_candidates(name):
                candidate = f"{SALE_PATH}-{slug}"
                _, candidate_total = parse_list_page(
                    session.get_text(_with_params(candidate, [*status, "page=1"])) or "")
                if candidate_total:
                    base, total = candidate, candidate_total
                    break
            if not base:
                skipped += 1
                log.debug("%s: no brand URL found -> skipped", name)
                continue
            seen = _crawl_split(session, conn, base, status, 0, facet_cache, save_raw)
            done += seen
            log.debug("%s: %s ads seen (site reports %s)", name, seen, total)
        log.info("brands without a usable URL: %s", skipped)
    finally:
        if own_session:
            session.close()

    after = storage.count_rows(conn, TABLE)
    log.info("partition crawl finished: %s ads seen, %s new rows (%s -> %s in %s)",
             done, after - before, before, after, TABLE)
    conn.close()
    return after - before


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
          refresh: bool = False, save_raw: bool = False, by_brand: bool = False,
          used_only: bool = False, brands: Sequence[str] | None = None) -> int:
    """Crawl listing pages (or brand partitions), then (optionally) the detail page of each ad."""
    if by_brand:
        stored = crawl_by_brand(used_only=used_only, brands=brands, save_raw=save_raw)
    else:
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
    parser.add_argument("--by-brand", action="store_true",
                        help="crawl brand partitions: the only way to reach the whole catalogue "
                             "(the category page stops advancing after ~1,000 ads)")
    parser.add_argument("--used-only", action="store_true",
                        help="with --by-brand: only ads the site marks 'Đã qua sử dụng'")
    parser.add_argument("--brands", nargs="+", default=None, metavar="SLUG",
                        help="with --by-brand: only these brand slugs (e.g. toyota honda)")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of detail pages")
    parser.add_argument("--refresh", action="store_true", help="re-fetch detail pages already stored")
    parser.add_argument("--save-raw", action="store_true", help="also save the raw HTML of each page")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    crawl(pages=args.pages, details=args.details, limit=args.limit,
          refresh=args.refresh, save_raw=args.save_raw, by_brand=args.by_brand,
          used_only=args.used_only, brands=args.brands)
    print("\nNext: python -m src.sources.muaban.unified   (export the 21-column CSV)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
