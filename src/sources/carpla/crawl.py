"""carpla.vn: walk the product sitemap and map every detail page to the 21 unified columns."""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from datetime import datetime, timezone
from html import unescape

from tqdm import tqdm

from ...common import config, parsing, schema, storage
from ...common.http_client import ScraperSession

SOURCE = "carpla"
PLATFORM = "carpla"
SITEMAP_URL = "https://carpla.vn/sitemap_product.xml"
TABLE = "carpla_car"
EXISTING_FILES = ("carpla.csv",)

# same canonical spellings as src/sources/bonbanh, so brand-based grouping agrees across sources
MULTIWORD_BRANDS = {
    "mercedes benz": "Mercedes-Benz", "mercedes-benz": "Mercedes-Benz",
    "land rover": "Land Rover", "landrover": "Land Rover",
    "rolls royce": "Rolls-Royce", "rolls-royce": "Rolls-Royce",
    "aston martin": "Aston Martin", "alfa romeo": "Alfa Romeo",
    "vin fast": "VinFast", "lynk co": "Lynk & Co", "lynk & co": "Lynk & Co",
}
# specs printed as "label|value" pairs in the rendered page; the value is stored under an ASCII key so
# it can also be a SQLite column name
SPEC_FIELDS = {
    "Nhiên liệu": "fuel", "Kiểu dáng": "body", "Hộp số": "transmission",
    "Số chỗ": "seats", "Động cơ": "engine", "Xuất xứ": "origin",
}

log = logging.getLogger(SOURCE)

# carpla prints body styles the contract does not have; map them onto the allowed labels
# (docs/unified_schema.md: Sedan / SUV / Crossover / MPV / Hatchback / Pickup / Van / Truck / Other).
# "Xe du lịch" is carpla's generic "passenger car" tag and "Xe khách" its people carrier.
BODY_ALIASES = {"cuv": "Crossover", "suv": "SUV", "mpv": "MPV", "sedan": "Sedan",
                "hatchback": "Hatchback", "pickup": "Pickup", "bán tải": "Pickup",
                "van": "Van", "van/minibus": "Van", "minivan": "Van",
                "coupe": "Coupe", "convertible": "Convertible",
                "xe du lịch": "Other", "xe khách": "Minibus", "truck": "Truck"}
# The site writes some values more loosely than src/common/schema.py maps them.
FUEL_ALIASES = {"plug-in hybrid": "Hybrid", "hybrid": "Hybrid", "xăng": "Gasoline",
                "dầu": "Diesel", "điện": "Electric"}
TRANSMISSION_ALIASES = {"tự động": "Automatic", "số tự động": "Automatic",
                        "sàn": "Manual", "số sàn": "Manual",
                        "bán tự động": "Other", "số bán tự động": "Other"}

# every raw field a detail page yields — the SQLite table mirrors them so a re-run refreshes a row
RAW_COLUMNS = ["slug", "title", "province", "price_vnd", "odo", "year", "posted_at", *SPEC_FIELDS.values()]


def sitemap_urls(session: ScraperSession) -> list[str]:
    """Every vehicle detail URL carpla advertises, in sitemap order."""
    xml = session.get_text(SITEMAP_URL)
    if not xml:
        log.error("cannot read %s", SITEMAP_URL)
        return []
    return [url for url in re.findall(r"<loc>([^<]+)</loc>", xml) if "/xe/" in url]


def _text(page_html: str) -> str:
    """The rendered text with tags turned into separators, so "label|value" pairs can be read."""
    plain = re.sub(r"<script.*?</script>", " ", page_html, flags=re.S)
    plain = re.sub(r"<style.*?</style>", " ", plain, flags=re.S)
    return re.sub(r"\|+", "|", re.sub(r"<[^>]+>", "|", plain))


def _escaped(page_html: str, key: str) -> str:
    """Read a scalar out of the React Server Components payload (`\\"price\\":689000000`)."""
    match = re.search(rf'\\"{key}\\":\s*("(?:[^"\\]|\\.)*"|\[[^\]]*\]|\d+|true|false|null)', page_html)
    return match.group(1).strip('"') if match else ""


