# Plan — 3 → 10 November 2026: features, valuation models, anomaly screening, report

> Bản Word gửi nhóm được giữ **ngoài repo** (nhóm lưu trên Drive); trang này là bản kỹ thuật, luôn mới
> nhất. Sửa một chỗ thì sửa cả hai.

Work starts **Tuesday 3 November**; the dataset was frozen on 31 October. The teacher's report —
"Initial Results on Applying ML Models" — is due **Tuesday 10 November**. That is **7 working days** for
the modelling and one for the submission, so each member owns a **primary** deliverable and a **second**
one.

## 1. The input is frozen

| File | Rows | Use |
|---|---|---|
| `data/master/train_cohort_imputed.csv` | 70,244 | fit everything |
| `data/master/val_cohort_imputed.csv` | 14,964 | choose models, thresholds, feature sets |
| `data/master/test_cohort_imputed.csv` | 14,980 | **one** evaluation, at the freeze (Sat 7/11) |

26 columns: the 21 contract columns + `tier`, `duplicate_group_id`, `quality_flags`, `imputed`,
`model_group`. Forbidden in `X` (the gate in `tools/model_gate.py` enforces it): `price_vnd`,
`raw_price_text`, `price_status`, `listing_date`, `scraped_at`, `source_url`, `listing_id`,
`quality_flags`. Model `log1p(price_vnd)`; report metrics in log space **and** VND.

### 1.1 What already exists — build on it, do not rebuild it

| Already done | Proof / command |
|---|---|
| master, split, cohort, imputation, EDA | `python -m src.data_prep.pipeline` → `docs/week2_status.md` has every number |
| **feature tables** (`minimal`, `full`) + the train-fitted statistics | `python -m src.features.build_features --features full` → `data/master/{train,val,test}_features_full.csv`, `feature_stats.json`, `features_manifest.json` |
| **leakage gate** | `python -m tools.model_gate` → `RESULT: PASS` (forbidden columns, target copies, partition drift, group crossing) |
| **canary: does training work here, and what must a model beat** | `python -m tools.baseline_smoke` → median R²(log) **0.877** vs untuned LightGBM **0.946**, MAPE 18.8 % → 11.6 % |
| the data gates | `python -m tools.audit_master`, `python -m tools.validate_source_csv <csv>`, `python -m unittest discover -s tests` (124 tests) |
| the ML stack | `pip install -r requirements.txt` (sklearn, lightgbm, catboost, xgboost, joblib) |
| notebook conventions | `notebooks/README.md` — one folder per member, strip outputs before committing |
| **still to build this week** | `src/features/pipeline.py` (encoders fitted in-fold), `src/models/train.py`, `benchmark.py`, `anomaly.py`, `models/*.joblib`, `docs/benchmark.md`, the report |

The canary number is the floor, not the target: every model in §4 has to beat **R²(log) 0.946 / MAPE
11.6 %** to justify its complexity.

## 2. Day-1 blocker — Tue 3/11, first hour

`requirements.txt` already lists the stack; the first person to hit a problem reports it in the chat
instead of fighting it alone:

```powershell
pip install -r requirements.txt
pip install optuna shap      # optional; skip whatever will not build
python -c "import sklearn, lightgbm, joblib, matplotlib; print('ok')"
```

Wheels for CPython 3.14 were confirmed available (`scikit-learn 1.9.1`, `lightgbm 4.7.0`,
`catboost 1.2.10`, `xgboost 3.4.1`), so a version change should not be needed.

## 3. Contracts — publish each artefact v1 by Wed 4/11, 18:00

| Artefact | Owner | Path | Used by |
|---|---|---|---|
| Feature tables (`minimal`, `full`) + manifest | Quyền | `data/master/{train,val,test}_features_<variant>.csv` + `features_manifest.json` | T2, T3 |
| Fitted preprocessor | Phương | `models/preprocess.joblib` | T2, T3 |
| Benchmark table | Bảo | `data/master/model_results.json`, `docs/benchmark.md` | report §5 |
| Predictions + quantile intervals | Hiếu | `data/master/predictions_{val,test}.csv` — val handed over on Wed, test only at M2 (Sat) | T3 |
| Anomaly labels + thresholds | Phong | `data/master/anomaly_labels.csv`, `anomaly_thresholds.json` | report §7 |
| Feature importance | Duy | `data/master/feature_importance.csv` | report §4 |
| Error taxonomy | Tuấn Anh | `docs/error_taxonomy.md` | report §6–7 |

`predictions_*.csv` columns: `listing_id, duplicate_group_id, brand, model, manufacture_year,
mileage_km, location_province, source_platform, price_vnd, y_pred_log, y_pred_vnd, p10_vnd, p90_vnd,
residual, abs_pct_error`. T3 does not refit a model.

## 4. Assignment — two deliverables per person

**P** = primary (must finish), **S** = second (cut first if a day is lost, see §6).

### 4.1 Team 1 — features and preprocessing (Quyền, Phương, Quyết)

