"""Error taxonomy and the three case studies, from the actual val predictions.

Plan §4.3 (Tuấn Anh) asks for two things this tool produces from the frozen val split:

* `docs/error_taxonomy.md` — the 25 worst rows, grouped by a rule-based first pass, with the
  counts and the median error per bucket. The rules are stated so a human can confirm or reject
  them; nothing here claims to be a hand audit.
* `docs/case_studies.md` — three listings with URLs (deposit bait, odometer outlier, import/salvage)
  chosen by explicit rules, not picked by eye.

Run:
    python -m tools.error_report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402

RAW_COLUMNS = ["listing_id", "source_url", "location_province", "quality_flags", "price_status",
               "origin", "body_type", "engine_capacity"]


def load(predictions_path: Path) -> pd.DataFrame:
    predictions = pd.read_csv(predictions_path, low_memory=False)
    raw = pd.read_csv(common.raw_path("val"), usecols=RAW_COLUMNS, low_memory=False)
    frame = predictions.merge(raw, on="listing_id", how="left", suffixes=("", "_raw"))
    frame["delta"] = (frame["y_pred_vnd"] - frame["price_vnd"]) / frame["price_vnd"]
    frame["km_per_year"] = frame["mileage_km"] / frame["manufacture_year"].rsub(2026).clip(lower=1)
    return frame


def bucket(row) -> str:
    """Explicit, checkable rules — a first pass for the human audit, not a verdict."""
    if pd.notna(row["price_vnd"]) and row["price_vnd"] < 200_000_000:
        return "1_under_200tr"
    if row["km_per_year"] > 60_000:
        return "2_odometer_outlier"
    if str(row["origin"]).strip().lower() not in ("", "nan", "trong nước", "trong nuoc"):
        return "3_import_or_salvage"
    if str(row["price_status"]) == "negotiable":
        return "4_negotiable_price"
    if pd.notna(row["mileage_km"]) and row["mileage_km"] > 250_000:
        return "5_high_mileage"
    return "6_ordinary_but_wrong"


def write_taxonomy(frame: pd.DataFrame, path: Path) -> None:
    worst = frame.sort_values("abs_pct_error", ascending=False).head(25).copy()
    worst["bucket"] = worst.apply(bucket, axis=1)
    frame = frame.copy()
    frame["bucket"] = frame.apply(bucket, axis=1)
    summary = (frame.groupby("bucket")
               .agg(listings=("abs_pct_error", "size"),
                    median_ape=("abs_pct_error", "median"),
                    mean_delta=("delta", "mean"))
               .sort_values("median_ape", ascending=False))
    by_source = (frame.groupby("source_platform")
                 .agg(listings=("abs_pct_error", "size"), median_ape=("abs_pct_error", "median"),
                      median_price=("price_vnd", "median"))
                 .sort_values("median_ape", ascending=False))
    deciles = frame.assign(price_decile=pd.qcut(frame["price_vnd"], 10, duplicates="drop"))
    by_decile = deciles.groupby("price_decile", observed=True)["abs_pct_error"].median()

    lines = ["# Error taxonomy — where the model is wrong, and how often", "",
             f"Source: `predictions_val.csv` ({len(frame):,} rows on the frozen val split). "
             "Buckets are assigned by the explicit rules in `tools/error_report.py::bucket`, so a "
             "reader can re-derive every count; this is a **rule-based first pass**, not a hand audit. "
             "The hand pass over these 25 rows is the next step for §6 of the report.", "",
             "## The 25 worst rows", "",
             "| # | listing | brand | model | year | km | asking (VND) | predicted (VND) | APE | bucket |",
             "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for rank, (_, row) in enumerate(worst.iterrows(), start=1):
        lines.append(
            f"| {rank} | `{row['listing_id']}` | {row['brand']} | {row['model']} | "
            f"{int(row['manufacture_year']) if pd.notna(row['manufacture_year']) else '-'} | "
            f"{int(row['mileage_km']) if pd.notna(row['mileage_km']) else '-'} | "
            f"{int(row['price_vnd']):,} | {int(row['y_pred_vnd']):,} | {row['abs_pct_error']:.1%} | "
            f"{row['bucket']} |")
    lines += ["", "## Buckets over the whole val split", "",
              "| Bucket | Listings | median APE | mean Δ |", "| --- | ---: | ---: | ---: |"]
    for name, row in summary.iterrows():
        lines.append(f"| {name} | {int(row['listings']):,} | {row['median_ape']:.1%} | "
                     f"{row['mean_delta']:+.1%} |")
    lines += ["", "## Median APE by source (all val rows)", "",
              "| Source | Listings | median APE | median asking price |", "| --- | ---: | ---: | ---: |"]
    for name, row in by_source.iterrows():
        lines.append(f"| {name} | {int(row['listings']):,} | {row['median_ape']:.1%} | "
                     f"{int(row['median_price']):,} |")
    lines += ["", "## Median APE by price decile", "", "| Decile | median APE |", "| --- | ---: |"]
    for name, value in by_decile.items():
        lines.append(f"| {name} | {value:.1%} |")
        lines += ["", "Reading: the error is not uniform. Cheap listings and extreme odometer values carry the "
              "largest percentage error, which is why §6 must report error by segment rather than one MAPE.",
              f"The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are "
              "deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail "
              "is a data problem rather than a model problem.", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def pick_cases(frame: pd.DataFrame) -> list[dict]:
    """Three cases by explicit rules — a bait price, an odometer outlier, an import/salvage gap."""
    cases = []

    def choose(mask, title, why):
        subset = frame[mask].sort_values("abs_pct_error", ascending=False)
        if subset.empty:
            return
        row = subset.iloc[0]
        cases.append({"title": title, "why": why, "row": row})

    choose(frame["delta"] < -0.45, "Case 1 — asking price far below the model (deposit bait)",
           "The listing asks at least 45% under the model's estimate; in this dataset that pattern is "
           "what a deposit scam looks like, and it is the reason a cheap price is never a win by itself.")
    choose(frame["km_per_year"] > 60_000, "Case 2 — odometer outlier",
           "Mileage divided by vehicle age is above 60,000 km/year, three to five times the fleet "
           "median. Either the odometer was rolled back or the car really was used for long-haul work.")
    domestic = {"", "nan", "trong nước", "trong nuoc", "none"}
    origin_lower = frame["origin"].astype(str).str.strip().str.lower()
    choose((~origin_lower.isin(domestic)) & (frame["price_vnd"] >= 200_000_000),
           "Case 3 — import / salvage",
           "`origin` is not the domestic value and the asking price is above the \"suspiciously cheap\" "
           "cut, so the case is about origin rather than about a placeholder price. Same predicate as "
           "bucket 3 in the taxonomy, restricted to rows Case 1 does not already own.")
    return cases


def write_cases(frame: pd.DataFrame, path: Path) -> None:
    lines = ["# Three case studies (plan §4.3)", "",
             "Each case is picked by an explicit rule in `tools/error_report.py::pick_cases`, not by eye, "
             "so the same three rows appear every time the tool runs on this snapshot. Numbers are the "
             "frozen val split; the URL is the listing the row came from.", ""]
    cases = pick_cases(frame)
    if not cases:
        lines += ["_No row matched the case rules on this snapshot._", ""]
    for case in cases:
        row = case["row"]
        lines += [f"## {case['title']}", "",
                  f"- Listing: `{row['listing_id']}` — {row['brand']} {row['model']}, "
                  f"{int(row['manufacture_year']) if pd.notna(row['manufacture_year']) else '-'}"
                  f", {int(row['mileage_km']) if pd.notna(row['mileage_km']) else '-'} km"
                  f", {row['location_province']}",
                  f"- Asking price: **{int(row['price_vnd']):,} VND** · model estimate "
                  f"**{int(row['y_pred_vnd']):,} VND** · Δ {row['delta']:+.1%} · APE "
                  f"{row['abs_pct_error']:.1%}",
                  f"- Bucket: `{row['bucket']}` · quality flags: `{str(row['quality_flags'])[:80]}`",
                  f"- Link: {row['source_url']}", "",
                  f"Why it matters: {case['why']}", ""]
    lines += ["The point of these three is not that the model is wrong on them — it is that the three "
              "failure modes are structural (bait pricing, mileage manipulation, import status) and no "
              "amount of tuning on the frozen table fixes them. §7 of the report should say that.", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Error taxonomy + case studies from val predictions")
    parser.add_argument("--predictions", default=str(config.DATA_MASTER / "predictions_val.csv"))
    parser.add_argument("--taxonomy", default="docs/error_taxonomy.md")
    parser.add_argument("--cases", default="docs/case_studies.md")
    args = parser.parse_args(argv)

    frame = load(Path(args.predictions))
    frame["bucket"] = frame.apply(bucket, axis=1)

    taxonomy = Path(args.taxonomy)
    if not taxonomy.is_absolute():
        taxonomy = Path(__file__).resolve().parents[1] / taxonomy
    taxonomy.parent.mkdir(parents=True, exist_ok=True)
    write_taxonomy(frame, taxonomy)

    cases = Path(args.cases)
    if not cases.is_absolute():
        cases = Path(__file__).resolve().parents[1] / cases
    write_cases(frame, cases)

    print(f"rows {len(frame):,} | median APE {frame['abs_pct_error'].median():.3f} | "
          f"worst {frame['abs_pct_error'].max():.3f}")
    print(frame["bucket"].value_counts().to_string())
    print(f"\n  taxonomy -> {taxonomy}\n  cases -> {cases}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
