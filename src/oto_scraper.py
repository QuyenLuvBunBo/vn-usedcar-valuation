"""Cào xe cũ nhóm phổ thông châu Á trên oto.com.vn.

Phạm vi: Toyota, Hyundai, Kia, Mazda, Honda, Mitsubishi — chỉ tin "Xe cũ".
Nguồn: trang listing /mua-ban-xe-<brand>[/p<N>], 15 tin/trang, server-render.

Chạy:
    python -m src.oto_scraper                       # cào cả 6 hãng
    python -m src.oto_scraper --brands toyota kia   # chỉ 1 vài hãng
    python -m src.oto_scraper --pages 3             # giới hạn 3 trang/hãng (test)
    python -m src.oto_scraper --save-raw            # lưu thêm HTML thô từng trang
"""

from __future__ import annotations

import argparse
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

from . import config, storage
from .http_client import ScraperSession

BASE_URL = "https://oto.com.vn"
PER_PAGE = 15
TABLE = "oto_cars"

BRANDS: dict[str, str] = {
    "toyota": "Toyota",
    "hyundai": "Hyundai",
    "kia": "Kia",
    "mazda": "Mazda",
    "honda": "Honda",
    "mitsubishi": "Mitsubishi",
}

COLUMNS = [
    "url", "id", "brand", "model", "car_name", "title",
    "condition", "sold", "origin", "year", "price_text", "price_vnd",
    "km", "gearbox", "fuel", "body_type", "color",
    "province", "seller_name", "phone", "vip_type", "listing_type",
    "image_url", "source_page",
]

NUMERIC_COLUMNS = ("year", "price_vnd", "km", "sold")

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'
# Site viết lẫn lộn "tỷ"/"tỉ", "nghìn"/"ngàn" -> nhận cả hai.
PRICE_UNITS = {
    "triệu": 10**6, "triêu": 10**6, "tr": 10**6,
    "tỷ": 10**9, "tỉ": 10**9, "ty": 10**9, "ti": 10**9,
    "nghìn": 10**3, "ngàn": 10**3,
}
PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(triệu|triêu|tỷ|tỉ|nghìn|ngàn|tr|ty|ti)\b", re.I)
VALID_ORIGINS = {"trong nước", "nhập khẩu"}
VALID_CONDITIONS = {"xe cũ", "xe mới"}

log = logging.getLogger("oto_scraper")


# ---------------------------------------------------------------- tiện ích
def _clean(value: str | None) -> str:
    """Chuẩn hóa khoảng trắng và ký tự đặc biệt của HTML."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _first(node, xpath: str) -> str:
    """Lấy giá trị đầu tiên của xpath, trả về '' nếu không có."""
    found = node.xpath(xpath)
    return _clean(str(found[0])) if found else ""


def _text_of(node) -> str:
    """Gộp toàn bộ text con thành 1 chuỗi đã chuẩn hóa."""
    return _clean(" ".join(node.itertext()))


def parse_price(text: str) -> int | None:
    """Đổi '335 triệu' / '1 tỷ 045 triệu' / '1 tỉ 450 triệu' / '1,2 tỷ' -> số VND.

    Trả None nếu không có giá (ô giá rỗng, hoặc ghi 'Thỏa thuận'/'Liên hệ').
    """
    if not text:
        return None
    total = 0.0
    for number, unit in PRICE_RE.findall(text):
        total += float(number.replace(",", ".")) * PRICE_UNITS[unit.lower()]
    if total <= 0:
        return None
    return int(round(total))


def parse_km(tag: str) -> int | None:
    """Đổi '140.000 km' -> 140000."""
    digits = re.sub(r"\D", "", tag or "")
    return int(digits) if digits else None


def parse_year(car_name: str, title: str = "") -> int | None:
    """Lấy năm sản xuất từ '2014 - Toyota ...'; nếu không có thì dò trong tiêu đề."""
    match = re.match(r"^\s*((?:19|20)\d{2})\s*[-–]", car_name or "")
    if match:
        return int(match.group(1))
    match = re.search(r"\b((?:19|20)\d{2})\b", title or "")
    if match:
        year = int(match.group(1))
        if 1980 <= year <= 2100:
            return year
    return None



def parse_data_call(data_call: str) -> dict[str, str]:
    """Bóc thông tin cấu trúc trong thuộc tính data-call của nút "Gọi ngay".

    Định dạng (neo từ cuối để chịu được dấu '.' trong tên model):
        hãng.model.tình trạng.xuất xứ.năm.giá.loại xe.màu.listtype.viptype.id.
    Trả về {} nếu định dạng không khớp (khi đó dùng dữ liệu DOM/tinrao thay thế).
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

    # Kiểm tra chéo: lệch cấu trúc thì bỏ, tránh ghi dữ liệu rác.
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
    """Bóc dữ liệu 1 tin đăng từ thẻ div.item-car.

    Lưu ý về tin đã bán: khi tin bán xong, site thêm class "sold" và gỡ nút
    "Gọi ngay" -> không còn `data-call`/`data-phone`. Vì vậy các field
    origin/body_type/color/listing_type/phone sẽ rỗng với tin đã bán
    (cột `sold` = 1 giúp lọc ra chúng).
    """
    href = _first(item, './/h3/a/@href') or _first(item, './/div[@class="photo"]//a/@href')
    if not href:
        return None
    url = urljoin(BASE_URL, href)

    # Nguồn có cấu trúc sẵn: data-tinrao (hãng.model.tình trạng.id.vip) và data-call (đầy đủ hơn)
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
    """Đọc 'Có 892 tin bán xe ...' -> 892. None nếu không tìm thấy."""
    tree = html.fromstring(html_text)
    body = re.sub(r"\s+", " ", tree.text_content())
    match = re.search(r"C[oó]\s*([\d\.,]+)\s*tin", body)
    if not match:
        return None
    return int(match.group(1).replace(".", "").replace(",", ""))


