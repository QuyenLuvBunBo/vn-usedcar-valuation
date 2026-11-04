"""Reproduce artifact checks: python -m tools.verify_phuong --train PATH."""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy import sparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=Path("data/master/train_features_full.csv"))
    parser.add_argument("--artifact", type=Path, default=Path("models/preprocess.joblib"))
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--encoded-dir", type=Path, default=Path("data/master"))
    parser.add_argument("--output", type=Path, default=Path("docs/artifact_verification.json"))
    args = parser.parse_args()
    p = joblib.load(args.artifact)
    train = pd.read_csv(args.train, low_memory=False)
    if args.cohort:
        from src.features.pipeline import attach_imputed
        train = attach_imputed(train, pd.read_csv(args.cohort, low_memory=False))
    variant = p.variant
    rows = pd.read_csv(args.encoded_dir / f"train_{variant}_oof_rows.csv")
    X = sparse.load_npz(args.encoded_dir / f"X_train_{variant}_oof.npz")
    names = p.get_feature_names_out().tolist()
    assert type(p).__module__ == "src.features.pipeline"
    assert X.shape == (len(train), len(names))
    assert np.isfinite(X.data).all()
    assert rows.listing_id.equals(train.listing_id)
    assert rows.duplicate_group_id.equals(train.duplicate_group_id)
    assert rows.groupby("duplicate_group_id").fold.nunique().max() == 1
    np.testing.assert_allclose(rows.y_log, np.log1p(train.price_vnd))
    assert p.build_metadata_["training_sha256"] == hashlib.sha256(args.train.read_bytes()).hexdigest()
    keys = train[["brand", "model"]].copy()
    for c in keys:
        keys[c] = keys[c].astype("string").str.strip().fillna("__MISSING__").replace("", "__MISSING__")
    keys["y"] = np.log1p(train.price_vnd)
    actual = X[:, names.index("target__brand_model_log")].toarray().ravel()
    max_error = 0.0
    for fold in sorted(rows.fold.unique()):
        held = rows.fold.eq(fold).to_numpy()
        learn = keys.loc[~held]
        stats = learn.groupby(["brand", "model"]).y.agg(["sum", "count"])
        prior = learn.y.mean()
        stats["expected"] = (stats["sum"] + p.smoothing * prior) / (stats["count"] + p.smoothing)
        expected = keys.loc[held, ["brand", "model"]].merge(
            stats[["expected"]], how="left", on=["brand", "model"], sort=False
        ).expected.fillna(prior).to_numpy()
        np.testing.assert_allclose(actual[held], expected, rtol=1e-12, atol=1e-12)
        max_error = max(max_error, float(np.max(np.abs(actual[held] - expected))))
    before = joblib.hash(p)
    probe = train.iloc[:3].copy()
    probe.loc[probe.index[0], ["brand", "model"]] = ["unseen-brand", "unseen-model"]
    probe.loc[probe.index[1], "engine_capacity"] = np.nan
    transformed = p.transform(probe)
    assert np.isfinite(transformed.data).all()
    assert transformed[0, names.index("target__brand_model_log")] == p.target_encoder_.global_mean_
    assert before == joblib.hash(p)
    assert all(not any(c in n for c in ["price_vnd", "listing_id", "duplicate_group_id"]) for n in names)
    assert p.transform(train.iloc[:0]).shape == (0, len(names))
    report = {
        "training_rows": len(train), "duplicate_groups": int(train.duplicate_group_id.nunique()),
        "output_features": X.shape[1], "stored_matrix_finite": True,
        "row_order_matches_input": True, "data_hash_matches": True,
        "all_folds_group_disjoint": True, "oof_values_independently_verified_rows": len(train),
        "max_absolute_oof_error": max_error,
        "fresh_process_joblib_load": True, "importable_class_module": type(p).__module__,
        "unknown_pair_fallback": "training global log-target mean",
        "transform_does_not_mutate_fitted_state": True, "empty_input_supported": True,
        "validation_evaluated": False, "test_evaluated": False,
        "missing_flags_mode": p.missing_mode_,
        "remaining_input": None if p.missing_mode_ == "per_column" else "original listing_id,imputed from training cohort",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
