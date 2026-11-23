# vn-usedcar-valuation

Used-car **price valuation** and **listing anomaly detection** for the Vietnamese market.
Nine members collected **100,887 listings** from eight marketplaces, normalised them to one schema,
and trained a model that predicts the advertised price and flags suspicious ads.

*Introduction to Data Science — Group 14.*

## Results

| Item | Number |
|---|---|
| Master dataset | 100,887 listings · 8 platforms · 21 contract columns |
| Modelling cohort | 70,244 train / 14,964 val / 14,980 test (grouped split) |
| Model (`models/v2`) | LightGBM, 30 features, R²(log) **0.9470**, MAPE **11.25 %** full / **9.91 %** clean |
| P10–P90 band | **81.71 %** coverage (nominal 80 %), median width 118.9 M VND |
| Validation | 268 unit tests · blind test **8/8** · readiness **4/4** · parity **2.02e-09** |
| Test split | evaluated once (v1): R²(log) 0.9487, MAPE **10.9 %**, clean 10.1 % |

All prices are **advertised** prices, not transaction prices. The model is frozen: no retraining after
the Week 4 freeze (PR #17).

## Quick start

```powershell
git clone https://github.com/QuyenLuvBunBo/vn-usedcar-valuation.git
cd vn-usedcar-valuation
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt
$env:PYTHONIOENCODING='utf-8'
```

Data is not committed. Download the snapshot from Drive as described in
**[docs/data_handover.md](docs/data_handover.md)**, then rebuild the tables:

```powershell
python -m src.merge.build_master
python -m src.data_prep.split
python -m src.data_prep.pipeline
python -m src.features.build_features --features full
python -m src.features.extend --write --cohort-dir data/master/v2
python -m tools.model_gate --features data/master/v2/train_features_full.csv --quiet
python -m unittest discover -s tests -t .
```

The freeze commands are:

```powershell
python -m tools.live_blind_test                # 8/8 PASS
python -m tools.readiness_check --rows 120     # 4/4 PASS, parity 2.02e-09
python -m src.models.predict --selftest        # serving CLI OK
```

Price one car:

```powershell
python -m src.models.predict --record '{"brand":"Toyota","model":"Camry","manufacture_year":2020,"mileage_km":45000}'
```

## Repository layout

```
src/
  common/        config, HTTP session, storage, Vietnamese parsers, 21-column schema
  sources/       one package per marketplace (oto, bonbanh, chotot, carpla, muaban, …)
  merge/         build_master, dedupe
  data_prep/     split, normalize, missing-value imputation, quality flags, EDA
  features/      v1 features, v2 extension, preprocessing pipeline
  models/        benchmark, training, anomaly labels, serving Predictor
tests/           unit tests (no frozen data needed)
tools/           gates, crawlers, evaluation, live blind test, readiness check
docs/            the 15 documents listed below
data/            raw / processed / master — not committed
```

## Documentation

| Document | What it answers |
|---|---|
| [docs/evaluation.md](docs/evaluation.md) | data, label cleaning, v2 features, generalisation, backfill, model metrics, error summary |
| [docs/inference.md](docs/inference.md) | serving bundle `models/v2/`, warnings, `predict()` usage, parity |
| [docs/readiness_v2.md](docs/readiness_v2.md) | where the model is weak: price band, group thickness, trim, gearbox |
| [docs/live_blind_test_v2.md](docs/live_blind_test_v2.md) | eight unseen listings, expected warnings asserted |
| [docs/sources.md](docs/sources.md) | eight marketplaces, coverage vs catalogue, per-source caveats |
| [docs/unified_schema.md](docs/unified_schema.md) | the 21 columns, allowed values, normalisation rules |
| [docs/data_handover.md](docs/data_handover.md) | what to upload/download from Drive, checksums, verification |
| [docs/data_limitations.md](docs/data_limitations.md) | missing columns, deposit ads, odometer/import failures |
| [docs/eda_summary.md](docs/eda_summary.md) | price distribution, age/mileage, platform gap, figures |
| [docs/benchmark.md](docs/benchmark.md) · [docs/test_evaluation.md](docs/test_evaluation.md) | val benchmark and the single test evaluation |
| [docs/error_taxonomy.md](docs/error_taxonomy.md) · [docs/error_audit_25.md](docs/error_audit_25.md) | error buckets and the hand-read worst 25 |
| [docs/intervals.md](docs/intervals.md) | P10–P90 calibration |
| [docs/report_style.md](docs/report_style.md) | what belongs in the submitted report |

## Rules

- **Data is never committed.** `data/master/**`, `models/**`, `*.joblib`, `*.npz` are rebuilt or shared
  through Drive (`CONTRIBUTING.md` §6, `docs/data_handover.md`).
- **One test evaluation.** The test split is not used for tuning or model selection.
- **The serving path reads only `models/v2/`.** It cannot see `data/master`; `tests/test_predict.py`
  enforces that.
- Crawlers respect `robots.txt`, use a shared 1.5 s delay + retry/backoff, and keep raw HTML for offline
  re-parsing. Chợ Tốt's `Content-Signal` says `ai-train=no`; the project trains on the normalised
  price/spec table, not on the raw ad text.

The report PDF and slides live on Drive, not in the repository (`docs/report_style.md`).
