# Data handover — what to put on Drive, and what everybody downloads

Data is **not** in git (`CONTRIBUTING.md` §6). The dataset is frozen (`§3b`), so what is shared is a
snapshot: everyone who trains a model must be reading the *same bytes*.

Sizes below are the real ones on 2026-11-03.

## 0. Which file answers which question

`data/master` holds 17 CSVs because each layer answers a different question. Pick the file by the
question, not by the name that looks newest.

| Question | File | Rows × columns |
|---|---|---|
| What came out of the merge, before any filter? (**the raw master**) | `master_clean_dataset.csv` | 100,887 × 24 |
| What went into train / val / test? (grouped split, before the cohort rules) | `{train,val,test}.csv` | 70,707 / 15,063 / 15,098 × 24 |
| What is the **modelling cohort**? (implausible records removed, brands repaired, pre-imputation) | `{split}_cohort.csv` | 70,244 / 14,964 / 14,980 × 24 |
| What do we **train on**? (missing values filled, `model_group` added) | `{split}_cohort_imputed.csv` | same rows × 26 |
| What goes **into a model**? (derived + train-fitted features) | `{split}_features_{minimal,full}.csv` | same rows × 17 / 26 |

Rules that follow from the layers:

- **Fit on train only.** `master_clean_dataset.csv` and `{split}.csv` contain the val/test rows, so
  they are for *reading* (inspecting a source, checking a repair, writing the report) — never for
  fitting an encoder, a scaler or a target encoding.
- Prefer `{split}_cohort.csv` when you need the values **as published** (the `imputed` column does not
  exist yet); prefer `{split}_cohort_imputed.csv` when you need the table a model sees.


## 1. What to upload

### Folder `01_week3_mandatory/` — 30.6 MB, everyone downloads this

Only these are needed to run week 3. Nothing else. The folder also carries `README_drive.md` (what to do
on download) and `SHA256SUMS.txt` (one line per file, `eda/` included) — see §3.

| File (from `data/master/`) | Size | Needed by |
|---|---|---|
| `train_cohort_imputed.csv` | 21.3 MB | TB1, TB2, TB3 — fit everything |
| `val_cohort_imputed.csv` | 4.5 MB | choose models, thresholds, feature sets |
| `test_cohort_imputed.csv` | 4.5 MB | one evaluation, at the freeze |
| `split_summary.json` | 2 KB | report §1 (row counts, platforms per partition) |
| `normalize_report.json` | 7 KB | report §2/§4 (brand canonicals, cohort exclusions per reason) |
| `missing_report.json` | 5 KB | report §2 (missing rates before/after imputation) |
| `eda/eda_summary.md`, `eda_summary.json`, 6 × `.png` | 215 KB | report §3, figures |

### Folder `02_full_rebuild/` — 113 MB, only for whoever rebuilds

| File | Size | Reason to need it |
|---|---|---|
| `master_clean_dataset.csv` | 27.3 MB | change a cohort rule, inspect flags, re-split |
| `train.csv`, `val.csv`, `test.csv`, `unlabelled.csv` | 27.3 MB | the split before the cohort filter |
| `train_cohort.csv`, `val_cohort.csv`, `test_cohort.csv` | 27.1 MB | the cohort before imputation (honest missing rates) |

### Folder `03_sources/` — 50 MB, only for whoever re-runs `build_master`

Every `data/processed/*.csv` (18 files). Skip the `.jsonl` twins and `branch_check.csv` (a scratch
diff file) unless someone asks.

### Do **not** upload

`data/scraped.db` (93 MB, rebuildable by crawling), `data/raw/**` (raw HTML/JSON), `data/handover/`,
`bonbanh_final.csv` (a leftover of the Ollama title-filler, no longer produced), `logs/**`, and anything
from `models/` or `data/master/*.npz` (derived, and §5 explains why they are rebuilt instead of shipped).

## 2. Where it goes after downloading

Put the files back in exactly these paths, or nothing runs:

