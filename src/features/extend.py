"""Feature extension (v2): parse more engine displacement, add a trim rank, canonicalise the model.

`build_features.py` already emits the v1 table and stays untouched: v1 must keep its hashes, because
every number in the week-3 report was computed on it. This module writes **new** files beside it:

    data/master/v2/{train,val,test}_features_full.csv
    data/master/v2/features_v2_report.json
    docs/features_v2.md

What it adds, and why:

* `engine_capacity_parsed` — the v1 column is missing on 61 % of rows; when the site does not publish
  it, the model string often does ("Custin Cao Cấp 2.0T", "Accent Cao cấp 1.5 AT"). A deterministic
  parse (the same `ENGINE_RE` the imputation uses) rescues ~900 train rows without inventing a number.
* `trim_rank` ∈ {base, mid, top, unknown} — the tier word inside `sub_model_trim` or `model`. Trim is
  the feature that separates an LX from an EX, and v1 never used it at all.
* `trim_missing` — an indicator, because 55.7 % of the rows have no trim and the model must know that
  "unknown" is not "base".
* `model_canonical` — the model with variant tokens stripped, so `Custin Cao Cấp 2.0T` and
  `Custin` become one level (3,351 → ~2,500 levels, i.e. thicker groups). The original `model` column
  is kept for comparison, never replaced.
* `variant_tokens` / `variant_count` — the tokens that were stripped, kept as text so the information
  is available to a model that wants it.

**No statistic is fitted here.** Every column is a function of its own row, so nothing can leak from
val into train. Anything that needs a group statistic (a median, a target encoding) belongs in
`src/features/pipeline.py`, which fits inside the training fold.

Run:
    python -m src.features.extend --write
    python -m src.features.extend --variant full --out-dir data/master/v2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import config  # noqa: E402
from src.data_prep.missing import ENGINE_RE  # noqa: E402

SPLITS = ("train", "val", "test")
TARGET = "price_vnd"
NEW_COLUMNS = ("engine_capacity_parsed", "engine_parsed", "trim_rank", "trim_missing",
               "model_canonical", "variant_tokens", "variant_count")

# Tier words, checked in this order; the first hit wins. Accented and unaccented spellings both occur.
TOP_WORDS = ("cao cấp", "cao cap", "đặc biệt", "dac biet", "signature", "executive", "luxury",
             "premium", "platinum", "ultimate", "gt line", "gt-line", "full option")
MID_WORDS = ("plus", "sport", "style", "comfort", "elegance", "deluxe", "limited", "pro", "turbo")
BASE_WORDS = ("tiêu chuẩn", "tieu chuan", "base", "standard", "entry", "số sàn", "so san")

GEARBOX_RE = re.compile(r"(?<![a-z])(\d{0,2})(at|mt|cvt|dct|dsg|tiptronic)(?![a-z])", re.I)
DRIVE_RE = re.compile(r"(?<![a-z0-9])(4wd|awd|2wd|fwd|4x4|rwd)(?![a-z0-9])", re.I)
FUEL_RE = re.compile(r"(?<![a-z])(hybrid|diesel|phev|ev|electric)(?![a-z])", re.I)
YEAR_RE = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")
DISPLACEMENT_RE = re.compile(r"(?<![\d.,])([1-6][.,]\d)\s*(t|d|i|l|gdi|vvt|turbo)?(?![a-z0-9])", re.I)
SPACES_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[\s,;|/]+")
MIN_ENGINE, MAX_ENGINE = 0.6, 8.0   # outside this range a "displacement" is a model number, not litres


def parse_engine(text: str | None) -> float | None:
    """First plausible displacement in a free-text badge ('2.5Q' -> 2.5, 'RX 300' -> None)."""
    if not text:
        return None
    for match in ENGINE_RE.finditer(str(text)):
        value = float(match.group(1).replace(",", "."))
        if MIN_ENGINE <= value <= MAX_ENGINE:
            return value
    return None


def fill_engine(row_engine, *texts) -> tuple[float | None, bool]:
    """`(value, parsed)` — keep the site's number, otherwise parse the badges."""
    try:
        value = float(row_engine)
        if value > 0:
            return value, False
    except (TypeError, ValueError):
        pass
    for text in texts:
        parsed = parse_engine(text)
        if parsed is not None:
            return parsed, True
    return None, False


def trim_rank(trim: str | None, model: str | None = None) -> str:
    """base / mid / top / unknown from the tier word, trim column first then the model string."""
    for text in (trim, model):
        haystack = str(text or "").casefold()
        if not haystack.strip():
            continue
        for words, rank in ((TOP_WORDS, "top"), (MID_WORDS, "mid"), (BASE_WORDS, "base")):
            if any(word in haystack for word in words):
                return rank
    return "unknown"


