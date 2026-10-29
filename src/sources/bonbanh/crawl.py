"""bonbanh.com: walk the listing pages and map every card to the 21 unified columns.

The card is self-sufficient (schema.org microdata + a one-line summary), so there is no detail-page step:
one request returns 20 finished records.

Card shape (verified 2026-10-29 on /oto/page,251):

    <li class="car-item row1" itemscope itemtype="http://schema.org/Car">
      <a itemprop="url" href="xe-toyota-innova-cross-2.0-cvt-2024-7030280">
        <div class="cb1">Xe cũ<br><b>2024</b></div>
        <div class="cb2_02"><h3 itemprop="name">Toyota Innova Cross 2.0 CVT - 2024</h3></div>
        <div class="cb3"><b itemprop="price" content="748000000">748 Triệu</b></div>
        <div class="cb4"><b>TP HCM</b></div>
        <div class="cb6_02">*Xe nhập khẩu, màu trắng, máy xăng 2.0 L, số tự động, 8 chỗ, đã đi 35,000 km ...</div>
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import unicodedata
from pathlib import Path

from lxml import html
from tqdm import tqdm

from ...common import config, parsing, schema, storage
from ...common.http_client import ScraperSession

SOURCE = "bonbanh"
PLATFORM = "bonbanh"
BASE_URL = "https://bonbanh.com"
PAGE_URL = "https://bonbanh.com/oto/page,{page}"
TABLE = "bonbanh_ad"

# The two files the team already has; their ids are the ones a top-up crawl must skip.
EXISTING_FILES = ("bonbanh_new.csv", "bonbanh_oldcars.csv")

# The one-line summary is comma separated, so each field can be read on its own.
SUMMARY_PATTERNS = {
    "origin": r"(nhập khẩu|lắp ráp trong nước|trong nước)",
    "fuel": r"(máy xăng|máy dầu|xe điện|hybrid|máy điện)",
    "engine": r"(\d[.,]\d)\s*L\b",
    "transmission": r"(số tự động|số sàn|số bán tự động|bán tự động)",
    "seats": r"(\d{1,2})\s*chỗ",
    "km": r"đã đi\s*([\d.,]+)\s*km",
}

log = logging.getLogger(SOURCE)

# The detail page carries the three fields the listing card omits. Only these are read from it.
DETAIL_SPEC_LABELS = {
    "Kiểu dáng": "body_detail",
    "Xuất xứ": "origin_detail",
    "Hộp số": "transmission_detail",
    "Số chỗ": "seats_detail",
}
DETAIL_COLUMNS = [*DETAIL_SPEC_LABELS.values(), "seller_detail", "seller_name", "date_detail", "detail_done"]

# Every raw field the card carries — the SQLite table mirrors these so a re-run refreshes, not duplicates.
RAW_COLUMNS = ["code", "name", "price_raw", "price_vnd", "province", "summary", *SUMMARY_PATTERNS,
               *DETAIL_COLUMNS]

# Two body styles bonbanh prints in a form the contract does not have (docs/unified_schema.md lists the
# allowed labels). Everything else is handled by schema.normalize_body.
BODY_ALIASES = {"bán tải / pickup": "Pickup", "convertible/cabriolet": "Convertible",
                "van/minivan": "Van", "bán tải": "Pickup"}

# bonbanh writes some makes over two words. The merge keys on the brand, so they are collapsed to one
# canonical spelling — the same names muaban's BRAND_ALIASES uses, so both sources group together.
MULTIWORD_BRANDS = {
    "mercedes benz": "Mercedes-Benz", "mercedes-benz": "Mercedes-Benz",
    "land rover": "Land Rover", "landrover": "Land Rover",
    "rolls royce": "Rolls-Royce", "rolls-royce": "Rolls-Royce",
    "aston martin": "Aston Martin", "alfa romeo": "Alfa Romeo",
    "vin fast": "VinFast",
}


def parse_list_page(page_html: str) -> list[dict]:
    """Parse one listing page -> the raw fields of every card (20 per page)."""
    tree = html.fromstring(page_html)
    records: list[dict] = []
    for card in tree.xpath('//li[contains(@class,"car-item")]'):
        href = parsing.first(card, ".//a/@href")
        code = re.search(r"-(\d{6,})$", href)
        if not href or not code:
            continue                                   # an ad without a code cannot be identified
        summary = parsing.clean_text(" ".join(card.xpath('.//div[contains(@class,"cb6_02")]//text()')))
        fields = {}
        for key, pattern in SUMMARY_PATTERNS.items():
            match = re.search(pattern, summary, re.I)
            fields[key] = parsing.clean_text(match.group(0)) if match else ""
        records.append({
            "url": f"{BASE_URL}/{href.lstrip('/')}",
            "code": code.group(1),
            "name": parsing.clean_text(" ".join(card.xpath('.//h3[@itemprop="name"]//text()'))),
            "price_vnd": (card.xpath('.//b[@itemprop="price"]/@content') or [""])[0],
            "price_raw": parsing.clean_text(" ".join(card.xpath('.//b[@itemprop="price"]//text()'))),
            "province": parsing.clean_text(" ".join(card.xpath('.//div[@class="cb4"]//text()'))),
            "summary": summary,
            **fields,
        })
    return records


def _nfc(value) -> str:
    """Normalize Vietnamese text to NFC before comparing.

    The detail page sometimes delivers decomposed characters ("Ba" + U+0300 + "n"), which looks identical
    but never compares equal to the composed "Bản" used in this file's tables.
    """
    return unicodedata.normalize("NFC", str(value or "")).strip()


def split_name(name: str) -> tuple[str, str, str]:
    """'Toyota Innova Cross 2.0 CVT - 2024' -> ('Toyota', 'Innova Cross 2.0 CVT', '').

    bonbanh prints "<brand> <model> <grade> - <year>". Most makes are one token ("VinFast", "LandRover"),
    but a few are two, and the merge keys on the brand, so they must not become the model
    ("Mercedes Benz GLS" -> brand Mercedes-Benz, not brand Mercedes + model "Benz GLS").
    """
    body = re.sub(r"\s*-\s*\d{4}\s*$", "", name or "").strip()     # drop the trailing "- 2024"
    tokens = body.split()
    for size in (2, 1):
        candidate = " ".join(tokens[:size])
        canonical = MULTIWORD_BRANDS.get(candidate.lower())
        if canonical:
            return canonical, " ".join(tokens[size:]), ""
    brand, _, rest = body.partition(" ")
    return brand, rest.strip(), ""          # the grade is not separable without a model table


def to_unified(raw: dict) -> dict:
    """Map one card to the 21 unified columns (docs/unified_schema.md)."""
    brand, model, trim = split_name(raw.get("name", ""))
    record = dict.fromkeys(schema.SCHEMA_COLUMNS)
    record.update({
        "listing_id": f"BAN_{raw['code']}",
        "source_platform": PLATFORM,
        "brand": brand or "Unknown",
        "model": model or "Unknown",
        "sub_model_trim": trim,
        "manufacture_year": parsing.parse_year_text(raw.get("name", "")),
        "mileage_km": parsing.parse_km_text(re.sub(r"[^\d.,]", "", raw.get("km", ""))),
        "transmission": schema.normalize_transmission(raw.get("transmission")),
        "fuel_type": schema.normalize_fuel(str(raw.get("fuel", "")).replace("xe ", "")),
        "origin": schema.normalize_origin(raw.get("origin_detail") or raw.get("origin")),
        "body_type": BODY_ALIASES.get(_nfc(raw.get("body_detail")).lower(),
                                      schema.normalize_body(raw.get("body_detail"))),
        "engine_capacity": parsing.to_float(raw.get("engine", "").replace(",", ".").replace(" L", "")),
        "seats": parsing.to_int(re.sub(r"\D", "", raw.get("seats", ""))),
        "location_province": schema.normalize_province(raw.get("province")),
        # a salon gets its own subdomain on bonbanh; the detail page is the only place that shows it
        "seller_type": raw.get("seller_detail") or "Unknown",
        "price_vnd": parsing.to_int(raw.get("price_vnd")),
        "source_url": raw.get("url"),
        "listing_date": raw.get("date_detail") or "",     # detail page only
        "scraped_at": config.now_iso(),
        "raw_price_text": raw.get("price_raw"),
        "price_status": schema.price_status(parsing.to_int(raw.get("price_vnd")), raw.get("price_raw")),
    })
    return record



def existing_ids() -> set[str]:
    """listing_ids the team already collected, so a top-up crawl only adds what is missing."""
    ids: set[str] = set()
    for name in EXISTING_FILES:
        path = config.DATA_PROCESSED / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            ids.update(row["listing_id"] for row in csv.DictReader(fh) if row.get("listing_id"))
    return ids


def crawl(from_page: int = 1, to_page: int | None = None, skip_existing: bool = True,
          out: str = "bonbanh_extra") -> list[dict]:
    """Walk the listing pages, keep the ads we do not have yet, and write the 21-column CSV."""
    config.ensure_dirs()
    known = existing_ids() if skip_existing else set()
    if known:
        log.info("%d listing_ids already collected -> they will be skipped", len(known))

    conn = storage.open_db()
    storage.create_table(conn, TABLE, RAW_COLUMNS)
    storage.ensure_columns(conn, TABLE, RAW_COLUMNS)   # the table may predate a parser change

    records: list[dict] = []
    seen: set[str] = set()
    page = max(from_page, 1)
    with ScraperSession() as session:
        with tqdm(desc=SOURCE, unit="trang", initial=page - 1) as bar:
            while to_page is None or page <= to_page:
                page_html = session.get_text(PAGE_URL.format(page=page))
                if page_html is None:
                    log.warning("page %d did not load -> stopping", page)
                    break
                cards = parse_list_page(page_html)
                if not cards:
                    log.info("page %d carries no card -> end of the catalogue", page)
                    break
                fresh = [card for card in cards if card["code"] not in seen]
                if not fresh:
                    log.info("page %d repeats the previous page -> stopping", page)
                    break
                seen.update(card["code"] for card in fresh)
                storage.upsert_rows(conn, TABLE, fresh)
                new = [card for card in fresh if f"BAN_{card['code']}" not in known]
                records.extend(to_unified(card) for card in new)
                bar.update(1)
                bar.set_postfix(giu=f"{len(records):,}")
                page += 1

    conn.close()
    path = storage.save_csv(records, out, schema.SCHEMA_COLUMNS)

def parse_detail_page(page_html: str) -> dict:
    """Read the three fields the listing card does not print: body style, seller type, posting date.

    The detail page is server-rendered and regular: the specs live in `div.box_car_detail` as
    label/value rows, and the seller block exposes an `a.cname` link whose href is the showroom's own
    subdomain — that subdomain is exactly what separates a salon from a private seller
    (src/common/schema.py: seller_type_from_subdomain).
    """
    tree = html.fromstring(page_html)
    found: dict[str, str] = {}

    for row in tree.xpath('//div[contains(@class,"box_car_detail")]//div[@class="row" or @class="row_last"]'):
        label = parsing.clean_text(" ".join(row.xpath('.//div[@class="label"]//text()'))).rstrip(":").strip()
        value = parsing.clean_text(" ".join(row.xpath('.//div[@class="txt_input"]//text()')))
        key = DETAIL_SPEC_LABELS.get(label)
        if key and value:
            found[key] = value

    if not found:
        # no spec table at all: the ad was removed and bonbanh serves a stub. Inventing a seller type
        # here would turn a dead page into a "private seller", so nothing is reported.
        return {}

    seller_href = parsing.first(tree, '//a[contains(@class,"cname")]/@href')
    found["seller_name"] = parsing.first(tree, '//a[contains(@class,"cname")]/text()')
    found["seller_detail"] = schema.seller_type_from_subdomain(seller_href)

    page_text = parsing.clean_text(" ".join(tree.xpath("//text()")))
    # bonbanh prints "Đăng ngày 9/10/2026" — the day and month may be one digit, the year never is
    date_match = re.search(r"Đăng ngày\s*(\d{1,2})/(\d{1,2})/(\d{4})", page_text)
    if date_match:
        found["date_detail"] = f"{date_match.group(3)}-{int(date_match.group(2)):02d}-{int(date_match.group(1)):02d}"
    return found


def crawl_details(limit: int | None = None, skip_existing: bool = True) -> int:
    """Fetch a detail page for every stored card that still lacks one (resumable).

    Cards whose ad is already in `bonbanh_new.csv` / `bonbanh_oldcars.csv` are skipped: those files were
    crawled from detail pages by their owners, so their body style, seller type and date are already in
    the merge. Only the ads this top-up crawl added need the extra request.
    """
    config.ensure_dirs()
    conn = storage.open_db()
    storage.create_table(conn, TABLE, RAW_COLUMNS)
    storage.ensure_columns(conn, TABLE, RAW_COLUMNS)

    known = existing_ids() if skip_existing else set()
    # a row is pending when it was never fetched, when the fetch failed, or when the page had no date
    # (an earlier date rule only accepted two-digit days and months, so those rows are redone here)
    where = ("detail_done IS NULL OR detail_done = '' OR date_detail IS NULL OR date_detail = ''")
    rows = conn.execute(f'SELECT code, url FROM "{TABLE}" WHERE {where} ORDER BY code').fetchall()
    pending = [row for row in rows if f"BAN_{row['code']}" not in known]
    if limit:
        pending = pending[:int(limit)]        # slice after the filter, so --detail-limit means "N pages"
    log.info("%d detail pages to fetch (%d already-collected ads skipped)", len(pending), len(rows) - len(pending))
    if not pending:
        conn.close()
        return 0

    ok = 0
    with ScraperSession() as session:
        with tqdm(total=len(pending), desc=f"{SOURCE} detail", unit="tin") as bar:
            for row in pending:
                url = row["url"]
                page_html = session.get_text(url)
                fields = parse_detail_page(page_html) if page_html else {}
                fields["detail_done"] = "1" if fields else "0"
                storage.upsert_rows(conn, TABLE, [{"url": url, **fields}])
                ok += 1 if fields else 0
                bar.update(1)
                bar.set_postfix(ok=f"{ok:,}")
    conn.close()
    log.info("%d detail pages parsed", ok)
    return ok


    log.info("%d ads kept -> %s", len(records), path)
    return records


def reexport(out: str = "bonbanh_extra", skip_existing: bool = True) -> list[dict]:
    """Re-map every card already stored in SQLite — a parser fix without a second crawl."""
    config.ensure_dirs()
    conn = storage.open_db()
    if not conn.execute("select name from sqlite_master where type='table' and name=?", (TABLE,)).fetchone():
        conn.close()
        log.error("table %s does not exist yet -> crawl first", TABLE)
        return []
    cards = storage.read_rows(conn, TABLE)
    conn.close()
    known = existing_ids() if skip_existing else set()
    records = [to_unified(card) for card in cards if f"BAN_{card['code']}" not in known]
    records.sort(key=lambda row: str(row.get("listing_id")))
    path = storage.save_csv(records, out, schema.SCHEMA_COLUMNS)
    log.info("%d ads re-exported from the database -> %s", len(records), path)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bonbanh.com top-up crawler")
    parser.add_argument("--from-page", type=int, default=1)
    parser.add_argument("--to-page", type=int, default=None)
    parser.add_argument("--pages", type=int, default=None, help="how many pages to walk (default: all)")
    parser.add_argument("--include-existing", action="store_true",
                        help="also write the ads already present in bonbanh_new/bonbanh_oldcars")
    parser.add_argument("--reexport", action="store_true",
                        help="rebuild the CSV from data/scraped.db without any request (after a parser fix)")
    parser.add_argument("--details", action="store_true",
                        help="fetch each stored ad's detail page for body_type / seller_type / listing_date")
    parser.add_argument("--detail-limit", type=int, default=None,
                        help="how many detail pages to fetch this run (resumable)")
    parser.add_argument("--out", default="bonbanh_extra")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.details:
        crawl_details(args.detail_limit, not args.include_existing)
        if not args.reexport:
            return 0
    if args.reexport:
        reexport(args.out, not args.include_existing)
        return 0
    to_page = args.to_page
    if args.pages:
        to_page = args.from_page + args.pages - 1
    crawl(args.from_page, to_page, not args.include_existing, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
