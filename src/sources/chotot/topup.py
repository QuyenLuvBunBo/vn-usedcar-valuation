"""Chotot top-up crawl: reach the listings the two member exports never included.

Why this is a separate module from `crawl.py`:

    `crawl.py` is the southern member's crawler: it seeds province pages, follows the listing links
    it finds, and exports everything it holds into `chotot_mien_nam.csv`. A top-up must not rewrite
    that hand-over file, and it must not count a listing twice against `chotot_mua_ban_oto.csv`
    (the nationwide export). So this module keeps its own queue and its own table and writes only
    `data/processed/chotot_extra.csv`, holding the ids neither file has.

What the source allows (measured 2026-10-30, not assumed):

    * `xe.chotot.com/robots.txt` is `Allow: /` for `*`, with `Disallow: /*page=` still in force.
      Website pagination is therefore **off limits**, and this module drops every `?page=` URL instead
      of fetching it (the count is reported).
    * `sitemap-oto-model-*.xml` (79,040 URLs) and `sitemap-xe-oto-brand.xml` (5,824) are published,
      but both kinds of page are rendered client-side: two sampled pages returned 0 parsable listing
      links and an empty `__NEXT_DATA__`.
    * What *does* return server-rendered listing links is the listing family: `/mua-ban-oto`, the
      province pages and the district/brand pages in `urls_mo_rong.txt` (~25 ads per page).
    * **The route that scales is the JSON gateway**: `gateway.chotot.com/v1/public/ad-listing`
      (`limit` + `o`), whose host publishes no robots.txt at all, so the website's `/*page=` rule does
      not apply to it. `chotot_scraper.py` already drives that route and slices the query by
      price/year to get around its 10,000-result window; this module therefore does not re-implement
      it. `--filter-ids` and `--import-csv` connect the two: drop the ids the team already has before
      the detail step, then map the export into the 21-column contract and merge it here.

The website route (`--max-requests`) stays for what the API cannot give: it is breadth of index pages,
one page each — spend a fixed request budget, resume through SQLite, report what was hit. The API
route is the one for volume; see the module docstring of `chotot_scraper.py` and `docs/crawl_gap.md`.

Run:
    python -m src.sources.chotot.topup --status                 # progress + ETA, no requests
    python -m src.sources.chotot.topup --max-requests 300       # a bounded slice
    python -m src.sources.chotot.topup --max-requests 3000      # a longer slice
    python -m src.sources.chotot.topup --export-only            # rebuild the CSV from SQLite
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from src.common import config, storage
from src.common.http_client import ScraperSession
from .geography import PROVINCES
from .html_parser import parse_detail_page, parse_list_page
from .robots import BASE, Robots, canonical
from .unified import FIELDS, normalize, write_csv

TABLE = "chotot_topup_raw"
QUEUE = "chotot_topup_queue"
EXTRA_NAME = "chotot_extra"
# Every file whose ids this crawl must not repeat. The extra file is not listed: it is rebuilt from
# this module's own table, so re-running exports the same rows instead of appending to them.
KNOWN_FILES = ("chotot_mua_ban_oto.csv", "chotot_mien_nam.csv")
SEED_URLS = Path(__file__).with_name("urls_mo_rong.txt")
VERIFY_RE = re.compile(r"verify you are human|checking your browser|access denied", re.I)


class StopCrawl(RuntimeError):
    """An access problem (denied, verification screen): stop and keep what is already stored."""


# --------------------------------------------------------------------- state
def init(db) -> None:
    """Create this module's own tables; the member tables are never touched."""
    storage.create_table(db, TABLE, ["id", "raw", "kind"])
    db.execute(f'CREATE TABLE IF NOT EXISTS {QUEUE}(url TEXT PRIMARY KEY, kind TEXT, '
               f'status TEXT DEFAULT "pending", error TEXT)')
    db.commit()


