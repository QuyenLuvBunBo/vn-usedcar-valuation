"""Crawler for carmudi.vn (passenger cars). Listing pages -> detail pages -> SQLite.

Site facts (recon 2026-10-20, see docs/sources/carmudi.md):
  * Next.js site; listing page https://www.carmudi.vn/xe-o-to/ shows only ~800-950 active ads,
    so this source can NOT reach 6,000 rows alone (the leader's fallback is tinbanxe.vn).
  * The structured fields are unreliable: unfilled ads default to "Xe mới" / "Xăng" / "Số sàn"
    and "No data" for the year. The title (year, AT/MT) and the free-text description carry the
    real values -> unified.py cross-checks them.

Listing pages are filled by the site's own JSON API (found with DevTools, 2026-10-20):
    POST https://api.carmudi.vn/api/v1/get-car-page?limit=20&page=N      body {"data": "?page=N&last_page=41"}
    response: data.data.data = [ads...], data.data.meta = {current_page, last_page, ...}
The HTML of /xe-o-to/ ignores ?page=N (pagination is client-side), so the HTML list parser is only
used as a fallback / for saved pages.

Every request keeps the repo rules: 1.5 s delay, retry/backoff, 429 handling (via ScraperSession).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Sequence
from urllib.parse import urljoin

import requests
from lxml import html
from tqdm import tqdm

from ...common import config, storage
from ...common.http_client import ScraperSession
from ...common.parsing import clean_text, text_of

SOURCE = "carmudi"
BASE_URL = "https://www.carmudi.vn"
LIST_URL = f"{BASE_URL}/xe-o-to/"
PAGE_PARAM = "page"          # UNVERIFIED: confirm with `python -m tools.paging <LIST_URL>`
API_URL = "https://api.carmudi.vn/api/v1/get-car-page"
PAGE_SIZE = 20
TABLE_LIST = "carmudi_cars"
TABLE_DETAIL = "carmudi_car_details"

log = logging.getLogger(SOURCE)

AD_HREF_RE = re.compile(r"/ban-xe-oto-[a-z0-9-]*?-?(\d+)/?$", re.I)
DATE_RE = re.compile(r"Ngày đăng:\s*(\d{4}-\d{2}-\d{2})")
PRICE_TXT_RE = re.compile(r"\d[\d.,]*\s*(?:tỷ|tỉ|triệu|tr|nghìn|ngàn)(?:\s*\d[\d.,]*\s*(?:triệu|tr|nghìn|ngàn))?", re.I)
TOTAL_RE = re.compile(r"Có\s+([\d.,]+)\s+tin bán xe", re.I)


# ----------------------------------------------------------------- listing page
def list_url(page: int) -> str:
    return LIST_URL if page <= 1 else f"{LIST_URL}?{PAGE_PARAM}={page}"


def parse_total(page_html: str) -> int | None:
    """'Có 807 tin bán xe ...' -> 807."""
    m = TOTAL_RE.search(clean_text(page_html))
    return int(re.sub(r"\D", "", m.group(1))) if m else None


def _card_lines(card) -> list[str]:
    return [t for t in (clean_text(x) for x in card.itertext()) if t]


def parse_card(card, href: str) -> dict:
    """One listing card -> raw dict. Card text order (observed): year, mileage, fuel,
    transmission, price, province."""
    lines = _card_lines(card)
    m = AD_HREF_RE.search(href)
    title = clean_text("".join(card.xpath(".//h3//text()"))) or (lines[0] if lines else "")
    price_text = next((ln for ln in lines if PRICE_TXT_RE.fullmatch(ln)), "")
    rest = [ln for ln in lines if ln != title and ln != price_text]
    # the province is the last remaining line; the 4 attribute lines come first
    province = rest[-1] if len(rest) >= 5 else ""
    attrs = rest[:4] if province else rest
    attrs += [""] * (4 - len(attrs))
    return {
        "url": urljoin(BASE_URL, href),
        "id": m.group(1) if m else "",
        "title": title,
        "year_text": attrs[0],
        "km_text": attrs[1],
        "fuel": attrs[2],
        "gearbox": attrs[3],
        "price_text": price_text,
        "province": province,
    }


def parse_list_page(page_html: str) -> list[dict]:
    """Return one raw dict per ad on a listing page (deduplicated by ad id)."""
    tree = html.fromstring(page_html)
    seen: dict[str, dict] = {}
    for link in tree.xpath('//h3/a[contains(@href,"/ban-xe-oto-")]'):
        href = link.get("href") or ""
        if not AD_HREF_RE.search(href):
            continue
        card = link
        for _ in range(4):  # climb until the container also holds the price
            card = card.getparent()
            if card is None:
                break
            if PRICE_TXT_RE.search(text_of(card)) and len(card.xpath(".//h3")) == 1:
                break
        if card is None:
            continue
        rec = parse_card(card, href)
        if rec["id"] and rec["id"] not in seen:
            seen[rec["id"]] = rec
    return list(seen.values())


# ------------------------------------------------------------------ detail page
LABEL_KEYS = {  # site label -> ASCII column name
    "Nhiên liệu": "d_fuel", "Số KM": "d_km", "Hộp số": "d_gearbox", "Địa điểm": "d_location",
    "Đăng bởi": "d_seller", "Hãng xe": "d_brand", "Dòng xe": "d_model", "Kiểu dáng": "d_body",
    "Xuất xứ": "d_origin", "Số chỗ": "d_seats", "Màu sắc": "d_color",
}


def parse_detail_page(page_html: str, url: str) -> dict:
    """Detail page -> fields the listing card lacks (posted date, seller, description, body type)."""
    tree = html.fromstring(page_html)
    lines = _card_lines(tree)
    flat = " | ".join(lines)
    out: dict[str, str] = {"url": url, "d_title": clean_text("".join(tree.xpath("//h1//text()")))}
    m = DATE_RE.search(" ".join(lines))
    out["d_posted"] = m.group(1) if m else ""

    price = ""
    h1 = tree.xpath("//h1")
    if h1:  # price is the heading right after the title
        nxt = h1[0].xpath("following::*[self::h2 or self::h3][1]//text()")
        price = clean_text("".join(nxt))
    out["d_price_text"] = price if PRICE_TXT_RE.search(price) else ""

    for label, key in LABEL_KEYS.items():
        value = ""
        for i, ln in enumerate(lines):
            if ln == label and i + 1 < len(lines):
                value = lines[i + 1]
                break
            if ln.startswith(label) and len(ln) > len(label):  # "Hãng xeToyota" (label+value fused)
                value = ln[len(label):].strip()
                break
        out[key] = value

    desc = ""
    if "Mô tả" in lines:
        i = lines.index("Mô tả")
        desc = " ".join(ln for ln in lines[i + 1:i + 6] if ln not in ("Xem tất cả",))
    out["d_description"] = desc
    out["d_has_phone_block"] = "1" if "Gọi người bán" in flat else ""
    return out


# ------------------------------------------------------------------- helpers
def dedupe_rows(rows: Sequence[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for r in rows:
        seen[r["url"]] = r
    return list(seen.values())


def setup_logging() -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.LOGS_DIR / "carmudi.log", encoding="utf-8")],
    )


def crawl_listings(max_pages: int | None, save_raw: bool) -> list[dict]:
    """Walk listing pages until a page brings no NEW ad id (also protects against a wrong
    PAGE_PARAM: page 2 would repeat page 1, so we stop and warn)."""
    rows: list[dict] = []
    known: set[str] = set()
    with ScraperSession() as session, tqdm(desc="carmudi list", unit="page") as bar:
        page = 0
        while max_pages is None or page < max_pages:
            page += 1
            text = session.get_text(list_url(page))
            if text is None:
                break
            if save_raw:
                storage.save_raw(text, f"carmudi_list_{page:04d}")
            if page == 1:
                log.info("site reports %s ads in total", parse_total(text))
            fresh = [r for r in parse_list_page(text) if r["id"] not in known]
            if not fresh:
                if page == 2:
                    log.warning("page 2 had no new ads -> PAGE_PARAM=%r is probably wrong", PAGE_PARAM)
                break
            known.update(r["id"] for r in fresh)
            rows.extend(fresh)
            bar.update(1)
    return rows


def crawl_details(rows: list[dict], conn, save_raw: bool, limit: int | None = None) -> list[dict]:
    done = {r["url"] for r in storage.read_rows(conn, TABLE_DETAIL)}
    todo = [r["url"] for r in rows if r["url"] not in done][:limit]
    out: list[dict] = []
    with ScraperSession() as session:
        for url in tqdm(todo, desc="carmudi detail", unit="ad"):
            text = session.get_text(url)
            if text is None:
                continue
            if save_raw:
                storage.save_raw(text, "carmudi_detail_" + url.rstrip("/").rsplit("-", 1)[-1])
            out.append(parse_detail_page(text, url))
            if len(out) % 50 == 0:  # checkpoint so a long crawl can resume
                storage.upsert_rows(conn, TABLE_DETAIL, out[-50:])
    if out:
        storage.upsert_rows(conn, TABLE_DETAIL, out[-(len(out) % 50 or 50):])
    return out


def parse_raw_files() -> tuple[list[dict], list[dict]]:
    """--from-raw: re-parse saved HTML (read as decoded text, never bytes)."""
    lists, details = [], []
    for p in sorted(config.DATA_RAW.glob("carmudi_list_*.html")):
        lists.extend(parse_list_page(p.read_text(encoding="utf-8")))
    for p in sorted(config.DATA_RAW.glob("carmudi_detail_*.html")):
        m = re.search(r"carmudi_detail_(\d+)", p.name)
        url = next((r["url"] for r in lists if m and r["id"] == m.group(1)), f"{BASE_URL}/?id={m.group(1) if m else ''}")
        details.append(parse_detail_page(p.read_text(encoding="utf-8"), url))
    return dedupe_rows(lists), details


# ------------------------------------------------------------------- JSON API
# Keys are UNVERIFIED except id / name / slug / brandName (seen in DevTools). Every other field is
# looked up through candidate names; run `--probe` and fix the lists below if a column is empty.
CANDIDATES = {
    "title": ("name", "title"),
    "brand": ("brandName", "brand_name", "brand"),
    "model": ("modelName", "model_name", "model"),
    "price": ("price", "priceText", "price_text", "priceFormat", "formattedPrice"),
    "year": ("year", "manufactureYear", "manufacture_year", "yearOfManufacture"),
    "km": ("mileage", "km", "odometer", "kilometer", "kms"),
    "fuel": ("fuel", "fuelName", "fuelType", "fuel_type"),
    "gearbox": ("transmission", "transmissionName", "gearbox", "transmissionType"),
    "province": ("cityName", "city", "province", "location", "address"),
    "body": ("bodyTypeName", "bodyType", "body_type", "body"),
    "seller": ("sellerName", "userName", "user_name", "createdBy", "seller", "user"),
    "posted": ("created_at", "createdAt", "published_at", "publishedAt", "postedAt", "updated_at"),
    "desc": ("description", "content", "desc"),
}


def _scalar(value) -> str:
    """API values may be numbers or {id,name}/{title} objects -> clean string ('' when empty)."""
    if value is None or value is False:
        return ""
    if isinstance(value, dict):
        for k in ("name", "title", "label", "value"):
            if value.get(k):
                return _scalar(value[k])
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return clean_text(str(value))


def pick(item: dict, field: str) -> str:
    for key in CANDIDATES[field]:
        text = _scalar(item.get(key))
        if text:
            return text
    return ""


def item_to_row(item: dict) -> dict:
    slug = _scalar(item.get("slug")).lstrip("/")
    rid = _scalar(item.get("id"))
    return {
        "url": urljoin(BASE_URL + "/", slug) if slug else f"{BASE_URL}/ban-xe-oto-{rid}/",
        "id": rid, "title": pick(item, "title"), "brand": pick(item, "brand"), "model": pick(item, "model"),
        "year_text": pick(item, "year"), "km_text": pick(item, "km"), "fuel": pick(item, "fuel"),
        "gearbox": pick(item, "gearbox"), "price_text": _scalar(item.get("priceDisplay")) or pick(item, "price"), "province": pick(item, "province"),
        "body": pick(item, "body"), "seller": pick(item, "seller"), "posted": pick(item, "posted"),
        "desc": pick(item, "desc"),
    }


def api_post(session: ScraperSession, page: int, last_page: int) -> dict | None:
    """POST one API page with the repo's delay/retry rules (ScraperSession only wraps GET)."""
    url = f"{API_URL}?limit={PAGE_SIZE}&page={page}"
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/plain, */*",
               "Origin": BASE_URL, "Referer": f"{BASE_URL}/xe-o-to/"}
    body = {"data": f"?page={page}&last_page={last_page}"}
    for attempt in range(1, session.max_retries + 1):
        session._sleep_if_needed()
        try:
            resp = session.session.post(url, json=body, headers=headers, timeout=session.timeout)
            session._last_request_at = time.monotonic()
            if resp.status_code == 429:
                time.sleep(float(resp.headers.get("Retry-After", session.delay * 5)))
                continue
            if resp.status_code in (401, 403):
                log.error("%s from the API -> blocked or needs headers/cookie", resp.status_code)
                return None
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("API page %s attempt %s/%s failed: %s", page, attempt, session.max_retries, exc)
            time.sleep(2 ** attempt)
    return None


def unpack(payload: dict) -> tuple[list[dict], int | None]:
    inner = (((payload or {}).get("data") or {}).get("data") or {})
    items = inner.get("data") or []
    last = (inner.get("meta") or {}).get("last_page")
    return items, int(last) if last else None


def crawl_api(max_pages: int | None, save_raw: bool, last_page: int = 41) -> list[dict]:
    rows: list[dict] = []
    known: set[str] = set()
    with ScraperSession() as session:
        page = 0
        with tqdm(desc="carmudi api", unit="page") as bar:
            while max_pages is None or page < max_pages:
                page += 1
                payload = api_post(session, page, last_page)
                if payload is None:
                    break
                items, last = unpack(payload)
                if page == 1 and last:
                    last_page = last
                    log.info("API reports %s pages (~%s ads)", last, last * PAGE_SIZE)
                if save_raw:
                    storage.save_raw(json.dumps(payload, ensure_ascii=False), f"carmudi_api_{page:04d}")
                fresh = [item_to_row(i) for i in items if _scalar(i.get("id")) not in known]
                if not fresh:
                    break
                known.update(r["id"] for r in fresh)
                rows.extend(fresh)
                bar.update(1)
                if page >= last_page:
                    break
    return rows


def probe() -> int:
    """Print the keys + values of the FIRST ad, so the CANDIDATES lists can be checked/fixed."""
    with ScraperSession() as session:
        payload = api_post(session, 1, 41)
    items, last = unpack(payload or {})
    if not items:
        print("No items. Top-level keys:", list((payload or {}).keys()))
        return 1
    print(f"last_page={last}, ads on page={len(items)}")
    print(json.dumps(items[0], ensure_ascii=False, indent=2)[:4000])
    print("\nmapped ->", json.dumps(item_to_row(items[0]), ensure_ascii=False, indent=2))
    return 0



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crawl carmudi.vn passenger cars")
    p.add_argument("--probe", action="store_true", help="print the first API ad (check field names) and exit")
    p.add_argument("--pages", type=int, default=None, help="limit API pages (20 ads each)")
    p.add_argument("--detail", action="store_true", help="also crawl each detail page (HTML)")
    p.add_argument("--detail-limit", type=int, default=None)
    p.add_argument("--save-raw", action="store_true", help="save API JSON / HTML under data/raw (gitignored)")
    p.add_argument("--from-raw", action="store_true", help="re-parse saved API JSON, no network")
    return p


def rows_from_raw_api() -> list[dict]:
    rows: dict[str, dict] = {}
    for f in sorted(config.DATA_RAW.glob("carmudi_api_*.json")):
        items, _ = unpack(json.loads(f.read_text(encoding="utf-8")))
        for it in items:
            r = item_to_row(it)
            rows[r["id"]] = r
    return list(rows.values())


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    if args.probe:
        return probe()
    conn = storage.open_db()
    storage.create_table(conn, TABLE_LIST, ["id", "title", "brand", "model", "year_text", "km_text", "fuel", "gearbox",
                                            "price_text", "province", "body", "seller", "posted", "desc"])
    storage.create_table(conn, TABLE_DETAIL, ["d_title", "d_posted", "d_price_text", *LABEL_KEYS.values(), "d_description", "d_has_phone_block"])
    rows = rows_from_raw_api() if args.from_raw else crawl_api(args.pages, args.save_raw)
    if rows:  # an older scraped.db may lack the new API columns
        storage.ensure_columns(conn, TABLE_LIST, list(rows[0]))
    storage.upsert_rows(conn, TABLE_LIST, rows)
    details: list[dict] = []
    if args.detail and not args.from_raw:
        details = crawl_details(rows, conn, args.save_raw, args.detail_limit)
        if details:
            storage.ensure_columns(conn, TABLE_DETAIL, list(details[0]))
            storage.upsert_rows(conn, TABLE_DETAIL, details)
    log.info("listings=%s details=%s -> now run: python -m src.sources.carmudi.unified", len(rows), len(details))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
