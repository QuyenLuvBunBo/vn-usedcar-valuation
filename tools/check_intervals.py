"""Do the P10/P90 bands actually cover 80 % of the asking prices?

`src/models/train.py --quantiles` writes `p10_vnd` / `p90_vnd`, and T3 turns them into the
Bargain / Overpriced labels. Neither of those is worth anything if the band is miscalibrated, so this
tool measures it: nominal coverage is 80 %, and a calibrated pair of quantile fits should leave roughly
10 % of the prices below P10 and 10 % above P90.

Run:
    python -m tools.check_intervals
    python -m tools.check_intervals --predictions data/master/predictions_test.csv --doc docs/intervals_test.md
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
NOMINAL = 0.80
TOLERANCE = 0.05          # the band is "acceptable" within ±5 points of nominal


def summarise(frame: pd.DataFrame) -> dict:
    price = frame["price_vnd"].to_numpy(dtype=float)
    low = frame["p10_vnd"].to_numpy(dtype=float)
    high = frame["p90_vnd"].to_numpy(dtype=float)
    below = float((price < low).mean())
    above = float((price > high).mean())
    width = high - low
    return {"rows": int(len(frame)), "below": below, "inside": 1.0 - below - above, "above": above,
            "median_width": float(np.median(width)),
            "median_relative_width": float(np.median(width / np.clip(frame["y_pred_vnd"], 1, None))),
            "median_ape": float(np.median(frame["abs_pct_error"]))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coverage of the P10/P90 bands")
    parser.add_argument("--predictions", default=str(config.DATA_MASTER / "predictions_val.csv"))
    parser.add_argument("--doc", default="docs/intervals.md")
    args = parser.parse_args(argv)

    frame = pd.read_csv(args.predictions, low_memory=False)
    if frame["p10_vnd"].isna().all() or frame["p90_vnd"].isna().all():
        raise SystemExit(f"{args.predictions} has no P10/P90 columns -> rerun train --quantiles")

    overall = summarise(frame)
    by_source = (frame.groupby("source_platform")
                 .apply(lambda part: pd.Series(summarise(part)), include_groups=False)
                 .sort_values("inside", ascending=False))
    verdict = "PASS" if abs(overall["inside"] - NOMINAL) <= TOLERANCE else "MISALIBRATED"

    lines = [
        "# Are the P10/P90 bands calibrated?", "",
        f"Source: `{Path(args.predictions).name}` ({overall['rows']:,} rows). Nominal coverage "
        f"**{NOMINAL:.0%}**; a calibrated pair of quantile fits puts ≈10 % of the prices below P10 and "
        f"≈10 % above P90.", "",
        "| Measure | Value |", "| --- | ---: |",
        f"| inside the band | **{overall['inside']:.2%}** |",
        f"| price below P10 | {overall['below']:.2%} |",
        f"| price above P90 | {overall['above']:.2%} |",
        f"| median band width | {overall['median_width']:,.0f} VND |",
        f"| median width / point estimate | {overall['median_relative_width']:.1%} |",
        f"| median APE of the point estimate | {overall['median_ape']:.1%} |", "",
        f"**Verdict: {verdict}** (tolerance ±{TOLERANCE:.0%} around nominal).", "",
        "## Coverage by platform", "",
        "| Platform | Rows | Inside | Below P10 | Above P90 |", "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, row in by_source.iterrows():
        lines.append(f"| {name} | {int(row['rows']):,} | {row['inside']:.1%} | {row['below']:.1%} | "
                     f"{row['above']:.1%} |")
    lines += ["", "## Reading", "",
              "- Coverage below nominal means the band is too narrow: the P10 fit is too high and the P90 "
              "fit too low, so `Bargain` / `Overpriced` labels fire less often than the definition intends.",
              "- Coverage above nominal means the opposite: the bands are wide and the labels are "
              "conservative.",
              "- An asymmetry between `below` and `above` is the useful signal: too many prices above P90 "
              "means the upper quantile is under-fitted, which is what a plain squared-loss model does "
              "when the price distribution has a long right tail.",
              "- The bands are fitted with 500-tree LightGBM quantile models and **are not tuned**; the "
              "numbers here are the reason to tune them, not proof that they are fine.", ""]
    doc = Path(args.doc)
    if not doc.is_absolute():
        doc = REPO / doc
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    print(f"rows {overall['rows']:,} | inside {overall['inside']:.2%} (nominal {NOMINAL:.0%}) | "
          f"below {overall['below']:.2%} | above {overall['above']:.2%} -> {verdict}")
    print(f"  doc -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
