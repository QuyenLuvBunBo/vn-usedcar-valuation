"""Summarise and quality-check a crawled CSV with pandas.

Run: python -m tools.summarize_oto [csv_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSV = Path("data/processed/oto_cars.csv")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else CSV
    if not path.exists():
        print("File not found:", path)
        return

    df = pd.read_csv(path)
    print("=" * 70)
    print(f"FILE: {path}  |  {len(df)} rows x {len(df.columns)} columns")
    print("=" * 70)

    print("\n### Listings per brand")
    print(df["brand"].value_counts().to_string())

    print("\n### Condition / origin")
    print(df["condition"].value_counts().to_string())
    print(df["origin"].value_counts(dropna=False).to_string())

    print("\n### Price (million VND) per brand")
    priced = df.dropna(subset=["price_vnd"]).copy()
    priced["price_m"] = (priced["price_vnd"] / 1e6).round(1)
    stats = priced.groupby("brand")["price_m"].agg(["count", "min", "median", "max"]).round(1)
    print(stats.to_string())
    print(f"\nTotal: {len(priced)}/{len(df)} listings have a price "
          f"({len(priced) / len(df) * 100:.1f}%)")

    print("\n### Manufacture year")
    print(df["year"].describe().round(1).to_string())
    print(df["year"].value_counts().sort_index().tail(8).to_string())

    print("\n### Mileage (km)")
    print(df["km"].describe().round(0).to_string())

    print("\n### Top 10 models")
    print(df["model"].value_counts().head(10).to_string())

    print("\n### Top 10 provinces / cities")
    print(df["province"].value_counts().head(10).to_string())

    print("\n### Transmission / fuel / body type")
    print(df["gearbox"].value_counts(dropna=False).to_string())
    print(df["fuel"].value_counts(dropna=False).to_string())
    print(df["body_type"].value_counts(dropna=False).head(10).to_string())

    print("\n### Missing values per column")
    missing = df.isna().sum()
    missing = missing[missing > 0]
    print(missing.to_string() if len(missing) else "  (none)")

    print("\n### Detail-page data (if crawled)")
    if "d_title" in df.columns and df["d_title"].notna().any():
        have = int(df["d_title"].notna().sum())
        print(f"  Detail pages crawled: {have}/{len(df)} listings")
        for col in ("d_price_vnd", "d_color", "d_seats", "d_image_count",
                    "d_seller_name", "d_seller_address", "d_description", "d_specs"):
            if col in df.columns:
                n = int(df[col].notna().sum())
                print(f"  {col:18s} {n:5d} ({n / len(df) * 100:5.1f}%)")

        both = df.dropna(subset=["price_vnd", "d_price_vnd"])
        if len(both):
            mismatch = int((both["price_vnd"].astype("int64") != both["d_price_vnd"].astype("int64")).sum())
            print(f"  Cross-check listing vs detail price: match {len(both) - mismatch}/{len(both)} "
                  f"(mismatch {mismatch})")

        sold_detail = df[df["d_title"].notna()]
        print(f"  Of those with detail data: sold {int(sold_detail['sold'].sum())}, "
              f"missing colour {int(sold_detail['d_color'].isna().sum())}")
    else:
        print("  (no detail pages yet — run: python -m src.sources.oto --detail-only)")

    print("\n### Duplicate checks")
    print(f"  duplicate url : {int(df['url'].duplicated().sum())}")
    print(f"  duplicate id  : {int(df['id'].duplicated().sum())}")
    print(f"  (brand, model, year, price, km, seller) duplicates: "
          f"{int(df.duplicated(subset=['brand', 'model', 'year', 'price_vnd', 'km', 'seller_name']).sum())}")

    print("\n### Outlier checks")
    print(f"  price <= 20 million    : {int((df['price_vnd'] <= 2e7).sum())}")
    print(f"  km <= 5                : {int((df['km'] <= 5).sum())}  (sellers typing 1 km)")
    print(f"  year < 2000            : {int((df['year'] < 2000).sum())}")
    print(f"  year > 2026            : {int((df['year'] > 2026).sum())}")


if __name__ == "__main__":
    main()
