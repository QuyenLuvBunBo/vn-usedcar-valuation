"""EDA on the merged dataset (plan §4.3): numbers + the five figures the report needs.

Reads `data/master/master_clean_dataset.csv`, writes five PNGs into `docs/figures/` and
`docs/eda_summary.md` with the numbers behind each figure.

Run:
    python -m tools.eda_summary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TIERS = ("1_domestic", "2_import", "3_luxury")


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    fig.clf()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EDA summary + figures on the merged dataset")
    parser.add_argument("--master", default=str(config.DATA_MASTER / "master_clean_dataset.csv"))
    parser.add_argument("--doc", default="docs/eda_summary.md")
    parser.add_argument("--figures", default="docs/figures")
    args = parser.parse_args(argv)

    frame = pd.read_csv(args.master, low_memory=False)
    frame = frame[frame["price_vnd"].between(10_000_000, 50_000_000_000)]
    figures = Path(args.figures)
    if not figures.is_absolute():
        figures = REPO / figures
    doc = Path(args.doc)
    if not doc.is_absolute():
        doc = REPO / doc

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axis = plt.subplots(figsize=(7, 4))
    axis.hist(np.log10(frame["price_vnd"]), bins=60, color="#3b6ea5")
    axis.set_xlabel("log10(asking price, VND)")
    axis.set_ylabel("listings")
    axis.set_title(f"Asking price, {len(frame):,} listings")
    _save(fig, figures / "fig1_price_distribution.png")

    by_province = (frame.groupby("location_province")
                   .agg(listings=("price_vnd", "size"), median_price=("price_vnd", "median"))
                   .sort_values("listings", ascending=False).head(12))
    fig, axis = plt.subplots(figsize=(7, 5))
    axis.barh(by_province.index[::-1], by_province["median_price"][::-1] / 1e9, color="#4f8a5b")
    axis.set_xlabel("median asking price (billion VND)")
    axis.set_title("Median price by province — top 12 by volume")
    _save(fig, figures / "fig2_price_by_province.png")

    by_source = (frame.groupby("source_platform")
                 .agg(listings=("price_vnd", "size"), median_price=("price_vnd", "median"))
                 .sort_values("listings", ascending=False))
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.bar(by_source.index.astype(str), by_source["listings"], color="#7d5aa5")
    axis.set_ylabel("listings")
    axis.tick_params(axis="x", rotation=30)
    axis.set_title("Listings per source platform")
    _save(fig, figures / "fig3_listings_by_source.png")

    by_year = frame.groupby("manufacture_year")["price_vnd"].median()
    by_year = by_year[by_year.index >= 2010]
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.plot(by_year.index, by_year.to_numpy() / 1e9, marker="o", color="#a55a3b")
    axis.set_xlabel("manufacture year")
    axis.set_ylabel("median asking price (billion VND)")
    axis.set_title("Median price by model year")
    _save(fig, figures / "fig4_price_by_year.png")

    frame = frame.assign(price_per_1000km=frame["price_vnd"]
                         / (frame["mileage_km"].clip(lower=1) / 1000))
    tiers = [tier for tier in TIERS if tier in set(frame["tier"].dropna())] or ["all"]
    data = [(frame.loc[frame["tier"] == tier, "price_per_1000km"] if tier != "all"
             else frame["price_per_1000km"]).dropna().clip(upper=5e9) / 1e6 for tier in tiers]
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.boxplot(data, tick_labels=tiers, showfliers=False)
    axis.set_ylabel("million VND per 1000 km")
    axis.set_title("Price per 1000 km by tier")
    _save(fig, figures / "fig5_price_per_km_by_tier.png")

    counts = frame["source_platform"].value_counts()
    lines = ["# EDA summary — merged dataset", "",
             f"{len(frame):,} listings with a usable asking price (10 million – 50 billion VND), from "
             "`master_clean_dataset.csv`. Figures are in `docs/figures/`.", "",
             "## Volume by source", "", "| Source | Listings | Median price (VND) |",
             "| --- | ---: | ---: |"]
    for name, row in by_source.iterrows():
        lines.append(f"| {name} | {int(row['listings']):,} | {int(row['median_price']):,} |")
    lines += ["", f"The largest platform carries **{counts.iloc[0]:,}** listings "
              f"({counts.iloc[0] / len(frame):.0%} of the table); the long tail of smaller platforms is what "
              "makes a cross-platform price index possible at all.", "",
              "## Price by region (top 12 by volume)", "", "| Province | Listings | Median price (VND) |",
              "| --- | ---: | ---: |"]
    for name, row in by_province.iterrows():
        lines.append(f"| {name} | {int(row['listings']):,} | {int(row['median_price']):,} |")
    lines += ["", "## Median price by model year", "", "| Year | Median price (VND) |", "| ---: | ---: |"]
    for year, value in by_year.items():
        lines.append(f"| {int(year)} | {int(value):,} |")
    lines += ["", "## Reading", "",
              "- Price is right-skewed even after the sanity filter, which is why every model fits "
              "`log1p(price_vnd)` and why R²(VND) always looks better than R²(log).",
              "- Regional medians differ by more than a factor of two across the top 12 provinces, so "
              "`location_province` (grouped into `province_group`) is a real feature, not noise.",
              "- Volume is concentrated on one platform, so a per-platform error breakdown in §6 is "
              "mandatory: a single MAPE would hide the smaller platforms.",
              "- Figures: `fig1_price_distribution.png`, `fig2_price_by_province.png`, "
              "`fig3_listings_by_source.png`, `fig4_price_by_year.png`, `fig5_price_per_km_by_tier.png`.", ""]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"listings {len(frame):,} | sources {len(by_source)} | provinces "
          f"{frame['location_province'].nunique():,}")
    print(f"  figures -> {figures}\n  doc     -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
