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
                                                         # a subset -> data/master/master_partial_*.csv,
                                                         # never the master itself

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
# muaban.net replaced anycar.vn, whose site is offline (docs/sources/muaban.md).
# A source split between two members is one platform but two files, so it gets two keys that share a
# platform: bonbanh (Duy: 2019+ / Hiếu: 1995-2018) and chotot (Phong: southern provinces only — the
# northern and central half is not crawled yet, see docs/sources/*.md).
SOURCE_FILES: dict[str, tuple[str, str]] = {
    "oto": ("oto_unified", "listed"),
    "oto_archive": ("oto_archive_unified", "archived"),
    "bonbanh_new": ("bonbanh_new", "listed"),
    "bonbanh_old": ("bonbanh_oldcars", "listed"),
    # optional top-up files: created by `python -m src.sources.bonbanh` / `... .carpla` and skipped
    # until they exist (docs/crawl_gap.md explains what is still missing at each site)
    "bonbanh_extra": ("bonbanh_extra", "listed"),
    # chotot was crawled twice: Phong's southern half, then Bảo's nationwide file (63 provinces).
    # `chotot_full` comes first so the fuller export wins when both carry the same listing_id.
    "chotot_full": ("chotot_mua_ban_oto", "listed"),
    "chotot_nam": ("chotot_mien_nam", "listed"),
    "carmudi": ("carmudi", "listed"),
    "carpla": ("carpla", "listed"),
    "carpla_extra": ("carpla_extra", "listed"),
    "muaban": ("muaban", "listed"),
    "tinbanxe": ("tinbanxe", "listed"),
    "vucar": ("vucar", "listed"),
}

MASTER_COLUMNS = [*schema.SCHEMA_COLUMNS, "tier", "duplicate_group_id", "quality_flags"]

# `source_platform` is a contract enum (docs/unified_schema.md), so the internal source key must not
# leak into the CSV: every key maps to its canonical platform name, and the archive tier belongs to the
# same platform as the live one. This is applied to every row (not only to blank cells), because an
# exporter may write its own key ("tinbanxe") instead of the enum value ("tinbanxe.vn").
SOURCE_PLATFORMS = {
    "oto": "oto.com.vn", "oto_archive": "oto.com.vn",
    "bonbanh_new": "bonbanh", "bonbanh_old": "bonbanh", "bonbanh_extra": "bonbanh",
    "chotot_full": "chotot", "chotot_nam": "chotot",
    "carmudi": "carmudi", "carpla": "carpla", "carpla_extra": "carpla",
    "muaban": "muaban.net",
    "tinbanxe": "tinbanxe.vn", "vucar": "vucar.vn",
}
# Spellings that are not the enum value, mapped to it (a source exporter spells its platform its own way).
PLATFORM_ALIASES = {"tinbanxe": "tinbanxe.vn", "vucar": "vucar.vn", "oto": "oto.com.vn",
                    "muaban": "muaban.net"}

# Report §4.3 domain rules: provisional scope rules, not proof of an error.
PRICE_REVIEW_LOW = 30_000_000            # below this -> review candidate
PRICE_SEPARATE_SEGMENT = 25_000_000_000  # above this -> "separate segment" and a review
# A second, deliberately loose ceiling. The report only defines the 25-billion "separate segment" rule, and
# a 22-66 billion Rolls-Royce belongs there — but a few ads carry a price that is an obvious unit error
# on the seller's side ("465000 Tỷ", "110000 Tỷ"). Those are not a segment of the market, so they get
# their own flag instead of being reported as luxury cars. Provisional, like every cutoff in §4.3.
PRICE_IMPLAUSIBLE_HIGH = 100_000_000_000
KM_MIN_PLAUSIBLE = 100                   # a <100 km reading is normal only on a nearly new car
KM_MAX_PLAUSIBLE = 1_000_000
NEW_CAR_GRACE_YEARS = 2
YEAR_SCOPE_START = 1995
# Report §4.3 asks for "sensitivity to the cutoffs": the audit prints how many rows each ceiling catches.
PRICE_CEILING_SENSITIVITY = (25_000_000_000, 50_000_000_000, 100_000_000_000, 200_000_000_000)


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
    elif price >= PRICE_IMPLAUSIBLE_HIGH:
        # not a market segment: a unit error on the seller's side (see PRICE_IMPLAUSIBLE_HIGH)
        flags.append("implausible_price_high")
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


def canonical_platform(source_key: str, raw_value) -> str:
    """Return the contract enum value for `source_platform` (never the internal source key).

    Two steps, so a new file never injects a value the schema does not allow: the source key decides the
    platform when it is known (`oto_archive` is still `oto.com.vn`), otherwise the spelling the exporter
    wrote is translated through PLATFORM_ALIASES, and only an unknown label falls through as-is.
    """
    known = SOURCE_PLATFORMS.get(source_key)
    if known:
        return known
    value = str(raw_value or "").strip()
    return PLATFORM_ALIASES.get(value, value or source_key)


def canonical_price_status(row: dict) -> str:
    """Enforce the `price_status` enum, because the column is *derived* from the other two price fields.

    A source that writes something outside the contract (chotot_mua_ban_oto.csv writes "Unknown") would
    otherwise put a non-enum value into the master. The value is recomputed rather than guessed: a row
    with an asking price is `full`, a row without one is `invalid`, and the negotiable/instalment wording
    is still read from `raw_price_text` when the source kept it.
    """
    value = str(row.get("price_status") or "").strip()
    if value in schema.PRICE_STATUS_VALUES:
        return value
    return schema.price_status(_num(row.get("price_vnd"), int), row.get("raw_price_text"))