def parse_detail_page(page_html: str, url: str) -> dict:
    """One carpla detail page -> the raw fields this site exposes."""
    text = _text(page_html)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.S)
    title = parsing.clean_text(title_match.group(1)) if title_match else ""

    specs = {}
    for label, key in SPEC_FIELDS.items():
        found = re.search(re.escape(label) + r"\|([^|]{0,40})\|", text)
        specs[key] = parsing.clean_text(found.group(1)) if found else ""

    # the dealer block ends with "<dealer>|<province>|Xem cửa hàng"
    province = re.search(r"\|([^|]{2,30})\|\s*Xem cửa hàng", text)
    # postedAt is the ad's bump list; createdAt is the fallback when the ad was never bumped
    posted = _escaped(page_html, "postedAt").strip("[]") or _escaped(page_html, "createdAt")
    posted_at = ""
    if posted.isdigit():
        posted_at = datetime.fromtimestamp(int(posted), timezone.utc).isoformat(timespec="seconds")

    return {
        "url": url,
        "slug": url.rstrip("/").rsplit("-", 1)[-1],
        "title": title,
        "province": parsing.clean_text(province.group(1)) if province else "",
        "price_vnd": _escaped(page_html, "price"),
        "odo": _escaped(page_html, "odo"),
        "year": _escaped(page_html, "year"),
        "posted_at": posted_at,
        **specs,
    }


def _slug_km(url: str) -> int | None:
    """carpla encodes the odometer in the slug: `/xe/mitsubishi-attrage-2024---52800km-f8w9u`."""
    match = re.search(r"-(\d+)km", url or "")
    return int(match.group(1)) if match else None


def _title_km(title: str) -> int | None:
    """The odometer printed in the title ("Bán xe Ford Everest 2018 - 102,000km"), when the JSON has none."""
    match = re.search(r"([\d,.]+)\s*km", title or "")
    return parsing.parse_km_text(match.group(1)) if match else None


