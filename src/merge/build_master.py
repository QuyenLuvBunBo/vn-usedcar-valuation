"""Week 2: merge every source CSV into the Master Dataset (data/master/master_clean_dataset.csv).

Stages 1-3 of the report's data-preparation workflow:

  1. Normalize    — already done by each source exporter (16 attributes + 5 metadata columns).
  2. Deduplicate  — composite hashing (brand, model, trim, year, province, ± km tolerance) assigns a
                    duplicate_group_id. Nothing is merged or dropped here: a group is a review
                    candidate, and keeping a group (not a row) together is what the train/val/test
                    split needs, so the leakage control happens later without losing evidence.
  3. Audit & flag — the report's domain rules produce quality_flags; records are flagged, never deleted.

On top of the shared 21 columns the master adds: tier, duplicate_group_id, quality_flags.

Run:
    python -m src.merge.build_master                     # every source file that exists yet
    python -m src.merge.build_master --sources oto oto_archive

Every source file must already pass: python -m tools.validate_source_csv data/processed/<file>.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from datetime import datetime

from ..common import config, schema, storage
from ..data_prep.missing import measure_missing
from . import dedupe

log = logging.getLogger("build_master")

# source name -> (file stem in data/processed, tier)
# `tier` says whether the car was advertised when we captured it. oto.com.vn is the only source with
# both: its live snapshot plus the long tail of pages the site still serves (docs/sources/oto.md).
SOURCE_FILES: dict[str, tuple[str, str]] = {
    "oto": ("oto_unified", "listed"),
    "oto_archive": ("oto_archive_unified", "archived"),
    "bonbanh": ("bonbanh", "listed"),
    "chotot": ("chotot", "listed"),
    "carmudi": ("carmudi", "listed"),
    "carpla": ("carpla", "listed"),
    "anycar": ("anycar", "listed"),
}

MASTER_COLUMNS = [*schema.SCHEMA_COLUMNS, "tier", "duplicate_group_id", "quality_flags"]

# Report §4.3 domain rules: provisional scope rules, not proof of an error.
PRICE_REVIEW_LOW = 30_000_000            # below this -> review candidate
PRICE_SEPARATE_SEGMENT = 25_000_000_000  # above this -> "separate segment" and a review
KM_MIN_PLAUSIBLE = 100                   # a <100 km reading is normal only on a nearly new car
KM_MAX_PLAUSIBLE = 1_000_000
NEW_CAR_GRACE_YEARS = 2
YEAR_SCOPE_START = 1995


def _blank(value) -> bool:
    """True for '', None and the spellings CSV/pandas use for a missing value."""
    return value is None or str(value).strip() in ("", "None", "nan", "NaN")


def _num(value, cast):
    """Cast a CSV cell to int/float, returning None when it is empty or not a number."""
    if _blank(value):
        return None
    try:
        return cast(float(str(value).strip()))
    except ValueError:
        return None


def _capture_year(rows: list[dict]) -> int:
    """Latest capture year in the data (from scraped_at) — the age rules need it."""
    years = []
    for row in rows:
        head = str(row.get("scraped_at") or "")[:4]
        if head.isdigit():
            years.append(int(head))
    return max(years) if years else datetime.now().year


def quality_flags(row: dict, capture_year: int) -> str:
    """Reasons this record needs review (report §4.3) — ';'-joined, '' when the record is clean."""
    flags: list[str] = []
    price = _num(row.get("price_vnd"), int)
    km = _num(row.get("mileage_km"), float)
    year = _num(row.get("manufacture_year"), int)

    if price is None:
        flags.append("missing_price")
    elif price < PRICE_REVIEW_LOW:
        flags.append("implausible_price_low")
    elif price > PRICE_SEPARATE_SEGMENT:
        flags.append("luxury_segment")

    if km is None:
        flags.append("missing_mileage")
    elif km > KM_MAX_PLAUSIBLE:
        flags.append("implausible_mileage_high")
    elif km < KM_MIN_PLAUSIBLE and year and year <= capture_year - NEW_CAR_GRACE_YEARS:
        flags.append("low_mileage_older_car")

    if year is None:
        flags.append("missing_year")
    elif not YEAR_SCOPE_START <= year <= capture_year:
        flags.append("year_out_of_scope")

    return ";".join(flags)


def load_source(name: str) -> tuple[list[dict] | None, str]:
    """Read one source CSV, check the 21-column contract, and tag its tier."""
    stem, tier = SOURCE_FILES[name]
    for path in (config.DATA_PROCESSED / f"{stem}.csv", config.DATA_PROCESSED / f"{name}.csv"):
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            if header != schema.SCHEMA_COLUMNS:
                log.error("%s does not match the 21-column contract -> run "
                          "'python -m tools.validate_source_csv %s' first", path.name, path)
                return None, path.name
            rows = list(reader)
        for row in rows:
            row["tier"] = tier
            if _blank(row.get("source_platform")):
                row["source_platform"] = name
        return rows, path.name
    return None, ""


def build(sources: list[str] | None = None) -> tuple[list[dict], dict[str, dict]]:
    """Read every available source file and concatenate the records (normalize ran upstream).

    Per-source row counts and missing rates are collected here: the Milestone 1 report needs both.
    """
    rows: list[dict] = []
    per_source: dict[str, dict] = {}
    for name in (sources or list(SOURCE_FILES)):
        part, file_name = load_source(name)
        if part is None:
            log.warning("no usable file for %-12s -> skipping", name)
            continue
        missing = measure_missing(part)
        worst = sorted(missing.items(), key=lambda kv: -kv[1]["rate"])[:3]
        per_source[name] = {
            "file": file_name,
            "tier": SOURCE_FILES[name][1],
            "rows": len(part),
            "worst_missing": ", ".join(f"{col} {info['rate'] * 100:.0f}%" for col, info in worst),
        }
        log.info("%-12s %6d listings  (%s)", name, len(part), file_name)
        rows.extend(part)
    log.info("Total after merging: %d listings", len(rows))
    return rows, per_source


def audit_and_flag(rows: list[dict]) -> dict[str, int]:
    """Deduplicate, flag, and print the merged audit (the Milestone 1 numbers)."""
    capture_year = _capture_year(rows)
    rows = dedupe.duplicate_groups(rows, capture_year=capture_year)
    for row in rows:
        row["quality_flags"] = quality_flags(row, capture_year)

    stats = dedupe.group_stats(rows)
    loose_groups = len({dedupe.loose_key(row) for row in rows})
    flag_counts: Counter[str] = Counter()
    for row in rows:
        flag_counts.update(flag for flag in str(row["quality_flags"]).split(";") if flag)

    total = len(rows)
    print(f"\n{'=' * 78}\nMASTER DATASET — {total:,} records (capture year {capture_year})\n{'=' * 78}")
    print(f"  unique listing_id : {len({r.get('listing_id') for r in rows}):,}/{total:,}")
    print(f"  unique source_url : {len({r.get('source_url') for r in rows}):,}/{total:,}")
    print("\nCandidate duplicates (report §4.2 — coarse key, review, no deletion):")
    print(f"  groups {stats['groups']:,} | with >1 record {stats['groups_over_one']:,} | "
          f"records sharing a group {stats['duplicate_rows']:,} "
          f"({stats['duplicate_rows'] / total * 100:.1f}%) | largest group {stats['largest_group']}")
    for count, label in dedupe.top_groups(rows):
        print(f"    {count:3d} x {label}")
    print(f"  ignoring trim+mileage (brand+model+year+province): {loose_groups:,} groups "
          f"-> the gap is what a review pass still has to look at")
    reposts = dedupe.repost_stats(rows, capture_year=capture_year)
    print(f"  same key + same asking price (renewed-ad signature): {reposts['rows']:,} records "
          f"in {reposts['groups']:,} groups")
    print("\nQuality flags (report §4.3 — flagged, not deleted):")
    for flag, count in flag_counts.most_common():
        print(f"  {flag:26s} {count:6,} ({count / total * 100:5.1f}%)")
    clean = sum(1 for row in rows if not row["quality_flags"])
    print(f"  {'(no flag)':26s} {clean:6,} ({clean / total * 100:5.1f}%)")
    return {"rows": total, **stats}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge the sources into the Master Dataset")
    parser.add_argument("--sources", nargs="+", default=list(SOURCE_FILES),
                        choices=list(SOURCE_FILES), help="which source files to merge")
    parser.add_argument("--out", default="master_clean_dataset")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.ensure_dirs()

    rows, per_source = build(args.sources)
    if not rows:
        log.error("nothing to merge — export at least one source first")
        return 1

    print(f"\n{'=' * 78}\nSOURCES\n{'=' * 78}")
    print(f"  {'source':13s} {'tier':9s} {'rows':>7s}  file  [most missing columns]")
    for name, info in per_source.items():
        print(f"  {name:13s} {info['tier']:9s} {info['rows']:7,}  {info['file']}"
              f"  [{info['worst_missing']}]")

    audit_and_flag(rows)

    path = storage.save_csv(rows, args.out, MASTER_COLUMNS, directory=config.DATA_MASTER)
    print(f"\nMaster Dataset: {path}")
    print("Next (report §4.3-4.4): split train/val/test by duplicate_group_id, then the missing-value"
          " strategy — both fitted on the training partition only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