def known_ids(processed: Path = config.DATA_PROCESSED) -> set[str]:
    """Numeric ids already handed over by the two members (and by a previous top-up)."""
    ids: set[str] = set()
    for name in KNOWN_FILES:
        path = processed / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for record in csv.DictReader(handle):
                ident = str(record.get("listing_id") or "")
                if ident.startswith("CHOTOT_"):
                    ids.add(ident[len("CHOTOT_"):])
    return ids


def seed_urls() -> list[str]:
    """The index pages this source still serves as HTML: national, provinces, districts/brands."""
    seeds = [BASE + "/mua-ban-oto"]
    seeds += [f"{BASE}/mua-ban-oto-{slug}" for slug in PROVINCES]
    if SEED_URLS.exists():
        for line in SEED_URLS.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                seeds.append(line)
    return list(dict.fromkeys(seeds))


def filter_ids(directory: Path, member_ids: set[str]) -> dict:
    """Drop the ids the team already has from `chotot_scraper.py`'s enumeration queue.

    The API answers newest-first, and the two member files are the newest ads — so a detail run over
    an unfiltered queue spends its whole budget re-fetching listings we already own. The full
    enumeration is kept as `listings_full.jsonl`; the queue the details step reads is rewritten in
    place with only the ids nobody has.
    """
    path = Path(directory) / "listings.jsonl"
    if not path.exists():
        raise SystemExit(f"not found: {path} (run 'chotot_scraper.py ids' first)")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()
               if line.strip()]
    keep = [record for record in records if str(record.get("list_id")) not in member_ids]
    (path.parent / "listings_full.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8")
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in keep) + "\n",
                    encoding="utf-8")
    dropped = len(records) - len(keep)
    print(f"  enumeration {len(records):,} ids -> {len(keep):,} unknown "
          f"({dropped:,} already in a member file, kept in listings_full.jsonl)")
    print(f"  next: chotot_scraper.py details  ->  export  ->  "
          f"topup --import-csv {path.parent / 'chotot_cars.csv'}")
    return {"enumeration": len(records), "unknown": len(keep), "dropped_known": dropped}


def kind_of(url: str) -> str:
    """A URL ending in `/<id>.htm` is a listing; everything else in scope is an index page."""
    return "detail" if re.search(r"/\d+\.htm$", urlsplit(url).path) else "index"


# ------------------------------------------------- deeper enumeration via the API
# `chotot_scraper.py ids` splits the catalogue by price only. Every one of its 27 slices was fetched
# to completion, but paging a live result set duplicates and skips ads (18,413 rows fetched, 13,469
# distinct ids). Splitting each price band by model year makes every cell small and stable, which is
# what closes the remaining gap. This runs the same public endpoint with a two-dimensional facet and
# appends what it finds to the queue the `details` step already reads.
API_LIST = "https://gateway.chotot.com/v1/public/ad-listing"
API_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ChototCatalogueReader/2.0)",
               "Accept": "application/json"}
API_PAGE = 20
YEAR_BANDS = ((1990, 1999), (2000, 2004), (2005, 2009), (2010, 2012), (2013, 2015),
              (2016, 2017), (2018, 2019), (2020, 2021), (2022, 2023), (2024, 2026))
PRICE_BANDS = ((0, 29_999_999), (30_000_000, 49_999_999), (50_000_000, 69_999_999),
               (70_000_000, 99_999_999), (100_000_000, 129_999_999), (130_000_000, 159_999_999),
               (160_000_000, 199_999_999), (200_000_000, 249_999_999), (250_000_000, 299_999_999),
               (300_000_000, 349_999_999), (350_000_000, 399_999_999), (400_000_000, 449_999_999),
               (450_000_000, 499_999_999), (500_000_000, 549_999_999), (550_000_000, 599_999_999),
               (600_000_000, 649_999_999), (650_000_000, 699_999_999), (700_000_000, 799_999_999),
               (800_000_000, 899_999_999), (900_000_000, 999_999_999),
               (1_000_000_000, 1_199_999_999), (1_200_000_000, 1_499_999_999),
               (1_500_000_000, 1_999_999_999), (2_000_000_000, 2_999_999_999),
               (3_000_000_000, 4_999_999_999), (5_000_000_000, 9_999_999_999),
               (10_000_000_000, 1_000_000_000_000))
