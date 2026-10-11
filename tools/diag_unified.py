"""Chẩn đoán 2 điểm yếu của unified schema: giá thiếu & engine_capacity thiếu.

Chạy: python -m tools.diag_unified
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.common import storage  # noqa: E402
from src.sources.oto.unified import derive_engine_capacity, derive_trim  # noqa: E402


def main() -> None:
    conn = storage.open_db()
    cars, details = {}, {}
    cars_rows = storage.read_rows(conn, "oto_cars")
    details = {r["url"]: r for r in storage.read_rows(conn, "oto_car_details")}
    cars = {r["url"]: r for r in cars_rows}

    print("### 1) Tin thiếu giá ở listing nhưng trang chi tiết có giá?")
    miss = [u for u, c in cars.items() if not c.get("price_vnd")]
    print(f"  thiếu giá ở listing: {len(miss)}")
    recovered = 0
    zero = 0
    none_detail = 0
    for url in miss:
        d = details.get(url, {})
        val = d.get("d_price_vnd")
        if val in (None, ""):
            none_detail += 1
        elif int(val) == 0:
            zero += 1
        else:
            recovered += 1
    print(f"  chi tiết có giá > 0 (dùng được)  : {recovered}")
    print(f"  chi tiết giá = 0                 : {zero}")
    print(f"  chi tiết không có giá            : {none_detail}")

    print("\n### 2) Vì sao engine_capacity thiếu? Xem trim của các tin không suy ra được")
    bad_trim: Counter = Counter()
    n_none = n_ok = 0
    for url, c in cars.items():
        d = details.get(url, {})
        trim = derive_trim(c.get("brand", ""), c.get("model", ""), d.get("d_title", ""), c.get("car_name", ""))
        engine = derive_engine_capacity(trim, d.get("d_title", ""), c.get("car_name", ""))
        if engine:
            n_ok += 1
        else:
            n_none += 1
            bad_trim[trim or "(rỗng)"] += 1
    print(f"  suy ra được: {n_ok} | không được: {n_none}")
    print("  Top 25 trim không suy ra được dung tích:")
    for trim, n in bad_trim.most_common(25):
        print(f"    [{n:4d}x] {trim!r}")

    print("\n### 3) Mẫu trim suy ra được (kiểm tra chất lượng)")
    samples = []
    for url, c in cars.items():
        d = details.get(url, {})
        trim = derive_trim(c.get("brand", ""), c.get("model", ""), d.get("d_title", ""), c.get("car_name", ""))
        engine = derive_engine_capacity(trim, d.get("d_title", ""), c.get("car_name", ""))
        if engine and len(samples) < 12:
            samples.append((c.get("brand"), c.get("model"), d.get("d_title"), trim, engine))
    for brand, model, title, trim, engine in samples:
        print(f"    {brand} {model} | title={title!r} | trim={trim!r} -> {engine}")

    print("\n### 4) location_province có bao nhiêu nhãn khác nhau (chuẩn hoá chưa?)")
    prov = Counter()
    for c in cars_rows:
        d = details.get(c["url"], {})
        specs = {}
        prov[d.get("d_city_code") or ""] += 1
    print("  city_code:", dict(prov))
    conn.close()


if __name__ == "__main__":
    main()
