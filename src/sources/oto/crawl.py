"""Crawl used cars in the Asian mainstream segment from oto.com.vn.

Scope: Toyota, Hyundai, Kia, Mazda, Honda, Mitsubishi — only "Xe cũ" (used) listings.
Source: listing pages /mua-ban-xe-<brand>[/p<N>], 15 listings per page, server-rendered.

Run:
    python -m src.sources.oto                        # all brands
    python -m src.sources.oto --group asia           # the six Asian brands
    python -m src.sources.oto --brands toyota kia    # only a few brands
    python -m src.sources.oto --pages 3              # limit to 3 pages per brand (test)
    python -m src.sources.oto --save-raw             # also save the raw HTML of each page
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
from collections import Counter
from typing import Iterable, Sequence
from urllib.parse import urljoin

from lxml import html
from tqdm import tqdm

from ...common import config, storage
from ...common.http_client import ScraperSession
from ...common.parsing import (
    clean_text as _clean,
    first as _first,
    parse_km_text,
    parse_vnd_price,
    parse_year_text,
    text_of as _text_of,
    to_int as _int_or_none,
)

# Backwards-compatible names: older code and tools call parse_price, parse_km, parse_year
parse_price = parse_vnd_price
parse_km = parse_km_text
parse_year = parse_year_text

# Brand lists live in separate modules so two owners never edit the same file
from .brands_asia import BRANDS as BRANDS_ASIA  # noqa: E402
from .brands_other import BRANDS as BRANDS_OTHER  # noqa: E402

BASE_URL = "https://oto.com.vn"
PER_PAGE = 15
TABLE = "oto_cars"

BRANDS: dict[str, str] = {**BRANDS_ASIA, **BRANDS_OTHER}

COLUMNS = [
    "url", "id", "brand", "model", "car_name", "title",
    "condition", "sold", "origin", "year", "price_text", "price_vnd",
    "km", "gearbox", "fuel", "body_type", "color",
    "province", "seller_name", "phone", "vip_type", "listing_type",
    "image_url", "source_page",
]

NUMERIC_COLUMNS = ("year", "price_vnd", "km", "sold")

# --- Listing detail pages (separate table, merged into the exported CSV) ---
DETAIL_TABLE = "oto_car_details"
DETAIL_COLUMNS = [
    "url", "d_title", "d_price_vnd", "d_price_text", "d_color", "d_seats", "d_city_code",
    "d_make_id", "d_model_id", "d_city_id", "d_segment_id", "d_seller_id",
    "d_vip_type", "d_image_count", "d_image_1", "d_seller_name",
    "d_seller_url", "d_seller_address", "d_description", "d_specs",
]
DETAIL_EXPORT_COLUMNS = COLUMNS + [c for c in DETAIL_COLUMNS if c != "url"]
DESCRIPTION_MAX = 4000
DETAIL_BATCH = 25

# --- Archive tier (sitemap URLs that are no longer in the public listings) ---
ARCHIVE_TABLE = "oto_archive"
ARCHIVE_COLUMNS = ["url", "ad_id", "in_listing", "listing_date", "sold_marker"] + [
    c for c in DETAIL_COLUMNS if c != "url"
]

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'
VALID_ORIGINS = {"trong nước", "nhập khẩu"}
VALID_CONDITIONS = {"xe cũ", "xe mới"}

log = logging.getLogger("oto_scraper")


# ------------------------------------------------------------- parser dữ liệu
def parse_data_call(data_call: str) -> dict[str, str]:
    """Extract the structured payload of the "Gọi ngay" (call) button's data-call attribute.

    Format (anchored from the end so dots inside a model name are tolerated):
        brand.model.condition.origin.year.price.body_type.color.listtype.viptype.id.
    Returns {} when the format does not match (the caller then falls back to DOM/tinrao data).
    """
    if not data_call or not data_call.endswith("."):
        return {}
    parts = data_call[:-1].split(".")
    if len(parts) < 11:
        return {}

    info = {
        "brand": parts[0],
        "model": ".".join(parts[1:-9]),
        "condition": parts[-9],
        "origin": parts[-8],
        "year": parts[-7],
        "price_text": parts[-6],
        "body_type": parts[-5],
        "color": parts[-4],
        "listing_type": parts[-3],
        "vip_type": parts[-2],
        "id": parts[-1],
    }

    # Cross-check: reject anything that does not fit the expected structure, so that no
    # garbage ends up in the dataset.
    if not re.fullmatch(r"\d{4}", info["year"]):
        return {}
    if not re.fullmatch(r"\d+", info["id"]):
        return {}
    if not re.fullmatch(r"V\d+", info["vip_type"]):
        return {}
    if not re.fullmatch(r"[A-Z]{1,2}\d+", info["listing_type"]):
        return {}
    if info["origin"].lower() not in VALID_ORIGINS:
        return {}
    if info["condition"].lower() not in VALID_CONDITIONS:
        return {}
    return info



# ------------------------------------------------------------------ parser
def parse_item(item, page_url: str) -> dict | None:
    """Extract one listing from a div.item-car card.

    Note on sold listings: once a car is sold the site adds the class "sold" and removes the
    "Gọi ngay" (call) button, so `data-call`/`data-phone` disappear. Therefore
    origin/body_type/color/listing_type/phone are empty for sold listings
    (the `sold` column marks them so they can be filtered out).
    """
    href = _first(item, './/h3/a/@href') or _first(item, './/div[@class="photo"]//a/@href')
    if not href:
        return None
    url = urljoin(BASE_URL, href)

    # Structured sources already provided by the site:
    #   data-tinrao -> brand.model.condition.id.vip   and   data-call -> the fuller payload
    tinrao = (item.get("data-tinrao") or "").split(".")
    data_call = parse_data_call(_first(item, './/a[contains(@class,"btn-tel")]/@data-call'))
    sold = 1 if "sold" in (item.get("class") or "").split() else 0

    title = _first(item, './/h3/a/@title')
    car_name = _first(item, './/span[@class="car-name"]/text()') or title

    tags = [_clean(t) for t in item.xpath('.//ul[@class="tag-list"]/li//text()') if _clean(t)]
    price_text = _clean(" ".join(t for t in item.xpath('.//p[@class="price"]//text()') if t.strip()))
    if not price_text:
        price_text = data_call.get("price_text", "")

    loc_nodes = item.xpath('.//li[@class="seller-location"]')
    seller_nodes = item.xpath('.//li[@class="seller-name"]')

    return {
        "url": url,
        "id": item.get("data-autoid") or data_call.get("id") or (tinrao[3] if len(tinrao) > 3 else ""),
        "brand": data_call.get("brand") or (tinrao[0] if tinrao else ""),
        "model": data_call.get("model") or (tinrao[1] if len(tinrao) > 1 else ""),
        "car_name": car_name,
        "title": title,
        "condition": data_call.get("condition") or (tinrao[2] if len(tinrao) > 2 else ""),
        "sold": sold,
        "origin": data_call.get("origin", ""),
        "year": parse_year(car_name, title)
        or (int(data_call["year"]) if data_call.get("year") else None),
        "price_text": price_text,
        "price_vnd": parse_price(price_text),
        "km": parse_km(next((t for t in tags if t.lower().endswith("km")), "")),
        "gearbox": next((t for t in tags if re.match(r"^Số ", t, re.I)), ""),
        "fuel": next((t for t in tags if re.match(r"^(Máy|Động cơ|Điện|Hybrid)", t, re.I)), ""),
        "body_type": data_call.get("body_type", ""),
        "color": data_call.get("color", ""),
        "province": _text_of(loc_nodes[0]) if loc_nodes else "",
        "seller_name": _text_of(seller_nodes[0]) if seller_nodes else "",
        "phone": _first(item, './/a[contains(@class,"btn-tel")]/@data-phone')
        or _clean(" ".join(item.xpath('.//li[@class="seller-phone"]//span[@class="txt"]//text()'))),
        "vip_type": data_call.get("vip_type")
        or next((p for p in tinrao if re.fullmatch(r"V\d+", p)), ""),
        "listing_type": data_call.get("listing_type", ""),
        "image_url": _first(item, './/img[@class="lozad"]/@data-src'),
        "source_page": page_url,
    }


def parse_total(html_text: str) -> int | None:
    """Read the site's "Có 892 tin bán xe ..." counter -> 892. None when it is absent."""
    tree = html.fromstring(html_text)
    body = re.sub(r"\s+", " ", tree.text_content())
    match = re.search(r"C[oó]\s*([\d\.,]+)\s*tin", body)
    if not match:
        return None
    return int(match.group(1).replace(".", "").replace(",", ""))


