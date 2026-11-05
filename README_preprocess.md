# Phương preprocessing

The preprocessing implementation from PR #7 is retained. Use
`src.features.pipeline` to build the preprocessor and its matching OOF matrix.

## Runtime and dependencies

The measured environment is **Python 3.12.14**, scikit-learn **1.8.0**, NumPy
**2.3.5**, pandas **3.0.3**, SciPy **1.17.0**, and joblib **1.5.3**.
All installed direct dependencies satisfy `requirements.txt`; the complete
comparison is in [runtime_requirements.json](docs/runtime_requirements.json).
The scikit-learn floor is now `>=1.6`, matching `GroupKFold(shuffle=True)`.

Use the existing requirements file. To reproduce the preprocessing versions:

```bash
python -m pip install -r requirements.txt "scikit-learn==1.8.0" "numpy==2.3.5" "pandas==3.0.3" "scipy==1.17.0" "joblib==1.5.3"
```

Build and load the joblib with matching Python and dependency versions. Matching
versions are necessary for hash comparison; cross-OS byte equality is not promised.
No additional requirements file is needed.

## Build and test

The final checked-in evidence covers **67 features / per_column / price
statistics excluded**, using the original frozen training cohort. All
**30 preprocessing tests** and **160 tests under tests/** passed; see the
[preprocessing log](docs/test_results.txt) and [full log](docs/full_test_results.txt).

From the repository root, with the two frozen input CSVs present, first commit
source changes. The checker requires a clean checkout and writes all three
evidence files together after both builds match:

```bash
python -m tools.check_preprocess_reproducibility --cohort data/master/train_cohort_imputed.csv --expected-features 67
```

It updates `docs/features.md`, `docs/artifact_verification.json`, and
`docs/artifact_reproducibility.json`. Commit these generated files after the run.
Do not run an unrelated opt-in build with `--describe` over the final description.

To also save usable artifacts without writing under frozen `data/master/`, add:

```bash
python -m tools.check_preprocess_reproducibility --cohort data/master/train_cohort_imputed.csv --expected-features 67 --artifacts-dir models/handoff
```

The exported joblib and metadata are under `models/handoff/models/`; the matching
OOF matrix and row map are under `models/handoff/encoded/`. These are local derived
artifacts and must not be committed. Commit or stash modified evidence before
rerunning the checker.

For your Windows `.venv`, no activation is required:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_features -v
.\.venv\Scripts\python.exe -m tools.check_preprocess_reproducibility --cohort data/master/train_cohort_imputed.csv --expected-features 67
```

On Linux/WSL use `./.venv/bin/python` instead.

## Feature count 67 or 69

For the frozen full dataset with the original per-column imputation flags:

| Configuration | Feature count | Price statistics |
| --- | ---: | --- |
| Default | 67 | Excluded |
| `--include-frozen-price-stats` | 69 | Included |

The default excludes `brand_retention_rate` and `province_price_index`. To include
both, use separate output paths for the optional experiment:

```bash
python -m src.features.pipeline --features full --cohort data/master/train_cohort_imputed.csv \
    --require-imputed --include-frozen-price-stats --output models/with-price-stats/preprocess.joblib \
    --encoded-dir models/with-price-stats/encoded
```

The flag adds two scaled values without missing-value indicators for those
columns. The real cohort produced **69** in a separate verified build; the
published reference evidence remains **67**. Output counts can differ on other
datasets because training category cardinalities control one-hot width.
Changing feature configuration requires retraining the downstream price model.

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

[artifact_reproducibility.json](docs/artifact_reproducibility.json) is the **only
reference table for artifact hashes**. [Data handover §5](docs/data_handover.md#5-artifacts-that-git-ignores--rebuild-and-compare-the-hash-do-not-ship-the-binary)
explains the scope, input provenance, and source commit. Hashes from the earlier
59-feature configuration have been replaced by measured 67-feature results.

The checker runs fresh processes in separate temporary directories, varies
relative/absolute input paths and Python hash seeds, verifies every OOF target
encoding in both runs, and checks the source checkout stays unchanged. Source
hashes normalize CRLF to LF; CSV and artifact hashes remain byte-exact. Evidence
is written only after all checks succeed. A failed run leaves any older report
unchanged; its timestamp must not be mistaken for a successful new run.

## Inference requires the imputation history

Before inference, call `attach_imputed(val, val_cohort_imputed)` before `transform`:

```python
import joblib
import pandas as pd
from src.features.pipeline import attach_imputed

preprocess = joblib.load("models/handoff/models/preprocess.joblib")
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
