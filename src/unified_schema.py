"""Chuẩn hoá dữ liệu oto.com.vn về Unified Schema (15 thuộc tính + 5 metadata) — Tuần 1.

Chạy:
    python -m src.unified_schema                 # dùng cache sitemap nếu có
    python -m src.unified_schema --fetch-sitemap # tải lại lastmod từ sitemap rồi mới xuất

Kết quả: data/processed/oto_unified.csv (+ .jsonl) và bảng audit độ phủ field.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys

from . import config, storage
from .http_client import ScraperSession

SOURCE_PLATFORM = "oto.com.vn"
LAST_MOD_CACHE = config.DATA_RAW / "sitemap_lastmod.json"
SITEMAPS = ("sitemap-detail-1.xml", "sitemap-detail-2.xml")
ENTRY_RE = re.compile(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Cho phép dính chữ ngay sau số (2.5Q, 1.5G, 2.4L) nhưng không khớp giữa số dài (123.45)
ENGINE_RE = re.compile(r"(?<![\d.])([0-9]\.[0-9])(?!\d)")

# 16 thuộc tính + 5 metadata của bảng Unified Schema (Table 2 trong report)
SCHEMA_COLUMNS = [
    # --- thuộc tính ---
    "listing_id", "source_platform", "brand", "model", "sub_model_trim",
    "manufacture_year", "mileage_km", "transmission", "fuel_type", "origin",
    "body_type", "engine_capacity", "seats", "location_province", "seller_type",
    "price_vnd",
    # --- metadata ---
    "source_url", "listing_date", "scraped_at", "raw_price_text", "price_status",
]

TRANSMISSION_MAP = {"số tự động": "Automatic", "số sàn": "Manual", "số hỗn hợp": "Other"}
FUEL_MAP = {
    "máy xăng": "Gasoline", "máy dầu": "Diesel", "hybrid": "Hybrid",
    "máy điện": "Electric", "điện": "Electric",
}
ORIGIN_MAP = {"trong nước": "CKD", "nhập khẩu": "CBU"}  # CKD = lắp ráp trong nước, CBU = nhập khẩu
BODY_MAP = {
    "bán tải": "Pickup", "van/minivan": "Van", "xe tải": "Truck",
    "sport car": "Sports", "mui trần": "Convertible", "crossover": "Crossover",
}
PROVINCE_MAP = {
    "tp.hcm": "TP. Hồ Chí Minh", "hcm": "TP. Hồ Chí Minh", "tphcm": "TP. Hồ Chí Minh",
    "sài gòn": "TP. Hồ Chí Minh", "hà nội": "Hà Nội", "hn": "Hà Nội",
    "đà nẵng": "Đà Nẵng", "hải phòng": "Hải Phòng", "cần thơ": "Cần Thơ",
}
CITY_CODE_MAP = {"SG": "TP. Hồ Chí Minh", "HN": "Hà Nội", "DN": "Đà Nẵng"}

NEGOTIABLE = ("thỏa thuận", "thương lượng", "liên hệ", "tl")
INSTALMENT = ("trả góp", "góp", "/tháng", "mỗi tháng")

log = logging.getLogger("unified_schema")


# ------------------------------------------------------------------ tiện ích
def _norm(value: str | None) -> str:
    """Chuẩn hoá để so khớp: gộp khoảng trắng, về chữ thường."""
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip().lower()


def _to_int(value) -> int | None:
    """Ép về int (SQLite trả về chuỗi); None nếu rỗng/không hợp lệ."""
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    """Ép về float; None nếu rỗng/không hợp lệ."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _km_from_text(value: str | None) -> float | None:
    """Đổi '140.000 km' -> 140000.0."""
    digits = re.sub(r"\D", "", value or "")
    return float(digits) if digits else None


def map_value(value: str | None, mapping: dict[str, str], unknown: str = "Unknown") -> str:
    """Ánh xạ nhãn tiếng Việt sang nhãn chuẩn; không khớp -> giữ nhãn gốc/Unknown."""
    key = _norm(value)
    if not key:
        return unknown
    if key in mapping:
        return mapping[key]
    compact = key.replace(" ", "")
    if compact in mapping:
        return mapping[compact]
    return value.strip() if value else unknown


def derive_trim(brand: str, model: str, title: str, car_name: str) -> str:
    """Tách sub_model_trim (vd '1.8G CVT', '2.5Q') khỏi tiêu đề hoặc car_name."""
    text = (title or "").strip()
    if not text and car_name:
        # car_name dạng "2021 - Honda CR-V 1.5 G - mô tả..."
        parts = [p.strip() for p in car_name.split(" - ")]
        text = parts[1] if len(parts) > 1 else car_name
    if not text:
        return ""
    trim = text
    for prefix in (f"{brand} {model}".strip(), model, brand):
        if prefix and trim.lower().startswith(prefix.lower()):
            trim = trim[len(prefix):]
            break
    trim = YEAR_RE.sub(" ", trim)
    trim = re.sub(r"^[\s\-–,\.]+|[\s\-–,\.]+$", "", trim)
    return re.sub(r"\s+", " ", trim)


