# Feature preprocessing

Variant: **full**. Fitted on **70,244 training rows**; output: **59 features**, SciPy CSR matrix.

## Inputs and transformations

Inputs are the engineered feature tables from build_features.py, not raw listings. price_vnd and identifiers are never emitted as model features. duplicate_group_id is used only to construct internal folds. Extra columns are ignored by a whitelist.

Numeric columns: `manufacture_year`, `mileage_km`, `engine_capacity`, `seats`, `vehicle_age`, `km_per_year`, `engine_per_seat`, `n_imputed`. Remaining missing values use train medians, followed by StandardScaler. A fixed current-missingness indicator is emitted for every numeric column. Entirely missing training numeric columns cause an error instead of a zero fill.

One-hot routing uses training cardinality only, including the missing token, with cutoff <= 40. Higher-cardinality fields use train-relative frequencies (unseen value = 0). brand/model additionally have a supervised joint encoding. Validation data never selects a category list or a routing method.

| Column | Training cardinality | Encoding |
| --- | ---: | --- |
| brand | 146 | frequency |
| model | 3244 | frequency |
| model_group | 716 | frequency |
| transmission | 3 | one-hot |
| fuel_type | 4 | one-hot |
| origin | 2 | one-hot |
| body_type | 14 | one-hot |
| seller_type | 2 | one-hot |
| source_platform | 8 | one-hot |
| province_group | 51 | frequency |
| age_band | 5 | ordinal |
| brand_age_band | 343 | frequency |
| is_luxury_segment | 2 | one-hot |

Age order: 0-2 = 0, 3-5 = 1, 6-9 = 2, 10-14 = 3, 15+ = 4; unknown/missing = -1. Unknown one-hot categories produce an all-zero block.

## Grouped target encoding

Target is log1p(price_vnd). For each brand/model pair, encoding = (sum of y_log + 20 * training mean y_log) / (pair count + 20). Unseen pairs use the training global mean in log space.

fit_transform uses up to 5 internal GroupKFold folds, seed 42. An entire duplicate_group_id stays in one fold. Each held-out row uses maps and a prior learned solely from the other folds. transform uses all training rows' maps for val/test. The global fallback in an internal fold is that fold's training mean, not the full-data mean.

**Model training must use fit_transform(X_train, y_log) or the saved OOF matrix. Do not train on preprocess.transform(X_train).** Place CarPreprocessor inside the model Pipeline for outer cross-validation, using group-aware outer splits as well.

## Missing and imputed flags

Artifact mode: **aggregate_only**.

With `imputed`, semicolon-separated field names produce imputed__any and eight per-column flags: body_type, transmission, fuel_type, origin, seller_type, seats, mileage_km, engine_capacity. The supplied n_imputed must equal the token count. Current NaN flags and historical imputation flags have different meanings and are kept separate.

Without `imputed`, n_imputed supports only imputed__any. Field-level history cannot be reconstructed from a count. This artifact does not yet satisfy the per-column imputation-history part of the assignment. Use --cohort data/master/train_cohort_imputed.csv --require-imputed to rebuild the complete artifact. Join each validation/inference cohort in the same way.

## Leakage boundaries

Default excluded precomputed price statistics: brand_retention_rate, province_price_index. They were computed upstream from training prices. Reusing their whole-training values inside outer CV leaks held-out fold targets. --include-frozen-price-stats is an explicit opt-in for an already frozen train/val protocol; never enable it for outer CV unless those statistics have been rebuilt within each outer fold. Their source files are not modified.

The provided engineered CSV also contains prior imputation and frequency-grouping decisions. This transformer cannot undo them. Fully strict raw-data CV requires rebuilding those upstream steps inside each outer fold. Encoder tests establish this module's boundary, not a blanket proof that all upstream features are leakage-free.

## Reproducibility and handoff

Run `python -m src.features.pipeline --features full --describe`. The CLI saves models/preprocess.joblib, models/preprocess_metadata.json, models/feature_names.json, data/master/X_train_full_oof.npz, and aligned data/master/train_full_oof_rows.csv. The row file includes the target, IDs, and fold assignment and must never be concatenated to the model matrix.

Custom classes load from src.features.pipeline; install/copy that module before joblib.load, and use the recorded dependency versions. This artifact replaces the earlier all-one-hot preprocessor and requires downstream models to be retrained.

No validation or test set was supplied or evaluated. No predictive metric is claimed. The project's one-time test evaluation remains reserved for M2 on 7 November 2026.

### Internal fold audit

| Fold | Fit rows | Held-out rows | Group overlap |
| ---: | ---: | ---: | ---: |
| 0 | 56389 | 13855 | 0 |
| 1 | 56475 | 13769 | 0 |
| 2 | 56059 | 14185 | 0 |
| 3 | 56195 | 14049 | 0 |
| 4 | 55858 | 14386 | 0 |

### Runtime versions

- scikit-learn == 1.8.0
- numpy == 2.3.5
- pandas == 2.2.3
- scipy == 1.17.0
- joblib == 1.5.3