def dedupe_listing_ids(rows: list[dict]) -> list[dict]:
    """One `listing_id` is one ad, so the same id must never occupy two rows.

    Two files can legitimately cover the same ad — chotot was crawled twice (southern half, then
    nationwide) — and `SOURCE_FILES` order decides which copy survives (the fuller export is listed
    first). Duplicates inside one source are already impossible: every crawler upserts on url.
    """
    seen: set[str] = set()
    kept: list[dict] = []
    for row in rows:
        key = str(row.get("listing_id") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kept.append(row)
    dropped = len(rows) - len(kept)
    if dropped:
        log.info("dropped %d rows whose listing_id was already merged (same ad in two files)", dropped)
    return kept


def load_source(name: str) -> tuple[list[dict] | None, str]:
    """Read one source CSV, check the 21-column contract, and tag its tier.

    The tier is a property of the file, so a combined export (every tier in one CSV, e.g.
    data/processed/oto.csv) can only be read through the fallback below — and then every row gets the
    same tier. That file is still supported, but it is not what this merge is meant to read.
    """
    stem, tier = SOURCE_FILES[name]
    candidates = (config.DATA_PROCESSED / f"{stem}.csv", config.DATA_PROCESSED / f"{name}.csv")
    for index, path in enumerate(candidates):
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
        if index:
            log.warning("%s: using the fallback file %s — every row is tagged tier=%s. If that file "
                        "concatenates several tiers, use the per-tier exports instead so the column "
                        "stays correct.", name, path.name, tier)
        for row in rows:
            row["tier"] = tier
            row["source_platform"] = canonical_platform(name, row.get("source_platform"))
            row["price_status"] = canonical_price_status(row)
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
    rows = dedupe_listing_ids(rows)
    log.info("Total after merging: %d listings", len(rows))
    return rows, per_source


def audit_and_flag(rows: list[dict]) -> dict[str, int]:
    """Deduplicate, flag, and print the merged audit (the Milestone 1 numbers)."""
    capture_year = _capture_year(rows)
    rows = dedupe.duplicate_groups(rows, capture_year=capture_year, fuzzy=True)
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
    fuzzy = dedupe.fuzzy_groups(rows, capture_year=capture_year)
    print(f"  fuzzy pass: {fuzzy['exact_groups']:,} exact-key groups -> {fuzzy['groups']:,} after merging "
          f"{fuzzy['merged_groups']:,} near-duplicates ({fuzzy['pairs_compared']:,} pairs compared)")
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

    # Report §4.3: "test sensitivity to the cutoffs" — show what each price ceiling would catch, so the
    # report can justify the one that is actually used instead of asserting it.
    prices = [_num(row.get("price_vnd"), int) for row in rows]
    prices = [price for price in prices if price and price > 0]
    print("\nPrice-ceiling sensitivity (report §4.3 — the cutoffs are provisional):")
    for ceiling in PRICE_CEILING_SENSITIVITY:
        caught = sum(1 for price in prices if price >= ceiling)
        marker = "  <- used for implausible_price_high" if ceiling == PRICE_IMPLAUSIBLE_HIGH else ""
        print(f"  above {ceiling / 1e9:6.0f} bn: {caught:5,} records ({caught / len(prices) * 100:.3f}%){marker}")
    return {"rows": total, **stats}


def partial_name(sources: list[str]) -> str:
    """Output name for a subset merge — never the master name, so a subset run cannot overwrite it.

    `--sources oto` used to write `master_clean_dataset.csv` with only oto's rows, silently destroying a
    full build. A subset now always lands in its own file; pass `--out` to choose the name.
    """
    suffix = "_".join(sources)
    return f"master_partial_{suffix}" if suffix and len(suffix) <= 60 else "master_partial_subset"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge the sources into the Master Dataset")
    parser.add_argument("--sources", nargs="+", default=list(SOURCE_FILES),
                        choices=list(SOURCE_FILES),
                        help="which source files to merge (a subset writes its own file, not the master)")
    parser.add_argument("--out", default=None,
                        help="output name (default: master_clean_dataset, or master_partial_<sources> "
                             "when --sources is a subset)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.ensure_dirs()

    selected = list(dict.fromkeys(args.sources))          # --sources can repeat a name
    subset = set(selected) != set(SOURCE_FILES)
    out = args.out or (partial_name(selected) if subset else "master_clean_dataset")
    if subset and not args.out:
        log.warning("merging a subset (%d/%d sources) -> writing %s.csv, NOT the master dataset",
                    len(selected), len(SOURCE_FILES), out)

    rows, per_source = build(selected)
    if not rows:
        log.error("nothing to merge — export at least one source first")
        return 1

    print(f"\n{'=' * 78}\nSOURCES\n{'=' * 78}")
    print(f"  {'source':13s} {'tier':9s} {'rows':>7s}  file  [most missing columns]")
    for name, info in per_source.items():
        print(f"  {name:13s} {info['tier']:9s} {info['rows']:7,}  {info['file']}"
              f"  [{info['worst_missing']}]")

    audit_and_flag(rows)

    path = storage.save_csv(rows, out, MASTER_COLUMNS, directory=config.DATA_MASTER)
    print(f"\nMaster Dataset: {path}")
    print("Next (report §4.3-4.4): split train/val/test by duplicate_group_id, then the missing-value"
          " strategy — both fitted on the training partition only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