def parse_list_page(html_text: str, page_url: str) -> list[dict]:
    """Extract every listing on one listing page."""
    tree = html.fromstring(html_text)
    records = []
    for item in tree.xpath(ITEM_XPATH):
        record = parse_item(item, page_url)
        if record:
            records.append(record)
    return records



# --------------------------------------------------------------- detail pages
def _hidden_inputs(tree) -> dict[str, str]:
    """Collect every <input type="hidden"> into a dict of id -> value."""
    return {
        inp.get("id"): _clean(inp.get("value"))
        for inp in tree.xpath("//input[@type='hidden']")
        if inp.get("id")
    }


def _int_or_none(value: str | None) -> int | None:
    """Turn a digit string (separators allowed) into an int; None when empty."""
    digits = re.sub(r"\D", "", value or "")
    return int(digits) if digits else None


def parse_detail_page(html_text: str, url: str) -> dict:
    """Extract the information from one listing's detail page.

    The detail page has NO publication date and NO full technical spec sheet
    (engine/power/dimensions). What it does provide:
      - hidden inputs : #price (numeric price), #numberOfSeat, #cityCode,
                        #hddMakeId, #hddModelId, #hddCityId, #hddSegmentId,
                        #hddUserId (seller id), #hddVipType, #countImage
      - data-tragia   : brand/model/condition/origin/year/price/body type/COLOUR/listtype
      - ul.list-info  : year, fuel, body type, condition, mileage, gearbox, origin, province
      - .box-salon    : seller (salon) name, subdomain, address, avatar
      - .content-description .description : the seller's description text
      - gallery images (/crop/640x480/...)
    """
    tree = html.fromstring(html_text)
    hidden = _hidden_inputs(tree)

    # The 8 specs inside ul.list-info (label in a <label>, value as text or a child div)
    specs: dict[str, str] = {}
    for li in tree.xpath('//ul[contains(@class,"list-info")]/li'):
        label = _first(li, ".//label/text()").rstrip(":")
        text = _text_of(li)
        value = text[len(label):].lstrip(": ").strip() if label and text.startswith(label) else text
        if label:
            specs[label] = value

    # The colour lives in data-tragia: brand.model.condition.origin.year.price.bodystyle.COLOUR...
    color = ""
    tragia = tree.xpath("//*[@data-tragia]/@data-tragia")
    if tragia:
        parts = tragia[0].rstrip(".").split(".")
        if len(parts) >= 8:
            color = _clean(parts[7])

    salon_nodes = tree.xpath('//div[contains(@class,"box-salon")]')
    salon = salon_nodes[0] if salon_nodes else None

    # Seller name: take the FULL text of the h3 (the name sits in a child <a>, so the first
    # text node is just whitespace)
    seller_name = ""
    if salon is not None:
        name_nodes = salon.xpath('.//h3[contains(@class,"name")]')
        if name_nodes:
            seller_name = _text_of(name_nodes[0])

    images: list[str] = []
    for src in tree.xpath("//img/@data-src") + tree.xpath("//img/@src"):
        if "/crop/640x480/" in src and src not in images:
            images.append(src)

    desc_nodes = tree.xpath(
        '//div[contains(@class,"content-description")]//div[contains(@class,"description")]'
    )

    # Displayed price: span.price sits inside span.price-big, so price-big must be excluded
    # (otherwise the first text node is whitespace and the value comes back empty).
    price_nodes = tree.xpath(
        '//div[contains(@class,"box-price")]//span[contains(@class,"price")'
        ' and not(contains(@class,"price-big"))]'
    )
    price_text = _text_of(price_nodes[0]) if price_nodes else ""

    return {
        "url": url,
        "d_title": _first(tree, '//h1[contains(@class,"title-detail")]//text()'),
        "d_price_vnd": _int_or_none(hidden.get("price")),
        "d_price_text": price_text,
        "d_color": color,
        "d_seats": _int_or_none(hidden.get("numberOfSeat")) or None,
        "d_city_code": hidden.get("cityCode", ""),
        "d_make_id": _int_or_none(hidden.get("hddMakeId")) or None,
        "d_model_id": _int_or_none(hidden.get("hddModelId")) or None,
        "d_city_id": _int_or_none(hidden.get("hddCityId")) or None,
        "d_segment_id": _int_or_none(hidden.get("hddSegmentId")) or None,
        "d_seller_id": _int_or_none(hidden.get("hddUserId")) or None,
        "d_vip_type": hidden.get("hddVipType", ""),
        "d_image_count": _int_or_none(hidden.get("countImage")) or (len(images) or None),
        "d_image_1": images[0] if images else "",
        "d_seller_name": seller_name,
        "d_seller_url": (
            _first(salon, './/h3[contains(@class,"name")]//a/@href')
            or _first(salon, './/*[contains(@class,"link-sub-domain")]//a/@href')
        ) if salon is not None else "",
        "d_seller_address": _first(salon, './/*[contains(@class,"des")]//p//text()') if salon is not None else "",
        "d_description": _text_of(desc_nodes[0])[:DESCRIPTION_MAX] if desc_nodes else "",
        "d_specs": json.dumps(specs, ensure_ascii=False) if specs else "",
    }



