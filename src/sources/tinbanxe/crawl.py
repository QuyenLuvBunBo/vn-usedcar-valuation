"""Crawler for tinbanxe.vn used-car classifieds (per-brand listing pages).

Recon facts (2026-10-20, docs/sources/tinbanxe.md):
  * Server-rendered HTML. Listing: https://tinbanxe.vn/mua-ban/oto/<brand>/cu/  (the page
    /mua-ban/oto/toyota/vios/cu/ exists; the brand-level URL and PAGE_PARAM are UNVERIFIED ->
    run `python -m tools.paging <url>` first).
  * Ad URL: https://tinbanxe.vn/<slug>-<id>/ ; ids reach ~88,600, so the archive is large enough
    to cover the 6,000-row quota.
  * Card: title, description beginning "Xe Xăng, Số sàn, 5 chỗ, màu Bạc, đã đi 86 km ...",
    price, province, then year / (blank) / transmission / fuel.
  * ⚠ "đã đi 86 km" may represent thousands of km (the description may say "odo 86.000km"); this is an inferred rule.
  * Real saved cards use div.t-x-list; location is in the first .info-2 .color-primary row, not the line after price.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from typing import Sequence
from urllib.parse import urljoin

from lxml import html
from tqdm import tqdm

from ...common import config, storage
from ...common.http_client import ScraperSession
from ...common.parsing import clean_text, text_of

SOURCE = "tinbanxe"
BASE_URL = "https://tinbanxe.vn"
PAGE_PARAM = "page"   # UNVERIFIED
TABLE = "tinbanxe_cars"
DETAIL_TABLE = "tinbanxe_car_details"
DETAIL_COLUMNS = [
    "url",
    "d_brand",
    "d_model",
    "d_year",
    "d_body",
    "d_fuel",
    "d_transmission",
    "d_mileage_km",
    "d_engine_capacity",
    "d_seats",
    "d_origin",
    "d_seller_name",
    "d_seller_type",
    "d_price_vnd",
    "d_location",
]
BRANDS = ["toyota", "honda", "hyundai", "kia", "vinfast", "mazda", "ford", "audi", "bmw", "mercedes-benz",
          "suzuki", "chevrolet", "infiniti", "genesis", "peugeot", "mitsubishi", "subaru", "porsche", "lexus",
          "mini", "renault", "nissan", "volkswagen", "isuzu", "jaguar", "volvo", "mg", "dongfeng", "lynk-co",
          "skoda", "ram", "wuling", "byd", "haima", "haval", "gac"]   # from the site's own menu

log = logging.getLogger(SOURCE)
AD_RE = re.compile(r"^(?:https://tinbanxe\.vn)?/([a-z0-9-]+)-(\d+)/?$")
PRICE_RE = re.compile(r"^\d[\d.,]*\s*(?:tỷ|tỉ|triệu|tr)(?:\s*\d+\s*triệu)?$", re.I)
HEAD_RE = re.compile(r"^Xe\s+(?P<fuel>[^,]+),\s*(?P<gearbox>[^,]+),\s*(?P<seats>\d+)\s*chỗ", re.I)
COLOR_RE = re.compile(r"màu\s+(?P<color>[^,]+?)\s*(?=,|$)", re.I)
KM_RE = re.compile(r"đã đi\s+(?P<km>[\d.,]+)\s*km", re.I)
IMG_TS_RE = re.compile(r"image_tin_dang/(\d{4})_(\d{2})/(\d{9,10})-")


def list_url(brand: str, page: int) -> str:
    base = f"{BASE_URL}/mua-ban/oto/{brand}/cu/"
    return base if page <= 1 else f"{base}?{PAGE_PARAM}={page}"


def parse_card(card, href: str, brand: str) -> dict:
    lines = [t for t in (clean_text(x) for x in card.itertext()) if t]
    m = AD_RE.match(href.replace(BASE_URL, ""))
    title = clean_text("".join(card.xpath(".//h3//text()")))
    spec = next((ln for ln in lines if ln.startswith("Xe ") and "chỗ" in ln), "")
    head, color_m, km_m = HEAD_RE.match(spec), COLOR_RE.search(spec), KM_RE.search(spec)
    desc_start = km_m.end() if km_m else (color_m.end() if color_m else (head.end() if head else 0))
    price = next((ln for ln in lines if PRICE_RE.match(ln)), "")

    # On real Tinbanxe cards, the line after the price is often "Xe cũ 2003",
    # not the location. Prefer the location row in .info-2; keep a fallback for
    # small/reconstructed fixtures and older markup variants.
    location_parts = card.xpath(
        './/ul[contains(concat(" ", normalize-space(@class), " "), " info-2 ")]'
        '/li[contains(concat(" ", normalize-space(@class), " "), " color-primary ")][1]//text()'
    )
    province = clean_text(" ".join(location_parts))
    if not province:
        province_footer = card.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " tinxe-location-footer ")]//text()')
        province = clean_text(" ".join(province_footer))
    if not province:
        i = lines.index(price) if price in lines else -1
        province = lines[i + 1] if i >= 0 and i + 1 < len(lines) else ""

    year = next((match.group(1) for text in (title, *lines) if (match := re.search(r"\b((?:19|20)\d{2})\b", text))), "")
    img = (card.xpath(".//img/@src") or [""])[0]
    return {
        "url": urljoin(BASE_URL, href), "id": m.group(2) if m else "", "brand": brand, "title": title,
        "price_text": price, "province": province, "year_text": year,
        "fuel": head.group("fuel").strip() if head else "", "gearbox": head.group("gearbox").strip() if head else "",
        "seats": head.group("seats") if head else "", "color": color_m.group("color").strip() if color_m else "",
        "km_text": km_m.group("km") if km_m else "", "desc": clean_text(spec[desc_start:]),
        "img_src": img,
    }


def _walk_json_objects(obj):
    """Duyet cac object trong JSON-LD, ke ca @graph va danh sach."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_json_objects(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_json_objects(value)


