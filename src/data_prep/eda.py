"""Week 2, EDA half: the five analyses the plan assigns to sub-team 3, as a re-runnable script.

A notebook is where these numbers get discussed; a module is where they are *produced*, so that the
report's figures and tables can be regenerated with one command and cannot drift from the data:

    price distribution          -> how heavy the tail is, and why the target is modelled in log space
    price by brand              -> which makes carry the market, and how wide each spread is
    price by year               -> the age-price curve the model has to learn
    price by odometer           -> is mileage informative once age is known?
    depreciation by brand       -> value lost by age 5, per brand (cross-sectional, not a panel)
    price gap between platforms -> the same car advertised on two sites, compared

Every table is printed as Markdown and written next to the figures, so a report section is a copy,
not a re-derivation. Caveat that must travel with the last two tables: they are **cross-sectional**
(different cars at different ages) and the sample is a snapshot, so they describe advertised prices,
not transaction prices, and not one vehicle's history.

Run:
    python -m src.data_prep.eda                        # figures + tables from train_cohort.csv
    python -m src.data_prep.eda --input data/master/train.csv --top-brands 20
    python -m src.data_prep.eda --no-figures           # tables only (fast)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")           # headless: figures are written to disk, never to a window
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd              # noqa: E402

from ..common import config      # noqa: E402

log = logging.getLogger("eda")

NUMERIC = ("price_vnd", "mileage_km", "manufacture_year", "engine_capacity", "seats")
QUANTILES = (0.10, 0.50, 0.90)


def load(path: Path) -> pd.DataFrame:
    """Read a split or cohort file, with the numeric columns actually numeric."""
    frame = pd.read_csv(path, low_memory=False)
    for column in NUMERIC:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def summary_stats(frame: pd.DataFrame, columns: tuple[str, ...] | None = None) -> pd.DataFrame:
    """The descriptive-statistics table the week-2 plan asks for, one row per numeric column.

    Reported on the modelling cohort (not on the raw master), because that is the data week 3 sees.
    """
    columns = columns or ("price_vnd", "mileage_km", "manufacture_year", "engine_capacity", "seats")
    rows = []
    for column in columns:
        series = frame[column].dropna() if column in frame.columns else pd.Series(dtype=float)
        if series.empty:
            continue
        rows.append({
            "column": column,
            "count": int(series.size),
            "missing_rate": round(1 - series.size / len(frame), 4),
            "mean": series.mean(),
            "std": series.std(),
            "min": series.min(),
            "p25": series.quantile(0.25),
            "median": series.median(),
            "p75": series.quantile(0.75),
            "max": series.max(),
        })
    return pd.DataFrame(rows).set_index("column")


def price_overview(frame: pd.DataFrame) -> pd.DataFrame:
    """Price per platform: size, median, p10/p90 and the share of the sample.

    The p90/p10 ratio is the number that justifies modelling `log(price)`: a spread of two orders of
    magnitude means an RMSE in VND is dominated by the few most expensive cars.
    """
    grouped = frame.groupby("source_platform")["price_vnd"]
    table = grouped.agg(rows="size", median="median",
                        p10=lambda s: s.quantile(QUANTILES[0]),
                        p90=lambda s: s.quantile(QUANTILES[2]))
    table["share"] = table["rows"] / len(frame)
    table["p90_over_p10"] = table["p90"] / table["p10"]
    return table.sort_values("rows", ascending=False)


def by_brand(frame: pd.DataFrame, top: int = 15) -> pd.DataFrame:
    """The biggest brands by listing count, with their median and interquartile spread."""
    grouped = frame.groupby("brand")["price_vnd"]
    table = grouped.agg(rows="size", median="median",
                        p25=lambda s: s.quantile(0.25), p75=lambda s: s.quantile(0.75))
    return table.sort_values("rows", ascending=False).head(top)


def by_year(frame: pd.DataFrame, since: int = 1995) -> pd.DataFrame:
    """Median asking price per model year — the age-price curve."""
    usable = frame[frame["manufacture_year"].between(since, frame["manufacture_year"].max())]
    table = usable.groupby("manufacture_year")["price_vnd"].agg(rows="size", median="median")
    return table[table["rows"] >= 5]


def by_mileage(frame: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """Median price per odometer decile: does the odometer carry signal of its own?

    Deciles (not fixed bins) are used because the distribution is skewed and a 0–20 000 km bin would
    otherwise hold half the sample.
    """
    usable = frame[frame["mileage_km"].notna() & (frame["mileage_km"] >= 0)].copy()
    usable["km_band"] = pd.qcut(usable["mileage_km"], bins, duplicates="drop")
    table = usable.groupby("km_band", observed=True)["price_vnd"].agg(rows="size", median="median")
    table["km_median"] = usable.groupby("km_band", observed=True)["mileage_km"].median()
    return table


def depreciation_by_brand(frame: pd.DataFrame, min_rows: int = 30) -> pd.DataFrame:
    """Value lost by age 5, per brand: 1 - median(price | age 5-6) / median(price | age 1-2).

    Cross-sectional, so it mixes cars of different trims and conditions — it is a market-level
    description, not a depreciation schedule for one vehicle. Brands thinner than `min_rows` in
    either band are dropped rather than shown with a number nobody should quote.
    """
    reference = int(frame["scraped_at"].astype(str).str[:4].max())
    aged = frame.assign(age=reference - frame["manufacture_year"])
    young = aged[aged["age"].between(1, 2)]
    older = aged[aged["age"].between(5, 6)]

    young_median = young.groupby("brand")["price_vnd"].agg(["size", "median"])
    older_median = older.groupby("brand")["price_vnd"].agg(["size", "median"])
    joined = young_median.join(older_median, lsuffix="_young", rsuffix="_old")
    joined = joined[(joined["size_young"] >= min_rows) & (joined["size_old"] >= min_rows)]
    table = pd.DataFrame({
        "rows_young": joined["size_young"],
        "rows_old": joined["size_old"],
        "median_age_1_2": joined["median_young"],
        "median_age_5_6": joined["median_old"],
    })
    table["value_lost_by_age5"] = 1 - table["median_age_5_6"] / table["median_age_1_2"]
    return table.sort_values("value_lost_by_age5")


def platform_gap(frame: pd.DataFrame, min_rows: int = 3) -> pd.DataFrame:
    """The same car on two platforms: each platform's price against *the other* platforms' price.

    Without matching, a platform-level median mostly measures *which cars* it lists (a dealership
    chain sells newer cars), not its pricing. Matching on brand+model+year removes that mix.

    The comparison is leave-one-out on purpose: against the median of the *other* cells in the same
    group, not against the group median. With only two platforms in a group the group median sits
    between them, so every ratio would be pushed toward 1 and the interesting deviation would vanish.
    A ratio of 1.05 therefore reads "this platform asks 5% more than the others for the same car".
    """
    usable = frame[frame["price_vnd"].notna() & frame["manufacture_year"].notna()]
    key = ["brand", "model", "manufacture_year"]
    per_cell = (usable.groupby([*key, "source_platform"])["price_vnd"]
                .agg(rows="size", median="median").reset_index())
    per_cell = per_cell[per_cell["rows"] >= min_rows]
    per_cell["platforms_in_group"] = per_cell.groupby(key)["source_platform"].transform("nunique")
    matched = per_cell[per_cell["platforms_in_group"] >= 2].copy()
    if matched.empty:
        return pd.DataFrame(columns=["rows", "matched_cells", "median_ratio", "p25_ratio", "p75_ratio"])

    others: list[float] = []
    for index, cell in matched.iterrows():
        same_group = matched[
            (matched["brand"] == cell["brand"])
            & (matched["model"] == cell["model"])
            & (matched["manufacture_year"] == cell["manufacture_year"])
            & (matched["source_platform"] != cell["source_platform"])]
        others.append(float(same_group["median"].median()))
    matched["others_median"] = others
    matched["ratio"] = matched["median"] / matched["others_median"]

    table = matched.groupby("source_platform")["ratio"].agg(
        matched_cells="size", median_ratio="median",
        p25_ratio=lambda s: s.quantile(0.25), p75_ratio=lambda s: s.quantile(0.75))
    table["rows"] = matched.groupby("source_platform")["rows"].sum()
    return table.sort_values("median_ratio")



# ------------------------------------------------------------------ figures
def figures(frame: pd.DataFrame, tables: dict[str, pd.DataFrame], out_dir: Path) -> dict[str, Path]:
    """Write the six report figures. Headless (Agg), so this runs on a server or in CI."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def save(name: str, title: str, ylabel: str = "") -> None:
        axis = plt.gca()
        axis.set_title(title)
        if ylabel:
            axis.set_ylabel(ylabel)
        plt.tight_layout()
        path = out_dir / f"{name}.png"
        plt.savefig(path, dpi=130)
        plt.close()
        written[name] = path

    price = frame["price_vnd"].dropna()
    positive = price[price > 0]
    plt.figure(figsize=(7, 4))
    plt.hist(positive, bins=60)
    plt.xscale("log")
    plt.xlabel("asking price (VND, log scale)")
    save("price_distribution", f"Advertised price, n={len(positive):,}", "listings")

    brand = tables["by_brand"]
    plt.figure(figsize=(7, 5))
    plt.barh(brand.index[::-1], brand["median"][::-1])
    plt.xlabel("median asking price (VND)")
    save("price_by_brand", f"Median price — top {len(brand)} brands by listing count")

    year = tables["by_year"]
    plt.figure(figsize=(7, 4))
    plt.plot(year.index, year["median"], marker="o")
    plt.xlabel("model year")
    save("price_by_year", "Median asking price by model year", "VND")

    km = tables["by_mileage"]
    plt.figure(figsize=(7, 4))
    plt.plot(km["km_median"], km["median"], marker="o")
    plt.xlabel("odometer (km, decile median)")
    save("price_by_mileage", "Median asking price by odometer decile", "VND")

    dep = tables["depreciation"]
    if not dep.empty:
        plt.figure(figsize=(7, 5))
        plt.barh(dep.index[::-1], dep["value_lost_by_age5"][::-1] * 100)
        plt.xlabel("value lost from age 1-2 to age 5-6 (%)")
        save("depreciation_by_brand", "Depreciation to age 5 (cross-sectional)")

    gap = tables["platform_gap"]
    if not gap.empty:
        plt.figure(figsize=(7, 4))
        plt.bar(gap.index, (gap["median_ratio"] - 1) * 100)
        plt.axhline(0, color="black", linewidth=0.8)
        plt.ylabel("price vs the same car elsewhere (%)")
        plt.xticks(rotation=20, ha="right")
        save("platform_gap", "Matched price gap between platforms")
    return written