def variant_tokens(model: str | None, trim: str | None = None) -> str:
    """Technical tokens that carry information but break a model name into levels (sorted, unique)."""
    text = " ".join(str(value or "") for value in (trim, model)).casefold()
    tokens: list[str] = []
    for match in DISPLACEMENT_RE.finditer(text):
        suffix = (match.group(2) or "").lower()
        tokens.append(match.group(1).replace(",", ".") + suffix)
    for match in GEARBOX_RE.finditer(text):
        tokens.append((match.group(1) or "") + match.group(2).lower())
    for match in DRIVE_RE.finditer(text):
        tokens.append(match.group(1).lower())
    for match in FUEL_RE.finditer(text):
        tokens.append(match.group(1).lower())
    return ";".join(sorted(set(tokens)))


def canonical_model(model: str | None) -> str:
    """The model name without tier words, displacement, gearbox, drive, fuel or a model year.

    Conservative on purpose: it only removes tokens that are clearly variants, so `CX-5`, `VF 8` and
    `S Class` survive. Anything left over (a single-letter trim code such as `2.5Q` -> `q`) is kept,
    and the original `model` column travels beside this one so nothing is lost.
    """
    text = str(model or "").casefold()
    for word in sorted(set(TOP_WORDS) | set(MID_WORDS) | set(BASE_WORDS), key=len, reverse=True):
        text = text.replace(word, " ")
    text = DISPLACEMENT_RE.sub(" ", text)
    text = GEARBOX_RE.sub(" ", text)
    text = DRIVE_RE.sub(" ", text)
    text = FUEL_RE.sub(" ", text)
    text = YEAR_RE.sub(" ", text)
    text = PUNCT_RE.sub(" ", text).strip()
    text = SPACES_RE.sub(" ", text)
    return text or "unknown"