```
<repo>/data/master/train_cohort_imputed.csv
<repo>/data/master/val_cohort_imputed.csv
<repo>/data/master/test_cohort_imputed.csv
<repo>/data/master/*.json
<repo>/data/master/eda/*
```
`data/master/` and `data/processed/` already exist in a fresh clone (they hold `.gitkeep`), so no folder
has to be created. Do **not** rename the files — every command in the repo uses these names.

## 3. Verify before you trust the copy

```powershell
$env:PYTHONIOENCODING='utf-8'
# 1. did the copy arrive intact?
Get-FileHash data/master/*_cohort_imputed.csv -Algorithm SHA256 | Format-Table Hash,Path
#    compare with SHA256SUMS.txt in the Drive folder

# 2. row counts must be exactly these
python -c "import pandas as pd; [print(f, len(pd.read_csv('data/master/'+f, low_memory=False))) for f in ('train_cohort_imputed.csv','val_cohort_imputed.csv','test_cohort_imputed.csv')]"

# 3. the gates must still pass
python -m tools.audit_master          # PROBLEMS: 0
python -m unittest discover -s tests  # 160 tests, OK (measured 2026-11-05)
```

Expected row counts: **70,244 / 14,964 / 14,980**, 26 columns. If a number differs, the file is stale —
download again instead of training on it.

## 4. When the data changes

Any new crawl or a changed cohort rule means a new snapshot: bump the Drive folder
(`01_week3_mandatory__2026-11-05`), regenerate `SHA256SUMS.txt`, and tell the group. Never overwrite a
folder people are already using — two people would then be reporting numbers from two different
datasets, which is exactly what `CONTRIBUTING.md` §3b exists to prevent.

## 5. Artifacts that git ignores — rebuild and compare the hash, do not ship the binary

The final reference configuration is **full / 67 features / per_column / optional
price statistics excluded**. It was rebuilt twice on 2026-11-05 from the original
frozen feature CSV and cohort; every OOF target encoding was independently checked
in both runs. No validation or test set was evaluated.

### Source and runtime

Evidence is produced by `python -m tools.check_preprocess_reproducibility …` on a clean
checkout. That tool records `git rev-parse HEAD` in `artifact_reproducibility.json`, refuses
to run while the tree is dirty, and re-checks `HEAD` before it writes anything, so the
`source_commit` field always names the tree the numbers came from. The provenance anchor
is therefore: that field, `pipeline_sha256`, and the two input hashes.

Do not record a commit that is not reachable from `main`. A **squash merge rewrites the
commit id**, which is what made an earlier draft of this section cite a commit nobody could
check out. Merge an evidence branch with a merge commit; if a squash is unavoidable, re-run
the checker on the new `main` (one command) and commit the refreshed report instead of
keeping the old ids.

The two dated logs (`docs/test_results.txt`, `docs/full_test_results.txt`) are run records
from a local, unpublished commit. They document that the suites passed; they are not
provenance for the current tree.

