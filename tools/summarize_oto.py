"""Tổng hợp & kiểm tra chất lượng dữ liệu đã cào (dùng pandas).

Chạy: python -m tools.summarize_oto [duong_dan_csv]
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
        print("Không thấy file:", path)
        return

    df = pd.read_csv(path)
    print("=" * 70)
    print(f"FILE: {path}  |  {len(df)} dòng x {len(df.columns)} cột")
    print("=" * 70)

    print("\n### Số tin theo hãng")
    print(df["brand"].value_counts().to_string())

    print("\n### Tình trạng / xuất xứ")
    print(df["condition"].value_counts().to_string())
    print(df["origin"].value_counts(dropna=False).to_string())

    print("\n### Giá (triệu VND) theo hãng")
    priced = df.dropna(subset=["price_vnd"]).copy()
    priced["price_m"] = (priced["price_vnd"] / 1e6).round(1)
    stats = priced.groupby("brand")["price_m"].agg(["count", "min", "median", "max"]).round(1)
    print(stats.to_string())
    print(f"\nTổng: {len(priced)}/{len(df)} tin có giá "
          f"({len(priced) / len(df) * 100:.1f}%)")

    print("\n### Năm sản xuất")
    print(df["year"].describe().round(1).to_string())
    print(df["year"].value_counts().sort_index().tail(8).to_string())

    print("\n### Số km đã đi")
    print(df["km"].describe().round(0).to_string())

    print("\n### Top 10 model")
    print(df["model"].value_counts().head(10).to_string())

    print("\n### Top 10 tỉnh/thành")
    print(df["province"].value_counts().head(10).to_string())

    print("\n### Hộp số / nhiên liệu / loại xe")
    print(df["gearbox"].value_counts(dropna=False).to_string())
    print(df["fuel"].value_counts(dropna=False).to_string())
    print(df["body_type"].value_counts(dropna=False).head(10).to_string())

    print("\n### Giá trị thiếu theo cột")
    missing = df.isna().sum()
    missing = missing[missing > 0]
    print(missing.to_string() if len(missing) else "  (không có)")

    print("\n### Dữ liệu trang chi tiết (nếu đã cào)")
    if "d_title" in df.columns and df["d_title"].notna().any():
        have = int(df["d_title"].notna().sum())
        print(f"  Đã có chi tiết: {have}/{len(df)} tin")
        for col in ("d_price_vnd", "d_color", "d_seats", "d_image_count",
                    "d_seller_name", "d_seller_address", "d_description", "d_specs"):
            if col in df.columns:
                n = int(df[col].notna().sum())
                print(f"  {col:18s} {n:5d} ({n / len(df) * 100:5.1f}%)")

        both = df.dropna(subset=["price_vnd", "d_price_vnd"])
        if len(both):
            mismatch = int((both["price_vnd"].astype("int64") != both["d_price_vnd"].astype("int64")).sum())
            print(f"  Kiểm chéo giá listing vs chi tiết: khớp {len(both) - mismatch}/{len(both)} "
                  f"(lệch {mismatch})")

        sold_detail = df[df["d_title"].notna()]
        print(f"  Trong số đã cào chi tiết: đã bán {int(sold_detail['sold'].sum())}, "
              f"thiếu màu {int(sold_detail['d_color'].isna().sum())}")
    else:
        print("  (chưa cào trang chi tiết — chạy: python -m src.oto_scraper --detail)")

    print("\n### Kiểm tra trùng lặp")
    print(f"  url trùng        : {int(df['url'].duplicated().sum())}")
    print(f"  id trùng         : {int(df['id'].duplicated().sum())}")
    print(f"  (hãng, model, năm, giá, km, người bán) trùng: "
          f"{int(df.duplicated(subset=['brand', 'model', 'year', 'price_vnd', 'km', 'seller_name']).sum())}")

    print("\n### Kiểm tra giá trị bất thường")
    print(f"  giá <= 20 triệu  : {int((df['price_vnd'] <= 2e7).sum())}")
    print(f"  km <= 5          : {int((df['km'] <= 5).sum())}  (tin đăng ghi 1 km)")
    print(f"  năm < 2000       : {int((df['year'] < 2000).sum())}")
    print(f"  năm > 2026       : {int((df['year'] > 2026).sum())}")


if __name__ == "__main__":
    main()