def derive_engine_capacity(*texts: str) -> float | None:
    """Ước lượng dung tích động cơ (L) từ trim/tiêu đề — vd '1.5 G' -> 1.5."""
    for text in texts:
        for found in ENGINE_RE.findall(text or ""):
            value = float(found)
            if 0.6 <= value <= 6.9:
                return value
    return None


def price_status_of(price_vnd: int | None, raw_price_text: str) -> str:
    """Trạng thái giá: full / negotiable / instalment / invalid."""
    text = _norm(raw_price_text)
    if any(k in text for k in INSTALMENT):
        return "instalment"
    if any(k in text for k in NEGOTIABLE):
        return "negotiable"
    return "full" if price_vnd else "invalid"


def seller_type_of(detail: dict | None) -> str:
    """Salon có subdomain riêng trên oto.com.vn; cá nhân thì không có."""
    if not detail:
        return "Unknown"
    return "Dealership/Salon" if (detail.get("d_seller_url") or "").strip() else "Private Individual"


def normalize_province(raw: str | None, city_code: str = "") -> str:
    """Chuẩn hoá tỉnh/thành; giữ nguyên nhãn gốc nếu chưa có trong từ điển."""
    key = _norm(raw)
    if key in PROVINCE_MAP:
        return PROVINCE_MAP[key]
    stripped = key.replace("tp.", "").replace("tp ", "").replace(" ", "")
    if stripped and stripped in PROVINCE_MAP:
        return PROVINCE_MAP[stripped]
    # dạng "Thủ Đức - Tp.HCM", "Quận 1, HCM"... -> gom về thành phố lớn
    for needle, name in (
        ("hcm", "TP. Hồ Chí Minh"), ("hồ chí minh", "TP. Hồ Chí Minh"), ("sài gòn", "TP. Hồ Chí Minh"),
        ("hà nội", "Hà Nội"), ("đà nẵng", "Đà Nẵng"), ("hải phòng", "Hải Phòng"), ("cần thơ", "Cần Thơ"),
    ):
        if needle in key:
            return name
    if raw and raw.strip():
        return raw.strip()
    return CITY_CODE_MAP.get((city_code or "").upper(), "Unknown")



# ------------------------------------------------------- lastmod từ sitemap
def fetch_lastmod_map(session: ScraperSession) -> dict[str, str]:
    """Tải sitemap-detail -> dict url -> lastmod (ngày đăng/đẩy tin gần nhất)."""
    result: dict[str, str] = {}
    for name in SITEMAPS:
        text = session.get_text(f"https://oto.com.vn/{name}")
        if not text:
            log.warning("không lấy được %s", name)
            continue
        entries = ENTRY_RE.findall(text)
        log.info("%s: %s entry", name, len(entries))
        for url, lastmod in entries:
            result[url] = lastmod
    return result


def load_lastmod_map(fetch: bool = False) -> dict[str, str]:
    """Đọc cache lastmod; tải mới nếu --fetch-sitemap hoặc chưa có cache."""
    if not fetch and LAST_MOD_CACHE.exists():
        cached = json.loads(LAST_MOD_CACHE.read_text(encoding="utf-8"))
        log.info("Dùng cache lastmod: %s (%s tin)", LAST_MOD_CACHE, len(cached))
        return cached
    with ScraperSession(delay=1.0) as session:
        mapping = fetch_lastmod_map(session)
    if mapping:
        config.ensure_dirs()
        LAST_MOD_CACHE.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        log.info("Đã lưu cache lastmod: %s (%s tin)", LAST_MOD_CACHE, len(mapping))
    return mapping


# --------------------------------------------------------------- transform
def _load_tables(conn: sqlite3.Connection) -> tuple[list[dict], dict[str, dict]]:
    """Đọc bảng oto_cars và oto_car_details (nếu đã cào chi tiết)."""
    cars = storage.read_rows(conn, "oto_cars")
    has_detail = any(
        row[0] == "oto_car_details"
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    )
    details = {r["url"]: r for r in storage.read_rows(conn, "oto_car_details")} if has_detail else {}
    return cars, details