def parse_list_page(html_text: str, page_url: str) -> list[dict]:
    """Bóc toàn bộ tin đăng trong 1 trang listing."""
    tree = html.fromstring(html_text)
    records = []
    for item in tree.xpath(ITEM_XPATH):
        record = parse_item(item, page_url)
        if record:
            records.append(record)
    return records



# --------------------------------------------------------------- parse lại raw
RAW_PAGE_RE = re.compile(r"^oto_(?P<brand>[a-z]+)_p(?P<page>\d+)\.html$")


def parse_raw_files(
    brands: Iterable[str] | None = None,
    only_used: bool = True,
    exclude_sold: bool = False,
) -> list[dict]:
    """Parse lại HTML thô trong data/raw (không gọi mạng).

    Dùng khi sửa parser: khỏi phải cào lại 181 trang, chỉ cần chạy lại bước parse.
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
    log.info("Parse lại %s file HTML thô -> %s record", used, len(records))
    return records


# -------------------------------------------------------------------- crawl
def list_url(brand: str, page: int) -> str:
    """URL trang listing: trang 1 không có hậu tố, các trang sau là /p<N>."""
    base = f"{BASE_URL}/mua-ban-xe-{brand}"
    return base if page <= 1 else f"{base}/p{page}"


def coerce_numeric(rows: Iterable[dict]) -> list[dict]:
    """Ép các cột số về int (SQLite lưu tất cả dạng TEXT khi đọc lại)."""
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
    """Loại tin trùng theo url (giữ bản ghi đầu tiên).

    Cần thiết vì khi đang cào, tin mới được đăng lên làm các trang dịch nội dung,
    nên cùng một tin có thể xuất hiện ở 2 trang khác nhau.
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
    """Sinh ra từng record của 1 hãng, dừng đúng theo tổng số tin công bố.

    Hai đặc thù của site cần xử lý:
    1. Trang vượt giới hạn (vd /p999) KHÔNG trả 404 mà trả "0 tin" + danh sách
       rơi về trang 1 -> phải tính số trang từ tổng số tin ("Có N tin").
    2. Thỉnh thoảng server trả về trang rỗng -> thử lại vài lần trước khi bỏ.
    """
    page = 1
    state = {"last_page": max_pages or 1, "total": None}
    bar = tqdm(total=state["last_page"], desc=f"{BRANDS.get(brand, brand):<11}", unit="trang")

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

                # Trang 1: đọc tổng số tin để biết cần cào bao nhiêu trang.
                if page == 1 and state["total"] is None:
                    state["total"] = parse_total(html_text)
                    if state["total"]:
                        state["last_page"] = math.ceil(state["total"] / PER_PAGE)
                        if max_pages is not None:
                            state["last_page"] = min(state["last_page"], max_pages)
                        log.info("[%s] tổng %s tin -> %s trang", brand, state["total"], state["last_page"])
                    else:
                        state["last_page"] = max_pages or 1
                        log.warning("[%s] không đọc được tổng số tin -> cào %s trang", brand, state["last_page"])
                    bar.total = state["last_page"]

                records = parse_list_page(html_text, url)
                if only_used:
                    kept = [r for r in records if r["condition"].lower() == "xe cũ"]
                    if len(kept) != len(records):
                        log.info("[%s] trang %s: loại %s tin không phải xe cũ",
                                 brand, page, len(records) - len(kept))
                    records = kept
                if exclude_sold:
                    kept = [r for r in records if not r["sold"]]
                    if len(kept) != len(records):
                        log.info("[%s] trang %s: loại %s tin đã bán",
                                 brand, page, len(records) - len(kept))
                    records = kept

                if records:
                    break
                log.warning("[%s] trang %s trả 0 tin (lần %s/%s) -> thử lại",
                            brand, page, attempt, page_retries)
                time.sleep(2 * attempt)

            if not records:
                log.error("[%s] bỏ qua trang %s: không có tin sau %s lần thử", brand, page, page_retries)
                break

            bar.update(1)
            bar.set_postfix_str(f"{len(records)} tin")
            yield from records
            page += 1
    finally:
        bar.close()