# --------------------------------------------------------------- reporting
def _md_table(table: pd.DataFrame, index_name: str = "") -> str:
    """Render a DataFrame as a Markdown table (no extra dependency, paste-ready for the report)."""
    def cell(value) -> str:
        if isinstance(value, float):
            if abs(value) < 1:                      # a ratio or a share
                return f"{value:.3f}"
            return f"{value:,.0f}"
        return str(value)

    header = [index_name, *(str(column) for column in table.columns)]
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for index, values in table.iterrows():
        lines.append("| " + " | ".join([cell(index), *(cell(v) for v in values)]) + " |")
    return "\n".join(lines)


SECTIONS = (
    ("summary_stats", "0. Descriptive statistics of the modelling cohort",
     "`count` and `missing_rate` are pre-imputation, i.e. what the sites actually published. The file "
     "week 3 trains on has the gaps filled and marks every filled cell in `imputed`, so a missingness "
     "indicator stays available."),
    ("price_overview", "1. Price distribution per platform",
     "p90/p10 above ~5 is why the target is modelled in log space: a VND-scale RMSE would be "
     "dominated by the expensive tail."),
    ("by_brand", "2. Median price by brand",
     "The wide p25-p75 bands inside one brand are trim and age, not only make."),
    ("by_year", "3. Median price by model year",
     "Advertised, cross-sectional: newer cars are listed at higher prices, which is the age signal "
     "the model learns."),
    ("by_mileage", "4. Median price by odometer decile",
     "Read together with the age curve — mileage and age are correlated, so the marginal effect of "
     "the odometer is smaller than this table alone suggests."),
    ("depreciation", "5. Value lost to age 5, by brand",
     "Cross-sectional (different cars at different ages), and advertised prices — a market-level "
     "description, not a depreciation schedule for one vehicle."),
    ("platform_gap", "6. Matched price gap between platforms",
     "Same brand+model+year, at least N listings per platform cell. Median 1.000 is expected and "
     "informative: a cross-posted ad usually carries the same asking price on both sites, so the "
     "deviation from 1 (p25 and the median) is the finding, not the mode."),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Week-2 EDA: tables and figures, re-runnable")
    parser.add_argument("--input", default="",
                        help="default: data/master/train_cohort.csv, else train.csv")
    parser.add_argument("--out-dir", default=str(config.DATA_MASTER / "eda"))
    parser.add_argument("--top-brands", type=int, default=15)
    parser.add_argument("--min-matched-rows", type=int, default=3,
                        help="listings a platform needs for one brand+model+year to be compared")
    parser.add_argument("--no-figures", action="store_true", help="tables only (no matplotlib)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    path = Path(args.input) if args.input else config.DATA_MASTER / "train_cohort.csv"
    if not args.input and not path.exists():
        path = config.DATA_MASTER / "train.csv"
    if not path.exists():
        log.error("no input file: %s -> run 'python -m src.data_prep.split' first", path)
        return 1

    frame = load(path)
    usable = frame[frame["price_vnd"].notna()]
    print(f"{path.name}: {len(frame):,} rows, {len(usable):,} with an asking price")

    tables = {
        "summary_stats": summary_stats(frame),
        "price_overview": price_overview(usable),
        "by_brand": by_brand(usable, args.top_brands),
        "by_year": by_year(usable),
        "by_mileage": by_mileage(usable),
        "depreciation": depreciation_by_brand(usable),
        "platform_gap": platform_gap(usable, args.min_matched_rows),
    }

    index_names = {"summary_stats": "column", "price_overview": "source_platform",
                   "by_brand": "brand", "by_year": "manufacture_year", "by_mileage": "km decile",
                   "depreciation": "brand", "platform_gap": "source_platform"}
    markdown = [f"# Week-2 EDA — `{path.name}`", "",
                f"{len(frame):,} listings, {len(usable):,} with an asking price. "
                "Generated by `python -m src.data_prep.eda`; every number below is reproducible.",
                ""]
    for key, title, note in SECTIONS:
        table = tables[key]
        print(f"\n## {title}")
        if table.empty:
            print("  (not enough matched rows in this snapshot)")
            markdown.extend([f"## {title}", "", "_Not enough matched rows in this snapshot._", ""])
            continue
        body = _md_table(table, index_names[key])
        print(body)
        print(f"  note: {note}")
        markdown.extend([f"## {title}", "", body, "", f"_{note}_", ""])

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eda_summary.md").write_text("\n".join(markdown), encoding="utf-8")
    summary = {key: table.reset_index().to_dict(orient="records") for key, table in tables.items()}
    (out_dir / "eda_summary.json").write_text(
        json.dumps({"input": str(path), "rows": len(frame), "tables": summary},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n  tables: {out_dir / 'eda_summary.md'} (+ .json)")

    if not args.no_figures:
        written = figures(usable, tables, out_dir)
        print(f"  figures: {', '.join(p.name for p in written.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