def _first_value(value):
    """Chuyen mot so gia tri JSON-LD ve text de luu vao SQLite."""
    if isinstance(value, dict):
        return clean_text(str(value.get("name") or value.get("value") or ""))
    if isinstance(value, list):
        return clean_text(", ".join(str(x) for x in value if x is not None))
    if value is None:
        return ""
    return clean_text(str(value))


def extract_visible_label(body_text: str, labels: Sequence[str]) -> str:
    """Read a value shown in the page's visible label/value attributes."""
    text = clean_text(body_text or "")
    for label in labels:
        # Handles flattened page text such as "Kiểu dáng: Sedan" and
        # "Kiểu dáng Sedan" without assuming anything from the vehicle model.
        match = re.search(
            rf"(?i)(?:^|\s){re.escape(label)}\s*:?\s*(Sedan|SUV|Hatchback|MPV|Crossover|Bán tải|Pickup|Van|Wagon|Convertible|Coupe|Truck)(?=\s|$|[,.;])",
            text,
        )
        if match:
            return clean_text(match.group(1))
    return ""


def parse_detail_page(page_html: str, url: str) -> dict:
    """Trich xuat thuoc tinh xe tu JSON-LD va noi dung trang chi tiet."""
    tree = html.fromstring(page_html)
    body_text = clean_text(" ".join(tree.xpath("//body//text()")))

    vehicle = None

    for script in tree.xpath('//script[@type="application/ld+json"]'):
        raw = script.text or ""

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        for obj in _walk_json_objects(data):
            types = obj.get("@type", [])
            if isinstance(types, str):
                types = [types]

            if any(t in ("Car", "Product", "Vehicle") for t in types):
                vehicle = obj
                break

        if vehicle:
            break

    if not vehicle:
        return {
            "url": url,
            "d_brand": "",
            "d_model": "",
            "d_year": "",
            "d_body": "",
            "d_fuel": "",
            "d_transmission": "",
            "d_mileage_km": "",
            "d_engine_capacity": "",
            "d_seats": "",
            "d_origin": "",
            "d_seller_name": "",
            "d_seller_type": "",
            "d_price_vnd": "",
            "d_location": "",
        }

    brand = _first_value(vehicle.get("brand"))
    model = _first_value(vehicle.get("model"))
    year = _first_value(vehicle.get("vehicleModelDate"))
    body_jsonld = _first_value(vehicle.get("bodyType"))
    # Prefer the page's explicit visible field when present: JSON-LD can omit
    # bodyType or contain a generic value that does not match the UI.
    body_visible = extract_visible_label(body_text, ("Kiểu dáng", "Dáng xe", "Loại xe"))
    body = body_visible or body_jsonld
    fuel = _first_value(vehicle.get("fuelType"))
    transmission = _first_value(vehicle.get("vehicleTransmission"))

    offers = vehicle.get("offers") or {}
    if isinstance(offers, list):
        offers = next((x for x in offers if isinstance(x, dict)), {})
    if not isinstance(offers, dict):
        offers = {}

    seller = offers.get("seller") or vehicle.get("seller") or {}
    seller_name = _first_value(seller.get("name")) if isinstance(seller, dict) else _first_value(seller)

    price = offers.get("price", "")

    # JSON-LD tren mau da kiem tra ghi 86, trong khi trang hien 86.000.
    # Vi vay doc so km tu nhan hien thi tren trang, khong tu dong nhan 1000.
    mileage = ""
    mileage_label = "\u0053\u1ed1 km \u0111\u00e3 \u0111i"
    mileage_match = re.search(
        re.escape(mileage_label) + r"\s*:\s*([\d.,]+)",
        body_text,
        flags=re.IGNORECASE,
    )
    if mileage_match:
        raw_mileage = mileage_match.group(1)
        # Tinbanxe dùng dấu chấm phân tách hàng nghìn:
        # "86.000" -> 86000
        mileage_digits = re.sub(r"\D", "", raw_mileage)
        mileage = int(mileage_digits) if mileage_digits else ""

    # Chi lay dung tich neu co don vi ro rang trong noi dung.
    engine_capacity = ""
    engine_patterns = [
        r"\b(\d+(?:[.,]\d+)?)\s*[Ll]\b",
        r"\b(\d{3,4})\s*(?:cc|cm3)\b",
    ]
    for pattern in engine_patterns:
        match = re.search(pattern, body_text, flags=re.IGNORECASE)
        if match:
            engine_capacity = match.group(1).replace(",", ".")
            break

    # Do not trust JSON-LD seatingCapacity by itself: the source may populate
    # a generic/default value (often 5). Keep seats only when the page visibly
    # states the number of seats. Support labels such as "Số chỗ: 7" and text
    # such as "7 chỗ", "7 ghế", or "7 seats". Otherwise leave it blank.
    seats = ""
    seat_patterns = [
        r"(?i)(?:số\s*chỗ(?:\s*ngồi)?|sức\s*chứa)\s*[:：-]?\s*(\d{1,2})\b",
        r"(?i)(?<!\d)(\d{1,2})\s*(?:chỗ|chổ|ghế|seats?)\b",
    ]
    for seat_pattern in seat_patterns:
        seat_match = re.search(seat_pattern, body_text)
        if seat_match:
            seat_value = int(seat_match.group(1))
            if 2 <= seat_value <= 60:
                seats = seat_value
                break
    origin = _first_value(vehicle.get("countryOfOrigin"))

    location = _first_value(vehicle.get("areaServed"))

    # Phan loai nguoi ban chi khi co dau hieu ro rang trong ten.
    seller_type = ""
    seller_lower = seller_name.casefold()
    if any(word in seller_lower for word in ("salon", "showroom", "cong ty", "c\u00f4ng ty")):
        seller_type = "Dealer"
    elif seller_name:
        seller_type = "Private"

    return {
        "url": url,
        "d_brand": brand,
        "d_model": model,
        "d_year": year,
        "d_body": body,
        "d_fuel": fuel,
        "d_transmission": transmission,
        "d_mileage_km": mileage,
        "d_engine_capacity": engine_capacity,
        "d_seats": seats,
        "d_origin": origin,
        "d_seller_name": seller_name,
        "d_seller_type": seller_type,
        "d_price_vnd": _first_value(price),
        "d_location": location,
    }


