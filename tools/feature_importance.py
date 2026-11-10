"""Gain-based feature importance for the LightGBM point model -> data/master/feature_importance.csv.

Report §4/§6 quote this table. One command, no notebook, so every number in the report can be
regenerated from the repository:

    python -m tools.feature_importance                     # models/lgbm_full.joblib
    python -m tools.feature_importance --model catboost     # models/catboost_full.joblib

LightGBM reports *gain* (total split improvement the feature earned, normalized to sum to 1),
which is the attribution the report table uses. Permutation importance is a separate, slower
study owned by Duy; this tool deliberately does not try to replace it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LightGBM gain importance -> feature_importance.csv")
    parser.add_argument("--model", default="lgbm", help="model name as saved by src/models/train.py")
    parser.add_argument("--features", default="full", choices=("minimal", "full"))
    args = parser.parse_args(argv)

    import joblib

    artifact_path = config.ROOT / "models" / f"{args.model}_{args.features}.joblib"
    if not artifact_path.exists():
        raise SystemExit(f"missing {artifact_path} -> run 'python -m src.models.train --model "
                         f"{args.model} --features {args.features}' first")
    artifact = joblib.load(artifact_path)

    if args.model == "lgbm":
        booster = artifact["model"].booster_
        names = booster.feature_name()
        gain = booster.feature_importance(importance_type="gain")
    elif args.model == "catboost":
        booster = artifact["model"]
        names = [feature for feature in booster.feature_names_]
        gain = booster.get_feature_importance()
    else:
        raise SystemExit(f"no importance extractor for {args.model!r} — use lgbm or catboost")

    frame = pd.DataFrame({"feature": names, "importance_gain": gain})
    frame["share"] = frame["importance_gain"] / frame["importance_gain"].sum()
    frame = frame.sort_values("importance_gain", ascending=False).reset_index(drop=True)
    frame["rank"] = frame.index + 1

    out = config.DATA_MASTER / "feature_importance.csv"
    frame.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"{'rank':>4s} {'feature':28s} {'share':>8s}")
    for row in frame.head(15).itertuples():
        print(f"{row.rank:>4d} {row.feature:28s} {row.share:>8.4f}")
    print(f"\n  wrote {out} ({len(frame)} features, model {args.model}/{args.features})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
