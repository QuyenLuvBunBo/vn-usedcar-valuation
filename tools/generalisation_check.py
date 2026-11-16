"""Leave-`brand|model`-out stress test: what happens to the score on a car the model never saw?

`docs/benchmark.md` reports R² 0.947 on val, but 97.75 % of the val rows are a `brand|model` that also
exists in train, so that number measures *interpolation inside a known nameplate*. This tool holds out
a share of the nameplates, retrains, and reports three slices of the same val split:

    val-seen-combos      val rows whose brand|model is still in the training set
    val-heldout-combos   val rows whose brand|model was deliberately removed
    val-unseen-combos    val rows whose brand|model never existed in train at all

**Leakage rules, because hiding a group is easy to get wrong:**

1. The hold-out is chosen from `brand|model` strings and row counts only — never from the price.
2. Price-derived features (`brand_retention_rate`, `province_price_index`) are **dropped** by default:
   they were fitted on the full train partition, so they would carry information *about* the hidden
   nameplates into the model. (They contribute ΔR² 0.0000 anyway — `docs/features_ablation.md` — so the
   test loses nothing; `--keep-price-stats` is available to prove that.)
3. No imputation or target encoding is fitted by this tool: the estimator is LightGBM on the frozen
   feature table, with `model` as a native categorical.

Run:
    python -m tools.generalisation_check
    python -m tools.generalisation_check --features v2 --share 0.30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.models import common  # noqa: E402

PRICE_STATS = ("brand_retention_rate", "province_price_index")
PARAMS = dict(n_estimators=300, learning_rate=0.06, num_leaves=63, min_child_samples=40,
              random_state=42, n_jobs=-1, verbose=-1)


def combo_key(frame: pd.DataFrame) -> pd.Series:
    """`brand|model` as a plain string — the only thing the hold-out is allowed to look at."""
    return frame["brand"].astype(str) + "|" + frame["model"].astype(str)


def select_holdout(train: pd.DataFrame, share: float = 0.20, seed: int = 42) -> set[str]:
    """Deterministically pick combos covering `share` of the training rows. Price is never read."""
    key = combo_key(train)
    counts = key.value_counts()
    order = np.random.RandomState(seed).permutation(counts.index.to_numpy())
    held, rows = set(), 0
    for combo in order:
        if rows >= share * len(train):
            break
        held.add(str(combo))
        rows += int(counts[combo])
    return held


def load(features: str, split: str, drop_price_stats: bool = True) -> pd.DataFrame:
    if features == "v2":
        path = config.DATA_MASTER / "v2" / f"{split}_features_full.csv"
        if not path.exists():
            raise SystemExit(f"missing {path} -> run 'python -m src.features.extend --write'")
        frame = pd.read_csv(path, low_memory=False)
        frame["listing_id"] = frame["listing_id"].astype(str)
    else:
        frame = common.load_split("full", split)
    if drop_price_stats:
        frame = frame.drop(columns=[c for c in PRICE_STATS if c in frame.columns])
    return frame


def fit_score(train: pd.DataFrame, slices: dict[str, pd.DataFrame]) -> dict[str, dict]:
    import lightgbm as lgb

    xtr, ytr = common.split_xy(train)
    prepared = {}
    for name, frame in slices.items():
        x, _ = common.split_xy(frame)
        prepared[name] = (frame, common.align_categories(xtr.copy(), x)[1])
    model = lgb.LGBMRegressor(**PARAMS)
    categorical = [c for c in xtr.columns if isinstance(xtr[c].dtype, pd.CategoricalDtype)]
    model.fit(xtr, np.log(ytr.to_numpy(dtype=float)), categorical_feature=categorical)
    out = {}
    for name, (frame, x) in prepared.items():
        out[name] = {**common.metrics(frame["price_vnd"], np.exp(model.predict(x))),
                     "rows": int(len(frame))}
    return out



def write_doc(doc: Path, payload: dict) -> None:
    def row(name: str, block: dict) -> str:
        return (f"| {name} | {block['rows']:,} | {block['r2_log']:.4f} | {block['mape']:.4f} | "
                f"{block['median_ape']:.4f} |")

    lines = [
        "# Generalisation — what the score looks like on a nameplate the model never saw",
        "",
        f"Generated {payload['generated_at']} by `python -m tools.generalisation_check` "
        f"(features `{payload['features']}`, share {payload['share']:.0%}, seed {payload['seed']}).",
        "",
        f"**{payload['heldout_combos']:,} `brand|model` levels ({payload['heldout_rows']:,} train rows, "
        f"{payload['heldout_share']:.1%} of train) were removed from training.** The estimator is a "
        f"fixed LightGBM ({PARAMS['n_estimators']} trees); nothing else changed.",
        "",
        f"Price-derived features dropped: **{payload['price_stats_dropped']}** "
        f"(`brand_retention_rate`, `province_price_index`) — they were fitted on the full train "
        f"partition, so on a leave-combo-out test they would carry information about the hidden "
        f"nameplates. The hold-out itself is chosen from `brand|model` strings and row counts only.",
        "",
        "| Slice of the val split | Rows | R²(log) | MAPE | median APE |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, block in payload["slices"].items():
        lines.append(row(name, block))
    lines += ["", f"Reference — the same estimator trained on **all** train rows, scored on all "
              f"{payload['reference']['rows']:,} val rows: R²(log) "
              f"{payload['reference']['r2_log']:.4f}, MAPE {payload['reference']['mape']:.4f}.", "",
              "## Reading", "",
              "- The reference is scored on **all** val rows, including the hard slices below, so it is "
              "lower than `val-seen-combos`: that gap is composition, not damage. Compare the slices with "
              "each other.",
              "- `val-seen-combos` is the honest version of the headline number for a nameplate the model "
              "knows.",
              "- `val-heldout-combos` is the stress test: no row of that nameplate was ever in training.",
              "- `val-unseen-combos` is the strongest test in the snapshot — those nameplates are absent "
              "from train even before the hold-out.",
              "- The drop is **not** a bug: a used-car price is largely a nameplate-and-age lookup "
              "(`docs/data_limitations.md`), and a model that has never seen the nameplate can only use "
              "segment-level signals (engine, body, year, platform).",
              "- `--features v2` repeats the same test on the extended table (engine parsed from the "
              "badge, trim rank, canonical model), which is where a better generalisation would show up "
              "first.", ""]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leave-brand|model-out stress test")
    parser.add_argument("--features", default="v1", choices=("v1", "v2"))
    parser.add_argument("--share", type=float, default=0.20, help="share of TRAIN ROWS to hold out")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--keep-price-stats", action="store_true",
                        help="keep brand_retention_rate / province_price_index (they were fitted on all "
                             "train rows, so this is the leaking variant — for comparison only)")
    parser.add_argument("--out", default=str(config.DATA_MASTER / "generalisation.json"))
    parser.add_argument("--doc", default="docs/generalisation.md")
    args = parser.parse_args(argv)

    drop = not args.keep_price_stats
    train = load(args.features, "train", drop)
    val = load(args.features, "val", drop)

    held = select_holdout(train, args.share, args.seed)
    key_train = combo_key(train)
    key_val = combo_key(val)
    keep = (~key_train.isin(held)).to_numpy()
    unseen = (~key_val.isin(set(key_train))).to_numpy()
    heldout = key_val.isin(held).to_numpy()

    slices = {
        "val-seen-combos": val[~unseen & ~heldout],
        "val-heldout-combos": val[heldout],
        "val-unseen-combos": val[unseen],
    }
    print(f"holding out {len(held):,} combos = {int((~keep).sum()):,} train rows "
          f"({(~keep).mean():.1%})")
    for name, frame in slices.items():
        print(f"  {name:22s} {len(frame):>6,} rows")

    started = time.monotonic()
    scores = fit_score(train[keep], slices)
    print(f"  fit + score in {time.monotonic() - started:.0f}s")

    reference = fit_score(train, {"val": val})["val"]
    payload = {
        "generated_at": config.now_iso(),
        "features": args.features,
        "share": args.share,
        "seed": args.seed,
        "price_stats_dropped": drop,
        "heldout_combos": int(len(held)),
        "heldout_rows": int((~keep).sum()),
        "heldout_share": round(float((~keep).mean()), 4),
        "slices": scores,
        "reference": reference,
        "note": "hold-out chosen from brand|model strings and row counts only; no price is read",
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    doc = (Path(args.doc) if Path(args.doc).is_absolute()
           else Path(__file__).resolve().parents[1] / args.doc)
    write_doc(doc, payload)
    for name, block in scores.items():
        print(f"  {name:22s} R2 {block['r2_log']:.4f}  MAPE {block['mape']:.4f}")
    print(f"  reference (all train)   R2 {reference['r2_log']:.4f}  MAPE {reference['mape']:.4f}")
    print(f"\n  json -> {args.out}\n  doc  -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