| Who | P — primary | S — second |
|---|---|---|
| **Quyền** (lead) | `src/features/build_features.py`: `vehicle_age`, `km_per_year`, `age_band`, `engine_per_seat`, `brand_age_band`, `is_luxury_segment` (brand list, **not** price), platform flag; emits `minimal` and `full` | `tools/model_gate.py` (done) + `--ablate` (Ridge on 20 k rows, drop one feature group at a time → ΔR² table for report §4) |
| **Phương** | `src/features/pipeline.py`: one-hot for ≤40 categories, ordinal for `age_band`, **target encoding of `brand|model` with inner K-fold**, scaler, missingness indicators from `imputed`; dump `models/preprocess.joblib` | `tests/test_features.py` (encoder never sees val; unseen category → global mean) + `docs/features.md` generated by `--describe` |
| **Quyết** | `province_price_index`, `geo_tier` and the cardinality study — see note below | `docs/features.md` review + the data caveats for the report (§8 limitations) |

`brand_retention_rate`, `province_price_index` and `province_group` are **already computed** by
`build_features.py`, fitted on train only and stored in `feature_stats.json`; Quyết's remaining job is
the cardinality study (`model` vs `model_group` vs target-encoded `brand|model`) and documenting the
formulas.

### 4.2 Team 2 — valuation models (Hiếu, Bảo, Duy)

| Who | P — primary | S — second |
|---|---|---|
| **Hiếu** (lead) | `src/models/train.py --model … --features minimal|full --seed …`: every metric in log space and VND, one row appended to `model_results.json`, model saved as `models/<model>_<features>.joblib` | **Quantile LightGBM** (P10/P50/P90) → `p10_vnd`, `p90_vnd` in `predictions_{val,test}.csv` + a **learning curve** at 10/25/50/100 % of train |
| **Bảo** | Baselines + linear family: median by `brand|model|year`, Ridge, Lasso, ElasticNet, k-NN (k=25, scaled) | `src/models/benchmark.py` → `docs/benchmark.md` + **Wilcoxon signed-rank** on absolute errors vs the best model |
| **Duy** | Boosters: **LightGBM** (workhorse), **CatBoost** (required row — native handling of the 3,212-level `brand|model`; cap `iterations=3000, od_type="Iter", od_wait=100`), XGBoost, Random Forest; tuning time-boxed **90 min per model** (RandomizedSearchCV ≤60 fits or Optuna ≤80 trials) | **Seed stability** (3 seeds → mean ± sd of R²) + **permutation importance** + **partial dependence** for the top-3 features |

### 4.3 Team 3 — anomaly detection and tagging (Phong, Tuấn Anh, Quang)

| Who | P — primary | S — second |
|---|---|---|
| **Phong** (lead) | `src/models/anomaly.py`: Δ = (ŷ − y)/y, IsolationForest, **thresholds calibrated on val** for a review rate of 2–5 %; write `anomaly_labels.csv` + `anomaly_thresholds.json` | **Interval rules** on P10/P90 (`Bargain` below P10, `Overpriced` above P90, `Fair` inside, `Suspicious` = outside **and** top-1 % iso score) + detector comparison (IsoForest vs LOF vs One-Class SVM) |
| **Tuấn Anh** | 3 case studies with URLs and numbers: a deposit-style ad, an odometer anomaly, a salvage/import anomaly | **Proxy** confusion matrix (`quality_flags` × `Suspicious`, stated as a proxy) + **error taxonomy**: inspect the 25 worst absolute errors → `docs/error_taxonomy.md` |
| **Quang** | Regenerate the EDA on the 100,887-row master: price by region (chotot is now 19,426), segment split, price-per-km, platform gap → `eda_summary.md` | 5 figures + captions for report §3, and the "what the model cannot see" note for §6 |

**Cross-review pairs** (a PR merges only after its pair comments): Quyền ↔ Hiếu · Phương ↔ Duy ·
Quyết ↔ Bảo · Phong ↔ Tuấn Anh · Quang reviews every figure.

## 5. Coordination: parallel, with three hand-offs

The tracks are **not** sequential. They meet at three dated hand-offs, and each one has a stand-in so
nobody waits:

| Hand-off | Date | Consumer starts earlier with |
|---|---|---|
| (1) feature tables (`minimal`, `full`) + `preprocess.joblib` | **Tue 3/11, 20:00** | the cohort's raw columns (`minimal` feature set) |
| (2) predictions from the shortlisted model | **Wed 4/11 (M1)**, refreshed **Fri 6/11** | the median-by-group baseline |
| (3) final labels + figures | **Sat 7/11, 18:00 (M2)** | draft labels computed on the baseline |

- **T2 freezes its shortlist on Thu 5/11, 20:00.** T3 re-runs labels once, on Sat 7/11. If T2 changes
  model after that, T3's labels are stale — so the shortlist date is a wall.
- **A hand-off slipping more than 4 hours means the consumer keeps its stand-in** and the owner
  delivers by the next milestone, incomplete if necessary.

## 6. Day by day and the cut list