def table_exists(conn, name: str) -> bool:
    """Check whether a table already exists in the SQLite database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def merge_details(conn, rows: list[dict]) -> list[dict]:
    """Merge detail-page data (its own table) into each record before exporting CSV/JSONL.

    Detail data lives in a separate table because it only exists after an extra crawl pass:
    if it were written into oto_cars, every listing re-crawl (ON CONFLICT DO UPDATE) would
    wipe those detail columns.
    """
    if not rows or not table_exists(conn, DETAIL_TABLE):
        return rows
    details = {r["url"]: r for r in storage.read_rows(conn, DETAIL_TABLE)}
    for row in rows:
        detail = details.get(row.get("url"))
        for col in DETAIL_COLUMNS:
            if col != "url":
                row[col] = detail.get(col) if detail else None
    return rows


def enrich_details(
    session: ScraperSession,
    conn,
    limit: int | None = None,
    refresh: bool = False,
    save_raw: bool = False,
    only_urls: set[str] | None = None,
) -> int:
    """Crawl detail pages for listings that do not have one yet (already-done rows are skipped,
    so the job is resumable).

    only_urls: crawl exactly this set of URLs (used to back-fill a small batch).
    """
    storage.create_table(conn, DETAIL_TABLE, DETAIL_COLUMNS)
    storage.ensure_columns(conn, DETAIL_TABLE, DETAIL_COLUMNS)

    done = set() if refresh else {r[0] for r in conn.execute(f'SELECT url FROM "{DETAIL_TABLE}"')}
    urls = [r[0] for r in conn.execute(f'SELECT url FROM "{TABLE}" ORDER BY url')]
    if only_urls is not None:
        todo = [u for u in urls if u in only_urls]
    else:
        todo = [u for u in urls if u not in done]
    if limit is not None:
        todo = todo[:limit]
    log.info("Detail pages: %s listings to crawl (already done %s / total %s)",
             len(todo), len(done), len(urls))
    if not todo:
        return 0

    buffer: list[dict] = []
    ok = fail = 0
    for url in tqdm(todo, desc="Details", unit="listing"):
        html_text = session.get_text(url, headers={"Referer": f"{BASE_URL}/mua-ban-xe"})
        if html_text is None:
            fail += 1
            continue
        if save_raw:
            storage.save_raw(html_text, f"detail_{url.rsplit('aidxc', 1)[-1]}")
        buffer.append(parse_detail_page(html_text, url))
        ok += 1
        if len(buffer) >= DETAIL_BATCH:
            storage.upsert_rows(conn, DETAIL_TABLE, buffer)
            buffer.clear()
    if buffer:
        storage.upsert_rows(conn, DETAIL_TABLE, buffer)
    log.info("Detail pages: finished %s listings, %s failed", ok, fail)
    return ok


# --------------------------------------------------------------- re-parse raw HTML



RAW_PAGE_RE = re.compile(r"^oto_(?P<brand>[a-z]+)_p(?P<page>\d+)\.html$")


def parse_raw_files(
    brands: Iterable[str] | None = None,
    only_used: bool = True,
    exclude_sold: bool = False,
) -> list[dict]:
    """Re-parse the raw HTML stored in data/raw (no network access).

    Use this after fixing the parser: no need to re-crawl 181 pages, just re-run the parse step.
    """
    files = sorted(config.DATA_RAW.glob("oto_*_p*.html"))
    records: list[dict] = []
    used = 0
    for path in files:
        match = RAW_PAGE_RE.match(path.name)
        if not match:
            continue
        brand, page = match.group("brand"), int(match.group("page"))
        if brands and brand not in brands:
            continue
        tree = html.fromstring(path.read_text(encoding="utf-8"))
        page_url = list_url(brand, page)
        used += 1
        for item in tree.xpath(ITEM_XPATH):
            record = parse_item(item, page_url)
            if not record:
                continue
            if only_used and record["condition"].lower() != "xe cũ":
                continue
            if exclude_sold and record["sold"]:
                continue
            records.append(record)
    log.info("Re-parsed %s raw HTML files -> %s records", used, len(records))
    return records


# -------------------------------------------------------------------- crawl
def list_url(brand: str, page: int) -> str:
    """Listing URL: page 1 has no suffix, later pages use /p<N>."""
    base = f"{BASE_URL}/mua-ban-xe-{brand}"
    return base if page <= 1 else f"{base}/p{page}"


def coerce_numeric(rows: Iterable[dict]) -> list[dict]:
    """Coerce numeric columns to int (SQLite returns every column as TEXT when read back)."""
    out: list[dict] = []
    for row in rows:
        for column in NUMERIC_COLUMNS:
            value = row.get(column)
            if value in (None, ""):
                row[column] = None
                continue
            try:
                row[column] = int(float(value))
            except (TypeError, ValueError):
                row[column] = None
        out.append(row)
    return out


def dedupe_rows(rows: Iterable[dict]) -> list[dict]:
    """Drop duplicate listings by url (keeping the first occurrence).

    Needed because while crawling, newly posted listings shift the pages, so the same listing
    can show up on two different pages.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = row.get("url") or row.get("id") or ""
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique



