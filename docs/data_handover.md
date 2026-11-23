# Data handover — what goes to Drive

Data is **not** committed. The snapshot is frozen, so what is shared is a set of files everyone can
read byte-for-byte. Sizes are the real ones on 2026-11-15.

## Folders

| Folder | Contents | Size | Needed by |
|---|---|---:|---|
| `01_week3_mandatory/` | the three `*_cohort_imputed.csv`, `split_summary.json`, `normalize_report.json`, `missing_report.json`, `eda/` | 30.6 MB | everyone who trains |
| `02_full_rebuild/` | `master_clean_dataset.csv`, `{train,val,test}.csv`, `{train,val,test}_cohort.csv`, `unlabelled.csv` | 113 MB | changing a cohort rule or re-splitting |
| `03_sources/` | every `data/processed/*.csv` (18 files) | 50 MB | re-running `build_master` |
| `04_models/2026-11-15_v2/` | `models/v2/` bundle (7 files), `README_model.md`, `SHA256SUMS.txt` | 7.9 MB | running `Predictor` / the demo |
| `05_week4_v2__2026-11-15/` | `data/master/v2/` features + imputed cohorts (6 files), `train_cohort.csv`, `val_cohort.csv`, `label_flags.csv`, `label_flags_report.json`, `evidence/`, `README_drive.md`, `SHA256SUMS.txt` | 87.7 MB | rebuilding/training v2 and running readiness checks |

Each folder carries `SHA256SUMS.txt`; the `04` and `05` folders also carry their own README.

## What is in the Week 4 snapshot

`05_week4_v2__2026-11-15/` is a **new** snapshot, not an overwrite of Week 3:

- `data/master/v2/{train,val,test}_features_full.csv` — the 30-feature v2 table.
- `data/master/v2/{train,val,test}_cohort_imputed.csv` — the v2 imputed cohorts.
- `data/master/v2/data_quality_v2.json`, `features_v2_report.json` — backfill and feature counts.
- `data/master/train_cohort.csv` — pre-imputation train cohort, needed to fit the frozen imputation
  statistics and the 1/k repeat weights.
- `data/master/val_cohort.csv` — raw val rows for `readiness_check` / `inference_smoke`.
- `data/master/label_flags.csv`, `label_flags_report.json` — Week 4 label-quality side table.
- `evidence/` — the small JSON/CSV behind the Week 4 numbers.

## Where it goes after download

```
<repo>/data/master/train_cohort_imputed.csv
<repo>/data/master/val_cohort_imputed.csv
<repo>/data/master/test_cohort_imputed.csv
<repo>/data/master/v2/*
<repo>/data/master/train_cohort.csv
<repo>/data/master/val_cohort.csv
<repo>/data/master/label_flags.csv
<repo>/models/v2/*
```

Do not rename files: every command uses these names.

## Verify before trusting a copy

```powershell
$env:PYTHONIOENCODING='utf-8'
# 1. hashes (compare with SHA256SUMS.txt in the Drive folder)
Get-FileHash data/master/train_cohort_imputed.csv, data/master/val_cohort_imputed.csv,
              data/master/test_cohort_imputed.csv -Algorithm SHA256

# 2. row counts must be exactly 70,244 / 14,964 / 14,980
python -c "import pandas as pd; [print(f, len(pd.read_csv('data/master/'+f, low_memory=False))) for f in ('train_cohort_imputed.csv','val_cohort_imputed.csv','test_cohort_imputed.csv')]"

# 3. gates and tests
python -m tools.audit_master          # PROBLEMS: 0 (needs 02_full_rebuild/master_clean_dataset.csv)
python -m unittest discover -s tests -t .   # 268 tests, OK
python -m tools.live_blind_test               # 8/8 PASS (models/v2)
python -m tools.readiness_check --rows 120    # 4/4 PASS (v2 data + val_cohort + label_flags)
```

Expected: 70,244 / 14,964 / 14,980 rows; parity **2.02e-09**; **268 tests OK**.

## Versioning

Any new crawl or changed cohort rule means a **new dated folder** (`01_week3_mandatory__2026-11-05`,
`05_week4_v2__2026-11-15`). Never overwrite a folder people are already using — two people quoting
numbers from two snapshots is exactly what the versioned folder prevents.

## Artifacts that git ignores

`data/master/**`, `encoded/**`, `models/**`, `*.npz`, `*.joblib`, `*_oof_rows.csv` are rebuilt by the
commands in the repository, never committed. The committed evidence is `docs/artifact_reproducibility.json`,
`docs/artifact_verification.json`, `docs/runtime_requirements.json` and the test logs. Share binaries
through `04_models/<date>/`; see `docs/inference.md` for the bundle contract.
