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
`bonbanh_final.csv` (a leftover of the Ollama title-filler, no longer produced), `logs/**`.

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
python -m unittest discover -s tests  # 130 tests, OK
```

Expected row counts: **70,244 / 14,964 / 14,980**, 26 columns. If a number differs, the file is stale —
download again instead of training on it.

## 4. When the data changes

Any new crawl or a changed cohort rule means a new snapshot: bump the Drive folder
(`01_week3_mandatory__2026-11-05`), regenerate `SHA256SUMS.txt`, and tell the group. Never overwrite a
folder people are already using — two people would then be reporting numbers from two different
datasets, which is exactly what `CONTRIBUTING.md` §3b exists to prevent.