LISTING_FIELDS = ("list_id", "subject", "price", "mfdate", "mileage_v2", "list_time",
                  "area_name", "region_name", "ward_name")


def _api_get(session, params: dict, rps: float) -> dict:
    """One API call with a politeness delay, retry and a stop on being blocked."""
    import time

    import requests

    for attempt in range(1, 4):
        time.sleep(max(0.0, 1.0 / rps - 0.05))
        try:
            response = session.get(API_LIST, params=params, headers=API_HEADERS, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if response.status_code in (401, 403, 429):
            raise StopCrawl(f"api_blocked_{response.status_code}")
        if response.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        if response.status_code != 200:
            raise StopCrawl(f"api_http_{response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise StopCrawl("api_not_json") from None
    raise StopCrawl("api_retries_exhausted")


def seed_api(directory: Path, rps: float = 2.0, max_cells: int = 0) -> dict:
    """Enumerate the API by price x model year and append the new ids to `listings.jsonl`."""
    import requests

    path = Path(directory) / "listings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    known: set[str] = set()
    for name in ("listings.jsonl", "listings_full.jsonl"):
        candidate = path.parent / name
        if candidate.exists():
            with candidate.open(encoding="utf-8-sig") as handle:
                for line in handle:
                    if line.strip():
                        known.add(str(json.loads(line).get("list_id")))

    session = requests.Session()
    found: dict[str, dict] = {}
    cells = [(price, year) for price in PRICE_BANDS for year in YEAR_BANDS]
    if max_cells:
        cells = cells[:max_cells]
    requests_made = 0
    for index, (price, year) in enumerate(cells, 1):
        offset, total = 0, None
        while total is None or offset < min(total, 10_000):
            payload = _api_get(session, {"cg": 2010, "st": "s,k", "limit": API_PAGE, "o": offset,
                                         "price": f"{price[0]}-{price[1]}",
                                         "mfdate": f"{year[0]}-{year[1]}"}, rps)
            requests_made += 1
            ads = payload.get("ads") or []
            total = payload.get("total") if isinstance(payload.get("total"), int) else len(ads)
            for ad in ads:
                # `list_id` is the identifier the detail endpoint and the listing URL use; `ad_id` is
                # the internal ad record and returns 404 there (verified 2026-10-30).
                ident = str(ad.get("list_id") or "")
                if ident and ident not in known and ident not in found:
                    found[ident] = {field: ad.get(field) for field in LISTING_FIELDS}
                    found[ident]["list_id"] = ident
            if not ads or total == 0:
                break
            offset += API_PAGE
        if index % 30 == 0:
            print(f"  cells {index}/{len(cells)} | requests {requests_made} | new ids {len(found):,}",
                  flush=True)

    with path.open("a", encoding="utf-8") as handle:
        for record in found.values():
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  enumerated {len(cells)} price x year cells in {requests_made:,} requests: "
          f"{len(found):,} ids the queue did not have -> {path}")
    print("  next: topup --filter-ids (optional) -> chotot_scraper.py details -> export -> import-csv")
    return {"cells": len(cells), "requests": requests_made, "new_ids": len(found)}



# --------------------------------------------------- import from the API route
# `chotot_scraper.py` collects the same source through the JSON gateway
# (gateway.chotot.com/v1/public/ad-listing, `limit` + `o`), which is the route the two member
# exports came from: it is not subject to the website's `Disallow: /*page=` and it can walk the
# whole catalogue by slicing the query. Its export is a 24-column working file, not the team
# contract, so this adapter maps it in. Reads the same raw labels the HTML parser produces.
BODY_ALIASES = {
    "sedan": "Sedan", "suv": "SUV", "crossover": "Crossover", "suv / cross over": "Other",
    "hatchback": "Hatchback", "pick-up (ban tai)": "bán tải", "minivan (mpv)": "MPV",
    "van": "Van", "coupe (2 cua)": "Coupe", "mui tran": "mui trần",
}
ORIGIN_ALIASES = {"viet nam": "trong nước", "nuoc khac": "nhập khẩu",
                  "nhap khau": "nhập khẩu", "dang cap nhat": ""}
# The site writes the short form ("Tự động"); the shared normalizers expect the long one.
TRANSMISSION_ALIASES = {"tu dong": "số tự động", "so tu dong": "số tự động",
                        "so san": "số sàn", "ban tu dong": "số hỗn hợp"}
FUEL_ALIASES = {"dong co hybrid": "hybrid"}


def _enum(value, values, default="Unknown"):
    return value if value in values else default


def api_row_to_contract(raw: dict) -> dict:
    """Map one row of `chotot_scraper.py export` to the team's 21 columns."""
    from src.common import schema as contract

    from .parsing import fold

    location = str(raw.get("location") or "")
    province = location.split(",")[-1].strip() if location else ""
    price_text = str(raw.get("price_vnd") or "").strip()
    price_vnd = int(float(price_text)) if re.fullmatch(r"[\d.]+", price_text) else None
    odo_text = str(raw.get("odo_km") or "").replace(".", "").replace(",", "").strip()
    year = str(raw.get("year") or "").strip()
    seats = str(raw.get("seats") or "").strip()
    body = BODY_ALIASES.get(fold(str(raw.get("body_type") or "")), raw.get("body_type"))
    origin = ORIGIN_ALIASES.get(fold(str(raw.get("origin") or "")), raw.get("origin"))
    gearbox = raw.get("transmission")
    gearbox = TRANSMISSION_ALIASES.get(fold(str(gearbox or "")), gearbox)
    fuel = raw.get("fuel")
    fuel = FUEL_ALIASES.get(fold(str(fuel or "")), fuel)
    listing_id = str(raw.get("list_id") or "").strip()
    posted = str(raw.get("posted_at_utc") or "").strip()[:10]

    return {
        "listing_id": f"CHOTOT_{listing_id}",
        "source_platform": "chotot",
        "brand": str(raw.get("brand") or "").strip() or "Unknown",
        "model": str(raw.get("model") or "").strip() or "Unknown",
        "sub_model_trim": str(raw.get("trim") or "").strip(),
        "manufacture_year": int(year) if year.isdigit() else None,
        "mileage_km": float(odo_text) if odo_text.isdigit() else None,
        "transmission": _enum(contract.normalize_transmission(gearbox),
                              contract.TRANSMISSION_VALUES),
        "fuel_type": _enum(contract.normalize_fuel(fuel), contract.FUEL_VALUES),
        "origin": _enum(contract.normalize_origin(origin) if origin else "Unknown",
                        contract.ORIGIN_VALUES),
        "body_type": _enum(contract.normalize_body(body), contract.BODY_VALUES),
        "engine_capacity": None,                      # not exposed by the API either
        "seats": int(seats) if seats.isdigit() else None,
        "location_province": contract.normalize_province(province),
        "seller_type": "Unknown",                     # no store link in the listing payload
        "price_vnd": price_vnd,
        "source_url": str(raw.get("url") or "").strip(),
        "listing_date": posted or None,
        "scraped_at": str(raw.get("scraped_at_utc") or "").strip() or config.now_iso(),
        "raw_price_text": None,                       # the API returns a number, not the ad text
        "price_status": contract.price_status(price_vnd, None),
    }


def import_csv(path: Path, processed: Path, member_ids: set[str]) -> dict:
    """Merge an API-route export into `chotot_extra.csv`, keeping one row per new listing."""
    source = Path(path)
    if not source.exists():
        raise SystemExit(f"not found: {source} (run 'python src/sources/chotot/chotot_scraper.py export')")
    with source.open(encoding="utf-8-sig", newline="") as handle:
        incoming = [api_row_to_contract(record) for record in csv.DictReader(handle)]

    merged: dict[str, dict] = {}
    out = processed / f"{EXTRA_NAME}.csv"
    if out.exists():
        with out.open(encoding="utf-8-sig", newline="") as handle:
            for record in csv.DictReader(handle):
                merged[str(record["listing_id"])] = record
    added = updated = skipped = 0
    for row in incoming:
        ident = row["listing_id"][len("CHOTOT_"):]
        if not ident or ident in member_ids:
            skipped += 1
            continue
        if row["listing_id"] in merged:
            merged[row["listing_id"]] = row       # a re-import refreshes the row it wrote before
            updated += 1
        else:
            merged[row["listing_id"]] = row
            added += 1

    processed.mkdir(parents=True, exist_ok=True)
    write_csv(out, [merged[key] for key in sorted(merged)], FIELDS)
    diagnostics = processed / EXTRA_NAME
    diagnostics.mkdir(parents=True, exist_ok=True)
    audit = {"generated_at": config.now_iso(), "file": str(out), "records": len(merged),
             "imported_from": str(source), "imported_rows": len(incoming),
             "added": added, "updated": updated, "skipped_known": skipped,
             "route": "gateway JSON API (chotot_scraper.py export)"}
    (diagnostics / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    print(f"  imported {len(incoming):,} rows from {source.name}: +{added:,} new, "
          f"{updated:,} refreshed ({skipped:,} in a member file) -> {out.name} ({len(merged):,} rows)")
    return audit



# --------------------------------------------------------------------- crawl
def enqueue(db, url: str, kind: str | None = None) -> bool:
    url = canonical(url)
    if not url:
        return False
    db.execute(f'INSERT OR IGNORE INTO {QUEUE}(url,kind) VALUES (?,?)', (url, kind or kind_of(url)))
    return True


def _mark(db, url: str, status: str, error: str | None = None) -> None:
    db.execute(f'UPDATE {QUEUE} SET status=?, error=? WHERE url=?', (status, error, url))
    db.commit()


def _next_pending(db, prefer_detail: bool = True):
    """Take a pending URL, preferring the kind the budget policy asks for.

    Enumeration is only useful in service of fetching listings: a run that spends its whole budget on
    index pages discovers thousands of links and stores nothing. The loop therefore prefers details
    once a page has produced them, and returns to enumeration when the detail supply runs dry.
    """
    order = ("detail", "index") if prefer_detail else ("index", "detail")
    for kind in order:
        row = db.execute(f'SELECT url,kind FROM {QUEUE} WHERE status="pending" AND kind=? LIMIT 1',
                         (kind,)).fetchone()
        if row:
            return row
    return None


def crawl(args) -> dict:
    """Spend at most `--max-requests` GETs, storing every new listing in this module's own table."""
    processed = Path(args.processed_out)
    processed.mkdir(parents=True, exist_ok=True)
    db = storage.open_db(args.db)
    init(db)
    known = known_ids(processed)
    counts = {"requests": 0, "index_pages": 0, "detail_pages": 0, "new_listings": 0,
              "already_known": 0, "robots_blocked": 0, "http_errors": 0, "parse_errors": 0}
    stop = "budget_reached"
    started = time.monotonic()

    with ScraperSession(delay=max(1.5, args.delay)) as session:
        robots_text = session.get_text(BASE + "/robots.txt") or ""
        if "user-agent:" not in robots_text.lower():
            raise StopCrawl("invalid_robots_response")
        robots = Robots(robots_text, agent=session.session.headers.get("User-Agent",
                                                                     config.USER_AGENT))
        for url in seed_urls():
            enqueue(db, url, "index")
        db.commit()

        try:
            while counts["requests"] < args.max_requests:
                # one index page is allowed to buy `--detail-ratio` listing fetches
                budget = args.detail_ratio * max(counts["index_pages"], 1)
                prefer_detail = counts["detail_pages"] < budget
                record = _next_pending(db, prefer_detail)
                if record is None:
                    stop = "queue_exhausted"
                    break
                url, kind = record
                # robots first: a `?page=` URL is dropped here, never fetched
                if not robots.allowed(url):
                    counts["robots_blocked"] += 1
                    _mark(db, url, "disallowed", "robots")
                    continue

                counts["requests"] += 1
                response = session.get(url)
                if response is None:
                    counts["http_errors"] += 1
                    _mark(db, url, "error", "http")
                    continue
                if not response.encoding or response.encoding.lower() == "iso-8859-1":
                    response.encoding = response.apparent_encoding
                page = response.text
                if VERIFY_RE.search(page):
                    raise StopCrawl("verification_or_security_screen")
                captured = config.now_iso()

                if kind == "detail":
                    raw = parse_detail_page(page, url, captured)
                    try:
                        unwrapped, _, _ = normalize(raw)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        counts["parse_errors"] += 1
                        _mark(db, url, "unparsed", "normalize_failed")
                        continue
                    counts["detail_pages"] += 1
                    ident = unwrapped["listing_id"][len("CHOTOT_"):]
                    if ident in known:
                        counts["already_known"] += 1
                        _mark(db, url, "known")
                        continue
                    storage.upsert_rows(db, TABLE, [{
                        "url": url, "id": ident, "kind": "detail",
                        "raw": json.dumps(raw, ensure_ascii=False)}])
                    known.add(ident)
                    counts["new_listings"] += 1
                    _mark(db, url, "done")
                else:
                    details, pages = parse_list_page(page, url)
                    for more in pages:
                        if robots.allowed(more):
                            enqueue(db, more, "index")
                        else:
                            counts["robots_blocked"] += 1        # measured: /*page= blocked
                    for detail in details:
                        match = re.search(r"/(\d+)\.htm$", urlsplit(detail).path)
                        if match and match.group(1) in known:
                            counts["already_known"] += 1
                            continue
                        enqueue(db, detail, "detail")
                    counts["index_pages"] += 1
                    _mark(db, url, "done")

                if counts["requests"] % 10 == 0:
                    elapsed = (time.monotonic() - started) or 1e-9
                    waiting = db.execute(f'SELECT COUNT(*) FROM {QUEUE} WHERE status="pending"'
                                         ).fetchone()[0]
                    print(f"  {counts['requests']:>5} requests "
                          f"({counts['requests'] / elapsed:.2f}/s) | new {counts['new_listings']:>4} | "
                          f"known {counts['already_known']:>5} | "
                          f"robots-blocked {counts['robots_blocked']:>3} | queue {waiting:>5}",
                          flush=True)
        except KeyboardInterrupt:
            stop = "interrupted"
        except StopCrawl as exc:
            stop = f"stopped:{exc}"
        finally:
            elapsed = time.monotonic() - started
            counts["seconds"] = round(elapsed, 1)
            counts["requests_per_second"] = round(counts["requests"] / elapsed, 3) if elapsed else 0
            counts["stop_reason"] = stop
            counts["queue_status"] = dict(db.execute(
                f'SELECT status, COUNT(*) FROM {QUEUE} GROUP BY status'))
            report = export(db, processed, known_ids(processed), counts)   # member ids only
            db.close()
    return report


def export(db, processed: Path, member_ids: set[str], context: dict) -> dict:
    """Write `chotot_extra.csv` from this module's table, plus the audit that travels with it."""
    rows, failures = [], 0
    for record in storage.read_rows(db, TABLE):
        raw = json.loads(record["raw"])
        try:
            row, _, _ = normalize(raw)
        except (ValueError, KeyError, TypeError, AttributeError):
            failures += 1
            continue
        if record["id"] in member_ids:
            continue                       # a member hand-over now covers this listing
        rows.append(row)
    rows.sort(key=lambda row: row["listing_id"])

    out = processed / f"{EXTRA_NAME}.csv"
    write_csv(out, rows, FIELDS)
    diagnostics = processed / EXTRA_NAME
    diagnostics.mkdir(parents=True, exist_ok=True)
    audit = {"generated_at": config.now_iso(), "file": str(out), "records": len(rows),
             "normalize_failures": failures, "not_a_coverage_guarantee": True, **context}
    (diagnostics / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    print(f"\n  {EXTRA_NAME}.csv: {len(rows):,} rows -> {out}")
    print(f"  stop={context.get('stop_reason')} requests={context.get('requests')} "
          f"new={context.get('new_listings')} already_known={context.get('already_known')} "
          f"robots_blocked={context.get('robots_blocked')} (see {diagnostics / 'audit.json'})")
    return audit


def status(args) -> int:
    """Report the queue without making a single request."""
    processed = Path(args.processed_out)
    db = storage.open_db(args.db)
    init(db)
    member = known_ids(processed)
    stored = storage.count_rows(db, TABLE)
    queue = dict(db.execute(f'SELECT status, COUNT(*) FROM {QUEUE} GROUP BY status'))
    pending = queue.get("pending", 0)
    extra = processed / f"{EXTRA_NAME}.csv"
    extra_rows = 0
    if extra.exists():
        with extra.open(encoding="utf-8-sig") as handle:
            extra_rows = max(0, sum(1 for _ in handle) - 1)
    # the measured rate beats the configured delay: the site answers slower than 1.5 s
    audit_path = processed / EXTRA_NAME / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
    rate = audit.get("requests_per_second") or (1 / max(1.5, args.delay))
    hours = pending / rate / 3600 if rate else 0
    print(f"member files            : {len(member):,} chotot ids")
    print(f"top-up stored           : {stored:,} listings ({extra_rows:,} in {extra.name})")
    print(f"queue                   : {queue or '{}'}")
    print(f"pending requests        : {pending:,}  (~{hours:.1f} h at the measured {rate:.2f} req/s)")
    print(f"robots-blocked pages    : {audit.get('robots_blocked', 0):,} "
          f"(`?page=` links the site forbids, never fetched)")
    print("next step               : python -m src.sources.chotot.topup --max-requests 300")
    db.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(config.ROOT / "data/scraped.db"))
    parser.add_argument("--processed-out", default=str(config.DATA_PROCESSED))
    parser.add_argument("--max-requests", type=int, default=300,
                        help="hard budget for this run; re-run to continue where it stopped")
    parser.add_argument("--delay", type=float, default=config.REQUEST_DELAY)
    parser.add_argument("--detail-ratio", type=int, default=8,
                        help="listing fetches an index page buys before enumerating again")
    parser.add_argument("--status", action="store_true", help="progress and ETA, no requests")
    parser.add_argument("--import-csv", default="",
                        help="import an API-route export from chotot_scraper.py into chotot_extra.csv")
    parser.add_argument("--filter-ids", default="",
                        help="drop member ids from chotot_scraper.py's listings.jsonl before 'details'")
    parser.add_argument("--seed-api", default="",
                        help="enumerate the API by price x year and append new ids to listings.jsonl")
    parser.add_argument("--seed-rps", type=float, default=2.0,
                        help="requests per second for --seed-api (the API's own limit is unstated)")
    parser.add_argument("--seed-cells", type=int, default=0,
                        help="only the first N price x year cells (0 = all)")
    args = parser.parse_args(argv)
    if args.max_requests < 1 or args.delay < 0:
        parser.error("--max-requests must be positive and --delay non-negative")
    if args.status:
        return status(args)
    if args.filter_ids:
        filter_ids(Path(args.filter_ids), known_ids(Path(args.processed_out)))
        return 0
    if args.seed_api:
        try:
            seed_api(Path(args.seed_api), rps=args.seed_rps, max_cells=args.seed_cells)
        except StopCrawl as exc:
            print(f"stopped: {exc} — what was found so far is already appended to listings.jsonl")
            return 2
        return 0
    if args.import_csv:
        import_csv(Path(args.import_csv), Path(args.processed_out), known_ids(Path(args.processed_out)))
        return 0
    try:
        crawl(args)
    except StopCrawl as exc:
        print(f"stopped before the first request: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