Runtime: Python **3.12.14**, scikit-learn **1.8.0**, NumPy **2.3.5**, pandas
**3.0.3**, SciPy **1.17.0**, joblib **1.5.3**. This environment satisfies all direct
constraints in `requirements.txt`; see [runtime_requirements.json](runtime_requirements.json).
The sklearn floor has been corrected to `>=1.6`. For exact preprocessing version
installation commands, see [README_preprocess.md](../README_preprocess.md#runtime-and-dependencies).

### One authoritative hash report

[artifact_reproducibility.json](artifact_reproducibility.json) is the sole
reference for input and output SHA256 values, output sizes, runtime, measured
commit, and source hash. There is no second Markdown hash table to become stale.
The report now covers **67**, not the earlier 59-feature aggregate-only build.

The report's `models/` and `encoded/` paths are relative to each isolated build
root. If exported with `--artifacts-dir models/handoff`, compare those paths under
`models/handoff/`. They do not refer to a pre-existing matrix in `data/master/`.
The final feature description and independent verification are generated by the
same checker from the same successful build.

Joblib metadata stores only the input basenames and raw input hashes. Identical
input bytes and filenames, code, settings, and runtime reproduced the same
artifact bytes across different directories and Python hash seeds. This is not
a cross-OS or cross-version serialization guarantee.

`src/features/pipeline.py` writes every text output with LF — CSV via
`lineterminator="\n"`, JSON and Markdown via `newline="\n"` — so the hashes of
`train_full_oof_rows.csv`, `feature_names.json` and `preprocess_metadata.json` are
comparable between Windows and Linux for identical content. Before that fix a Windows
build produced a 3,937,041-byte `train_full_oof_rows.csv` (CRLF) against 3,866,796 bytes
(LF) elsewhere — same 70,244 rows, same folds, different hash. `.npz` and `.joblib`
remain runtime-specific: equal size and equal scientific content do not imply equal
bytes across NumPy/scikit-learn versions.

### Original inputs and generation command

Both uploaded inputs exactly match the team's frozen reference SHA256 values
(recorded in the JSON report): `train_features_full.csv` and
`train_cohort_imputed.csv`. Both contain 70,244 rows. The cohort was joined by
`listing_id`; 53,134 rows have nonempty imputation history, with token counts
matching `n_imputed`. No imputed fields were fabricated or filled with empty
strings for this real-data build.

From a clean checkout with both input CSVs in `data/master/`:

```bash
python -m tools.check_preprocess_reproducibility --cohort data/master/train_cohort_imputed.csv --expected-features 67 --artifacts-dir models/handoff
```

Internally each fresh process runs the equivalent of:

```bash
python -m src.features.pipeline --features full --train inputs/train_features_full.csv --cohort inputs/train_cohort_imputed.csv --require-imputed --output models/preprocess.joblib --encoded-dir encoded --describe --docs features.md
python -m tools.verify_phuong --train inputs/train_features_full.csv --cohort inputs/train_cohort_imputed.csv --artifact models/preprocess.joblib --encoded-dir encoded --output verification.json
```

The second run uses absolute input paths. All five output hashes must match.
The checker then writes `docs/features.md`, `docs/artifact_verification.json`, and
`docs/artifact_reproducibility.json` together. Commit that evidence after running.
It never rewrites the frozen input CSVs or writes under `data/master/`.

### Compare and use the final artifacts

The final preprocessor expects the original `imputed` history at inference.
Join the corresponding cohort by listing_id before calling transform. Train a
model using the matching OOF matrix or fit_transform; do not train it on
transform(training_data), which uses whole-training target maps.

```python
import joblib

p = joblib.load("models/handoff/models/preprocess.joblib")
assert len(p.get_feature_names_out()) == 67
assert p.build_metadata_["training_sha256"].startswith("62bf8aa4")
assert p.build_metadata_["cohort_sha256"].startswith("8c613849")
assert len(p.target_encoder_.fold_audit_) == 5
assert all(f["group_overlap"] == 0 for f in p.target_encoder_.fold_audit_)
assert p.build_metadata_["training_source"] == "train_features_full.csv"
assert p.build_metadata_["cohort_source"] == "train_cohort_imputed.csv"
```

These are sanity checks, not complete equivalence checks. With a different OS
or runtime, rebuild there and compare names, folds, metadata and numerical
outputs; differing serialized bytes alone do not establish a bug. Use matching
library versions to load saved models.

- Keep derived binaries in local storage or a separately versioned Drive model
  folder, never `git add -f` them into the repository.
- `encoded/train_full_oof_rows.csv` contains targets and identifiers. Never
  concatenate it into the model matrix.
- All **30 preprocessing tests** and **160 tests under tests/** passed. Full logs
  are committed. The separate crawler smoke command still encounters pre-existing
  merge-conflict markers in `src/sources/oto/brands_other.py`; these changes do
  not establish that the entire crawler application is runnable.
