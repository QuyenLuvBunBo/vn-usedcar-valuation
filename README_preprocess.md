# Phương preprocessing

The preprocessing implementation from PR #7 is retained. Use
`src.features.pipeline` to build the preprocessor and its matching OOF matrix.

## Runtime and dependencies

The current regression run passes **29 tests** (27 original tests plus two
regression tests for price-statistic indicators and path-independent metadata).
See [the complete dated test log](docs/test_results.txt) for the measured runtime.
Building and loading should use the same Python and dependency versions; the
full environment is recorded in `preprocess_metadata.json`. The pipeline uses
`GroupKFold(shuffle=True)`, which requires scikit-learn 1.6 or newer, even though
the repository's broad requirements currently allow 1.5.

Use the repository's existing `requirements.txt`. This update does not change
dependencies or require an additional requirements file.

## Build and test

Run from the repository root, with the frozen input CSVs already present:

```bash
python -m unittest discover -s tests -p test_features.py -v
python -m src.features.pipeline --features full --cohort data/master/train_cohort_imputed.csv \
    --require-imputed --describe
```

The command regenerates `docs/features.md`, `models/preprocess.joblib`, metadata,
feature names, the OOF matrix, and its aligned rows CSV. Do not regenerate the
upstream frozen datasets just to resolve an artifact-loading error.

## Feature count 67 or 69

For the frozen full dataset with the original per-column imputation flags:

| Configuration | Feature count | Price statistics |
| --- | ---: | --- |
| Default | 67 | Excluded |
| `--include-frozen-price-stats` | 69 | Included |

The default excludes `brand_retention_rate` and `province_price_index`. To include
both, add the flag to the build command:

```bash
python -m src.features.pipeline --features full --cohort data/master/train_cohort_imputed.csv \
    --require-imputed --include-frozen-price-stats --describe
```

The flag adds two scaled numeric values, without extra missing-value indicators
for those two columns. All other preprocessing remains unchanged. Counts can
differ for other datasets because one-hot categories are fitted on training data.

Both commands use the same output paths, so the last build replaces the earlier
artifacts. Rebuild with the default command for the final 67-feature handoff.
Use a matching preprocessor and trained price model; changing the feature
configuration requires retraining the price model.

Report section 5 must state **67/default** or **69/with-price-statistics** for each
experiment. The reviewer reports that `--ablate` and `model_gate` experiments used
69 features; identify those separately from default 67-feature results. Do not
use whole-training price statistics inside outer cross-validation unless they
are recomputed within each outer training fold.

## Reproducible metadata

`preprocess_metadata.json` stores only source filenames and SHA256 content hashes:

```text
training_source = train_features_full.csv
training_sha256 = SHA256 of the training CSV bytes
cohort_source = train_cohort_imputed.csv
cohort_sha256 = SHA256 of the cohort CSV bytes
```

No absolute directory or working-directory prefix is stored in either source
field. Moving identical input files, with the same filenames, between directories
therefore does not change the embedded metadata. Use the same data, settings,
Python and dependency versions when comparing complete artifact hashes.

Artifact hashes and their verification status have one documentation source:
[data handover §5](docs/data_handover.md#5-artifacts-that-git-ignores--rebuild-and-compare-the-hash-do-not-ship-the-binary).
The checked-in feature description and independent verification currently cover
**59 features / aggregate_only**. The original cohort is still needed to measure
the final **67-feature** artifact; the stale pre-PR-9 hashes have been removed.

With both frozen inputs present, verify two independent builds without changing
`data/master/` or your existing model artifacts:

```bash
python -m tools.check_preprocess_reproducibility \
    --cohort data/master/train_cohort_imputed.csv --expected-features 67
```

The check uses separate temporary directories and fresh Python processes, varies
relative/absolute input paths, independently verifies OOF values in both builds,
and writes `docs/artifact_reproducibility.json` only after all hashes match.
Copy the resulting hashes and environment into data handover §5, then regenerate
`docs/features.md` and `docs/artifact_verification.json` with the final build.

## Inference requires the imputation history

Before inference, call `attach_imputed(val, val_cohort_imputed)` before `transform`:

```python
import joblib
import pandas as pd
from src.features.pipeline import attach_imputed

preprocess = joblib.load("models/preprocess.joblib")
val = pd.read_csv("data/master/val_features_full.csv", low_memory=False)
val_cohort_imputed = pd.read_csv("data/master/val_cohort_imputed.csv", low_memory=False)
val = attach_imputed(val, val_cohort_imputed)
X_val = preprocess.transform(val)
```

The join uses `listing_id`, validates coverage, and preserves row order. The
original `imputed` history is required for all eight per-column flags. A
`ValueError` when it is absent is intentional and does not mean the joblib is
corrupt. Do not rebuild with `aggregate_only` to bypass the error. Keep the
`src.features.pipeline` module importable when loading the artifact.

Train downstream models on `fit_transform(train, y_log)` or the matching saved
OOF matrix. Use `transform` on validation/inference data. Do not train on
`preprocess.transform(train)`, which uses full-training target maps.

## Documentation and review

- [Generated feature documentation](docs/features.md)
- [Phương handoff](docs/phuong_handoff.md)

The core encoding and grouped folds are unchanged. The train/validation target
correlations alone are not a proof of no leakage; group separation and the tests
that perturb held-out targets provide more direct evidence. No test-set model
evaluation is part of this hygiene change.