def build_unified(conn: sqlite3.Connection, lastmods: dict[str, str]) -> list[dict]:
    """Ghép oto_cars + oto_car_details rồi chuẩn hoá về Unified Schema."""
    cars, details = _load_tables(conn)

    rows: list[dict] = []
    for car in cars:
        detail = details.get(car["url"], {})
        specs: dict[str, str] = {}
        if detail.get("d_specs"):
            try:
                specs = json.loads(detail["d_specs"])
            except ValueError:
                specs = {}

        trim = derive_trim(
            car.get("brand", ""), car.get("model", ""),
            detail.get("d_title", ""), car.get("car_name", ""),
        )
        # Giá: ưu tiên listing; nếu listing để trống thì lấy từ trang chi tiết
        price_vnd = _to_int(car.get("price_vnd")) or _to_int(detail.get("d_price_vnd"))
        raw_price = (car.get("price_text") or "").strip() or (detail.get("d_price_text") or "").strip()

        # Dự phòng từ ul.list-info của trang chi tiết: tin ĐÃ BÁN không có data-call
        # ở listing nên thiếu xuất xứ/loại xe/hộp số, nhưng trang chi tiết vẫn đủ.
        origin_raw = car.get("origin") or specs.get("Xuất xứ", "")
        body_raw = car.get("body_type") or specs.get("Kiểu dáng", "")
        fuel_raw = car.get("fuel") or specs.get("Nhiên liệu", "")
        gear_raw = car.get("gearbox") or specs.get("Hộp số", "")
        year = _to_int(car.get("year")) or _to_int(specs.get("Năm SX"))
        mileage = _to_float(car.get("km")) or _km_from_text(specs.get("Km đã đi"))

        rows.append({
            "listing_id": f"OTO_{car.get('id') or ''}",
            "source_platform": SOURCE_PLATFORM,
            "brand": car.get("brand") or "Unknown",
            "model": car.get("model") or "Unknown",
            "sub_model_trim": trim,
            "manufacture_year": year,
            "mileage_km": mileage,
            "transmission": map_value(gear_raw, TRANSMISSION_MAP),
            "fuel_type": map_value(fuel_raw, FUEL_MAP),
            "origin": map_value(origin_raw, ORIGIN_MAP),
            "body_type": map_value(body_raw, BODY_MAP),
            "engine_capacity": derive_engine_capacity(
                trim, detail.get("d_title", ""), car.get("car_name", "")
            ),
            "seats": _to_int(detail.get("d_seats")),
            "location_province": normalize_province(
                specs.get("Tỉnh thành") or car.get("province"), detail.get("d_city_code", "")
            ),
            "seller_type": seller_type_of(detail),
            "price_vnd": price_vnd,
            "source_url": car.get("url"),
            "listing_date": lastmods.get(car.get("url") or ""),
            "scraped_at": car.get("scraped_at"),
            "raw_price_text": raw_price or None,
            "price_status": price_status_of(price_vnd, raw_price),
        })
    return rows



# ------------------------------------------------------------------- audit
def audit(rows: list[dict]) -> None:
    """In bảng kiểm toán độ phủ / tỷ lệ thiếu từng cột (Milestone 1 yêu cầu)."""
    total = len(rows) or 1
    print("\n" + "=" * 74)
    print(f"AUDIT UNIFIED SCHEMA — {len(rows)} tin")
    print("=" * 74)
    print(f"{'column':22s} {'filled':>7s} {'missing':>8s} {'rate':>7s} {'distinct':>9s}")
    for col in SCHEMA_COLUMNS:
        filled = sum(1 for r in rows if r.get(col) not in (None, "", "Unknown"))
        distinct = len({r.get(col) for r in rows if r.get(col) not in (None, "")})
        print(f"{col:22s} {filled:7d} {total - filled:8d} {filled / total * 100:6.1f}% {distinct:9d}")

    print("\nPhân bố các cột phân loại:")
    for col in ("price_status", "seller_type", "transmission", "fuel_type", "origin"):
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get(col))
            counts[key] = counts.get(key, 0) + 1
        top = ", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        print(f"  {col:15s}: {top}")

    print("\nKiểm tra theo quy tắc miền (domain rules) của report:")
    print(f"  giá < 30 triệu (đưa vào review): {sum(1 for r in rows if (r.get('price_vnd') or 0) and r['price_vnd'] < 30_000_000)}")
    print(f"  giá > 25 tỷ (segment riêng)    : {sum(1 for r in rows if (r.get('price_vnd') or 0) > 25_000_000_000)}")
    print(f"  odometer < 100 km              : {sum(1 for r in rows if (r.get('mileage_km') or 0) < 100)}")
    print(f"  odometer > 1.000.000 km        : {sum(1 for r in rows if (r.get('mileage_km') or 0) > 1_000_000)}")
    years = [r["manufacture_year"] for r in rows if r.get("manufacture_year")]
    if years:
        print(f"  năm SX: {min(years)}–{max(years)} | ngoài scope 1995–nay: "
              f"{sum(1 for y in years if y < 1995)}")


# --------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    """Tham số dòng lệnh."""
    parser = argparse.ArgumentParser(
        description="Xuất Unified Schema (15 thuộc tính + 5 metadata) cho dữ liệu oto.com.vn",
    )
    parser.add_argument("--out", default="oto_unified", help="tên file CSV/JSONL đầu ra")
    parser.add_argument("--fetch-sitemap", action="store_true",
                        help="tải lại listing_date (lastmod) từ sitemap-detail")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    lastmods = load_lastmod_map(fetch=args.fetch_sitemap)

    conn = storage.open_db()
    rows = build_unified(conn, lastmods)
    conn.close()

    csv_path = storage.save_csv(rows, args.out, SCHEMA_COLUMNS)
    jsonl_path = storage.save_jsonl(rows, args.out)
    audit(rows)
    print(f"\nCSV   : {csv_path}\nJSONL : {jsonl_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

