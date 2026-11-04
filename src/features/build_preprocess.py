"""Build models/preprocess.joblib from build_features.py's TRAIN output.

Run from the repository root:
    python build_preprocess.py
    python build_preprocess.py --features minimal

Requires pandas, numpy, scikit-learn >= 1.2, and joblib.
The saved object is a fitted sklearn ColumnTransformer, not a price model.
Input at inference must already have the selected engineered feature columns
with numeric dtypes for numeric fields and strings/np.nan for categoricals.
Raw-listing imputation and feature engineering remain upstream; preserve their
train-fitted statistics, including feature_stats.json, for inference.
For cross-validation, refit preprocessing inside each fold. The full variant's
price-derived features also need fold-local statistics (prefer out-of-fold
values for training rows).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


BASE_CATEGORICAL = [
    "brand", "model", "model_group", "transmission", "fuel_type", "origin",
    "body_type", "seller_type", "source_platform",
]
BASE_NUMERIC = ["manufacture_year", "mileage_km", "engine_capacity", "seats"]
VARIANTS = {
    "minimal": (BASE_CATEGORICAL + ["location_province"], BASE_NUMERIC),
    "full": (
        BASE_CATEGORICAL + [
            "province_group", "age_band", "brand_age_band", "is_luxury_segment",
        ],
        BASE_NUMERIC + [
            "vehicle_age", "km_per_year", "engine_per_seat", "n_imputed",
            "brand_retention_rate", "province_price_index",
        ],
    ),
}


def build_preprocess(train_path: Path, output_path: Path, variant: str):
    categorical, numeric = VARIANTS[variant]
    train = pd.read_csv(train_path, low_memory=False, encoding="utf-8-sig")
    required = numeric + categorical
    missing = [column for column in required if column not in train]
    if missing:
        raise ValueError(f"Training feature table lacks columns: {missing}")
    if train.empty:
        raise ValueError("Training feature table is empty.")

    X_train = train.loc[:, required].copy()
    for column in numeric:
        X_train[column] = pd.to_numeric(X_train[column], errors="raise")
        if np.isinf(X_train[column].to_numpy(dtype=float)).any():
            raise ValueError(f"{column} contains infinity; fix feature generation first.")
    empty_numeric = [column for column in numeric if X_train[column].isna().all()]
    if empty_numeric:
        raise ValueError(f"Cannot learn a median for entirely missing columns: {empty_numeric}")
    for column in categorical:
        X_train[column] = X_train[column].map(
            lambda value: np.nan if pd.isna(value) else str(value)
        )

    preprocess = ColumnTransformer(
        transformers=[
            ("numeric", Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]), numeric),
            ("categorical", Pipeline([
                ("imputer", SimpleImputer(
                    strategy="constant", fill_value="Unknown", keep_empty_features=True,
                )),
                ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=True)),
            ]), categorical),
        ],
        remainder="drop",
        sparse_threshold=1.0,
    )
    preprocess.fit(X_train)
    preprocess.build_metadata_ = {
        "variant": variant,
        "training_file": str(train_path.resolve()),
        "training_rows": len(X_train),
        "sklearn_version": sklearn.__version__,
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
        "joblib_version": joblib.__version__,
        "input_stage": "engineered feature table, not raw listings",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(preprocess, output_path, compress=3)
    print(f"Saved {output_path}: {len(X_train):,} training rows, "
          f"{len(required)} input columns, "
          f"{len(preprocess.get_feature_names_out())} output features")
    print(f"Use the same scikit-learn version when loading: {sklearn.__version__}")
    return preprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", choices=VARIANTS, default="full")
    parser.add_argument("--train", type=Path)
    parser.add_argument("--output", type=Path, default=Path("models/preprocess.joblib"))
    args = parser.parse_args()
    train_path = args.train or Path(f"data/master/train_features_{args.features}.csv")
    if not train_path.is_file():
        parser.error(f"Missing {train_path}. Generate or provide the TRAIN feature CSV first.")
    build_preprocess(train_path, args.output, args.features)


if __name__ == "__main__":
    main()
