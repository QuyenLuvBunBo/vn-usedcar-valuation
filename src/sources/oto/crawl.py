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

# Tên tương thích: code cũ / tool cũ gọi parse_price, parse_km, parse_year
parse_price = parse_vnd_price
parse_km = parse_km_text
parse_year = parse_year_text

# Danh sách hãng tách riêng để 2 người cùng nguồn không phải sửa chung 1 file
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

# --- Trang chi tiết (bảng riêng, ghép vào CSV khi xuất) ---
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

ITEM_XPATH = '//div[contains(@class,"item-car") and contains(@class,"dev-item-car")]'
VALID_ORIGINS = {"trong nước", "nhập khẩu"}
VALID_CONDITIONS = {"xe cũ", "xe mới"}

log = logging.getLogger("oto_scraper")


# ------------------------------------------------------------- parser dữ liệu
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



# --------------------------------------------------------------- trang chi tiết
def _hidden_inputs(tree) -> dict[str, str]:
    """Lấy toàn bộ <input type="hidden"> thành dict id -> value."""
    return {
        inp.get("id"): _clean(inp.get("value"))
        for inp in tree.xpath("//input[@type='hidden']")
        if inp.get("id")
    }


def _int_or_none(value: str | None) -> int | None:
    """Đổi chuỗi số (có thể lẫn dấu) thành int; None nếu rỗng."""
    digits = re.sub(r"\D", "", value or "")
    return int(digits) if digits else None