def crawl_brand(
    session: ScraperSession,
    brand: str,
    max_pages: int | None = None,
    only_used: bool = True,
    exclude_sold: bool = False,
    save_raw: bool = False,
    page_retries: int = 3,
) -> Iterable[dict]:
    """Yield every record of one brand, stopping exactly at the advertised listing count.

    Two quirks of this site have to be handled:
    1. An out-of-range page (e.g. /p999) does NOT return 404 — it returns "0 tin" plus a list
       that falls back to page 1, so the number of pages must come from the counter
       ("Có N tin").
    2. The server occasionally returns an empty page -> retry a few times before giving up.
    """
    page = 1
    state = {"last_page": max_pages or 1, "total": None}
    bar = tqdm(total=state["last_page"], desc=f"{BRANDS.get(brand, brand):<11}", unit="page")

    try:
        while page <= state["last_page"]:
            url = list_url(brand, page)
            records: list[dict] = []

            for attempt in range(1, page_retries + 1):
                html_text = session.get_text(url, headers={"Referer": f"{BASE_URL}/mua-ban-xe"})
                if html_text is None:
                    time.sleep(2 * attempt)
                    continue

                if save_raw:
                    storage.save_raw(html_text, f"oto_{brand}_p{page:03d}")

                # Page 1: read the total listing count to know how many pages to crawl.
                if page == 1 and state["total"] is None:
                    state["total"] = parse_total(html_text)
                    if state["total"]:
                        state["last_page"] = math.ceil(state["total"] / PER_PAGE)
                        if max_pages is not None:
                            state["last_page"] = min(state["last_page"], max_pages)
                        log.info("[%s] %s listings in total -> %s pages",
                                 brand, state["total"], state["last_page"])
                    else:
                        state["last_page"] = max_pages or 1
                        log.warning("[%s] could not read the listing counter -> crawling %s page(s)",
                                    brand, state["last_page"])
                    bar.total = state["last_page"]

                records = parse_list_page(html_text, url)
                if only_used:
                    kept = [r for r in records if r["condition"].lower() == "xe cũ"]
                    if len(kept) != len(records):
                        log.info("[%s] page %s: dropped %s non-used listing(s)",
                                 brand, page, len(records) - len(kept))
                    records = kept
                if exclude_sold:
                    kept = [r for r in records if not r["sold"]]
                    if len(kept) != len(records):
                        log.info("[%s] page %s: dropped %s sold listing(s)",
                                 brand, page, len(records) - len(kept))
                    records = kept

                if records:
                    break
                log.warning("[%s] page %s returned 0 listings (attempt %s/%s) -> retrying",
                            brand, page, attempt, page_retries)
                time.sleep(2 * attempt)

            if not records:
                log.error("[%s] skipping page %s: no listings after %s attempts",
                          brand, page, page_retries)
                break

            bar.update(1)
            bar.set_postfix_str(f"{len(records)} listings")
            yield from records
            page += 1
    finally:
        bar.close()




