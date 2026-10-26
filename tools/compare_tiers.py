"""Compare the two oto.com.vn tiers: currently listed vs archive (no longer listed).

Tier A (listing)  : data/processed/oto_unified.csv          — cars advertised right now
Tier B (archive)  : data/processed/oto_archive_unified.csv  — pages still served, not listed

Run: python -m tools.compare_tiers
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common import config  # noqa: E402

LISTING_CSV = config.DATA_PROCESSED / "oto_unified.csv"
ARCHIVE_CSV = config.DATA_PROCESSED / "oto_archive_unified.csv"


def _load(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        print(f"[missing] {path.name} — run the crawl/export first")
        return None
    df = pd.read_csv(path)
    df["price_m"] = pd.to_numeric(df["price_vnd"], errors="coerce") / 1e6
    return df


def _price(df: pd.DataFrame) -> str:
    p = df["price_m"].dropna()
    if not p.empty:
        return (f"{len(p):6d}  min {p.min():8.1f}  p25 {p.quantile(.25):8.1f}  "
                f"median {p.median():8.1f}  p75 {p.quantile(.75):8.1f}  max {p.max():9.1f}")
    return "no price"


def _section(title: str) -> None:
    print(f"\n{'=' * 92}\n{title}\n{'=' * 92}")


def main() -> int:
    listing, archive = _load(LISTING_CSV), _load(ARCHIVE_CSV)
    if listing is None or archive is None:
        return 1

    _section("SIZE")
    print(f"A. currently listed : {len(listing):7,} rows")
    print(f"B. archive          : {len(archive):7,} rows")
    print(f"   B/A ratio        : {len(archive) / len(listing):7.2f}x")
    overlap = set(listing["listing_id"]) & set(archive["listing_id"])
    print(f"   row overlap      : {len(overlap):7,} (must be 0 — the export drops live ads from the archive file)")

    _section("PRICE (million VND)")
    for label, df in (("A. currently listed", listing), ("B. archive", archive)):
        print(f"{label:20s} {_price(df)}")

    _section("AGE (manufacture year)")
    for label, df in (("A. currently listed", listing), ("B. archive", archive)):
        years = pd.to_numeric(df["manufacture_year"], errors="coerce").dropna()
        buckets = {
            "<2010": int((years < 2010).sum()),
            "2010-2015": int(years.between(2010, 2015).sum()),
            "2016-2020": int(years.between(2016, 2020).sum()),
            "2021+": int((years >= 2021).sum()),
        }
        print(f"{label:20s} median {years.median():.0f} | {buckets}")

    _section("MILEAGE (km)")
    for label, df in (("A. currently listed", listing), ("B. archive", archive)):
        km = pd.to_numeric(df["mileage_km"], errors="coerce").dropna()
        print(f"{label:20s} n={len(km):6,} | median {km.median():,.0f} | "
              f"p25 {km.quantile(.25):,.0f} | p75 {km.quantile(.75):,.0f}")

    _section("SELLER TYPE / ORIGIN / TRANSMISSION")
    for label, df in (("A. currently listed", listing), ("B. archive", archive)):
        seller = df["seller_type"].value_counts(normalize=True).round(3).to_dict()
        origin = df["origin"].value_counts(normalize=True).round(3).to_dict()
        gear = df["transmission"].value_counts(normalize=True).round(3).to_dict()
        print(f"{label:20s} seller {seller}")
        print(f"{'':20s} origin {origin}")
        print(f"{'':20s} gearbox {gear}")

    _section("TOP BRANDS AND CITIES")
    for label, df in (("A. currently listed", listing), ("B. archive", archive)):
        print(f"{label}:")
        print("  brands:", df["brand"].value_counts().head(6).to_dict())
        print("  cities:", df["location_province"].value_counts().head(6).to_dict())

    _section("WHAT THE ARCHIVE ADDS")
    only_a = set(listing["model"]) - set(archive["model"])
    only_b = set(archive["model"]) - set(listing["model"])
    shared = set(listing["model"]) & set(archive["model"])
    print(f"models: {len(shared)} in both, {len(only_a)} only listed, {len(only_b)} only in archive")
    if only_b:
        print("  archive-only models (sample):", sorted(only_b)[:12])

    # same brand+model+year: does the archived asking price differ from the live one?
    key = ["brand", "model", "manufacture_year"]
    a = listing.dropna(subset=["price_m", "manufacture_year"]).groupby(key)["price_m"].median()
    b = archive.dropna(subset=["price_m", "manufacture_year"]).groupby(key)["price_m"].median()
    common = a.index.intersection(b.index)
    if len(common):
        diff = (b.loc[common] - a.loc[common])
        print(f"comparable (brand, model, year) groups: {len(common):,} | "
              f"median price difference (archive - listed): {diff.median():+.1f} million VND")

    _section("DATA QUALITY FLAGS")
    for label, df in (("A. currently listed", listing), ("B. archive", archive)):
        price = pd.to_numeric(df["price_vnd"], errors="coerce")
        km = pd.to_numeric(df["mileage_km"], errors="coerce")
        year = pd.to_numeric(df["manufacture_year"], errors="coerce")
        print(f"{label:20s} no price {price.isna().sum():5,} | price<30M {(price < 3e7).sum():5,} | "
              f"price>25B {(price > 2.5e10).sum():4,} | km>1M {(km > 1e6).sum():4,} | "
              f"year<1995 {(year < 1995).sum():4,} | no year {year.isna().sum():5,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