def parse_detail_page(html_text: str, url: str) -> dict:
    """Bóc thông tin trang chi tiết của 1 tin đăng.

    Trang chi tiết KHÔNG có ngày đăng và KHÔNG có bảng thông số kỹ thuật chi tiết
    (động cơ/công suất/kích thước). Những gì lấy được:
      - input ẩn  : #price (giá dạng số), #numberOfSeat (số chỗ), #cityCode,
                    #hddMakeId, #hddModelId, #hddCityId, #hddSegmentId,
                    #hddUserId (id người bán), #hddVipType, #countImage
      - data-tragia : tên hãng/dòng/tình trạng/xuất xứ/năm/giá/loại xe/MÀU/listtype
      - ul.list-info: Năm SX, Nhiên liệu, Kiểu dáng, Tình trạng, Km đã đi, Hộp số,
                      Xuất xứ, Tỉnh thành
      - .box-salon  : tên salon/người bán, subdomain, địa chỉ, avatar
      - .content-description .description : mô tả của người bán
      - ảnh gallery (ảnh /crop/640x480/...)
    """
    tree = html.fromstring(html_text)
    hidden = _hidden_inputs(tree)

    # 8 thông số trong ul.list-info (nhãn nằm trong <label>, giá trị là text/div con)
    specs: dict[str, str] = {}
    for li in tree.xpath('//ul[contains(@class,"list-info")]/li'):
        label = _first(li, ".//label/text()").rstrip(":")
        text = _text_of(li)
        value = text[len(label):].lstrip(": ").strip() if label and text.startswith(label) else text
        if label:
            specs[label] = value

    # màu xe nằm trong data-tragia: hãng.dòng.tình trạng.xuất xứ.năm.giá.loại xe.MÀU.listtype...
    color = ""
    tragia = tree.xpath("//*[@data-tragia]/@data-tragia")
    if tragia:
        parts = tragia[0].rstrip(".").split(".")
        if len(parts) >= 8:
            color = _clean(parts[7])

    salon_nodes = tree.xpath('//div[contains(@class,"box-salon")]')
    salon = salon_nodes[0] if salon_nodes else None

    # Tên salon: lấy TOÀN BỘ text của h3 (tên nằm trong <a> con, text node đầu là khoảng trắng)
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

    # Giá hiển thị: span.price nằm trong span.price-big; phải loại price-big ra
    # (nếu không, text node đầu tiên sẽ là khoảng trắng -> rỗng).
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
    """Kiểm tra bảng đã tồn tại trong SQLite chưa."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def merge_details(conn, rows: list[dict]) -> list[dict]:
    """Ghép dữ liệu trang chi tiết (bảng riêng) vào record để xuất CSV/JSONL.

    Để riêng một bảng vì dữ liệu chi tiết chỉ có sau khi cào thêm: nếu ghi chung
    vào oto_cars thì mỗi lần cào lại listing (ON CONFLICT DO UPDATE) sẽ xoá mất
    các cột chi tiết này.
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
    """Cào trang chi tiết cho các tin chưa có (đã có thì bỏ qua -> chạy tiếp được).

    only_urls: chỉ cào đúng danh sách URL này (dùng để cào bù một nhóm nhỏ tin).
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
    log.info("Trang chi tiết: cần cào %s tin (đã có %s / tổng %s)", len(todo), len(done), len(urls))
    if not todo:
        return 0

    buffer: list[dict] = []
    ok = fail = 0
    for url in tqdm(todo, desc="Chi tiết", unit="tin"):
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
    log.info("Trang chi tiết: xong %s tin, lỗi %s tin", ok, fail)
    return ok


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
    parser.add_argument("--brands", nargs="+", default=None, choices=list(BRANDS),
                        help="chỉ cào các hãng này (mặc định: theo --group)")
    parser.add_argument("--group", choices=("all", "asia", "other"), default="all",
                        help="nhóm hãng: asia = 6 hãng phổ thông châu Á, other = các hãng còn lại")
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
    parser.add_argument("--detail", action="store_true",
                        help="cào thêm trang chi tiết từng tin (mô tả, màu, số chỗ, salon...); "
                             "~1 request/tin nên chạy sẽ lâu")
    parser.add_argument("--detail-only", action="store_true",
                        help="chỉ cào trang chi tiết từ danh sách tin có trong DB (không cào lại listing)")
    parser.add_argument("--detail-limit", type=int, default=None,
                        help="giới hạn số tin cào chi tiết (dùng để test nhanh)")
    parser.add_argument("--detail-refresh", action="store_true",
                        help="cào lại chi tiết cả những tin đã có (mặc định bỏ qua tin đã có)")
    parser.add_argument("--detail-save-raw", action="store_true",
                        help="lưu HTML thô trang chi tiết vào data/raw (tốn dung lượng)")
    parser.add_argument("--detail-missing-price", action="store_true",
                        help="cào lại chi tiết cho các tin THIẾU GIÁ ở listing, để lấy raw_price_text")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()

    # --group: chia phần việc giữa 2 người cùng nguồn
    if args.brands is None:
        if args.group == "asia":
            args.brands = list(BRANDS_ASIA)
        elif args.group == "other":
            args.brands = list(BRANDS_OTHER)
        else:
            args.brands = list(BRANDS)

    if args.detail_missing_price:
        args.detail_only = True  # cào bù chi tiết -> chỉ đọc DB, không cào lại listing
    if args.detail_only:
        args.from_db = True

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

    # Cào thêm trang chi tiết nếu được yêu cầu (~1 request/tin)
    if args.detail or args.detail_only:
        only_urls = None
        if args.detail_missing_price:
            only_urls = {r["url"] for r in all_rows if not (r.get("price_text") or "").strip()}
            log.info("Cào bù chi tiết cho %s tin thiếu giá ở listing", len(only_urls))
        with ScraperSession() as session:
            enrich_details(
                session,
                conn,
                limit=args.detail_limit,
                refresh=args.detail_refresh,
                save_raw=args.detail_save_raw,
                only_urls=only_urls,
            )

    # Ghép dữ liệu chi tiết (nếu đã có) vào record rồi mới xuất file
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
        log.info("  %-12s %5d tin", name, count)
    log.info("-" * 62)
    log.info("Số tin lần xuất này : %s (đã loại trùng)", len(all_rows))
    log.info("Tổng trong DB       : %s (khóa chính = url)", total_db)
    sold_count = sum(1 for r in all_rows if r.get("sold"))
    log.info("Trong đó đã bán     : %s tin (%.1f%%) — dùng --exclude-sold để bỏ",
             sold_count, sold_count / len(all_rows) * 100 if all_rows else 0)
    if detail_count:
        log.info("Đã có trang chi tiết: %s tin (đã ghép vào CSV/JSONL)", detail_count)
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