# --------------------------------------------------------------------- main
def setup_logging() -> None:
    """Log to the console and to logs/oto_scraper.log."""
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.LOGS_DIR / "oto_scraper.log", encoding="utf-8"),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    """Declare the command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Crawl used cars in the Asian mainstream segment from oto.com.vn",
    )
    parser.add_argument("--brands", nargs="+", default=None, choices=list(BRANDS),
                        help="crawl only these brands (default: whatever --group selects)")
    parser.add_argument("--group", choices=("all", "asia", "other"), default="all",
                        help="brand group: asia = six Asian mainstream brands, other = the rest")
    parser.add_argument("--pages", type=int, default=None,
                        help="limit the number of pages per brand (default: crawl everything)")
    parser.add_argument("--include-new", action="store_true",
                        help="also take 'Xe mới' (brand-new) listings (default: used cars only)")
    parser.add_argument("--exclude-sold", action="store_true",
                        help="drop sold listings (class 'sold'; the site removes the call button, "
                             "so phone/origin are missing for them)")
    parser.add_argument("--save-raw", action="store_true",
                        help="save the raw HTML of every page under data/raw")
    parser.add_argument("--out", default="oto_cars", help="output CSV/JSONL file name")
    parser.add_argument("--from-db", action="store_true",
                        help="do not crawl: just re-export CSV/JSONL from the database")
    parser.add_argument("--from-raw", action="store_true",
                        help="do not crawl: re-parse the raw HTML in data/raw (after a parser fix)")
    parser.add_argument("--detail", action="store_true",
                        help="also crawl each listing's detail page (description, colour, seats, "
                             "salon...); about 1 request per listing, so it takes a while")
    parser.add_argument("--detail-only", action="store_true",
                        help="crawl detail pages only, for the listings already in the database")
    parser.add_argument("--detail-limit", type=int, default=None,
                        help="cap the number of detail pages to crawl (for quick tests)")
    parser.add_argument("--detail-refresh", action="store_true",
                        help="re-crawl detail pages even for listings that already have one")
    parser.add_argument("--detail-save-raw", action="store_true",
                        help="save the raw HTML of detail pages under data/raw (large files)")
    parser.add_argument("--detail-missing-price", action="store_true",
                        help="back-fill detail pages for listings with NO price, to recover "
                             "raw_price_text")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()

    # --group: split the work between the two owners of this source
    if args.brands is None:
        if args.group == "asia":
            args.brands = list(BRANDS_ASIA)
        elif args.group == "other":
            args.brands = list(BRANDS_OTHER)
        else:
            args.brands = list(BRANDS)

    if args.detail_missing_price:
        args.detail_only = True  # back-filling details -> read the DB only, do not re-crawl listings
    if args.detail_only:
        args.from_db = True

    conn = storage.open_db()
    storage.create_table(conn, TABLE, COLUMNS)
    storage.ensure_columns(conn, TABLE, COLUMNS)
    per_brand: Counter = Counter()

    if args.from_db:
        all_rows = coerce_numeric(storage.read_rows(conn, TABLE))
        log.info("Re-exporting from the DB: %s listings (no crawling)", len(all_rows))
    elif args.from_raw:
        all_rows = dedupe_rows(
            parse_raw_files(
                args.brands,
                only_used=not args.include_new,
                exclude_sold=args.exclude_sold,
            )
        )
        storage.upsert_rows(conn, TABLE, all_rows)
        log.info("Re-parsed and overwrote %s listings in the DB from raw HTML", len(all_rows))
    else:
        all_rows = []
        with ScraperSession() as session:
            for brand in args.brands:
                before = len(all_rows)
                all_rows.extend(
                    crawl_brand(
                        session,
                        brand,
                        max_pages=args.pages,
                        only_used=not args.include_new,
                        exclude_sold=args.exclude_sold,
                        save_raw=args.save_raw,
                    )
                )
                storage.upsert_rows(conn, TABLE, all_rows)
                log.info("-> %s done: %s listings", BRANDS[brand], len(all_rows) - before)

        duplicates = len(all_rows) - len(dedupe_rows(all_rows))
        if duplicates:
            log.warning("%s duplicate urls (new listings pushed older ones across pages) -> removed",
                        duplicates)
        all_rows = dedupe_rows(all_rows)

    for row in all_rows:
        per_brand[row.get("brand") or "?"] += 1

    # Crawl detail pages too, when requested (~1 request per listing)
    if args.detail or args.detail_only:
        only_urls = None
        if args.detail_missing_price:
            only_urls = {r["url"] for r in all_rows if not (r.get("price_text") or "").strip()}
            log.info("Back-filling detail pages for %s listings without a price", len(only_urls))
        with ScraperSession() as session:
            enrich_details(
                session,
                conn,
                limit=args.detail_limit,
                refresh=args.detail_refresh,
                save_raw=args.detail_save_raw,
                only_urls=only_urls,
            )

    # Merge detail data (when available) into the records before exporting
    detail_count = storage.count_rows(conn, DETAIL_TABLE) if table_exists(conn, DETAIL_TABLE) else 0
    if detail_count:
        all_rows = merge_details(conn, all_rows)
        export_columns = DETAIL_EXPORT_COLUMNS
    else:
        export_columns = COLUMNS

    csv_path = storage.save_csv(all_rows, args.out, export_columns)
    jsonl_path = storage.save_jsonl(all_rows, args.out)

    total_db = storage.count_rows(conn, TABLE)
    conn.close()

    log.info("=" * 62)
    for name, count in per_brand.most_common():
        log.info("  %-12s %5d listings", name, count)
    log.info("-" * 62)
    log.info("Exported this run : %s listings (deduplicated)", len(all_rows))
    log.info("Total in the DB   : %s (primary key = url)", total_db)
    sold_count = sum(1 for r in all_rows if r.get("sold"))
    log.info("Of which sold     : %s listings (%.1f%%) — use --exclude-sold to drop them",
             sold_count, sold_count / len(all_rows) * 100 if all_rows else 0)
    if detail_count:
        log.info("Detail pages      : %s listings crawled (merged into CSV/JSONL)", detail_count)
    log.info("CSV   : %s", csv_path)
    log.info("JSONL : %s", jsonl_path)

    priced = [r["price_vnd"] for r in all_rows if r.get("price_vnd")]
    if priced:
        log.info("Price: %s/%s listings have a price | min %.0f million | median %.0f million | "
                 "max %.2f billion VND",
                 len(priced), len(all_rows),
                 min(priced) / 1e6,
                 sorted(priced)[len(priced) // 2] / 1e6,
                 max(priced) / 1e9)
    return 0


if __name__ == "__main__":
    sys.exit(main())

