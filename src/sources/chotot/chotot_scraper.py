#!/usr/bin/env python3
"""Chợ Tốt Xe - full car scraper .

Usage:
    python scraper.py preflight
    python scraper.py ids      [--max-ids 200]
    python scraper.py details  [--max-details 50]
    python scraper.py export
    python scraper.py all      [--max-ids 200 --max-details 50]   # trial run
"""
import argparse
import csv
import json
import math
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

if sys.version_info < (3, 10):
    raise RuntimeError("Use Python 3.10 or newer.")
if shutil.which("curl") is None:
    raise RuntimeError("curl is required (install it and make sure it is on PATH).")

# ============================== CONFIGURATION ==============================
# These are defaults; most can be overridden from the command line.
OUTPUT_DIR = "chotot_output"

LIST_PER_PAGE = 20           # listing page size (20 is proven to work; the API may allow up to 50)
LIST_RPS = 2.0               # listing requests per second
DETAIL_RPS = 3.0             # detail requests per second, all workers combined
DETAIL_WORKERS = 4
SPLIT_AT = 9000              # a slice reporting >= this many ads is split into smaller slices
WINDOW_CAP = 10_000          # the API never serves more than this many results for one query

MAX_LISTING_IDS = None       # trial run: stop collecting ids after this many (e.g. 200)
MAX_DETAILS = None           # trial run: fetch at most this many detail records (e.g. 50)
INCLUDE_UNAVAILABLE = False  # True: keep rows of ads that disappeared (HTTP 404) in the CSV
# ===========================================================================

OUT = LISTINGS_PATH = SLICES_PATH = DETAILS_PATH = CSV_PATH = REPORT_PATH = None


def init_paths(output_dir):
    global OUT, LISTINGS_PATH, SLICES_PATH, DETAILS_PATH, CSV_PATH, REPORT_PATH
    OUT = Path(output_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    LISTINGS_PATH = OUT / "listings.jsonl"    # one line per ad id found by the listing crawl
    SLICES_PATH = OUT / "slices.jsonl"        # crawl log: lets step 1 resume without re-probing
    DETAILS_PATH = OUT / "details.jsonl"      # one line per parsed detail record
    CSV_PATH = OUT / "chotot_cars.csv"
    REPORT_PATH = OUT / "report.json"
    print("Output folder:", OUT.resolve())


# ================================ HTTP client ================================
BASE_URL = "https://xe.chotot.com"
CATALOGUE_URL = BASE_URL + "/mua-ban-oto"
GATEWAY_URL = "https://gateway.chotot.com"
API_LIST = GATEWAY_URL + "/v1/public/ad-listing"
ALLOWED_HOSTS = {"xe.chotot.com", "gateway.chotot.com", "www.chotot.com"}
CAR_CATEGORY_ID = "2010"      # category 2010 = Ô tô
USER_AGENT = "Mozilla/5.0 (compatible; ChototCatalogueReader/2.0)"


class HttpError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Blocked(RuntimeError):
    """The site keeps answering 403/429; the crawl stops and can be resumed later."""


class Throttle:
    """Thread-safe global rate limiter with a shared back-off after 403/429."""

    def __init__(self, rps):
        self.interval = 1.0 / rps
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.penalty_until = 0.0
        self.strikes = 0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at, self.penalty_until)
            self.next_at = start + self.interval * random.uniform(0.9, 1.3)
        time.sleep(max(0.0, start - now))

    def penalize(self):
        with self.lock:
            self.strikes += 1
            pause = min(300, 15 * 2 ** (self.strikes - 1))
            self.penalty_until = max(self.penalty_until, time.monotonic() + pause)
            return self.strikes, pause

    def success(self):
        with self.lock:
            self.strikes = 0


