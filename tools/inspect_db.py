"""Inspect the SQLite data: which columns are mostly empty, plus unusual sample rows.

Run: python -m tools.inspect_db
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = Path("data/scraped.db")
COLS = ["origin", "body_type", "color", "listing_type", "vip_type", "province",
        "seller_name", "phone", "year", "price_vnd", "km"]


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM oto_cars").fetchone()[0]
    print(f"oto_cars: {total} rows\n")

    print("### Empty/NULL rows per column")
    for col in COLS:
        n = conn.execute(
            f'SELECT COUNT(*) FROM oto_cars WHERE "{col}" IS NULL OR "{col}" = ""'
        ).fetchone()[0]
        print(f"  {col:14s} empty {n:5d} ({n / total * 100:5.1f}%)")

    print("\n### 8 rows with an empty origin")
    rows = conn.execute(
        'SELECT id, brand, model, car_name, price_text, origin, body_type, color, '
        'listing_type, vip_type, source_page FROM oto_cars '
        'WHERE "origin" IS NULL OR "origin" = "" LIMIT 8'
    ).fetchall()
    for r in rows:
        print(f"\n  id={r['id']} | {r['brand']} {r['model']} | {r['price_text']!r}")
        print(f"    car_name={r['car_name'][:70]!r}")
        print(f"    origin={r['origin']!r} body={r['body_type']!r} color={r['color']!r} "
              f"listtype={r['listing_type']!r} vip={r['vip_type']!r}")
        print(f"    source_page={r['source_page']}")

    print("\n### 3 rows with a complete origin (for comparison)")
    for r in conn.execute(
        'SELECT id, brand, model, origin, body_type, color, listing_type, vip_type '
        'FROM oto_cars WHERE origin = "Nhập khẩu" OR origin = "Trong nước" LIMIT 3'
    ):
        print(f"  id={r['id']} {r['brand']} {r['model']} origin={r['origin']!r} "
              f"body={r['body_type']!r} color={r['color']!r} list={r['listing_type']!r} vip={r['vip_type']!r}")
    conn.close()


if __name__ == "__main__":
    main()
