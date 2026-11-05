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
python -m unittest discover -s tests  # require the full run to finish with OK
```

Expected row counts: **70,244 / 14,964 / 14,980**, 26 columns. If a number differs, the file is stale —
download again instead of training on it.

## 4. When the data changes

Any new crawl or a changed cohort rule means a new snapshot: bump the Drive folder
(`01_week3_mandatory__2026-11-05`), regenerate `SHA256SUMS.txt`, and tell the group. Never overwrite a
folder people are already using — two people would then be reporting numbers from two different
datasets, which is exactly what `CONTRIBUTING.md` §3b exists to prevent.

## 5. Artifacts that git ignores — rebuild and compare the hash, do not ship the binary

`models/`, `*.joblib`, and generated files under `data/master/` are ignored by git.
Rebuild derived artifacts from the frozen inputs; never force-add the binaries.

### Current verification status (2026-11-05)

PR #9 changed both source metadata fields to basenames. The joblib is now
**independent of input directory paths** when input bytes and filenames,
configuration, code, Python, and dependency versions match. This does not imply
byte-identical serialization across operating systems or different runtimes.

The stale pre-PR-9 67-feature output hashes have been removed. **The final
67-feature real-data hashes are pending:** the original training cohort was not
available for this correction. The currently verified configuration is
**59 features / aggregate_only**, without the cohort. It is not the final handoff.

Two fresh-process builds of the available 70,244-row frozen feature CSV, in
separate temporary directories with relative versus absolute input paths and
different Python hash seeds, produced identical bytes for all five output files.
The independent verifier checked every OOF target encoding in both runs.

Measured source: commit `2aa4af7cd23ca40a6ba055ec69e3d6d015d6bf13` (correction based on
`52a6da6`). Documentation edits were uncommitted during measurement; the pipeline
and checker code were committed. Pipeline SHA256:
`186550702F237EAEAF61D5FEC017C3EEA369535C1E98999B3C0A4FD02CD8C2FA`.

Runtime: Python 3.12.14 / scikit-learn 1.8.0 / pandas 2.2.3 / NumPy 2.3.5 /
SciPy 1.17.0 / joblib 1.5.3. Full machine-readable evidence, including metadata
and feature-name hashes: [artifact_reproducibility.json](artifact_reproducibility.json).

The following hashes apply **only to the 59-feature aggregate_only build**.
The checker writes matrices to temporary `encoded/` directories; names below
use the ordinary pipeline output layout.

| Output | Size (bytes) | SHA256 |
| --- | ---: | --- |
| `models/preprocess.joblib` | 124780 | `EF58DF467BCAB7BE7E04E03C2486BF017D3D408F5ECE162D0CBA2E9F926B2D4D` |
| `data/master/X_train_full_oof.npz` | 2379676 | `A32E0F7E84B1231CC1C71B0BD0F5BC36B4E1CC23F41E605E73FF22C29A907041` |
| `data/master/train_full_oof_rows.csv` | 3866796 | `05E1F9F2BE7B27AE8BDE6DC2C62117D7530217BB1D1033733282FB64DC876DB5` |

### Finish the 67-feature reference build

Use exactly these frozen input files. The feature hash was rechecked locally;
the cohort hash remains the team's existing reference, not a new measurement.

| Input | SHA256 |
| --- | --- |
| `data/master/train_features_full.csv` | `62BF8AA4082A6D338337434524EEA22CBE7E9E596CB3F5690ABDB8C868920450` |
| `data/master/train_cohort_imputed.csv` | `8C6138495676C4DCF308B09BAC30F34C807FD8011B02EEFC1BBFC0AC0DD07427` |

With both files present, run from the repository root:

```bash
python -m src.features.pipeline --features full \
  --cohort data/master/train_cohort_imputed.csv --require-imputed --describe
python -m tools.verify_phuong --cohort data/master/train_cohort_imputed.csv
python -m tools.check_preprocess_reproducibility \
  --cohort data/master/train_cohort_imputed.csv --expected-features 67
```

The checker copies frozen inputs into two temporary directories, uses separate
Python processes, checks OOF values independently, and fails if any output hash
differs. It writes a success report only after both builds match; a failed run
does not refresh any earlier report. It never writes to `data/master/`.
After success, replace the table above with the **67-feature** hashes and record
the new source commit, date, and all runtime versions. Commit the regenerated
feature documentation, independent verification, and reproducibility report.

### Compare artifacts correctly

With the same environment, compare hashes for the same feature configuration.
When OS/Python/dependency versions differ, hash differences alone do not establish
a bug. Rebuild in the target environment and compare loaded metadata, feature
names, folds, and numerical outputs. Do not assume cross-version joblib loading
is supported; use the recorded build environment to inspect an older artifact.

For the **final 67-feature handoff**, retain these sanity checks (they do not by
themselves prove complete artifact equivalence):

```python
import joblib

p = joblib.load("models/preprocess.joblib")
assert len(p.get_feature_names_out()) == 67
assert p.build_metadata_["training_sha256"].startswith("62bf8aa4")
assert len(p.target_encoder_.fold_audit_) == 5
assert all(f["group_overlap"] == 0 for f in p.target_encoder_.fold_audit_)
assert p.build_metadata_["training_source"] == "train_features_full.csv"
assert p.build_metadata_["cohort_source"] == "train_cohort_imputed.csv"
```

- Rebuild by default. Matching output hashes establish matching bytes, not proof
  of source-code or data provenance; keep input hashes and the source commit too.
- If exact artifacts must be archived, use `04_models/<date>/` on Drive with a
  separate `SHA256SUMS.txt` and recorded runtime. Never mix them into the frozen
  input snapshot or commit them with `git add -f`.
- `train_full_oof_rows.csv` contains targets and identifiers; never concatenate
  it into the model feature matrix.
- This section is the single documentation source for reference hashes. Other
  documents link here. Remeasure after code, inputs, settings, or runtime change.