class Client:
    MARK = "\n__HTTP_STATUS__:"

    def __init__(self, rps, timeout=60, max_blocks=6):
        self.exe = shutil.which("curl")
        if self.exe is None:
            raise RuntimeError("curl is required.")
        self.throttle = Throttle(rps)
        self.timeout = timeout
        self.max_blocks = max_blocks

    def _curl(self, url, accept):
        cmd = [
            self.exe, "--silent", "--show-error", "--location", "--compressed",
            "--connect-timeout", "15", "--max-time", str(self.timeout),
            "--write-out", self.MARK + "%{http_code}",
            "--header", f"Accept: {accept}",
            "--header", "Accept-Language: vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "--header", f"Origin: {BASE_URL}",
            "--header", f"Referer: {CATALOGUE_URL}",
            "--header", f"User-Agent: {USER_AGENT}",
            url,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=self.timeout + 10)
        payload, sep, code_text = res.stdout.rpartition(self.MARK)
        status = int(code_text) if sep and code_text.strip().isdigit() else 0
        return res.returncode, status, payload, res.stderr.strip()

    def get(self, url, *, accept="application/json", ok=(200,)):
        """Return (status, body). 4xx outside `ok` raises HttpError; 403/429 back off, then Blocked."""
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in ALLOWED_HOSTS:
            raise ValueError(f"Only public HTTPS URLs on {sorted(ALLOWED_HOSTS)} are supported.")
        attempt = 0
        while True:
            self.throttle.wait()
            try:
                rc, status, body, err = self._curl(url, accept)
            except subprocess.TimeoutExpired:
                rc, status, body, err = -1, 0, "", "timeout"
            if rc == 0 and status in ok:
                self.throttle.success()
                return status, body
            if status in (403, 429):
                strikes, pause = self.throttle.penalize()
                print(f"HTTP {status}: pausing {pause}s (strike {strikes}/{self.max_blocks})", flush=True)
                if strikes > self.max_blocks:
                    raise Blocked(f"HTTP {status} persisted; stopping. Progress is saved, rerun to resume later.")
                continue
            if rc == 0 and 400 <= status < 500:
                raise HttpError(status, f"HTTP {status} for {url}")
            attempt += 1
            if attempt >= 4:
                raise HttpError(status or -1, f"Request failed after retries (HTTP {status}, curl {rc}): {err or body[:120]!r}")
            time.sleep(2 ** attempt)


def check_robots(client):
    """Check robots.txt of BOTH hosts used: the website and the API gateway."""
    targets = [
        (BASE_URL, ["/mua-ban-oto", "/1.htm"]),
        (GATEWAY_URL, ["/v1/public/ad-listing", "/v1/public/ad-listing/1"]),
    ]
    for host, paths in targets:
        try:
            status, txt = client.get(host + "/robots.txt", accept="text/plain", ok=(200, 404))
        except HttpError as exc:
            raise RuntimeError(f"Could not read {host}/robots.txt ({exc}); not continuing blind.") from exc
        if status == 404 or not txt.strip():
            print(f"{host}: no robots.txt, no crawl restrictions published.")
            continue
        rp = RobotFileParser()
        rp.parse(txt.splitlines())
        for path in paths:
            if not rp.can_fetch("*", host + path):
                raise RuntimeError(f"robots.txt of {host} disallows {path}; stopping.")
        delay = rp.crawl_delay("*")
        if delay:
            client.throttle.interval = max(client.throttle.interval, float(delay))
        print(f"{host}: robots.txt allows the paths used" + (f" (crawl-delay {delay}s honoured)" if delay else "."))


