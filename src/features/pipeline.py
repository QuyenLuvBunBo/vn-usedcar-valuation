"""Phuong's week-3 preprocessing. Run from the repository root with -m.

fit_transform(X_train, y_log) returns group-held-out target encodings.
transform(X_val) applies the frozen full-training mappings. Do not use
transform(X_train) to train a model: that would use in-sample target means.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy import sparse
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.utils.validation import check_is_fitted

BASE_CAT = ["brand", "model", "model_group", "transmission", "fuel_type",
            "origin", "body_type", "seller_type", "source_platform"]
BASE_NUM = ["manufacture_year", "mileage_km", "engine_capacity", "seats"]
FULL_CAT = BASE_CAT + ["province_group", "age_band", "brand_age_band", "is_luxury_segment"]
FULL_NUM = BASE_NUM + ["vehicle_age", "km_per_year", "engine_per_seat", "n_imputed",
                      "brand_retention_rate", "province_price_index"]
PRICE_STATS = ["brand_retention_rate", "province_price_index"]
IMPUTED_FIELDS = ["body_type", "transmission", "fuel_type", "origin", "seller_type",
                  "seats", "mileage_km", "engine_capacity"]
AGE_ORDER = ["0-2", "3-5", "6-9", "10-14", "15+"]
MISSING = "__MISSING__"


def _require_frame(X):
    if not isinstance(X, pd.DataFrame):
        raise TypeError("Use a pandas DataFrame with named engineered feature columns.")
    if not X.columns.is_unique:
        raise ValueError("Input column names must be unique.")


def _strings(values):
    text = values.astype("string").str.strip()
    return text.mask(text.isna() | text.eq(""), MISSING).astype(str)


def _pair_keys(X):
    return list(zip(_strings(X["brand"]), _strings(X["model"])))


def _target(y, X):
    if y is None:
        raise ValueError("y_log is required: pass np.log1p(training price_vnd).")
    if isinstance(y, pd.Series) and not y.index.equals(X.index):
        raise ValueError("X and y indexes differ; align them before fitting.")
    values = np.asarray(y, dtype=float)
    if values.ndim != 1 or len(values) != len(X) or not np.isfinite(values).all():
        raise ValueError("y_log must be a finite 1D vector aligned with X.")
    return values


def _learn_means(keys, y, smoothing):
    global_mean = float(np.mean(y))
    stats = {}
    for key, value in zip(keys, y):
        total, count = stats.get(key, (0.0, 0))
        stats[key] = (total + float(value), count + 1)
    mapping = {key: (total + smoothing * global_mean) / (count + smoothing)
               for key, (total, count) in stats.items()}
    return global_mean, mapping


class GroupTargetEncoder(TransformerMixin, BaseEstimator):
    """Smoothed brand/model means; duplicate groups never cross internal folds."""

    def __init__(self, n_splits=5, smoothing=20.0, random_state=42):
        self.n_splits = n_splits
        self.smoothing = smoothing
        self.random_state = random_state

    def fit(self, X, y):
        _require_frame(X)
        if self.smoothing < 0 or self.n_splits < 2:
            raise ValueError("smoothing must be >= 0 and n_splits >= 2.")
        if len(X) == 0:
            raise ValueError("Training data is empty.")
        values = _target(y, X)
        self.global_mean_, self.mapping_ = _learn_means(_pair_keys(X), values, self.smoothing)
        self.n_samples_seen_ = len(X)
        return self

    def fit_transform(self, X, y=None, **fit_params):
        if fit_params:
            raise TypeError(f"Unexpected fit parameters: {sorted(fit_params)}")
        _require_frame(X)
        if "duplicate_group_id" not in X or X["duplicate_group_id"].isna().any():
            raise ValueError("Training requires nonmissing duplicate_group_id for grouped folds.")
        groups = _strings(X["duplicate_group_id"])
        if groups.eq(MISSING).any():
            raise ValueError("duplicate_group_id cannot be blank.")
        n_groups = groups.nunique()
        if n_groups < 2:
            raise ValueError("At least two duplicate groups are required for cross-fitting.")
        self.fit(X, y)
        values = _target(y, X)
        keys = _pair_keys(X)
        folds = GroupKFold(n_splits=min(self.n_splits, n_groups), shuffle=True,
                          random_state=self.random_state)
        group_codes, _ = pd.factorize(groups, sort=True)
        encoded = np.empty(len(X), dtype=float)
        self.oof_fold_ids_ = np.empty(len(X), dtype=int)
        self.fold_audit_ = []
        for fold, (train_idx, held_idx) in enumerate(folds.split(X, values, group_codes)):
            prior, mapping = _learn_means([keys[i] for i in train_idx], values[train_idx],
                                         self.smoothing)
            encoded[held_idx] = [mapping.get(keys[i], prior) for i in held_idx]
            self.oof_fold_ids_[held_idx] = fold
            overlap = set(groups.iloc[train_idx]) & set(groups.iloc[held_idx])
            if overlap:
                raise RuntimeError("Internal duplicate group leakage.")
            self.fold_audit_.append({
                "fold": fold, "train_rows": len(train_idx), "heldout_rows": len(held_idx),
                "train_groups": int(groups.iloc[train_idx].nunique()),
                "heldout_groups": int(groups.iloc[held_idx].nunique()),
                "group_overlap": 0, "global_mean_log": prior,
            })
        return encoded.reshape(-1, 1)

    def transform(self, X):
        check_is_fitted(self, "mapping_")
        _require_frame(X)
        return np.asarray([self.mapping_.get(k, self.global_mean_) for k in _pair_keys(X)],
                          dtype=float).reshape(-1, 1)

    def get_feature_names_out(self, input_features=None):
        return np.asarray(["target__brand_model_log"], dtype=object)


def attach_imputed(features, cohort):
    """One-to-one listing_id join; never align two files by row position."""
    for name, frame in [("features", features), ("cohort", cohort)]:
        if "listing_id" not in frame or frame.listing_id.isna().any():
            raise ValueError(f"{name} requires nonmissing listing_id.")
        if frame.listing_id.duplicated().any():
            raise ValueError(f"{name} contains duplicate listing_id values.")
    if "imputed" not in cohort:
        raise ValueError("Cohort lacks the original imputed column.")
    mapped = cohort.set_index("listing_id")["imputed"].fillna("")
    absent = ~features.listing_id.isin(mapped.index)
    if absent.any():
        raise ValueError(f"Cohort is missing {int(absent.sum())} feature listing IDs.")
    out = features.copy()
    out["imputed"] = out.listing_id.map(mapped)
    return out


class CarPreprocessor(TransformerMixin, BaseEstimator):
    """Model-independent transformer for already engineered minimal/full tables.

    Target-derived upstream price statistics are excluded by default because
    their fold-local provenance cannot be verified from a feature CSV.
    """

    def __init__(self, variant="full", max_onehot=40, n_splits=5, smoothing=20.0,
                 random_state=42, missing_policy="auto", include_frozen_price_stats=False):
        self.variant = variant
        self.max_onehot = max_onehot
        self.n_splits = n_splits
        self.smoothing = smoothing
        self.random_state = random_state
        self.missing_policy = missing_policy
        self.include_frozen_price_stats = include_frozen_price_stats

    def _validate(self, X):
        _require_frame(X)
        required = self.numeric_ + self.categorical_
        absent = [name for name in required if name not in X]
        if absent:
            raise ValueError(f"Missing engineered input columns: {absent}")
        if self.missing_mode_ == "per_column" and "imputed" not in X:
            raise ValueError("This artifact requires imputed flags; join the cohort by listing_id.")
        if self.missing_mode_ == "aggregate_only" and "n_imputed" not in X:
            raise ValueError("This artifact requires n_imputed at inference.")

    def _numeric(self, X):
        out = X[self.numeric_].apply(pd.to_numeric, errors="raise").astype(float)
        if np.isinf(out.to_numpy()).any():
            raise ValueError("Numeric input contains infinity; fix upstream feature generation.")
        return out

    def _cats(self, X):
        return pd.DataFrame({c: _strings(X[c]) for c in self.categorical_}, index=X.index)

    def _flags(self, X):
        if self.missing_mode_ == "per_column":
            tokens = [set(part.strip() for part in str(value).split(";") if part.strip())
                      for value in X["imputed"].fillna("")]
            unknown = set().union(*tokens) - set(IMPUTED_FIELDS) if tokens else set()
            if unknown:
                raise ValueError(f"Unrecognized imputed field names: {sorted(unknown)}")
            counts = np.asarray([len(row) for row in tokens], dtype=float)
            if "n_imputed" in X:
                supplied = pd.to_numeric(X.n_imputed, errors="raise").to_numpy(dtype=float)
                if not np.array_equal(supplied, counts):
                    raise ValueError("n_imputed does not match original imputed tokens.")
            fields = np.asarray([[float(c in row) for c in IMPUTED_FIELDS] for row in tokens])
            return np.column_stack([counts > 0, fields]).astype(float)
        if self.missing_mode_ == "aggregate_only":
            count = pd.to_numeric(X.n_imputed, errors="raise").to_numpy(dtype=float)
            if not np.isfinite(count).all() or (count < 0).any() or (count % 1 != 0).any():
                raise ValueError("n_imputed must contain finite nonnegative integers.")
            return (count > 0).astype(float).reshape(-1, 1)
        return np.empty((len(X), 0))

    def fit(self, X, y):
        _require_frame(X)
        if self.variant not in ("minimal", "full") or self.max_onehot < 1:
            raise ValueError("Choose minimal/full and a positive max_onehot.")
        if self.missing_policy not in ("auto", "require"):
            raise ValueError("missing_policy must be auto or require.")
        _target(y, X)
        if not len(X):
            raise ValueError("Training data is empty.")
        self.numeric_ = list(BASE_NUM if self.variant == "minimal" else FULL_NUM)
        self.categorical_ = list(BASE_CAT + ["location_province"]
                                 if self.variant == "minimal" else FULL_CAT)
        self.excluded_price_stats_ = []
        if not self.include_frozen_price_stats:
            self.excluded_price_stats_ = [c for c in PRICE_STATS if c in self.numeric_]
            self.numeric_ = [c for c in self.numeric_ if c not in PRICE_STATS]
        if "imputed" in X:
            self.missing_mode_ = "per_column"
        elif self.missing_policy == "require":
            raise ValueError("Per-column imputed flags required; supply the imputed column.")
        elif "n_imputed" in X:
            self.missing_mode_ = "aggregate_only"
            warnings.warn("Original imputed field is absent; only aggregate flags are available.",
                          UserWarning)
        else:
            self.missing_mode_ = "unavailable"
            warnings.warn("Original imputation flags unavailable; only current missingness is used.",
                          UserWarning)
        self._validate(X)
        self._flags(X)
        numbers = self._numeric(X)
        empty = numbers.columns[numbers.isna().all()].tolist()
        if empty:
            raise ValueError(f"Cannot fit numeric medians for entirely missing columns: {empty}")
        self.imputer_ = SimpleImputer(strategy="median")
        self.scaler_ = StandardScaler()
        self.scaler_.fit(self.imputer_.fit_transform(numbers))
        categories = self._cats(X)
        self.cardinality_ = {c: int(categories[c].nunique()) for c in self.categorical_}
        candidates = [c for c in self.categorical_ if c != "age_band"]
        self.onehot_columns_ = [c for c in candidates if self.cardinality_[c] <= self.max_onehot]
        self.frequency_columns_ = [c for c in candidates if c not in self.onehot_columns_]
        self.onehot_ = None
        if self.onehot_columns_:
            self.onehot_ = OneHotEncoder(handle_unknown="ignore", sparse_output=True, dtype=np.float64)
            self.onehot_.fit(categories[self.onehot_columns_])
        self.frequency_maps_ = {
            c: categories[c].value_counts(normalize=True).to_dict() for c in self.frequency_columns_
        }
        self.target_encoder_ = GroupTargetEncoder(self.n_splits, self.smoothing, self.random_state)
        self.target_encoder_.fit(X, y)
        self.training_rows_ = len(X)
        self.feature_names_in_ = np.asarray(self.numeric_ + self.categorical_, dtype=object)
        self.n_features_in_ = len(self.feature_names_in_)
        self.versions_ = {"scikit-learn": sklearn.__version__, "numpy": np.__version__,
                          "pandas": pd.__version__, "scipy": scipy.__version__,
                          "joblib": joblib.__version__}
        self.feature_names_out_ = self._names()
        return self

    def fit_transform(self, X, y=None, **fit_params):
        if fit_params:
            raise TypeError(f"Unexpected fit parameters: {sorted(fit_params)}")
        self.fit(X, y)
        heldout_means = self.target_encoder_.fit_transform(X, y)
        return self._assemble(X, heldout_means)

    def _names(self):
        names = [f"numeric__{c}" for c in self.numeric_]
        names += [f"missing_now__{c}" for c in self.numeric_]
        if self.onehot_ is not None:
            names += [f"onehot__{c}" for c in self.onehot_.get_feature_names_out()]
        names += [f"frequency__{c}" for c in self.frequency_columns_]
        if "age_band" in self.categorical_:
            names += ["ordinal__age_band"]
        if self.missing_mode_ != "unavailable":
            names += ["imputed__any"]
        if self.missing_mode_ == "per_column":
            names += [f"imputed__{c}" for c in IMPUTED_FIELDS]
        names += ["target__brand_model_log"]
        return np.asarray(names, dtype=object)

    def _assemble(self, X, target_encoded):
        self._validate(X)
        if not len(X):
            return sparse.csr_matrix((0, len(self.feature_names_out_)))
        numbers, cats = self._numeric(X), self._cats(X)
        blocks = [sparse.csr_matrix(self.scaler_.transform(self.imputer_.transform(numbers))),
                  sparse.csr_matrix(numbers.isna().to_numpy(dtype=float))]
        if self.onehot_ is not None:
            blocks.append(self.onehot_.transform(cats[self.onehot_columns_]))
        if self.frequency_columns_:
            values = np.column_stack([
                cats[c].map(self.frequency_maps_[c]).fillna(0.0) for c in self.frequency_columns_
            ])
            blocks.append(sparse.csr_matrix(values))
        if "age_band" in self.categorical_:
            age = cats.age_band.map(dict(zip(AGE_ORDER, range(len(AGE_ORDER))))).fillna(-1)
            blocks.append(sparse.csr_matrix(age.to_numpy().reshape(-1, 1)))
        blocks += [sparse.csr_matrix(self._flags(X)), sparse.csr_matrix(target_encoded)]
        result = sparse.hstack(blocks, format="csr")
        if not np.isfinite(result.data).all():
            raise ValueError("Nonfinite transformed values.")
        return result

    def transform(self, X):
        check_is_fitted(self, "feature_names_out_")
        return self._assemble(X, self.target_encoder_.transform(X))

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, "feature_names_out_")
        return self.feature_names_out_.copy()

    def describe(self):
        check_is_fitted(self, "feature_names_out_")
        rows = []
        for c in self.categorical_:
            method = "ordinal" if c == "age_band" else "one-hot" if c in self.onehot_columns_ else "frequency"
            rows.append(f"| {c} | {self.cardinality_[c]} | {method} |")
        audit = getattr(self.target_encoder_, "fold_audit_", [])
        missing_status = (
            "This artifact includes all eight per-column imputation-history flags. "
            "Keep the original imputed column available for every inference row."
            if self.missing_mode_ == "per_column" else
            "This artifact does not yet satisfy the per-column imputation-history part of "
            "the assignment. Use --cohort data/master/train_cohort_imputed.csv "
            "--require-imputed to rebuild the complete artifact."
        )
        lines = [
            "# Feature preprocessing", "",
            f"Variant: **{self.variant}**. Fitted on **{self.training_rows_:,} training rows**; "
            f"output: **{len(self.feature_names_out_)} features**, SciPy CSR matrix.", "",
            "## Inputs and transformations", "",
            "Inputs are the engineered feature tables from build_features.py, not raw listings. "
            "price_vnd and identifiers are never emitted as model features. duplicate_group_id "
            "is used only to construct internal folds. Extra columns are ignored by a whitelist.", "",
            "Numeric columns: " + ", ".join(f"`{c}`" for c in self.numeric_) + ". "
            "Remaining missing values use train medians, followed by StandardScaler. "
            "A fixed current-missingness indicator is emitted for every numeric column. "
            "Entirely missing training numeric columns cause an error instead of a zero fill.", "",
            f"One-hot routing uses training cardinality only, including the missing token, "
            f"with cutoff <= {self.max_onehot}. Higher-cardinality fields use train-relative "
            "frequencies (unseen value = 0). brand/model additionally have a supervised joint encoding. "
            "Validation data never selects a category list or a routing method.", "",
            "| Column | Training cardinality | Encoding |", "| --- | ---: | --- |", *rows, "",
            "Age order: 0-2 = 0, 3-5 = 1, 6-9 = 2, 10-14 = 3, 15+ = 4; unknown/missing = -1. "
            "Unknown one-hot categories produce an all-zero block.", "",
            "## Grouped target encoding", "",
            f"Target is log1p(price_vnd). For each brand/model pair, encoding = "
            f"(sum of y_log + {self.smoothing:g} * training mean y_log) / "
            f"(pair count + {self.smoothing:g}). Unseen pairs use the training global mean in log space.", "",
            f"fit_transform uses up to {self.n_splits} internal GroupKFold folds, seed {self.random_state}. "
            "An entire duplicate_group_id stays in one fold. Each held-out row uses maps and a prior "
            "learned solely from the other folds. transform uses all training rows' maps for val/test. "
            "The global fallback in an internal fold is that fold's training mean, not the full-data mean.", "",
            "**Model training must use fit_transform(X_train, y_log) or the saved OOF matrix. "
            "Do not train on preprocess.transform(X_train).** Place CarPreprocessor inside the "
            "model Pipeline for outer cross-validation, using group-aware outer splits as well.", "",
            "## Missing and imputed flags", "",
            f"Artifact mode: **{self.missing_mode_}**.", "",
            "With `imputed`, semicolon-separated field names produce imputed__any and eight "
            "per-column flags: " + ", ".join(IMPUTED_FIELDS) + ". "
            "The supplied n_imputed must equal the token count. Current NaN flags and historical "
            "imputation flags have different meanings and are kept separate.", "",
            "Without `imputed`, n_imputed supports only imputed__any. Field-level history cannot "
            "be reconstructed from a count. " + missing_status +
            " Join each validation/inference cohort in the same way.", "",
            "## Leakage boundaries", "",
            "Default excluded precomputed price statistics: " +
            (", ".join(self.excluded_price_stats_) or "none") + ". "
            "They were computed upstream from training prices. Reusing their whole-training values "
            "inside outer CV leaks held-out fold targets. --include-frozen-price-stats is an explicit "
            "opt-in for an already frozen train/val protocol; never enable it for outer CV unless "
            "those statistics have been rebuilt within each outer fold. Their source files are not modified.", "",
            "The provided engineered CSV also contains prior imputation and frequency-grouping decisions. "
            "This transformer cannot undo them. Fully strict raw-data CV requires rebuilding those "
            "upstream steps inside each outer fold. Encoder tests establish this module's boundary, "
            "not a blanket proof that all upstream features are leakage-free.", "",
            "## Reproducibility and handoff", "",
            f"Run `python -m src.features.pipeline --features {self.variant} --describe`. "
            "The CLI saves models/preprocess.joblib, models/preprocess_metadata.json, "
            f"models/feature_names.json, data/master/X_train_{self.variant}_oof.npz, and aligned "
            f"data/master/train_{self.variant}_oof_rows.csv. The row file includes the target, IDs, and fold "
            "assignment and must never be concatenated to the model matrix.", "",
            "Custom classes load from src.features.pipeline; install/copy that module before "
            "joblib.load, and use the recorded dependency versions. This artifact replaces the "
            "earlier all-one-hot preprocessor and requires downstream models to be retrained.", "",
            "No validation or test set was supplied or evaluated. No predictive metric is claimed. "
            "The project's one-time test evaluation remains reserved for M2 on 7 November 2026.", "",
            "### Internal fold audit", "",
            "| Fold | Fit rows | Held-out rows | Group overlap |",
            "| ---: | ---: | ---: | ---: |",
            *[f"| {r['fold']} | {r['train_rows']} | {r['heldout_rows']} | {r['group_overlap']} |" for r in audit],
            "", "### Runtime versions", "",
            *[f"- {name} == {version}" for name, version in self.versions_.items()], "",
        ]
        return "\n".join(lines)


def make_preprocessor(**kwargs):
    return CarPreprocessor(**kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", choices=["minimal", "full"], default="full")
    parser.add_argument("--train", type=Path)
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--output", type=Path, default=Path("models/preprocess.joblib"))
    parser.add_argument("--encoded-dir", type=Path, default=Path("data/master"))
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--docs", type=Path, default=Path("docs/features.md"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--smoothing", type=float, default=20.0)
    parser.add_argument("--require-imputed", action="store_true")
    parser.add_argument("--include-frozen-price-stats", action="store_true")
    args = parser.parse_args(argv)
    source = args.train or Path(f"data/master/train_features_{args.features}.csv")
    train = pd.read_csv(source, low_memory=False)
    if args.cohort:
        train = attach_imputed(train, pd.read_csv(args.cohort, low_memory=False))
    price = pd.to_numeric(train["price_vnd"], errors="raise")
    if not np.isfinite(price).all() or (price <= 0).any():
        raise ValueError("Training prices must be finite and positive.")
    if train.listing_id.isna().any() or train.listing_id.duplicated().any():
        raise ValueError("Training listing_id must be nonmissing and unique.")
    preprocess = CarPreprocessor(
        variant=args.features, n_splits=args.folds, smoothing=args.smoothing,
        random_state=args.seed, missing_policy="require" if args.require_imputed else "auto",
        include_frozen_price_stats=args.include_frozen_price_stats,
    )
    y_log = np.log1p(price)
    X_oof = preprocess.fit_transform(train, y_log)
    metadata = {
        "training_source": str(source), "training_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "training_rows": len(train), "variant": args.features, "output_features": X_oof.shape[1],
        "target": "log1p(price_vnd)", "missing_mode": preprocess.missing_mode_,
        "per_column_imputation_requirement_complete": preprocess.missing_mode_ == "per_column",
        "excluded_price_stats": preprocess.excluded_price_stats_,
        "seed": args.seed, "folds": preprocess.target_encoder_.fold_audit_,
        "versions": preprocess.versions_, "validation_evaluated": False, "test_evaluated": False,
        "python_version": platform.python_version(),
        "cohort_source": str(args.cohort) if args.cohort else None,
        "cohort_sha256": hashlib.sha256(args.cohort.read_bytes()).hexdigest() if args.cohort else None,
    }
    preprocess.build_metadata_ = metadata
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.encoded_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(preprocess, args.output, compress=3)
    for name, value in [("preprocess_metadata.json", metadata),
                        ("feature_names.json", preprocess.get_feature_names_out().tolist())]:
        (args.output.parent / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    matrix_path = args.encoded_dir / f"X_train_{args.features}_oof.npz"
    sparse.save_npz(matrix_path, X_oof)
    row_data = train[["listing_id", "duplicate_group_id", "price_vnd"]].copy()
    row_data["y_log"] = y_log.to_numpy()
    row_data["fold"] = preprocess.target_encoder_.oof_fold_ids_
    row_data.to_csv(args.encoded_dir / f"train_{args.features}_oof_rows.csv", index=False)
    if args.describe:
        args.docs.parent.mkdir(parents=True, exist_ok=True)
        args.docs.write_text(preprocess.describe(), encoding="utf-8")
    print(json.dumps({"saved": str(args.output), "oof_matrix": str(matrix_path),
                      "rows": len(train), "features": X_oof.shape[1],
                      "missing_mode": preprocess.missing_mode_}, indent=2))
    return 0


if __name__ == "__main__":
    # Keep serialized class paths importable rather than __main__.CarPreprocessor.
    from importlib import import_module
    raise SystemExit(import_module("src.features.pipeline").main())
