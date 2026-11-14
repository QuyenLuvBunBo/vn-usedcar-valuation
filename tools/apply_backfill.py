"""Build the v2 cohort: v1 plus the fields the backfill actually observed — nothing else moves.

Two sources of new cells, both **fill-only**:

1. `data/processed/bonbanh_backfill.csv` — the patch from `tools/backfill_bonbanh.py`
   (`engine_capacity`, `seller_type`, `body_type`, with the salon/engine parsed from the page).
2. `sub_model_trim` derived from the `model` string we already have. A bonbanh title is
   `brand + model + trim` ("Hyundai Custin Cao Cấp 2.0T"), so when v1's trim is blank and the model
   contains a tier word, the trim is the part of the model that is not the canonical model. This needs
   no request and no statistic — it is a deterministic split of an existing string, and it is recorded
   as `model_trim` in `v2_filled`.

Hard rules, asserted at the end of the run:

* the row count and the `listing_id` order are identical to v1 (the split does not move);
* `price_vnd`, `mileage_km`, `brand`, `model`, `manufacture_year` are byte-identical to v1;
* a field is replaced only when v1 has no observation of it (blank / Unknown / listed in `imputed`);
* `imputed` loses the columns that are now observed, and `v2_filled` records where each new cell came
  from, so nothing can silently pass a statistic off as data.

Run:
    python -m tools.apply_backfill --write
    python -m tools.apply_backfill --patch data/processed/bonbanh_backfill.csv --out-dir data/master/v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.features.extend import canonical_model, trim_rank  # noqa: E402

SPLITS = ("train", "val", "test")
TARGET = "price_vnd"
UNTOUCHABLE = ("listing_id", "source_url", "brand", "model", "manufacture_year", "mileage_km",
               TARGET, "scraped_at", "listing_date", "raw_price_text", "price_status",
               "source_platform", "location_province", "tier", "duplicate_group_id",
               "quality_flags")
PATCH_FIELDS = ("engine_capacity", "seller_type", "body_type")
BLANK = ("", "nan", "none", "unknown")


def load_cohort(split: str) -> pd.DataFrame:
    path = config.DATA_MASTER / f"{split}_cohort_imputed.csv"
    frame = pd.read_csv(path, low_memory=False)
    frame["listing_id"] = frame["listing_id"].astype(str)
    return frame


def load_patch(path: Path) -> dict[str, dict]:
    """Only rows that actually filled something; a captcha row has `filled` empty."""
    if not path.exists():
        print(f"  no patch at {path} — the v2 build will carry only the offline trim")
        return {}
    frame = pd.read_csv(path, low_memory=False)
    frame = frame[frame["filled"].notna() & (frame["filled"].astype(str) != "")]
    return {str(row["listing_id"]): row for _, row in frame.iterrows()}


def derive_trim(model: str | None) -> str | None:
    """The part of `model` that is not the canonical model, when it carries a tier word."""
    text = str(model or "").strip()
    if not text or trim_rank(None, text) == "unknown":
        return None
    canonical = set(canonical_model(text).split())
    leftover = [token for token in text.casefold().split() if token not in canonical]
    return " ".join(leftover) or None


def apply_patch(frame: pd.DataFrame, patch: dict[str, dict]) -> tuple[pd.DataFrame, dict]:
    """Fill only what v1 does not observe, and record the provenance per row."""
    out = frame.copy()
    history = out["imputed"].fillna("").astype(str)
    filled_sets = [set(part for part in cell.split(";") if part) for cell in history]
    provenance: list[str] = ["" for _ in range(len(out))]
    counts = {field: 0 for field in PATCH_FIELDS}
    counts["sub_model_trim"] = 0

    for position, row in enumerate(out.itertuples(index=False)):
        listing = str(getattr(row, "listing_id"))
        sources: list[str] = []
        record = patch.get(listing)
        if record is not None:
            for field in PATCH_FIELDS:
                value = record.get(field)
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    continue
                blank = str(getattr(row, field) or "").strip().casefold() in BLANK
                if not (blank or field in filled_sets[position]):
                    continue
                out.at[out.index[position], field] = value
                filled_sets[position].discard(field)
                counts[field] += 1
                sources.append(f"bonbanh_detail:{field}")
        if str(getattr(row, "source_platform")) == "bonbanh":
            trim = str(getattr(row, "sub_model_trim") or "").strip()
            if trim.casefold() in BLANK:
                derived = derive_trim(getattr(row, "model"))
                if derived:
                    out.at[out.index[position], "sub_model_trim"] = derived
                    counts["sub_model_trim"] += 1
                    sources.append("model_trim")
        provenance[position] = ";".join(sources)

    out["imputed"] = [";".join(sorted(parts)) for parts in filled_sets]
    out["v2_filled"] = provenance
    return out, counts


def assert_invariants(before: pd.DataFrame, after: pd.DataFrame, split: str) -> None:
    """The split must not move, and no observed value may be overwritten."""
    if len(before) != len(after):
        raise SystemExit(f"{split}: row count changed {len(before)} -> {len(after)}")
    if before["listing_id"].tolist() != after["listing_id"].tolist():
        raise SystemExit(f"{split}: listing_id order changed")
    for column in UNTOUCHABLE:
        if column not in before.columns:
            continue
        left = before[column].astype(str).fillna("")
        right = after[column].astype(str).fillna("")
        if not left.equals(right):
            raise SystemExit(f"{split}: column {column!r} changed — fill-only was violated")
    allowed = {"engine_capacity", "seller_type", "body_type", "sub_model_trim", "imputed", "v2_filled"}
    touched = {column for column in before.columns
               if not before[column].astype(str).fillna("").equals(after[column].astype(str).fillna(""))}
    unexpected = touched - allowed
    if unexpected:
        raise SystemExit(f"{split}: unexpected columns changed: {sorted(unexpected)}")


def write_doc(doc: Path, payload: dict) -> None:
    counts = payload["counts"]
    lines = [
        "# v2 snapshot — what the backfill actually observed",
        "",
        f"Generated {payload['generated_at']} by `python -m tools.apply_backfill --write`.",
        f"Patch: `{payload['patch'] or 'none — no page was fetched'}`.",
        "",
        "**v1 is untouched**: the same rows, the same `listing_id` order, the same split and byte-identical",
        "`price_vnd`, `mileage_km`, `brand`, `model`, `manufacture_year` (asserted in the code, not by eye).",
        "",
        "| Split | Rows | engine_capacity | seller_type | body_type | sub_model_trim |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split, block in counts.items():
        lines.append(f"| {split} | {block['rows']:,} | {block['engine_capacity']:,} | "
                     f"{block['seller_type']:,} | {block['body_type']:,} | "
                     f"{block['sub_model_trim']:,} |")
    lines += ["", "## Where the new cells come from", "",
              "- `bonbanh_detail:<field>` — parsed from the live detail page by "
              "`tools/backfill_bonbanh.py` (engine displacement from \"Động cơ\", the salon subdomain for "
              "`seller_type`, \"Kiểu dáng\" for `body_type`).",
              "- `model_trim` — the trim text derived from the `model` string we already had. A bonbanh "
              "title is `brand + model + trim`; the trim is what is left after the canonical model, and "
              "it is only written when the model contains a tier word. No request, no statistic.",
              "",
              "`imputed` loses every column that is now observed, so a downstream tool can still tell a "
              "crawled value from an imputed one, and `v2_filled` says which is which per row.", "",
              "## Status of the bonbanh crawl", "",
              payload["crawl_note"], ""]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the v2 cohort (fill-only) from v1 + a patch")
    parser.add_argument("--patch", default="data/processed/bonbanh_backfill.csv")
    parser.add_argument("--out-dir", default=str(config.DATA_MASTER / "v2"))
    parser.add_argument("--report", default=str(config.DATA_MASTER / "v2" / "data_quality_v2.json"))
    parser.add_argument("--doc", default="docs/data_quality_v2.md")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    patch_path = Path(args.patch)
    if not patch_path.is_absolute():
        patch_path = config.ROOT / patch_path
    patch = load_patch(patch_path)
    out_dir = Path(args.out_dir)
    print(f"patch rows with a filled field: {len(patch):,}")

    counts = {}
    for split in SPLITS:
        before = load_cohort(split)
        after, block = apply_patch(before, patch)
        assert_invariants(before, after, split)
        block["rows"] = int(len(after))
        counts[split] = block
        print(f"  {split:6s} rows {len(after):>7,}  engine {block['engine_capacity']:>5,}  "
              f"seller {block['seller_type']:>5,}  body {block['body_type']:>4,}  "
              f"trim {block['sub_model_trim']:>6,}")
        if args.write:
            out_dir.mkdir(parents=True, exist_ok=True)
            after.to_csv(out_dir / f"{split}_cohort_imputed.csv", index=False, lineterminator="\n")

    payload = {"generated_at": config.now_iso(), "patch": str(patch_path) if patch else "",
               "counts": counts,
               "crawl_note": ("The crawler (`tools/backfill_bonbanh.py`) is resumable and soft-block "
                              "aware: bonbanh answered a 200 captcha page after ~2,100 concurrent "
                              "requests, so the run stopped and recorded nothing for those rows "
                              "(`docs/recon_decision.md` §3). Re-running the command picks up exactly "
                              "where it stopped.")}
    if args.write:
        Path(args.report).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8", newline="\n")
        doc = (Path(args.doc) if Path(args.doc).is_absolute()
               else Path(__file__).resolve().parents[1] / args.doc)
        write_doc(doc, payload)
        print(f"\n  cohort -> {out_dir}\n  report -> {args.report}\n  doc    -> {doc}")
    else:
        print("  dry run — pass --write to create the v2 cohort")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

