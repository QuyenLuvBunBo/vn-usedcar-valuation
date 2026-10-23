import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://bonbanh.com/",
}

# After you solve the captcha by hand in a browser, pass that browser's cookie (and
# its User-Agent, they are often tied together) to the script via env vars:
#   BONBANH_COOKIE="name=value; name2=value2"   BONBANH_UA="Mozilla/5.0 ..."
if os.environ.get("BONBANH_COOKIE"):
    HEADERS["Cookie"] = os.environ["BONBANH_COOKIE"]
if os.environ.get("BONBANH_UA"):
    HEADERS["User-Agent"] = os.environ["BONBANH_UA"]

# all brands, used cars, 1997..2018 (already filtered by the site)
LIST_URL = "https://bonbanh.com/oto-tu-nam-1997-den-nam-2018-cu-da-qua-su-dung"
OUTPUT_FILE = "bonbanh.csv"
TITLES_FILE = "bonbanh_titles.csv"  # side file for the LLM step (brand / model / trim)
YEAR_MIN, YEAR_MAX = 1997, 2018
MAX_RETRIES = 3
REQ_DELAY = (1.0, 2.0)  # polite random delay before EVERY request (seconds)
MAX_BLOCK_STREAK = 5  # consecutive blocks before we stop the run

COLUMNS = [
    "listing_id",
    "source_platform",
    "brand",
    "model",
    "sub_model_trim",
    "manufacture_year",
    "mileage_km",
    "transmission",
    "fuel_type",
    "origin",
    "body_type",
    "engine_capacity",
    "seats",
    "location_province",
    "seller_type",
    "price_vnd",
    "source_url",
    "listing_date",
    "scraped_at",
    "raw_price_text",
    "price_status",
]

TITLES_COLUMNS = [
    "listing_id",
    "source_url",
    "crumb_brand",
    "crumb_model",
    "raw_title",
    "manufacture_year",
    "raw_body",
    "seller_address",
]

LABELS = {
    "Năm sản xuất": "year",
    "Số Km đã đi": "mileage",
    "Xuất xứ": "origin",
    "Kiểu dáng": "body",
    "Hộp số": "trans",
    "Động cơ": "engine",
    "Số chỗ ngồi": "seats",
}

PRICE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?\s*tỷ(?:\s*\d+(?:[.,]\d+)?\s*(?:triệu)?)?"
    r"|\d+(?:[.,]\d+)?\s*triệu)",
    re.I,
)

_local = threading.local()


# ---------- rate-limit handling ----------

_block_lock = threading.Lock()
_block_until = 0.0
_block_streak = 0
_abort = False


def wait_if_blocked():
    """All threads pause while a cooldown is active."""
    while True:
        with _block_lock:
            wait = _block_until - time.time()
        if wait <= 0:
            return
        time.sleep(min(wait, 5))


def report_block(reason):
    """Called on 403/429/503 or a 'soft block' page. Escalating shared cooldown."""
    global _block_until, _block_streak, _abort
    with _block_lock:
        _block_streak += 1
        cooldown = min(60 * 2 ** (_block_streak - 1), 900)  # 60,120,240,480,900s
        _block_until = max(_block_until, time.time() + cooldown)
        streak = _block_streak
        if streak >= MAX_BLOCK_STREAK:
            _abort = True
    print(
        f"     BLOCKED ({reason}); streak {streak}/{MAX_BLOCK_STREAK}, "
        f"cooling down {cooldown}s"
    )


def report_ok():
    global _block_streak
    with _block_lock:
        _block_streak = 0


# ---------- http ----------


def get_session():
    if not hasattr(_local, "session"):
        s = requests.Session()
        s.headers.update(HEADERS)
        _local.session = s
    return _local.session