# --------------------------------------------------------------------- main
def setup_logging() -> None:
    """Log ra console + logs/oto_scraper.log."""
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
    """Khai báo tham số dòng lệnh."""
    parser = argparse.ArgumentParser(
        description="Cào xe cũ nhóm phổ thông châu Á trên oto.com.vn",
    )
    parser.add_argument("--brands", nargs="+", default=list(BRANDS), choices=list(BRANDS),
                        help="chỉ cào các hãng này (mặc định: cả 6 hãng)")
    parser.add_argument("--pages", type=int, default=None,
                        help="giới hạn số trang mỗi hãng (mặc định: cào hết)")
    parser.add_argument("--include-new", action="store_true",
                        help="lấy cả tin 'Xe mới' (mặc định chỉ xe cũ)")
    parser.add_argument("--exclude-sold", action="store_true",
                        help="bỏ tin đã bán (class 'sold'; mất phone/xuất xứ do site gỡ nút gọi)")
    parser.add_argument("--save-raw", action="store_true",
                        help="lưu HTML thô từng trang vào data/raw")
    parser.add_argument("--out", default="oto_cars", help="tên file CSV/JSONL đầu ra")
    parser.add_argument("--from-db", action="store_true",
                        help="không cào, chỉ xuất lại CSV/JSONL từ dữ liệu có trong DB")
    parser.add_argument("--from-raw", action="store_true",
                        help="không cào, parse lại HTML thô trong data/raw (dùng khi vừa sửa parser)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()

    conn = storage.open_db()
    storage.create_table(conn, TABLE, COLUMNS)
    storage.ensure_columns(conn, TABLE, COLUMNS)
    per_brand: Counter = Counter()

    if args.from_db:
        all_rows = coerce_numeric(storage.read_rows(conn, TABLE))
        log.info("Xuất lại từ DB: %s tin (không cào)", len(all_rows))
    elif args.from_raw:
        all_rows = dedupe_rows(
            parse_raw_files(
                args.brands,
                only_used=not args.include_new,
                exclude_sold=args.exclude_sold,
            )
        )
        storage.upsert_rows(conn, TABLE, all_rows)
        log.info("Đã parse lại & ghi đè %s tin vào DB từ HTML thô", len(all_rows))
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
                log.info("-> %s xong: %s tin", BRANDS[brand], len(all_rows) - before)

        duplicates = len(all_rows) - len(dedupe_rows(all_rows))
        if duplicates:
            log.warning("Có %s tin trùng url (tin mới chen vào khi phân trang dịch) -> đã loại bỏ",
                        duplicates)
        all_rows = dedupe_rows(all_rows)

    for row in all_rows:
        per_brand[row.get("brand") or "?"] += 1

    csv_path = storage.save_csv(all_rows, args.out, COLUMNS)
    jsonl_path = storage.save_jsonl(all_rows, args.out)

    total_db = storage.count_rows(conn, TABLE)
    conn.close()

    log.info("=" * 62)
    for name, count in per_brand.most_common():
        log.info("  %-12s %5d tin", name, count)
    log.info("-" * 62)
    log.info("Số tin lần xuất này : %s (đã loại trùng)", len(all_rows))
    log.info("Tổng trong DB       : %s (khóa chính = url)", total_db)
    sold_count = sum(1 for r in all_rows if r.get("sold"))
    log.info("Trong đó đã bán     : %s tin (%.1f%%) — dùng --exclude-sold để bỏ",
             sold_count, sold_count / len(all_rows) * 100 if all_rows else 0)
    log.info("CSV   : %s", csv_path)
    log.info("JSONL : %s", jsonl_path)

    priced = [r["price_vnd"] for r in all_rows if r.get("price_vnd")]
    if priced:
        log.info("Giá: %s/%s tin có giá | thấp nhất %.0f triệu | trung vị %.0f triệu | cao nhất %.2f tỷ",
                 len(priced), len(all_rows),
                 min(priced) / 1e6,
                 sorted(priced)[len(priced) // 2] / 1e6,
                 max(priced) / 1e9)
    return 0


if __name__ == "__main__":
    sys.exit(main())