def _slug_words(url: str) -> list[str]:
    """The car words in a carpla slug: `/xe/isuzu-d-max-euro5-...-f8whc` -> ['isuzu', 'd', 'max', ...]."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-[a-z0-9]{5}$", "", slug)     # trailing listing id
    slug = re.sub(r"--.*$", "", slug)             # "---52800km-"
    slug = re.sub(r"-\d{4}$", "", slug)           # trailing year
    return [word for word in slug.split("-") if word]


def split_title(title: str, url: str = "") -> tuple[str, str]:
    """'Bán xe Ford Everest 2018 - 102,000km' -> ('Ford', 'Everest').

    Most pages title the car ("Bán xe <brand> <model> <year>"), and that path is used. Some ads carry a
    marketing sentence instead; the slug still names the car, so it is the fallback (model capped at four
    words, because a slug can also contain a promotion).
    """
    body = unescape(title or "")
    if body.startswith("Bán xe"):
        body = re.sub(r"^Bán xe\s+", "", body)
        body = re.sub(r"\s*[-–]?\s*[\d,.]+\s*km\s*$", "", body).strip()   # "- 102,000km"
        body = re.sub(r"\s+\d{4}\b.*$", "", body).strip()                 # the year and anything after it
        words = body.split()
        limit = 12
    else:
        words = [word.capitalize() for word in _slug_words(url)]
        limit = 5                                                        # brand + four model words
    tokens = words[:limit]
    for size in (3, 2, 1):
        canonical = MULTIWORD_BRANDS.get(" ".join(tokens[:size]).lower())
        if canonical:
            return canonical, " ".join(tokens[size:limit]) or "Unknown"
    if not tokens:
        return "Unknown", "Unknown"
    return tokens[0], " ".join(tokens[1:limit]) or "Unknown"


def _spec(raw: dict, key: str) -> str:
    """Read one spec value, dropping a value that is really the next label (an empty cell on the page)."""
    value = str(raw.get(key) or "").strip()
    return "" if value in SPEC_FIELDS else value


def to_unified(raw: dict) -> dict:
    """Map one detail page to the 21 unified columns (docs/unified_schema.md)."""
    brand, model = split_title(raw.get("title", ""), raw.get("url", ""))
    price = parsing.to_int(raw.get("price_vnd"))
    body_raw = _spec(raw, "body")
    record = dict.fromkeys(schema.SCHEMA_COLUMNS)
    record.update({
        "listing_id": f"CARPLA_{raw['slug'].upper()}",
        "source_platform": PLATFORM,
        "brand": brand,
        "model": model,
        "sub_model_trim": "",
        "manufacture_year": parsing.to_int(raw.get("year")) or parsing.parse_year_text(raw.get("title")),
        "mileage_km": (parsing.to_int(raw.get("odo")) or _title_km(raw.get("title", ""))
                       or _slug_km(raw.get("url", ""))),
        "transmission": TRANSMISSION_ALIASES.get(_spec(raw, "transmission").lower(),
                                                 schema.normalize_transmission(_spec(raw, "transmission"))),
        "fuel_type": FUEL_ALIASES.get(_spec(raw, "fuel").lower().replace("xe ", ""),
                                      schema.normalize_fuel(_spec(raw, "fuel").replace("xe ", ""))),
        "origin": schema.normalize_origin(_spec(raw, "origin")),
        "body_type": BODY_ALIASES.get(body_raw.lower(), schema.normalize_body(body_raw)),
        "engine_capacity": None,          # carpla does not print the displacement
        "seats": parsing.to_int(re.sub(r"\D", "", _spec(raw, "seats"))),
        "location_province": schema.normalize_province(raw.get("province")),
        "seller_type": "Dealership/Salon",   # carpla only lists its own showroom inventory
        "price_vnd": price,
        "source_url": raw.get("url"),
        "listing_date": raw.get("posted_at") or "",
        "scraped_at": config.now_iso(),
        "raw_price_text": str(price) if price else "",
        "price_status": schema.price_status(price, str(price) if price else ""),
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


def crawl(limit: int | None = None, skip_existing: bool = True,
          out: str = "carpla_extra") -> list[dict]:
    """Walk the sitemap, keep the cars we do not have yet, and write the 21-column CSV."""
    config.ensure_dirs()
    known = existing_ids() if skip_existing else set()
    if known:
        log.info("%d listing_ids already collected -> they will be skipped", len(known))

    conn = storage.open_db()
    storage.create_table(conn, TABLE, RAW_COLUMNS)
    storage.ensure_columns(conn, TABLE, RAW_COLUMNS)

    records: list[dict] = []
    with ScraperSession() as session:
        urls = sitemap_urls(session)
        if not urls:
            conn.close()
            return []
        log.info("%d detail pages in the sitemap", len(urls))
        for url in tqdm(urls[:limit] if limit else urls, desc=SOURCE, unit="xe"):
            if f"CARPLA_{url.rstrip('/').rsplit('-', 1)[-1].upper()}" in known:
                continue
            page_html = session.get_text(url)
            if page_html is None:
                log.warning("%s did not load -> skipped", url)
                continue
            raw = parse_detail_page(page_html, url)
            storage.upsert_rows(conn, TABLE, [raw])
            records.append(to_unified(raw))

    conn.close()
    path = storage.save_csv(records, out, schema.SCHEMA_COLUMNS)
    log.info("%d cars kept -> %s", len(records), path)
    return records


def reexport(out: str = "carpla_extra") -> list[dict]:
    """Re-map every row already stored in SQLite — a parser fix without a second crawl."""
    config.ensure_dirs()
    conn = storage.open_db()
    if not conn.execute("select name from sqlite_master where type='table' and name=?", (TABLE,)).fetchone():
        conn.close()
        log.error("table %s does not exist yet -> crawl first", TABLE)
        return []
    raw_rows = storage.read_rows(conn, TABLE)
    conn.close()
    records = [to_unified(raw) for raw in raw_rows]
    records.sort(key=lambda row: str(row.get("listing_id")))
    path = storage.save_csv(records, out, schema.SCHEMA_COLUMNS)
    log.info("%d cars re-exported from the database -> %s", len(records), path)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="carpla.vn top-up crawler")
    parser.add_argument("--limit", type=int, default=None, help="how many sitemap pages to visit")
    parser.add_argument("--include-existing", action="store_true",
                        help="also write the cars already present in carpla.csv")
    parser.add_argument("--reexport", action="store_true",
                        help="rebuild the CSV from data/scraped.db without any request (after a parser fix)")
    parser.add_argument("--out", default="carpla_extra")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.reexport:
        reexport(args.out)
        return 0
    crawl(args.limit, not args.include_existing, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