def parse_list_page(page_html: str, brand: str) -> list[dict]:
    tree = html.fromstring(page_html)
    seen: dict[str, dict] = {}

    for card in tree.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " t-x-list ")]'
    ):
        links = card.xpath(".//h3/a[@href]")
        if not links:
            continue

        a = links[0]
        href = a.get("href", "").strip()

        if not AD_RE.match(href.replace(BASE_URL, "")):
            continue

        rec = parse_card(card, href, brand)

        if rec["id"] and rec["id"] not in seen:
            seen[rec["id"]] = rec

    return list(seen.values())


def setup_logging() -> None:
    config.ensure_dirs()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(config.LOGS_DIR / "tinbanxe.log", encoding="utf-8")])


def crawl_brand(session: ScraperSession, brand: str, max_pages: int | None, save_raw: bool, known: set[str]) -> list[dict]:
    rows: list[dict] = []
    page = 0
    while max_pages is None or page < max_pages:
        page += 1
        text = session.get_text(list_url(brand, page))
        if text is None:
            break
        if save_raw:
            storage.save_raw(text, f"tinbanxe_{brand}_{page:04d}")
        fresh = [r for r in parse_list_page(text, brand) if r["id"] not in known]
        if not fresh:
            if page == 2:
                log.warning("%s: page 2 had no new ads -> PAGE_PARAM=%r is probably wrong", brand, PAGE_PARAM)
            break
        known.update(r["id"] for r in fresh)
        rows.extend(fresh)
    return rows