| Date | What must exist by the end of the day |
|---|---|
| **Tue 3/11** | Libraries installed; branches open; T1 publishes the column list (tables already built: `minimal` + `full`); T2 baseline + Ridge on `minimal`; T3 Δ on the baseline. **M0 20:00**: 2 rows in `model_results.json` |
| **Wed 4/11** | `preprocess.joblib` v1 + leakage test; LightGBM and CatBoost v1; T3 first `anomaly_labels.csv`. **M1 20:00: ≥ 4 benchmark rows, R² on val posted in the chat** |
| **Thu 5/11** | Tuning (time-boxed); full feature set; `--ablate` table; `docs/features.md`. **T2 shortlist frozen 20:00** |
| **Fri 6/11** | Benchmark v1 (≥ 5 models × 2 feature sets) + Wilcoxon test; quantile intervals; error taxonomy; EDA refresh + figures |
| **Sat 7/11** | **M2 18:00 — freeze**: best model fixed, **one** test evaluation, final labels, every figure exported, `model_results.json` complete |
| **Sun 8/11** | Report complete draft: every section, figures embedded, numbers cross-checked against the JSON |
| **Mon 9/11** | Two review rounds (cross-review pairs), formatting, submission dry-run, PDF exported |
| **Tue 10/11** | **Submit before 12:00** — keep the afternoon as buffer |

Cut order when a day is lost (drop from the top):

1. XGBoost (LightGBM and CatBoost stay — CatBoost is **not** on this list)
2. Partial dependence + seed stability (Duy)
3. Learning curve (Hiếu)
4. k-NN + ElasticNet (Bảo)
5. LOF / One-Class SVM comparison (Phong)
6. Feature ablation (Quyền)
7. Cardinality study (Quyết)
8. Third case study + error taxonomy narrowed to the worst 10 (Tuấn Anh)

**Never cut**: the feature tables (`minimal` + `full`) + `preprocess.joblib`, the benchmark with
median/Ridge/RF/LightGBM/**CatBoost**, the single test evaluation, Δ labels + one case study, the EDA
refresh, the report.

## 7. Goals — what "done" means

1. `python -m src.features.build_features && python -m src.models.train --model lgbm` runs from a clean
   checkout and writes the artefacts in §3.
2. `docs/benchmark.md` compares ≥ 5 models on val, states the feature set and the tuning budget, and
   has exactly one test column filled — at M2.
3. `anomaly_labels.csv` + thresholds + 3 case studies + the proxy matrix + `docs/error_taxonomy.md`.
4. `tools/model_gate.py` and the unit tests pass; a leak fails the gate instead of producing a score.
5. Every number in the report can be regenerated by a command in this repository.

## 8. Report — 3 writers and 1 editor

Three writers, one per team; everyone else still owns their numbers and hands over a five-line summary
plus the table or figure by the writer's draft date.

| Writer | Sections | Draft by | Numbers come from |
|---|---|---|---|
| **Quyền** (T1) | §1 pipeline recap, §2 data quality, §4 features | Fri 6/11 | `split_summary.json`, `normalize_report.json`, `missing_report.json`, `docs/features.md` |
| **Hiếu** (T2) | §5 benchmark, §6 error analysis | Sat 7/11 (after M2) | `model_results.json`, `docs/benchmark.md`, `feature_importance.csv`, `docs/error_taxonomy.md` |
| **Phong** (T3) | §3 EDA, §7 anomaly, §8 limitations | Sat 7/11 | `eda_summary.md` + figures, `anomaly_labels.csv`, `anomaly_thresholds.json` |
| **Quyền** (editor) | one voice, one layout, cross-references, the PDF, the form | Mon 9/11 | — |

If a writer is short of a number, the owner hands it over the same day — silence is not an input.

## 9. Risks in a 7-day window

| Risk | Fallback |
|---|---|
| A library will not build on a teammate's machine | wheels were verified for CPython 3.14 (`lightgbm 4.7`, `xgboost 3.4`, `catboost 1.2.10`); if one still fails, `HistGradientBoostingRegressor` covers the tree row and the substitution is stated in report §5 |
| R² below the 0.88 target | the canary already reaches 0.946 on val, so a low number means a bug, not a weak feature set: check the gate, then report the real number and explain what is missing (trim 56 % empty, engine 61 % imputed) |
| Tuning eats a day | the 90-minute time box per model is a rule, not a suggestion; the untuned model stays as its own row |
| A team loses a day | §6 cut list, applied in order, no discussion |
| Report written in one night | impossible by design: report §1, §2 and §4 are due Fri 6/11, before the freeze |
| Someone proposes more data | after 10/11 — the split and every number would have to be rebuilt |

## 10. Checklist before submitting

- [ ] `pip install -r requirements.txt` works on a machine that is not mine
- [ ] `model_results.json`: every model, its feature set, its tuning budget
- [ ] exactly one test column filled, at M2 (Sat 7/11)
- [ ] `anomaly_labels.csv` + `anomaly_thresholds.json` + 3 case studies with URLs
- [ ] `docs/benchmark.md`, `docs/features.md`, `docs/error_taxonomy.md` exist and are current
- [ ] the report states: advertised price ≠ transaction price, and the three data limitations
- [ ] every figure/table reproducible by a command in the repo
- [ ] file format, page count, file name and submitter confirmed against the teacher's form
- [ ] submitted before 12:00 on Tue 10/11



