# Inference — the v2 bundle, and how to price one car

`src/models/predict.py` turns a raw listing into a price and a band. It reads **only**
`models/v2/`; it never opens `data/master`, so a prediction cannot pick up a training row or a
statistic that was fitted after the fact. `tests/test_predict.py::ZeroLeakageTests` proves that by
making every `pandas.read_csv` call raise during a prediction.

`models/` is git-ignored (`CONTRIBUTING.md` §2: derived binaries go to Drive, the repository keeps the
text evidence). This page is that evidence: it records the bundle's metadata, hashes and metrics.

## 1. The bundle

| File | Contents |
|---|---|
| `model_point.joblib` | LightGBM on `log1p(price_vnd)`, the adopted **step 3** configuration |
| `quantiles.joblib` | P10 / P50 / P90 LightGBM fits + the conformal log-shifts |
| `categories.json` | the category list of every categorical column (unseen level → NaN) |
| `impute_stats.json` | the train-fitted imputation statistics: hierarchical modes, seats map, median by age band, median by brand\|model, rare-model set |
| `feature_stats.json` | the statistics `build_features.apply_stats` applies (province list, retention, price index) |
| `known.json` | brand\|model counts and medians, deposit threshold, placeholder limits, year window, engine range |
| `metadata.json` | feature order, params, weights, val metrics, source hashes, versions, git commit |

Regenerate with `python -m tools.export_v2_model` (full, ~2 min) or `--fast` (point model only, ~12 s,
used by `tools/clean_check.py`).

## 2. Recorded metadata (bundle of 2026-11-14)

| | |
|---|---|
| git commit | `988321c` |
| features | 30 (`docs/features_v2.md`) · rows train 70,244 · val 14,964 |
| weights | `1/k` for repeated ads — 18,655 train rows down-weighted |
| params | LightGBM 300 trees, lr 0.06, 63 leaves, `min_child_samples` 40, seed 42 |
| versions | Python 3.14.8 · pandas 3.0.3 · numpy 2.4.6 · lightgbm 4.7.0 |

**Point model on val**

| view | R²(log) | RMSE(log) | R²(VND) | MAE (VND) | MAPE | median APE |
|---|---:|---:|---:|---:|---:|---:|
| val_full (14,964) | 0.9470 | 0.1904 | 0.9167 | 81,338,287 | 0.1125 | 0.0618 |
| val_clean (9,644) | 0.9548 | 0.1667 | 0.9199 | 79,636,034 | 0.0991 | 0.0613 |

**Band** (conformal shift measured on train, grouped 2-fold OOF — val stays a holdout)

| | |
|---|---:|
| shift P10 / P90 (log) | −0.023244 / +0.020953 |
| val coverage (nominal 80 %) | **81.71 %** |
| median band width | 118,884,403 VND |

**Source hashes** (first 12 hex of SHA-256)

| Source | sha256 |
|---|---|
| `data/master/v2/train_features_full.csv` | `51dc3cc0b037` |
| `data/master/v2/val_features_full.csv` | `07526ace85cf` |
| `data/master/train_cohort.csv` | `0d41536494c2` |
| `data/master/label_flags.csv` | `3cfe73458dc0` |

## 3. Train–serving parity

`python -m tools.inference_smoke` takes val rows (half complete, half with blanks that force the
imputation path), rebuilds the raw record, runs `Predictor.predict_one`, and compares it with the
exported model scored directly on the v2 feature row:

```
complete     rows  10 · max |ratio-1| 0.00e+00
with-blanks  rows  10 · max |ratio-1| 0.00e+00
PASS — max error 0.00e+00 (tolerance 1e-03)
```

Rows whose v2 cohort was backfilled (`v2_filled` not empty) are excluded on purpose: their feature row
holds a value the raw cohort never had, so the two paths *should* differ there.

Rows whose odometer is a **placeholder** (≤ 100 km or ≥ 900,000 km) are excluded for the same reason:
`Predictor` treats the sentinel as missing and imputes the age-band median, while the frozen feature
row kept the sentinel it was trained on. `tests/test_predict.py` covers that rule directly.

Rows the v2 cohort **imputed at build time** are not a parity test either: `impute_stats.json` is
fitted on `train_cohort.csv`, while the v2 cohort's imputation is a different snapshot for a few
groups (e.g. Honda|CR-V engine 1.75 L in the bundle vs 2.0 L in the cohort). That is a recorded
artefact mismatch, not a serving-path defect — the exact-parity scope and the exclusions are in
`docs/readiness_v2.md` §“Serving parity”.

## 4. Warnings a caller can rely on

| `code` | When | Severity |
|---|---|---|
| `unseen_brand_model` | the `brand\|model` never appears in training | high |
| `thin_group` | fewer than 20 training rows for the combo | medium |
| `implausible_year` | outside 1980…capture year | high |
| `placeholder_odometer` | ≤ 100 km or ≥ 900,000 km | medium |
| `deposit_suspect` | **only when the caller passes `price_vnd`**: asking < 25 % of the segment median | high |
| `engine_out_of_range` | displacement outside 0.6–8.0 L | low |
| `no_band` | the bundle was exported with `--fast` | low |

Each warning carries a `code` (stable, for a UI) and a `message` (human text). The `trace` object
reports which fields were imputed, whether the engine came from a badge parse, the trim rank and the
canonical model — the same decisions the training table made.

Two serving rules worth knowing:

- **Category matching ignores case and extra whitespace.** `brand`, `model`, the contract categorical
  columns and `location_province` are mapped to the bundle's own spelling through
  `categories.json` / `feature_stats.json`, and `known.json` is looked up the same way. `4MATIC`,
  `4Matic`, `  glc 300 4matic ` all price as the trained `GLC 300 4Matic`, so a spelling variant no
  longer raises a false `unseen_brand_model` or moves the estimate.
- **A placeholder odometer is imputed, not used.** A value ≤ 100 km or ≥ 900,000 km is blanked before
  `fill_median_by_age`, so the age-band median fills it and `trace.imputed` contains `mileage_km`,
  matching the warning text. The frozen training table kept those sentinels, which is why
  `tools/inference_smoke` skips such rows (see §3).

## 5. Usage

```python
from src.models.predict import Predictor

predictor = Predictor.load("models/v2")
predictor.predict_one({"brand": "Toyota", "model": "Camry", "manufacture_year": 2020,
                       "mileage_km": 45000, "transmission": "Số tự động", "fuel_type": "Xăng",
                       "location_province": "Hà Nội", "sub_model_trim": "2.5Q"})
# {'price_vnd': 811433362, 'p10_vnd': …, 'p50_vnd': …, 'p90_vnd': …, 'warnings': [...], 'trace': {...}}
```

```powershell
python -m src.models.predict --record '{"brand":"Toyota","model":"Camry","manufacture_year":2020}'
python -m src.models.predict --csv cars.csv --out prices.csv
python -m src.models.predict --selftest        # three built-in records, checks the warnings fire
```

`price_vnd` is an **advertised** price estimate (`docs/data_limitations.md` §1), not a transaction
price; the band is the 80 % interval from the quantile fits, and it is wider for thin groups by design.