# ================================ text helpers ================================
def fold(text):
    """Lower-case, strip Vietnamese diacritics and punctuation: 'Số Km đã đi' -> 'so km da di'."""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def clean_text(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = ", ".join(t for t in (clean_text(v) for v in value) if t)
    elif isinstance(value, dict):
        value = value.get("label") or value.get("value") or value.get("name")
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip().rstrip(".").strip()   # "7." -> "7"
    return None if text in ("", "$undefined", "undefined", "null", "None") else text


def digits_int(value):
    """'125.000 km' -> 125000, 775000000 -> 775000000 (digits only, for km and VND)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"\D", "", clean_text(value) or "")
    return int(digits) if digits else None


def first_int(value):
    """'7 chỗ' -> 7"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    m = re.search(r"\d+", clean_text(value) or "")
    return int(m.group()) if m else None


def to_year(value):
    m = re.search(r"(?:19|20)\d{2}", clean_text(value) or "")
    return int(m.group()) if m else None


def iso_from_ms(value):
    try:
        v = float(value)
        if v > 1e11:
            v /= 1000.0
        return datetime.fromtimestamp(v, timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------- "Thông số kỹ thuật" label -> column -------------------
SPEC_LABELS = {          # folded Vietnamese labels exactly as the detail page shows them
    "brand":        ["hang", "hang xe"],
    "model":        ["dong xe"],
    "year":         ["nam san xuat"],
    "trim":         ["phien ban xe", "phien ban"],
    "transmission": ["hop so"],
    "fuel":         ["nhien lieu"],
    "body_type":    ["kieu dang"],
    "seats":        ["so cho", "so cho ngoi"],
    "odo":          ["so km da di"],
    "origin":       ["xuat xu"],
    "color":        ["mau sac"],
    "condition":    ["tinh trang"],
}
SPEC_IDS = {             # only a fallback when a record carries ids but no labels
    "brand": ["carbrand"], "model": ["carmodel"], "year": ["mfdate"], "trim": ["carversion", "version"],
    "transmission": ["gearbox"], "fuel": ["fuel"], "body_type": ["cartype", "carbody"],
    "seats": ["carseats"], "odo": ["mileage_v2", "mileage"], "origin": ["carorigin", "origin"],
    "color": ["color"], "condition": ["condition"],
}
KNOWN_LABELS = {l for ls in SPEC_LABELS.values() for l in ls}


def _generic_pairs(obj, found):
    if isinstance(obj, dict):
        if isinstance(obj.get("label"), str) and "value" in obj:
            found.append(obj)
        for v in obj.values():
            _generic_pairs(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _generic_pairs(v, found)


def collect_specs(payload):
    """Return [{'id','label','value'}] from a detail-API payload or a page's __NEXT_DATA__."""
    raw = []
    if isinstance(payload, dict):
        if isinstance(payload.get("parameters"), list):
            raw += [p for p in payload["parameters"] if isinstance(p, dict)]
        ap = payload.get("ad_params")
        if isinstance(ap, dict):
            raw += [p for p in ap.values() if isinstance(p, dict)]
        elif isinstance(ap, list):
            raw += [p for p in ap if isinstance(p, dict)]
    if not raw:
        _generic_pairs(payload, raw)
    out, seen = [], set()
    for p in raw:
        value = clean_text(p.get("value"))
        label = p.get("label") if isinstance(p.get("label"), str) else None
        ident = p.get("id") if isinstance(p.get("id"), str) else None
        if value is None or not (label or ident):
            continue
        key = ident or fold(label)
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": ident, "label": label, "value": value})
    return out


def map_specs(specs):
    by_label, by_id = {}, {}
    for s in specs:
        if s["label"]:
            by_label.setdefault(fold(s["label"]), s["value"])
        if s["id"]:
            by_id.setdefault(s["id"], s["value"])
    out = {}
    for field, labels in SPEC_LABELS.items():
        value = next((by_label[l] for l in labels if by_label.get(l)), None)
        if value is None:
            value = next((by_id[i] for i in SPEC_IDS[field] if by_id.get(i)), None)
        out[field] = value
    return out


def find_ad(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("ad"), dict):
            return obj["ad"]
        if "list_id" in obj and "subject" in obj:
            return obj
        for v in obj.values():
            r = find_ad(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_ad(v)
            if r:
                return r
    return {}


def extract_next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


COLUMNS = [
    "list_id", "url", "brand", "model", "trim", "year", "body_type", "transmission", "fuel", "seats",
    "odo_km", "odo_suspect", "origin", "color", "condition", "price_vnd", "location", "posted_at_utc",
    "title_raw", "specs_json", "detail_source", "detail_status", "error", "scraped_at_utc",
]


def parse_detail(payload, list_id, *, source, listing=None, scraped_at=None, status=200, error=None):
    listing = listing or {}
    ad = find_ad(payload) if payload else {}
    specs = collect_specs(payload) if payload else []
    m = map_specs(specs)

    def pick(*vals):
        return next((v for v in vals if v not in (None, "")), None)

    loc_parts = []
    for src in (ad, listing):
        loc_parts = [clean_text(src.get(k)) for k in ("ward_name", "area_name", "region_name")]
        loc_parts = [p for p in loc_parts if p]
        if loc_parts:
            break

    return {
        "list_id": str(list_id),
        "url": f"{BASE_URL}/{list_id}.htm",
        "brand": m["brand"],
        "model": m["model"],
        "trim": m["trim"],
        "year": to_year(pick(m["year"], ad.get("mfdate"))),
        "body_type": m["body_type"],
        "transmission": m["transmission"],
        "fuel": m["fuel"],
        "seats": first_int(m["seats"]),
        "odo_km": digits_int(pick(m["odo"], ad.get("mileage_v2"), listing.get("mileage_v2"))),
        "odo_suspect": None,
        "origin": m["origin"],
        "color": m["color"],
        "condition": m["condition"],
        "price_vnd": digits_int(pick(ad.get("price"), listing.get("price"))),
        "location": ", ".join(loc_parts) or None,
        "posted_at_utc": iso_from_ms(pick(ad.get("list_time"), listing.get("list_time"))),
        "title_raw": clean_text(pick(ad.get("subject"), listing.get("subject"))),
        "specs_json": json.dumps({s["label"] or s["id"]: s["value"] for s in specs}, ensure_ascii=False) if specs else None,
        "detail_source": source,
        "detail_status": status,
        "error": error,
        "scraped_at_utc": scraped_at or now_iso(),
    }


def odo_suspect(odo, year, this_year=None):
    """Flag placeholder odometer values (1234, 123456, 11111, <100 km on an old car)."""
    if odo is None:
        return None
    this_year = this_year or datetime.now().year
    s = str(odo)
    if len(s) >= 3 and (s in "1234567890" or s in "9876543210" or len(set(s)) == 1):
        return True
    if odo < 100 and year is not None and year <= this_year - 2:
        return True
    return False


# ============================ step 1: listing crawl ============================
def load_jsonl(path):
    path = Path(path)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue          # half-written last line after a crash


def append_jsonl(fh, obj):
    fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    fh.flush()


# ---------------- slicing the catalogue below the 10k window ----------------
FILTER_PARAM = {"price": "price", "mfdate": "mfdate"}   # query-parameter names of the range filters
RANGE_SYNTAXES = ["{lo}-{hi}", "{lo},{hi}"]             # tried in this order by probe_filters()
RANGE_SYNTAX = {}                                       # filled by probe_filters()
PRICE_MAX = 10 ** 12
YEAR_MIN, YEAR_MAX = 1900, datetime.now().year + 2
PRICE_CUTS = [0, 30_000_000, 50_000_000, 70_000_000, 100_000_000, 130_000_000, 160_000_000,
              200_000_000, 250_000_000, 300_000_000, 350_000_000, 400_000_000, 450_000_000,
              500_000_000, 550_000_000, 600_000_000, 650_000_000, 700_000_000, 800_000_000,
              900_000_000, 1_000_000_000, 1_200_000_000, 1_500_000_000, 2_000_000_000,
              3_000_000_000, 5_000_000_000, 10_000_000_000]
LISTING_KEYS = ("subject", "price", "mfdate", "mileage_v2", "list_time", "area_name", "region_name", "ward_name")
STATS = {"skipped_ads": 0}


def fetch_list_page(client, node, offset, limit):
    q = {"cg": CAR_CATEGORY_ID, "st": "s,k", "limit": limit, "o": offset, "page": offset // limit + 1}
    for dim, (lo, hi) in node.items():
        q[FILTER_PARAM[dim]] = RANGE_SYNTAX[dim].format(lo=lo, hi=hi)
    _, raw = client.get(f"{API_LIST}?{urlencode(q)}", accept="application/json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("gateway.chotot.com did not return valid JSON.") from exc
    ads, total = (data.get("ads"), data.get("total")) if isinstance(data, dict) else (None, None)
    if not isinstance(ads, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError(f"Unexpected listing payload (ads={type(ads).__name__}, total={total!r}).")
    return total, ads


def probe_filters(client):
    """Find out which range syntax the API accepts and check the filter really filters."""
    total0, ads = fetch_list_page(client, {}, 0, LIST_PER_PAGE)
    sample = next((a for a in ads if (digits_int(a.get("price")) or 0) > 0 and to_year(a.get("mfdate"))), None)
    if sample is None:
        raise RuntimeError("Could not find a sample ad with price and year to probe the filters.")
    print(f"Unfiltered query reports total = {total0:,}"
          + ("  <- this is the result-window cap, not the catalogue size" if total0 >= WINDOW_CAP else ""))
    for dim in ("price", "mfdate"):
        value = digits_int(sample.get(dim))
        RANGE_SYNTAX.pop(dim, None)
        for syntax in RANGE_SYNTAXES:
            RANGE_SYNTAX[dim] = syntax
            try:
                total, got = fetch_list_page(client, {dim: (value, value)}, 0, LIST_PER_PAGE)
            except (ValueError, HttpError):
                continue
            if total > 0 and got and all(digits_int(a.get(dim)) == value for a in got):
                print(f"Filter '{dim}' works with syntax {syntax!r} (single-value check -> {total:,} ads).")
                break
        else:
            RANGE_SYNTAX.pop(dim, None)
            print(f"WARNING: filter '{dim}' did not work with any known syntax.")
    if "price" not in RANGE_SYNTAX:
        raise RuntimeError(
            "The price filter was not accepted, so the catalogue cannot be sliced. Open "
            "xe.chotot.com/mua-ban-oto in a browser, apply a price filter, copy the parameter name/format "
            "from the address bar or the network tab, and edit FILTER_PARAM / RANGE_SYNTAXES.")


def split_node(node):
    """Return smaller slices covering `node`, or None if it cannot be split any further."""
    price = node.get("price")
    if price is None:
        edges = PRICE_CUTS + [PRICE_MAX + 1]
        return [{**node, "price": (edges[i], edges[i + 1] - 1)} for i in range(len(edges) - 1)]
    lo, hi = price
    if hi > lo:
        mid = (lo + hi) // 2
        return [{**node, "price": (lo, mid)}, {**node, "price": (mid + 1, hi)}]
    if "mfdate" in RANGE_SYNTAX:            # one single price holds >= SPLIT_AT ads: cut it by year
        lo, hi = node.get("mfdate", (YEAR_MIN, YEAR_MAX))
        if hi > lo:
            mid = (lo + hi) // 2
            return [{**node, "mfdate": (lo, mid)}, {**node, "mfdate": (mid + 1, hi)}]
    return None


def node_key(node):
    return json.dumps({k: list(v) for k, v in sorted(node.items())}, sort_keys=True)


def as_node(obj):
    return {k: tuple(v) for k, v in obj.items()}


def check_filter(node, ads):
    """Guard against a silently ignored filter (it would just return the same 10k ads again)."""
    if not node or not ads:
        return
    bad = sum(
        any((v := digits_int(ad.get(dim))) is not None and not lo <= v <= hi for dim, (lo, hi) in node.items())
        for ad in ads)
    if bad > 0.1 * len(ads):
        raise RuntimeError(f"{bad}/{len(ads)} ads fall outside the requested slice {node}: the API is not "
                           "applying the filter as expected. Re-run probe_filters().")


def listing_record(ad, list_id):
    rec = {"list_id": list_id}
    rec.update({k: ad.get(k) for k in LISTING_KEYS})
    return rec


def enumerate_leaf(client, node, total, first_ads, seen, lf):
    pages = math.ceil(min(total, WINDOW_CAP) / LIST_PER_PAGE)
    got = new = 0
    prev, ads = None, first_ads
    for p in range(pages):
        if p > 0:
            _, ads = fetch_list_page(client, node, p * LIST_PER_PAGE, LIST_PER_PAGE)
        if not ads:
            break
        ids = [str(a.get("list_id") or a.get("ad_id")) for a in ads]
        if ids == prev:
            raise RuntimeError(f"Slice {node}: page {p + 1} repeated the previous page (pagination loop).")
        prev = ids
        for ad, lid in zip(ads, ids):
            if not lid.isdigit():
                STATS["skipped_ads"] += 1
                continue
            got += 1
            if lid not in seen:
                seen.add(lid)
                new += 1
                append_jsonl(lf, listing_record(ad, lid))
    return got, new


def crawl_listings(client, max_ids=None):
    seen = {str(r["list_id"]) for r in load_jsonl(LISTINGS_PATH)}
    slice_log = {r["key"]: r for r in load_jsonl(SLICES_PATH)}
    print(f"Resuming with {len(seen):,} ids and {len(slice_log):,} logged slices." if seen or slice_log else "Fresh start.")
    stack, stopped_early, handled = [{}], False, 0
    with LISTINGS_PATH.open("a", encoding="utf-8") as lf, SLICES_PATH.open("a", encoding="utf-8") as sf:
        while stack:
            if max_ids and len(seen) >= max_ids:
                stopped_early = True
                break
            node = stack.pop()
            key = node_key(node)
            rec = slice_log.get(key)
            if rec is not None:                                   # already handled in an earlier session
                if rec["status"] == "split":
                    stack.extend(reversed([as_node(c) for c in rec["children"]]))
                continue
            total, ads = fetch_list_page(client, node, 0, LIST_PER_PAGE)
            check_filter(node, ads)
            children = split_node(node) if total >= SPLIT_AT else None
            if total == 0 or not ads:
                rec = {"key": key, "status": "empty", "total": total, "got": 0}
            elif children:
                rec = {"key": key, "status": "split", "total": total,
                       "children": [{k: list(v) for k, v in c.items()} for c in children]}
                stack.extend(reversed(children))
            else:
                status = "capped" if total >= SPLIT_AT else "done"
                got, new = enumerate_leaf(client, node, total, ads, seen, lf)
                rec = {"key": key, "status": status, "total": total, "got": got, "new": new}
                if got < 0.97 * min(total, WINDOW_CAP):
                    print(f"  note: slice {key} returned {got}/{total} ads (the live feed shifted while paging).")
                if status == "capped":
                    print(f"  WARNING: slice {key} still holds {total:,} ads and cannot be split further.")
            slice_log[key] = rec
            append_jsonl(sf, rec)
            handled += 1
            if rec["status"] in ("done", "capped") and handled % 5 == 0:
                print(f"slices handled: {handled:,} | queue: {len(stack):,} | unique ids: {len(seen):,}", flush=True)
    leaves = [r for r in slice_log.values() if r["status"] in ("done", "capped")]
    summary = {
        "unique_ids": len(seen),
        "finished": not stopped_early and not stack,
        "leaf_slices": len(leaves),
        "sum_of_leaf_totals": sum(r["total"] for r in leaves),
        "capped_slices": [r["key"] for r in leaves if r["status"] == "capped"],
        "skipped_ads_without_id": STATS["skipped_ads"],
        "range_syntax": dict(RANGE_SYNTAX),
        "finished_at_utc": now_iso(),
    }
    (OUT / "listing_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return seen


# ============================ step 2: detail records ============================
def fetch_one(client, list_id, listing):
    """Fetch and parse one car's detail record. Never raises except Blocked."""
    ts = now_iso()
    try:
        _, raw = client.get(f"{API_LIST}/{list_id}", accept="application/json")
    except HttpError as exc:
        status = exc.status if exc.status in (404, 410) else (exc.status or -1)
        return parse_detail({}, list_id, source=None, listing=listing, scraped_at=ts, status=status, error=str(exc)[:200])
    try:
        row = parse_detail(json.loads(raw), list_id, source="api", listing=listing, scraped_at=ts)
    except (ValueError, TypeError) as exc:
        return parse_detail({}, list_id, source=None, listing=listing, scraped_at=ts, status=-2, error=f"parse: {exc}"[:200])
    if row["specs_json"] is None:          # API gave no spec list -> try the page's embedded JSON
        try:
            _, html = client.get(f"{BASE_URL}/{list_id}.htm", accept="text/html")
            data = extract_next_data(html)
            if data:
                alt = parse_detail(data, list_id, source="html", listing=listing, scraped_at=ts)
                if alt["specs_json"]:
                    row = alt
        except HttpError:
            pass
    return row


def quality_gate(rows):
    """Stop early if specs are not being parsed - the failure mode of the first version."""
    ok = [r for r in rows if r["detail_status"] == 200]
    if len(ok) < 20:
        return
    problems, warnings_ = [], []
    for field in ("brand", "model", "year", "transmission", "fuel", "body_type", "seats"):
        fill = sum(r[field] is not None for r in ok) / len(ok)
        if fill < 0.5:
            (problems if field in ("brand", "model", "year") else warnings_).append(f"{field} ({fill:.0%})")
    if warnings_:
        print("  WARNING low fill rate:", ", ".join(warnings_))
    if problems:
        labels = Counter()
        for r in ok:
            if r["specs_json"]:
                labels.update(json.loads(r["specs_json"]).keys())
        raise RuntimeError(f"Spec parsing failed for: {', '.join(problems)}. Labels actually seen: "
                           f"{labels.most_common(25)}. Compare them with SPEC_LABELS and sample_detail.json.")


def preflight_detail(list_client, detail_client, n=3):
    """Print the real specification block of live ads and verify it maps to columns."""
    _, ads = fetch_list_page(list_client, {}, 0, max(n, 5))
    good = 0
    for i, ad in enumerate(ads[:n]):
        list_id = str(ad["list_id"])
        _, raw = detail_client.get(f"{API_LIST}/{list_id}", accept="application/json")
        payload = json.loads(raw)
        if i == 0:
            (OUT / "sample_detail.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        specs = collect_specs(payload)
        mapped = map_specs(specs)
        print(f"\n--- ad {list_id} --- {len(specs)} spec entries")
        for s in specs:
            tag = "" if fold(s["label"] or "") in KNOWN_LABELS else "   (not mapped)"
            print(f"  {s['label'] or s['id']}: {s['value']}{tag}")
        print("  =>", {k: v for k, v in mapped.items() if v})
        good += all(mapped[f] for f in ("brand", "model", "year"))
    if good < max(1, n - 1):
        raise RuntimeError("Brand / model / year could not be read from the detail records. See the printed labels "
                           "above and sample_detail.json, then adjust SPEC_LABELS or collect_specs().")
    print("\nPre-flight OK: detail specs map to columns.")


def fetch_details(client, workers=None, max_details=None):
    workers = workers or DETAIL_WORKERS
    listings = {str(r["list_id"]): r for r in load_jsonl(LISTINGS_PATH)}
    done = {str(r["list_id"]) for r in load_jsonl(DETAILS_PATH) if r.get("detail_status") in (200, 404, 410)}
    todo = [i for i in listings if i not in done]
    if max_details:
        todo = todo[:max_details]
    eta_min = len(todo) / max(DETAIL_RPS, 0.1) / 60
    print(f"{len(listings):,} ids known, {len(done):,} already done, fetching {len(todo):,} "
          f"(about {eta_min:,.0f} min at {DETAIL_RPS}/s).")
    t0, fetched, gate_done = time.monotonic(), 0, False
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        with DETAILS_PATH.open("a", encoding="utf-8") as fh:
            for start in range(0, len(todo), 100):
                chunk = todo[start:start + 100]
                rows = list(pool.map(lambda i: fetch_one(client, i, listings[i]), chunk))
                for row in rows:
                    append_jsonl(fh, row)
                fetched += len(rows)
                if not gate_done:
                    quality_gate(rows)
                    gate_done = len([r for r in rows if r["detail_status"] == 200]) >= 20
                rate = fetched / (time.monotonic() - t0)
                print(f"details: {fetched:,}/{len(todo):,} | {rate:.1f}/s | ETA {(len(todo) - fetched) / rate / 60:,.0f} min", flush=True)
    except Blocked as exc:
        print("STOPPED:", exc)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return fetched


# ============================== step 3: CSV export ==============================
def export_csv():
    listings = {str(r["list_id"]): r for r in load_jsonl(LISTINGS_PATH)}
    details = {}
    for r in load_jsonl(DETAILS_PATH):                  # later lines win (retries)
        details[str(r["list_id"])] = r
    rows = []
    for lid in listings:
        r = details.get(lid)
        if r is None or (r["detail_status"] != 200 and not INCLUDE_UNAVAILABLE):
            continue
        r = dict(r)
        r["odo_suspect"] = odo_suspect(r.get("odo_km"), r.get("year"))
        rows.append(r)
    tmp = CSV_PATH.with_name(CSV_PATH.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(CSV_PATH)

    n = len(rows)
    status_counts = Counter(r["detail_status"] for r in details.values())
    fill = {c: round(sum(r.get(c) not in (None, "") for r in rows) / n, 3) if n else 0.0 for c in COLUMNS}
    report = {
        "ids_found": len(listings), "details_fetched": len(details), "rows_in_csv": n,
        "status_counts": {str(k): v for k, v in status_counts.items()},
        "ids_without_detail_yet": len(listings) - len(details),
        "fill_rate": fill, "exported_at_utc": now_iso(),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    weak = [c for c in ("brand", "model", "year", "transmission", "fuel", "body_type", "seats", "price_vnd") if fill[c] < 0.5]
    if n and weak:
        print("\nWARNING: these requested columns are mostly empty:", weak)
    if report["ids_without_detail_yet"]:
        print(f"\nNOTE: {report['ids_without_detail_yet']:,} ids still need the details step - rerun it to finish.")
    print("CSV saved at:", CSV_PATH.resolve())
    return rows


# ==================================== CLI ====================================
def build_parser():
    p = argparse.ArgumentParser(description="Chợ Tốt Xe car scraper (resumable, bypasses the 10k result window).")
    p.add_argument("command", choices=["preflight", "ids", "details", "export", "all"],
                   help="preflight: robots.txt + filter syntax + spec labels; ids: collect car ids; "
                        "details: fetch detail records; export: write the CSV; all: run every step in order")
    p.add_argument("--output-dir", default=OUTPUT_DIR, help=f"folder for progress files and CSV (default: {OUTPUT_DIR})")
    p.add_argument("--max-ids", type=int, default=MAX_LISTING_IDS, help="trial run: stop collecting ids after this many")
    p.add_argument("--max-details", type=int, default=MAX_DETAILS, help="trial run: fetch at most this many detail records")
    p.add_argument("--include-unavailable", action="store_true", default=INCLUDE_UNAVAILABLE,
                   help="keep rows of ads that disappeared (HTTP 404/410) in the CSV")
    p.add_argument("--list-rps", type=float, default=LIST_RPS, help=f"listing requests per second (default {LIST_RPS})")
    p.add_argument("--detail-rps", type=float, default=DETAIL_RPS, help=f"detail requests per second (default {DETAIL_RPS})")
    p.add_argument("--workers", type=int, default=DETAIL_WORKERS, help=f"detail worker threads (default {DETAIL_WORKERS})")
    return p


def main(argv=None):
    global LIST_RPS, DETAIL_RPS, DETAIL_WORKERS, INCLUDE_UNAVAILABLE
    args = build_parser().parse_args(argv)
    LIST_RPS, DETAIL_RPS, DETAIL_WORKERS = args.list_rps, args.detail_rps, args.workers
    INCLUDE_UNAVAILABLE = args.include_unavailable
    init_paths(args.output_dir)

    cmd = args.command
    if cmd == "export":
        export_csv()
        return 0

    list_client = Client(rps=LIST_RPS)
    detail_client = Client(rps=DETAIL_RPS)
    try:
        check_robots(list_client)
        if cmd in ("preflight", "ids", "all"):
            probe_filters(list_client)
        if cmd in ("preflight", "all"):
            preflight_detail(list_client, detail_client)
        if cmd in ("ids", "all"):
            crawl_listings(list_client, max_ids=args.max_ids)
        if cmd in ("details", "all"):
            fetch_details(detail_client, workers=DETAIL_WORKERS, max_details=args.max_details)
        if cmd == "all":
            export_csv()
    except Blocked as exc:
        print("STOPPED:", exc)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. Progress is saved; rerun the same command to resume.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())