"""CỔNG KIỂM TRA trước khi PR: file CSV của một nguồn có đúng Unified Schema không?

Chạy: python -m tools.validate_source_csv data/processed/<nguồn>.csv
Thoát code 0 = PASS (được merge), 1 = FAIL (sửa rồi chạy lại).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common import schema  # noqa: E402

REQUIRED_NON_EMPTY = ("listing_id", "source_platform", "source_url")
MAX_MISSING_WARN = 0.60  # cảnh báo nếu >60% thiếu


def validate(path: Path) -> int:
    """Trả về số lỗi (0 = pass)."""
    errors = 0
    print("=" * 76)
    print(f"KIỂM TRA SCHEMA: {path}")
    print("=" * 76)

    if not path.exists():
        print(f"[LỖI] không thấy file {path}")
        return 1

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)
    print(f"Số dòng: {len(rows):,} | số cột: {len(header)}")

    # 1) tên + thứ tự cột
    if header != schema.SCHEMA_COLUMNS:
        errors += 1
        print("[LỖI] cột không khớp Unified Schema")
        missing = [c for c in schema.SCHEMA_COLUMNS if c not in header]
        extra = [c for c in header if c not in schema.SCHEMA_COLUMNS]
        if missing:
            print("      thiếu:", ", ".join(missing))
        if extra:
            print("      thừa :", ", ".join(extra))
        if not missing and not extra:
            print("      đủ cột nhưng SAI THỨ TỰ (phải đúng thứ tự trong src/common/schema.py)")
    else:
        print("[OK ] đúng 21 cột và đúng thứ tự")

    if not rows:
        print("[LỖI] file không có dòng dữ liệu")
        return errors + 1

    # 2) cột bắt buộc không được rỗng
    for col in REQUIRED_NON_EMPTY:
        if col in header:
            blank = sum(1 for r in rows if not str(r.get(col) or "").strip())
            if blank:
                errors += 1
                print(f"[LỖI] {col}: {blank} dòng rỗng (cột bắt buộc)")

    # 3) cột số phải ép được về số
    for col in schema.NUMERIC_COLUMNS:
        if col not in header:
            continue
        bad = [r.get(col) for r in rows if str(r.get(col) or "").strip()
               and not str(r.get(col)).replace(".", "", 1).replace("-", "", 1).isdigit()]
        if bad:
            errors += 1
            print(f"[LỖI] {col}: {len(bad)} giá trị không phải số, ví dụ {bad[:3]}")

    # 4) giá trị categorical phải nằm trong danh sách chuẩn
    checks = {
        "transmission": schema.TRANSMISSION_VALUES,
        "fuel_type": schema.FUEL_VALUES,
        "origin": schema.ORIGIN_VALUES,
        "body_type": schema.BODY_VALUES,
        "seller_type": schema.SELLER_VALUES,
        "price_status": schema.PRICE_STATUS_VALUES,
    }
    for col, allowed in checks.items():
        if col not in header:
            continue
        counter = Counter(str(r.get(col)) for r in rows)
        weird = {v: n for v, n in counter.items() if v not in allowed and v not in ("", "None")}
        if weird:
            errors += 1
            print(f"[LỖI] {col}: giá trị lạ {weird} (chỉ dùng {sorted(allowed)})")

    # 5) độ phủ từng cột (cảnh báo)
    print("\nĐộ phủ từng cột:")
    for col in schema.SCHEMA_COLUMNS:
        if col not in header:
            continue
        blank = sum(1 for r in rows if str(r.get(col) or "").strip() in ("", "None"))
        rate = blank / len(rows)
        flag = "  <-- thiếu nhiều, ghi rõ lý do trong PR" if rate > MAX_MISSING_WARN else ""
        print(f"  {col:20s} {len(rows) - blank:6d} ({100 - rate * 100:5.1f}%){flag}")

    # 6) trùng khóa
    for key in ("listing_id", "source_url"):
        if key in header:
            dup = len(rows) - len({r.get(key) for r in rows})
            if dup:
                errors += 1
                print(f"[LỖI] {key}: {dup} dòng trùng giá trị")

    print("\n" + ("KẾT LUẬN: PASS ✅  (được phép mở PR)" if errors == 0
                  else f"KẾT LUẬN: FAIL ❌  ({errors} lỗi — sửa rồi chạy lại)"))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra CSV nguồn theo Unified Schema")
    parser.add_argument("path", help="đường dẫn file CSV, vd data/processed/oto.csv")
    args = parser.parse_args()
    return 1 if validate(Path(args.path)) else 0


if __name__ == "__main__":
    sys.exit(main())
