"""Type and key audit of the Master Dataset — the "kiểm tra kiểu dữ liệu" step of week 2.

`tools.validate_source_csv` guards each source file before the merge. This guards the *merged* output,
which is what the model and the report actually consume:

  * every numeric column parses (or is empty — never a stray string);
  * every date column is ISO 8601 (or empty);
  * every categorical value is inside the contract enum;
  * `listing_id` / `source_url` are unique and non-empty.

On top of the failures it prints a **diagnostics** block: rows that are perfectly valid and still poison
the model — a deposit-style asking price, a placeholder odometer, an impossible model year, the same ad
twice. Those are reported with counts and never counted as problems, because deleting or flagging them
changes the split (CONTRIBUTING §3b), so the decision belongs to a milestone, not to a gate.

Exit code 1 when anything fails, so it can be used as a gate before splitting the data.

    python -m tools.audit_master
    python -m tools.audit_master --master data/master/master_clean_dataset.csv
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config, schema

# date, or date + time with optional seconds/fraction/offset — the shapes the contract allows
ISO_8601 = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)

ENUM_COLUMNS = {
    "transmission": schema.TRANSMISSION_VALUES,
    "fuel_type": schema.FUEL_VALUES,
    "origin": schema.ORIGIN_VALUES,
    "body_type": schema.BODY_VALUES,
    "seller_type": schema.SELLER_VALUES,
    "price_status": schema.PRICE_STATUS_VALUES,
    "tier": {"listed", "archived"},
}


def diagnostics(frame: pd.DataFrame, deposit_threshold: float = 0.25,
                segment_min_rows: int = 30) -> list[str]:
    """Rows that are valid but poison the model. Reported only — never added to `problems`.

    The medians here are computed on the file being audited, which is fine for a *diagnostic*: the
    production version of the flag (docs/deposit_rule_proposal.md) must learn them on train only.
    """
    price = pd.to_numeric(frame["price_vnd"], errors="coerce")
    mileage = pd.to_numeric(frame["mileage_km"], errors="coerce")
    year = pd.to_numeric(frame["manufacture_year"], errors="coerce")
    lines: list[str] = []

    key = frame["brand"].fillna("").astype(str) + "|" + frame["model"].fillna("").astype(str)
    segment = price.groupby(key).agg(["size", "median"])
    segment = segment[segment["size"] >= segment_min_rows]["median"]
    overall = float(price.median()) if price.notna().any() else 0.0
    baseline = key.map(segment).fillna(overall).replace(0, pd.NA)
    deposit = price / baseline < deposit_threshold
    if deposit.any():
        cheap = price[deposit]
        lines.append(f"  deposit-style price   {int(deposit.sum()):>7,} rows "
                     f"(< {deposit_threshold:.0%} of the brand|model median; "
                     f"median asking {int(cheap.median()):,} VND)")

    placeholder = mileage.notna() & ((mileage <= 100) | (mileage >= 900_000))
    if placeholder.any():
        lines.append(f"  placeholder odometer  {int(placeholder.sum()):>7,} rows "
                     f"(<= 100 km or >= 900,000 km)")

    impossible = year.notna() & ~year.between(1980, 2026)
    if impossible.any():
        values = sorted(int(value) for value in year[impossible].unique())
        lines.append(f"  impossible model year {int(impossible.sum()):>7,} rows {values[:6]}")

    duplicated = frame.assign(_price=price).duplicated(
        subset=["brand", "model", "manufacture_year", "mileage_km", "price_vnd"], keep=False)
    duplicated &= price.notna()
    if duplicated.any():
        lines.append(f"  repeated advertisement{int(duplicated.sum()):>7,} rows "
                     f"({int(duplicated.sum()) // 2} pairs with identical car and price)")

    if not lines:
        lines.append("  none")
    return lines


def audit(path: Path) -> int:
    """Print the audit and return the number of problems found."""
    frame = pd.read_csv(path, dtype=str, low_memory=False)
    print(f"{path.name}: {len(frame):,} rows x {len(frame.columns)} columns")
    problems = 0

    print("\n--- numeric columns (parse or empty) ---")
    for column in schema.NUMERIC_COLUMNS:
        values = frame[column]
        present = values.notna() & (values.astype(str).str.strip() != "")
        unparseable = int((present & pd.to_numeric(values, errors="coerce").isna()).sum())
        print(f"  {column:18s} filled {int(present.sum()):>7,} | unparseable {unparseable}")
        problems += unparseable

    print("\n--- date columns (ISO 8601 or empty) ---")
    for column in ("listing_date", "scraped_at"):
        values = frame[column]
        present = values.notna() & (values.astype(str).str.strip() != "")
        text = values.astype(str).str.strip()
        # Parseability alone is not enough: pandas happily reads "10/2026" as October 2026, which is
        # exactly the shape a capture month takes when it is mistaken for a publication date.
        not_iso = present & ~text.str.match(ISO_8601)
        impossible = present & ~not_iso & pd.to_datetime(
            values.where(present), errors="coerce", utc=True, format="mixed").notna().eq(False)
        bad = int((not_iso | impossible).sum())
        print(f"  {column:18s} filled {int(present.sum()):>7,} | not ISO 8601 {int(not_iso.sum()):>6,}"
              f" | unparseable {int(impossible.sum())}")
        if bad:
            print(f"    example: {text[not_iso | impossible].head(3).tolist()}")
        problems += bad

    print("\n--- categorical columns (inside the contract enum) ---")
    for column, allowed in ENUM_COLUMNS.items():
        values = frame[column].fillna("").astype(str)
        outside = values[~values.isin(allowed) & (values != "")]
        print(f"  {column:18s} outside enum {len(outside):>5,}"
              + (f"  {outside.unique()[:4].tolist()}" if len(outside) else ""))
        problems += len(outside)

    print("\n--- keys ---")
    duplicates = int(frame.listing_id.duplicated().sum())
    empty_ids = int((frame.listing_id.fillna("") == "").sum())
    duplicate_urls = int(frame.source_url.duplicated().sum())
    print(f"  duplicate listing_id {duplicates} | empty listing_id {empty_ids} "
          f"| duplicate source_url {duplicate_urls}")
    problems += duplicates + empty_ids

    print("\n--- diagnostics (reported, never a failure) ---")
    for line in diagnostics(frame):
        print(line)

    print(f"\nPROBLEMS: {problems}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Type and key audit of the Master Dataset")
    parser.add_argument("--master", default=str(config.DATA_MASTER / "master_clean_dataset.csv"))
    args = parser.parse_args(argv)

    path = Path(args.master)
    if not path.exists():
        print(f"not found: {path} -> run 'python -m src.merge.build_master' first")
        return 1
    return 1 if audit(path) else 0


if __name__ == "__main__":
    sys.exit(main())
