"""PR GATE: does a source's CSV match the unified schema?

Run: python -m tools.validate_source_csv data/processed/<source>.csv
Exit code 0 = PASS (safe to merge), 1 = FAIL (fix it and run again).
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
MAX_MISSING_WARN = 0.60  # warn when a column is more than 60% empty


def validate(path: Path) -> int:
    """Return the number of errors (0 = pass)."""
    errors = 0
    print("=" * 76)
    print(f"SCHEMA CHECK: {path}")
    print("=" * 76)

    if not path.exists():
        print(f"[ERROR] file not found: {path}")
        return 1

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)
    print(f"Rows: {len(rows):,} | columns: {len(header)}")

    # 1) column names and order
    if header != schema.SCHEMA_COLUMNS:
        errors += 1
        print("[ERROR] columns do not match the unified schema")
        missing = [c for c in schema.SCHEMA_COLUMNS if c not in header]
        extra = [c for c in header if c not in schema.SCHEMA_COLUMNS]
        if missing:
            print("        missing:", ", ".join(missing))
        if extra:
            print("        extra  :", ", ".join(extra))
        if not missing and not extra:
            print("        all columns present but IN THE WRONG ORDER "
                  "(use the order in src/common/schema.py)")
    else:
        print("[OK ] 21 columns, correct order")

    if not rows:
        print("[ERROR] the file has no data rows")
        return errors + 1

    # 2) required columns must not be blank
    for col in REQUIRED_NON_EMPTY:
        if col in header:
            blank = sum(1 for r in rows if not str(r.get(col) or "").strip())
            if blank:
                errors += 1
                print(f"[ERROR] {col}: {blank} blank value(s) in a required column")

    # 3) numeric columns must parse as numbers
    for col in schema.NUMERIC_COLUMNS:
        if col not in header:
            continue
        bad = [r.get(col) for r in rows if str(r.get(col) or "").strip()
               and not str(r.get(col)).replace(".", "", 1).replace("-", "", 1).isdigit()]
        if bad:
            errors += 1
            print(f"[ERROR] {col}: {len(bad)} non-numeric value(s), e.g. {bad[:3]}")

    # 4) categorical columns must use the allowed values
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
            print(f"[ERROR] {col}: unexpected values {weird} (allowed: {sorted(allowed)})")

    # 5) per-column coverage (warning only)
    print("\nColumn coverage:")
    for col in schema.SCHEMA_COLUMNS:
        if col not in header:
            continue
        blank = sum(1 for r in rows if str(r.get(col) or "").strip() in ("", "None"))
        rate = blank / len(rows)
        flag = "  <-- mostly empty: explain why in the PR" if rate > MAX_MISSING_WARN else ""
        print(f"  {col:20s} {len(rows) - blank:6d} ({100 - rate * 100:5.1f}%){flag}")

    # 6) duplicate keys
    for key in ("listing_id", "source_url"):
        if key in header:
            dup = len(rows) - len({r.get(key) for r in rows})
            if dup:
                errors += 1
                print(f"[ERROR] {key}: {dup} duplicate value(s)")

    print("\n" + ("RESULT: PASS ✅  (you may open a pull request)" if errors == 0
                  else f"RESULT: FAIL ❌  ({errors} error(s) — fix them and run again)"))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a source CSV against the unified schema")
    parser.add_argument("path", help="path to the CSV, e.g. data/processed/oto.csv")
    args = parser.parse_args()
    return 1 if validate(Path(args.path)) else 0


if __name__ == "__main__":
    sys.exit(main())
