"""Error analysis for report §6 — the 25 worst val errors, from predictions_val.csv.

No training, no new fits: everything comes from the frozen predictions file, so the report's §6
table is a copy of this output. It answers three questions the section needs:

    python -m tools.error_analysis                     # predictions_val.csv
    python -m tools.error_analysis --split test        # predictions_test.csv (after M2)
    python -m tools.error_analysis --top 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="worst errors from a predictions file")
    parser.add_argument("--split", default="val", choices=("val", "test"))
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args(argv)

    path = config.DATA_MASTER / f"predictions_{args.split}.csv"
    if not path.exists():
        raise SystemExit(f"missing {path} -> run 'python -m src.models.train --model lgbm "
                         f"--features full --write-predictions --split {args.split}' first")
    frame = pd.read_csv(path, low_memory=False)
    frame["pct_error"] = frame["abs_pct_error"] * 100

    print(f"{path.name}: {len(frame):,} rows | MAPE {frame['abs_pct_error'].mean():.3f} | "
          f"median APE {frame['abs_pct_error'].median():.3f}")
    print(f"deciles of |% error|: p50 {frame['pct_error'].quantile(.5):.1f}  "
          f"p90 {frame['pct_error'].quantile(.9):.1f}  "
          f"p99 {frame['pct_error'].quantile(.99):.1f}")

    worst = frame.nlargest(args.top, "abs_pct_error")
    print(f"\n== worst {args.top} by |% error| ==")
    show = worst[["listing_id", "brand", "model", "manufacture_year", "mileage_km",
                  "location_province", "source_platform", "price_vnd", "y_pred_vnd", "pct_error"]]
    print(show.to_string(index=False, float_format=lambda v: f"{v:,.0f}"))

    print("\n== where the errors live (worst 5% vs the rest) ==")
    cut = frame["abs_pct_error"].quantile(0.95)
    hard = frame[frame["abs_pct_error"] >= cut]
    for column in ("brand", "source_platform", "location_province"):
        share = (hard[column].value_counts(normalize=True)
                 - frame[column].value_counts(normalize=True)).mul(100).round(1)
        print(f"\n  {column}: over-representation of the worst 5% (pp)")
        print(share[share.abs() >= 0.5].head(8).to_string())

    expensive = frame["price_vnd"].quantile(0.9)
    for name, mask in (("cheapest decile", frame["price_vnd"] <= frame["price_vnd"].quantile(0.1)),
                      ("priciest decile", frame["price_vnd"] >= expensive),
                      ("high mileage (top decile)",
                       frame["mileage_km"] >= frame["mileage_km"].quantile(0.9)),
                      ("15+ years old", frame["manufacture_year"] <= 2011)):
        part = frame[mask]
        if len(part):
            print(f"  {name:24s} n={len(part):>6,}  MAPE {part['abs_pct_error'].mean():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