# ------------------------------------------------------------------ building
def load_split(split: str, variant: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The frozen cohort (for `sub_model_trim` + the imputation history) and the v1 feature table."""
    cohort_path = config.DATA_MASTER / f"{split}_cohort_imputed.csv"
    features_path = config.DATA_MASTER / f"{split}_features_{variant}.csv"
    for path in (cohort_path, features_path):
        if not path.exists():
            raise SystemExit(f"missing {path} -> run 'python -m src.data_prep.pipeline' and "
                             f"'python -m src.features.build_features --features {variant}' first")
    cohort = pd.read_csv(cohort_path, low_memory=False)
    features = pd.read_csv(features_path, low_memory=False)
    cohort["listing_id"] = cohort["listing_id"].astype(str)
    features["listing_id"] = features["listing_id"].astype(str)
    return cohort, features


def extend_split(cohort: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Append the v2 columns to a copy of the v1 table, row order untouched."""
    lookup = cohort.set_index("listing_id")
    missing = [name for name in features["listing_id"] if name not in lookup.index]
    if missing:
        raise SystemExit(f"{len(missing)} feature rows are absent from the cohort, e.g. {missing[0]}")

    aligned = lookup.reindex(features["listing_id"])
    trim = aligned["sub_model_trim"].to_numpy()
    model = aligned["model"].to_numpy() if "model" in aligned else features["model"].to_numpy()
    imputed = aligned["imputed"].fillna("").astype(str).to_numpy()

    engines = []
    parsed_flags = []
    for raw, row_trim, row_model, history in zip(aligned["engine_capacity"].to_numpy(), trim, model,
                                                 imputed):
        was_imputed = "engine_capacity" in [part for part in history.split(";") if part]
        try:
            site_value = float(raw)
        except (TypeError, ValueError):
            site_value = None
        if site_value is not None and (pd.isna(site_value) or site_value <= 0):
            site_value = None
        if site_value is not None and not was_imputed:
            engines.append(site_value)
            parsed_flags.append(False)
            continue
        value, parsed = fill_engine(None, row_trim, row_model)
        if value is None:
            engines.append(site_value)          # keep the imputed number rather than inventing a gap
            parsed_flags.append(False)
        else:
            engines.append(value)
            parsed_flags.append(parsed)

    out = features.copy()
    out["engine_capacity_parsed"] = engines
    out["engine_parsed"] = parsed_flags
    out["trim_rank"] = [trim_rank(row_trim, row_model) for row_trim, row_model in zip(trim, model)]
    out["trim_missing"] = [not str(value).strip() or str(value).lower() in ("nan", "none")
                           for value in trim]
    out["model_canonical"] = [canonical_model(value) for value in model]
    out["variant_tokens"] = [variant_tokens(row_model, row_trim) for row_model, row_trim in zip(model, trim)]
    out["variant_count"] = [len([token for token in value.split(";") if token])
                            for value in out["variant_tokens"]]
    return out


# ------------------------------------------------------------------- report
def summarise(parts: dict[str, pd.DataFrame], variant: str) -> dict:
    """Counts a reader can re-derive: what each new column bought, per split."""
    report = {"generated_at": config.now_iso(), "variant": variant, "new_columns": list(NEW_COLUMNS),
              "note": "stateless columns only — no statistic is fitted here", "splits": {}}
    for split, frame in parts.items():
        report["splits"][split] = {
            "rows": int(len(frame)),
            "engine_parsed_from_text": int(frame["engine_parsed"].sum()),
            "engine_available_after": int(frame["engine_capacity_parsed"].notna().sum()),
            "trim_rank": {str(k): int(v) for k, v in frame["trim_rank"].value_counts().items()},
            "trim_missing_rate": round(float(frame["trim_missing"].mean()), 4),
            "model_levels_before": int(frame["model"].nunique()),
            "model_levels_after": int(frame["model_canonical"].nunique()),
            "variant_tokens_top": {str(k): int(v) for k, v in
                                   frame.loc[frame["variant_tokens"] != "", "variant_tokens"]
                                   .value_counts().head(8).items()},
        }
    return report


def write_doc(doc: Path, report: dict, variant: str) -> None:
    lines = [
        "# Feature extension (v2) — engine parsed from text, trim rank, canonical model",
        "",
        f"Generated {report['generated_at']} by `python -m src.features.extend --write` "
        f"(variant `{variant}`). v1 tables are **not** modified: the v2 tables live in "
        f"`data/master/v2/` so every week-3 number stays reproducible.",
        "",
        "All four columns are **stateless** — each is a function of its own row — so nothing can leak "
        "from validation into training. Group statistics (medians, target encoding) stay in "
        "`src/features/pipeline.py`, which fits them inside the training fold.",
        "",
        "| Split | Rows | Engine parsed from text | Engine available after | Trim missing | "
        "Model levels before → after |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split, block in report["splits"].items():
        lines.append(f"| {split} | {block['rows']:,} | {block['engine_parsed_from_text']:,} | "
                     f"{block['engine_available_after']:,} | {block['trim_missing_rate']:.1%} | "
                     f"{block['model_levels_before']:,} → {block['model_levels_after']:,} |")
    lines += ["", "## trim_rank", "",
              "| Split | base | mid | top | unknown |", "| --- | ---: | ---: | ---: | ---: |"]
    for split, block in report["splits"].items():
        ranks = block["trim_rank"]
        lines.append(f"| {split} | {ranks.get('base', 0):,} | {ranks.get('mid', 0):,} | "
                     f"{ranks.get('top', 0):,} | {ranks.get('unknown', 0):,} |")
    lines += ["", "## Reading", "",
              "- `engine_capacity_parsed` keeps the site's value unless the column was **imputed**; only "
              "then is the badge parsed. A parsed value is a fact from the listing text, not a median.",
              "- `trim_missing` is an indicator, not a fill: 55 % of the rows have no trim, and "
              "\"unknown\" must not be read as \"base\".",
              "- `model_canonical` merges variant spellings; the original `model` column is kept "
              "beside it so any merge can be audited row by row.",
              "- `variant_tokens` keeps what was stripped (displacement, gearbox, drive, fuel) so a "
              "model that wants it does not lose the information.", ""]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the v2 feature tables beside the frozen v1")
    parser.add_argument("--variant", default="full", choices=("minimal", "full"))
    parser.add_argument("--out-dir", default=str(config.DATA_MASTER / "v2"))
    parser.add_argument("--report", default=str(config.DATA_MASTER / "v2" / "features_v2_report.json"))
    parser.add_argument("--doc", default="docs/features_v2.md")
    parser.add_argument("--write", action="store_true", help="write the CSVs (default: dry run)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    parts = {}
    for split in SPLITS:
        cohort, features = load_split(split, args.variant)
        parts[split] = extend_split(cohort, features)
        block = parts[split]
        print(f"{split:6s} rows {len(block):>7,}  parsed engine "
              f"{int(block['engine_parsed'].sum()):>5,}  trim top/mid/base "
              f"{int((block['trim_rank'] == 'top').sum()):>5,}/"
              f"{int((block['trim_rank'] == 'mid').sum()):>5,}/"
              f"{int((block['trim_rank'] == 'base').sum()):>5,}  models "
              f"{block['model'].nunique():>5,} -> {block['model_canonical'].nunique():>5,}")

    report = summarise(parts, args.variant)
    if args.write:
        out_dir.mkdir(parents=True, exist_ok=True)
        for split, frame in parts.items():
            path = out_dir / f"{split}_features_{args.variant}.csv"
            frame.to_csv(path, index=False, lineterminator="\n")
            print(f"  {path.name}: {len(frame):,} rows x {len(frame.columns)} columns")
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8", newline="\n")
        doc = (Path(args.doc) if Path(args.doc).is_absolute()
               else Path(__file__).resolve().parents[2] / args.doc)
        write_doc(doc, report, args.variant)
        print(f"  report -> {args.report}\n  doc    -> {doc}")
    else:
        print("  dry run — pass --write to create the v2 tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