def get_with_retry(url, timeout=15):
    for attempt in range(1, MAX_RETRIES + 1):
        if _abort:
            return None
        wait_if_blocked()
        time.sleep(random.uniform(*REQ_DELAY))
        try:
            r = get_session().get(url, timeout=timeout)
            if r.status_code == 404:
                return r
            if r.status_code in (403, 429, 503):
                report_block(f"HTTP {r.status_code}")
                continue
            r.raise_for_status()
            r.encoding = "utf-8"
            return r
        except requests.RequestException as e:
            print(f"     Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            time.sleep(3 * attempt)
    return None


# ---------- normalizers (REPLACE with src/common helpers) ----------


def to_int(text):
    d = re.sub(r"\D", "", text or "")
    return int(d) if d else None


def price_to_vnd(text):
    """'1 Tỷ 150 Triệu' -> 1150000000. None if no definite price."""
    if not text:
        return None

    def num(p):
        m = re.search(p, text, re.I)
        return float(m.group(1).replace(",", ".")) if m else None

    ty = num(r"(\d+(?:[.,]\d+)?)\s*tỷ")
    trieu = num(r"(\d+(?:[.,]\d+)?)\s*triệu")
    if ty is None and trieu is None:
        return None
    return int(round(((ty or 0) * 1000 + (trieu or 0)) * 1_000_000))


def price_status(raw, vnd):
    t = (raw or "").lower()
    if vnd is not None:
        return "full"
    if "trả góp" in t:
        return "instalment"
    if "liên hệ" in t or "thỏa thuận" in t or "thoả thuận" in t:
        return "negotiable"
    return "invalid"


def map_transmission(v):
    t = (v or "").lower()
    if "tự động" in t:
        return "Automatic"
    if "số tay" in t or "sàn" in t:
        return "Manual"
    return "Other" if t else "Unknown"


def map_fuel(v):
    t = (v or "").lower()
    if "hybrid" in t:
        return "Hybrid"
    if "điện" in t or "electric" in t:
        return "Electric"
    if "dầu" in t or "diesel" in t:
        return "Diesel"
    if "xăng" in t:
        return "Gasoline"
    return "Unknown"


def map_origin(v):
    t = (v or "").lower()
    if "lắp ráp" in t:
        return "CKD"
    if "nhập" in t:
        return "CBU"
    return "Unknown"


def map_body(v):
    t = (v or "").lower()
    for key, out in [
        ("sedan", "Sedan"),
        ("suv", "SUV"),
        ("crossover", "Crossover"),
        ("hatchback", "Hatchback"),
        ("coupe", "Coupe"),
        ("convertible", "Convertible"),
        ("cabriolet", "Convertible"),
        ("wagon", "Wagon"),
        ("mpv", "MPV"),
        ("minivan", "MPV"),
        ("bán tải", "Pickup"),
        ("pickup", "Pickup"),
        ("van", "Van"),
        ("tải", "Truck"),
    ]:
        if key in t:
            return out
    return "Other" if t else "Unknown"


def engine_litres(v):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*L\b", v or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def to_iso_date(dmy):
    try:
        return datetime.strptime(dmy, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


# ---------- list page ----------


def extract_year(text):
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
    return int(years[-1]) if years else None


# listing links end with the numeric id: .../xe-hyundai-i30-cw-1.6-at-2011-6905111
LISTING_HREF_RE = re.compile(r"(?:^|/)xe-[^/\s]+-\d{6,9}/?$", re.I)


def find_car_items(soup):
    """One container per listing, found via its link (independent of CSS classes)."""
    items, seen_href = [], set()
    for a in soup.find_all("a", href=LISTING_HREF_RE):
        href = a["href"].strip()
        if href in seen_href:
            continue
        seen_href.add(href)
        items.append(a.find_parent("li") or a)
    return items


# list item text: "Bán xe Lexus RX 2021 300 giá 2 Tỷ 650 Triệu - Phú Thọ Mã: 6917414"
LIST_RE = re.compile(r"giá\s+(.+?)\s+-\s+(.+?)\s+Mã\s*:\s*(\d+)", re.I)
TITLE_ATTR_RE = re.compile(r"\bgia\s+(.+?)\s+-\s+([^-]+)$", re.I)


def parse_list_item(item):
    if item.name == "a":
        a = item
    else:
        a = (
            item.select_one("h3 a[href]")
            or item.find("a", href=LISTING_HREF_RE)
            or item.find("a", href=True)
        )
    if not a:
        return None
    link = a["href"].strip()
    if not link.startswith("http"):
        link = f"https://bonbanh.com/{link.lstrip('/')}"

    h3 = item.find("h3")
    if h3:
        raw_name = h3.get_text(" ", strip=True)
    else:  # title attr: "Ban xe oto cu Hyundai i30 2011 CW 1.6 AT gia 215 Triệu - Phú Thọ"
        t = re.sub(r"^Ban xe oto cu\s+", "", a.get("title") or "", flags=re.I)
        raw_name = re.sub(r"\s+gia\s+.*$", "", t, flags=re.I)
    text = item.get_text(" ", strip=True)

    price = loc = None
    m = LIST_RE.search(text)
    if m:
        price, loc = m.group(1).strip(), m.group(2).strip()
    else:
        m = TITLE_ATTR_RE.search(a.get("title") or "")
        if m:
            price, loc = m.group(1).strip(), m.group(2).strip()

    return {
        "title": re.sub(r"\s*-\s*(19|20)\d{2}\s*$", "", raw_name).strip(),
        "list_year": extract_year(raw_name) or extract_year(text[:120]),
        "raw_price_text": price,
        "location": loc,
        "source_url": link,
    }


def fetch_list_page(args):
    """Returns (records, total_pages, total_items) or None."""
    base, page_num = args
    url = base if page_num == 1 else f"{base}/page,{page_num}"
    for _ in range(MAX_RETRIES):
        resp = get_with_retry(url)
        if resp is None or resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        recs = [r for r in map(parse_list_item, find_car_items(soup)) if r]
        text = soup.get_text(" ", strip=True)
        m = re.search(r"Trang\s*\d+\s*/\s*(\d+)", text)
        t = re.search(r"Tổng\s*:\s*([\d.,]+)\s*tin", text)
        pages = int(m.group(1)) if m else 1
        items = to_int(t.group(1)) if t else None
        if recs:
            report_ok()
            return recs, pages, items
        if page_num == 1:  # let scrape() explain / dump the page
            return recs, pages, items
        report_block("page returned 200 but no listings")  # soft block
    return None


# ---------- detail page ----------


def find_price(soup, lines):
    """Price appears as 'Xe ... 2017 - 650 Triệu' near the top of the page."""
    for l in lines[:50]:
        m = re.match(r"^Xe .+?\s-\s*(.+)$", l)
        if m:
            tail = m.group(1)
            pm = PRICE_RE.search(tail)
            if pm:
                return pm.group(1).strip()
            if "liên hệ" in tail.lower():
                return "Liên hệ"
    # fallback: flattened text above the specs table
    flat = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    head = flat.split("Thông số kỹ thuật")[0]
    pm = PRICE_RE.search(head)
    if pm:
        return pm.group(1).strip()
    return None


def parse_breadcrumb(lines):
    head = " ".join(l for l in lines[:40] if l != "Loading...")
    m = re.search(
        r"Trang chủ\s*»\s*Ô tô\s*»\s*(.+?)\s*»\s*(.+?)\s*»\s*(?:\d{4})\b", head
    )
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    lines = [
        l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()
    ]
    out = {v: None for v in LABELS.values()}

    for i, line in enumerate(lines):
        for label, col in LABELS.items():
            if out[col] or not line.startswith(label):
                continue
            rest = line[len(label) :].lstrip(" :").strip()
            out[col] = rest or (lines[i + 1] if i + 1 < len(lines) else None)

    out["crumb_brand"], out["crumb_model"] = parse_breadcrumb(lines)
    out["raw_price"] = find_price(soup, lines)

    text = "\n".join(lines)

    def grab(p):
        m = re.search(p, text)
        return m.group(1).strip() if m else None

    out["listing_id"] = grab(r"Mã tin\s*:\s*(\d+)")
    out["posted"] = grab(r"Đăng ngày\s*(\d{2}/\d{2}/\d{4})")
    out["seller_address"] = grab(r"Địa chỉ\s*:\s*\n?(.+)")
    return out


def fetch_detail(rec):
    resp = get_with_retry(rec["source_url"])
    if resp is None or resp.status_code != 200:
        return {}
    d = parse_detail(resp.text)
    if not d.get("listing_id") and not d.get("year"):  # looks like a block page
        report_block("detail page had no data")
        return {}
    report_ok()
    return d


# ---------- build schema row ----------


def build_row(rec, d):
    year = to_int(d.get("year")) or rec["list_year"]
    raw_price = rec["raw_price_text"] or d.get("raw_price")
    vnd = price_to_vnd(raw_price)
    lid = d.get("listing_id") or re.sub(r"\D", "", rec["source_url"])[-9:] or None
    engine = d.get("engine")
    km = to_int(d.get("mileage"))
    return {
        "listing_id": f"BAN_{lid}" if lid else None,
        "source_platform": "bonbanh",
        "brand": None,  # filled by the LLM step
        "model": None,  # filled by the LLM step
        "sub_model_trim": None,  # filled by the LLM step
        "manufacture_year": year,
        "mileage_km": float(km) if km else None,  # 0 km -> null
        "transmission": map_transmission(d.get("trans")),
        "fuel_type": map_fuel(engine),
        "origin": map_origin(d.get("origin")),
        "body_type": map_body(d.get("body")),
        "engine_capacity": engine_litres(engine),
        "seats": to_int(d.get("seats")),
        "location_province": rec["location"],  # normalize later
        "seller_type": "Unknown",  # no reliable signal yet
        "price_vnd": vnd,
        "source_url": rec["source_url"],
        "listing_date": to_iso_date(d.get("posted")),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_price_text": raw_price,
        "price_status": price_status(raw_price, vnd),
    }


# ---------- main ----------


def save_csv(rows, path, columns=None):
    if rows:
        pd.DataFrame(rows, columns=columns).to_csv(
            path,
            mode="a",
            index=False,
            header=not os.path.exists(path),
            encoding="utf-8-sig",
        )


def load_seen_urls():
    if os.path.exists(OUTPUT_FILE):
        try:
            return set(pd.read_csv(OUTPUT_FILE, usecols=["source_url"])["source_url"])
        except Exception:
            pass
    return set()


def process(recs, detail_pool, seen, limit):
    """Fetch details for new in-range listings, save them, return count saved."""
    cands = []
    for rec in recs:
        if rec["source_url"] in seen:
            continue
        seen.add(rec["source_url"])
        if rec["list_year"] and YEAR_MIN <= rec["list_year"] <= YEAR_MAX:
            cands.append(rec)
    cands = cands[:limit]
    if not cands:
        return 0

    details = list(detail_pool.map(fetch_detail, cands))
    pairs = []
    for rec, det in zip(cands, details):
        if det:
            pairs.append((rec, det))
        else:
            seen.discard(rec["source_url"])  # failed: retry next run

    rows = [build_row(rec, det) for rec, det in pairs]
    save_csv(rows, OUTPUT_FILE, COLUMNS)
    # side file for the LLM step; join back to bonbanh.csv on source_url
    save_csv(
        [
            {
                "listing_id": f"BAN_{det.get('listing_id')}"
                if det.get("listing_id")
                else None,
                "source_url": rec["source_url"],
                "crumb_brand": det.get("crumb_brand"),
                "crumb_model": det.get("crumb_model"),
                "raw_title": rec["title"],
                "manufacture_year": rec["list_year"],
                "raw_body": det.get("body"),
                "seller_address": det.get("seller_address"),
            }
            for rec, det in pairs
        ],
        TITLES_FILE,
        TITLES_COLUMNS,
    )

    no_price = sum(1 for r in rows if r["raw_price_text"] is None)
    print(
        f"    +{len(rows)} saved | failed {len(cands) - len(rows)} | no price {no_price}"
    )
    return len(rows)


def scrape(target_count=5000, page_workers=1, detail_workers=1, pages_per_round=1):
    seen = load_seen_urls()
    collected = len(seen)
    print(f"Resuming with {collected} rows in {OUTPUT_FILE}. Target {target_count}.")
    if collected >= target_count:
        print(
            f"Already at target. Delete {OUTPUT_FILE} / {TITLES_FILE} to start "
            f"fresh, or raise target_count."
        )
        return

    first = fetch_list_page((LIST_URL, 1))
    if first is None:
        print("Could not fetch page 1 (blocked or network error).")
        return
    if not first[0]:
        r = get_with_retry(LIST_URL)
        html = r.text if r is not None else ""
        with open("debug_page1.html", "w", encoding="utf-8") as f:
            f.write(html)
        n_links = len(
            BeautifulSoup(html, "html.parser").find_all("a", href=LISTING_HREF_RE)
        )
        print("Page 1 loaded but no listings were parsed. Saved debug_page1.html")
        print(
            f'  length={len(html)}  "Mã:" count={html.count("Mã:")}  '
            f"<li>={html.count('<li')}  <h3>={html.count('<h3')}  listing links={n_links}"
        )
        print(
            "  Open debug_page1.html in a browser. No listings in it = probably rate limited:"
        )
        print(
            "  wait 30-60+ min (or until the site opens normally in your browser), then re-run."
        )
        return
    recs, total_pages, total_items = first
    print(f"{total_items} listings, {total_pages} pages")

    with (
        ThreadPoolExecutor(page_workers) as pages_pool,
        ThreadPoolExecutor(detail_workers) as detail_pool,
    ):
        pending, page = recs, 2
        while True:
            collected += process(pending, detail_pool, seen, target_count - collected)
            print(
                f"  page {min(page - 1, total_pages)}/{total_pages} | total {collected}"
            )
            if _abort:
                print(
                    "\nStopped: rate limited. Wait a while, then re-run (it resumes)."
                )
                break
            if collected >= target_count or page > total_pages:
                break
            chunk = [
                (LIST_URL, p)
                for p in range(page, min(page + pages_per_round, total_pages + 1))
            ]
            page += pages_per_round
            pending = []
            for r in pages_pool.map(fetch_list_page, chunk):
                if r:
                    pending.extend(r[0])

    print(f"\n[DONE] {collected} rows in {OUTPUT_FILE}")


if __name__ == "__main__":
    # TARGET=1000 python bonbanh_scraper.py  -> run in chunks (resumes from the CSV)
    scrape(target_count=int(os.environ.get("TARGET", 5000)))
