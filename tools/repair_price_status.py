"""Recompute the derived `price_status` column of a contract CSV (report §4.1 / docs/unified_schema.md).

Why this exists: `price_status` is not an observation, it is a function of the other two price fields —
`full` when the ad carries an asking price, `negotiable` / `instalment` when the wording says so, `invalid`
when there is no usable number (src/common/schema.py: price_status). A source that writes a placeholder
there ("Unknown") fails `tools.validate_source_csv` even though every value can be derived exactly.

Nothing is guessed: the recomputation uses only `price_vnd` and `raw_price_text`, which stay untouched.

    python -m tools.repair_price_status data/processed/chotot_mua_ban_oto.csv          # rewrite in place
    python -m tools.repair_price_status data/processed/x.csv --dry-run                 # report only
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import schema


def _to_int(value) -> int | None:
    text = str(value or "").strip()
    if not text or text.lower() in ("none", "nan", "null"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def repair(path: Path, dry_run: bool = False) -> dict[str, int]:
    """Rewrite `price_status` on every row that carries a value outside the contract enum."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "price_status" not in fieldnames:
        raise SystemExit(f"{path.name} has no price_status column — is it a contract CSV?")

    counts: dict[str, int] = {}
    changed = 0
    for row in rows:
        current = (row.get("price_status") or "").strip()
        derived = schema.price_status(_to_int(row.get("price_vnd")), row.get("raw_price_text"))
        if current in schema.PRICE_STATUS_VALUES:
            counts[current] = counts.get(current, 0) + 1
            continue
        counts[derived] = counts.get(derived, 0) + 1
        row["price_status"] = derived
        changed += 1

    print(f"{path.name}: {len(rows):,} rows | {changed:,} price_status values repaired")
    for value, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {value:12s} {count:>7,}")
    if changed and not dry_run:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"  -> written back to {path}")
    elif dry_run:
        print("  (dry run: nothing written)")
    return {"rows": len(rows), "changed": changed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute the derived price_status column")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    for name in args.files:
        repair(Path(name), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