def crawl_details(
    conn,
    limit: int | None = None,
    save_raw: bool = False,
    refresh: bool = False,
) -> int:
    """Crawl detail pages for listings already stored in SQLite."""

    storage.create_table(conn, DETAIL_TABLE, DETAIL_COLUMNS)

    cars = storage.read_rows(conn, TABLE)
    existing_details = storage.read_rows(conn, DETAIL_TABLE)

    done_urls = {
        row.get("url")
        for row in existing_details
        if row.get("url")
    }

    targets = [
        car
        for car in cars
        if car.get("url") and (refresh or car["url"] not in done_urls)
    ]

    if limit is not None:
        targets = targets[:limit]

    log.info(
        "Detail crawl: listings=%s, already_done=%s, pending=%s",
        len(cars),
        len(done_urls),
        len(targets),
    )

    saved = 0

    with ScraperSession() as session:
        for car in tqdm(targets, desc="tinbanxe details"):
            url = car["url"]

            try:
                page_html = session.get_text(url)

                if not page_html:
                    log.warning("Cannot fetch detail page: %s", url)
                    continue

                detail = parse_detail_page(page_html, url)

                if save_raw:
                    car_id = re.sub(
                        r"\D",
                        "",
                        str(car.get("id") or ""),
                    )
                    storage.save_raw(
                        page_html,
                        f"tinbanxe_ad_detail_{car_id or saved}",
                    )

                storage.upsert_rows(
                    conn,
                    DETAIL_TABLE,
                    [detail],
                )

                saved += 1

            except Exception:
                log.exception("Failed to crawl detail: %s", url)

    log.info(
        "Detail crawl finished: saved=%s -> table=%s",
        saved,
        DETAIL_TABLE,
    )

    return saved


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crawl tinbanxe.vn used cars")
    p.add_argument("--brands", nargs="+", default=BRANDS, choices=BRANDS)
    p.add_argument("--pages", type=int, default=None, help="max listing pages per brand")
    p.add_argument("--save-raw", action="store_true")
    p.add_argument("--from-raw", action="store_true")
    p.add_argument("--detail", action="store_true", help="crawl detail pages for existing listings")
    p.add_argument("--refresh-details", action="store_true", help="re-crawl details even when URL already exists in SQLite")
    p.add_argument("--detail-limit", type=int, default=None, help="maximum number of detail pages to crawl")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    conn = storage.open_db()
    storage.create_table(conn, TABLE, ["id", "brand", "title", "price_text", "province", "year_text", "fuel", "gearbox",
                                       "seats", "color", "km_text", "desc", "img_src"])
    if args.detail or args.refresh_details:
        try:
            crawl_details(
                conn,
                limit=args.detail_limit,
                save_raw=args.save_raw,
                refresh=args.refresh_details,
            )
        finally:
            conn.close()

        return 0
    rows: list[dict] = []
    known: set[str] = set()
    if args.from_raw:
        for p in sorted(config.DATA_RAW.glob("tinbanxe_*_*.html")):
            brand = p.name.split("_")[1]
            rows += [r for r in parse_list_page(p.read_text(encoding="utf-8"), brand) if r["id"] not in known and not known.add(r["id"])]
    else:
        with ScraperSession() as session:
            for brand in tqdm(args.brands, desc="tinbanxe brands"):
                got = crawl_brand(session, brand, args.pages, args.save_raw, known)
                storage.upsert_rows(conn, TABLE, got)  # checkpoint per brand
                rows += got
                log.info("%s: %s ads (total %s)", brand, len(got), len(rows))
    storage.upsert_rows(conn, TABLE, rows)
    conn.close()
    log.info("done: %s ads -> now run: python -m src.sources.tinbanxe.unified", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
