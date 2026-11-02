# Week 3 plan — features, valuation models, anomaly screening (31 Oct – 6 Nov 2026)

> Bản Word gửi nhóm/giảng viên được giữ **ngoài repo** (nhóm lưu trên Drive) để kho mã không chứa file
> nhị phân; nội dung kỹ thuật đầy đủ và luôn mới nhất nằm ở trang này.

This is the week the teacher's request depends on: **"Initial Results on Applying ML Models"**, due
**10/11/2026**. Week 3 produces the numbers and the model files; 7–10 November is the report, the
review and the submission. Everyone should be able to answer "what do I hand over, and when" from
this page.

## 0. The input is frozen — do not collect data this week

| File | Rows | Use |
|---|---|---|
| `data/master/train_cohort_imputed.csv` | 70,244 | fit everything |
| `data/master/val_cohort_imputed.csv` | 14,964 | choose models and thresholds |
| `data/master/test_cohort_imputed.csv` | 14,980 | **one** evaluation, at the freeze |

26 columns: the 21 contract columns + `tier`, `duplicate_group_id`, `quality_flags`, `imputed`,
`model_group`. The cohort already excludes implausible prices/years/mileage (see
`docs/week2_status.md`); `model_group` has the rare models collapsed to `Other`; `imputed` says which
cells were filled.

Rules that the report will be checked against:

1. **Target is `price_vnd`.** Never in `X`. Also never in `X`: `raw_price_text`, `price_status`,
   `listing_date`, `scraped_at`, `source_url`, `listing_id`, `quality_flags`.
2. **Every learned statistic is fitted on train only** — imputation is already done, but encoders,
   target encodings, scalers and the `Brand_Retention_Rate` aggregation are not. `val` and `test` are
   transformed, never fitted.
3. **Never re-crawl or rebuild the split this week.** A new crawl changes `duplicate_group_id`, so the
   numbers in the report would stop matching the data. Improvements to the source go in after 10/11.
4. Model the target as `log1p(price_vnd)` and report metrics in both log space and VND.

## 1. Day-1 blocker, everyone (Sat 31 Oct)

```powershell
pip install scikit-learn lightgbm joblib          # required
pip install xgboost catboost optuna shap          # optional, only if the wheel installs on Windows
python -c "import sklearn, lightgbm, joblib; print('ok')"
```

`requirements.txt` is a shared file: one PR adds these lines (owner: **Hiếu**, reviewers: Quyền,
Phương). Until that PR lands, nobody adds an import that fails on a clean checkout.

## 2. Contracts between the three tracks

Parallel work only merges if the artefacts have a fixed name and shape. These are the interfaces; the
owner publishes the first version by Monday 2 November and tells the others in the group chat.

| Artefact | Owner | Path | Consumed by |
|---|---|---|---|
| Feature tables | TB1 (Quyền) | `data/master/{train,val,test}_features.csv` | TB2, TB3 |
| Fitted preprocessor | TB1 (Phương) | `models/preprocess.joblib` | TB2, TB3 |
| Benchmark table | TB2 (Bảo) | `data/master/model_results.json` + `docs/benchmark.md` | report §5 |
| Test predictions | TB2 (Hiếu) | `data/master/predictions_test.csv` | TB3 |
| Anomaly labels | TB3 (Phong) | `data/master/anomaly_labels.csv` | report §7 |

`predictions_test.csv` must carry: `listing_id, duplicate_group_id, brand, model, manufacture_year,
mileage_km, location_province, source_platform, price_vnd, y_pred_log, y_pred_vnd, residual,
abs_pct_error`. TB3 does not refit a model; it reads this file.

## 3. Sub-team 1 — feature engineering and preprocessing (Quyền, Quyết, Phương)

Goal: one feature table plus the fitted pipeline that produces it, both reproducible from a command.

| Who | Task | Done when |
|---|---|---|
| **Quyền** (lead) | `src/features/build_features.py`: `vehicle_age`, `km_per_year`, `is_luxury_segment`, `platform_*` flags, price-per-km, and the guard `tools/model_gate.py` that fails if a forbidden column reaches `X` | `python -m src.features.build_features --split all` writes the three feature tables and prints row/column counts; the gate exits 1 on a leak |
| **Phương** | `src/features/pipeline.py`: `ColumnTransformer` — one-hot for the low-cardinality columns, ordinal/target encoding for `brand|model` (fit **inside** the training fold), scaler for the numerics, missingness indicators from `imputed`; dump to `models/preprocess.joblib` | fitting on train and transforming val/test runs in one command; a test proves the encoder never sees val |
| **Quyết** | `brand_retention_rate` (median price per brand × age band, train only) and `geo_tier` (big city / other, from `location_province`), plus the cardinality decision for `model` vs `model_group` | both features documented in the report with the formula and the train-only rule stated |

Report note TB1 must produce: a short table of every feature, its formula, and why it should matter.

## 4. Sub-team 2 — supervised valuation models (Hiếu, Bảo, Duy)

Goal: a benchmark table that answers "which model, how good, and what does it get wrong".

| Who | Task | Done when |
|---|---|---|
| **Hiếu** (lead) | `src/models/train.py --model … --features minimal|full`: load a feature table, fit, score, save `models/<name>.joblib`; metrics R², RMSE, MAE, MAPE in log space **and** VND; deterministic seed | one command per model; the run writes its row into `model_results.json` |
| **Bảo** | baselines and linear models: median-by-`brand|model|year`, Ridge, Lasso; `src/models/benchmark.py` builds the markdown table from `model_results.json` | the table has ≥ 4 rows (baseline + 3) and is committed as `docs/benchmark.md` |
| **Duy** | tree models: Random Forest, LightGBM (+ XGBoost/CatBoost if they install) and tuning with `RandomizedSearchCV` (≤ 40 fits) or Optuna (≤ 50 trials); feature importance / permutation importance | best model chosen on **val**, with the tuning budget and search space written down |

Hard rules: choose on val, touch test once at the freeze; a model is compared only on the same feature
set and the same split; report the tuning budget (a model that was not tuned must say so).

## 5. Sub-team 3 — anomaly detection and market tagging (Phong, Tuấn Anh, Quang)

Goal: from the best model's residuals, a defensible label per listing plus the evidence behind it.

| Who | Task | Done when |
|---|---|---|
| **Phong** (lead) | `src/models/anomaly.py`: relative error Δ = (y_pred − y)/y, `IsolationForest` on the feature table, and the four labels `Bargain Deal / Fair Value / Overpriced / Suspicious`; thresholds chosen on val | `data/master/anomaly_labels.csv` with `listing_id, delta, iso_score, label, reason`; threshold table in the report |
| **Tuấn Anh** | two case studies (a deposit-style ad, an odometer anomaly) plus a **proxy** confusion matrix: the `quality_flags` rules as "known suspects" vs the model's `Suspicious` label; state explicitly that it is a proxy, not ground truth | a small matrix (rule × model) and two listings quoted with their URLs and numbers |
| **Quang** | EDA update with the new 100,887-row master: price by region (chotot now has 19,426), price gap between platforms, and the 3–4 figures the report's §3 reuses; keep the scripts re-runnable | `data/master/eda/eda_summary.md` regenerated + the figures listed in the report |

Warning to keep in the text: a low asking price alone is **not** proof of a bargain, and a high
residual is **not** proof of fraud. Labels are a review queue.

## 5b. How the three tracks run: in parallel, with two hard hand-offs

The work is **not** sequential (TB1 → TB2 → TB3). The three tracks only depend on each other through
two artefacts, and both have a stand-in that lets the consumer start on day 1:

```
TB1 features ──(1)──► TB2 models ──(2)──► TB3 anomaly labels
      ▲                   │                      │
      └── stand-in: the cohort file itself, whose raw columns already support a baseline
                          └── stand-in: the median/Ridge predictions from M1
```

| Hand-off | Date | Consumer starts earlier with |
|---|---|---|
| (1) feature tables + `preprocess.joblib` v1 | **Sun 1/11, end of day** | the raw cohort columns (`manufacture_year`, `mileage_km`, `engine_capacity`, `seats`, `brand`, `model`, `body_type`) — that is the `minimal` feature set |
| (2) test predictions from a chosen model | **Tue 2/11 (M1), refreshed on Thu 4/11** | the median-by-group baseline, which needs no fitted pipeline at all |

Why not plain sequential: the calendar gives six working days, and 2 (features) + 3 (models) + 2
(anomaly) = seven. A single slip anywhere then lands on the report date, and the report is what is
graded. In parallel, a slip costs one team a day, not the deadline.

Why not fully parallel either: without §5's fixed artefact names and the two hand-off dates, three
tracks produce three incompatible tables and the merge at the freeze is a rewrite. So the rule is
**parallel execution, sequential interfaces** — the interface is fixed on day 1, the work is not.

Escalation rule: if a hand-off slips by more than one day, the consumer does not wait — it keeps using
its stand-in and the owner delivers the artefact by the next milestone, even if incomplete (missing
columns are better than a stopped track). Anyone who is blocked says so in the group chat the same day.


## 6. Day by day

| Date | Milestone |
|---|---|
| Sat 31/10 | Libraries installed; `requirements.txt` PR opened; every member branches off `main`; TB1 publishes the feature-table column list |
| Sun 1/11 | TB1 builds the feature tables; TB2 runs the median baseline + Ridge on `minimal`; TB3 computes Δ from the baseline predictions |
| **Mon 2/11** | **M1 — first number**: `model_results.json` has ≥ 3 rows and Duy can quote R² on val. Post it in the group chat |
| Tue 3/11 | Tree models running; `preprocess.joblib` v1; TB3 has a first `anomaly_labels.csv` |
| Wed 4/11 | Tuning; full feature set; TB2 error analysis by brand/segment/platform |
| Thu 5/11 | Benchmark v1 complete (≥ 5 models × 2 feature sets); figures for the report |
| **Fri 6/11** | **M2 — freeze**: best model fixed, **one** test evaluation, every number in `model_results.json`; nobody changes a feature after this |
| Sat 7/11 – Mon 9/11 | Report written section by section (§8), reviewed twice; dry-run of the submission |
| **Tue 10/11** | Submit the form before 12:00 |

## 7. Definition of done (week 3)

1. `python -m src.features.build_features && python -m src.models.train --model lgbm` runs from a clean
   checkout and writes the artefacts in §2.
2. `docs/benchmark.md` compares ≥ 5 models on val, states the feature set and the tuning budget, and
   has exactly one test column filled at the freeze.
3. `anomaly_labels.csv` + threshold table + 2 case studies + the proxy confusion matrix exist.
4. `tools/model_gate.py` and the unit tests pass; a leak makes it fail rather than produce a score.
5. Every number quoted in the report can be regenerated by a command in this repository.

## 8. Who writes which report section (7–10/11)

| Section | Writer | Content |
|---|---|---|
| §1 pipeline recap | Quyền | 8 platforms, 100,887 records, dedupe, the split, why grouped |
| §2 data quality | Hiếu | missing rates, the 5 repairs, cohort exclusions with reasons |
| §3 EDA | Quang | price distribution, age curve, odometer, platform gap |
| §4 features | Phương | feature table, encoders, leakage controls |
| §5 benchmark | Duy | model comparison, tuning, the winner and why |
| §6 error analysis | Bảo | residual by brand, segment, platform; what the model cannot see |
| §7 anomaly | Phong | Δ, IsolationForest, thresholds, case studies |
| §8 limitations | Tuấn Anh | advertised ≠ transaction price, chotot counter mismatch, carmudi template, engine 61 % filled |
| Editing, formatting, submission | Quyết | one voice, one layout, the form, the deadline |

## 9. Risks and fallbacks

| Risk | Fallback |
|---|---|
| LightGBM/CatBoost will not install on Windows | `HistGradientBoostingRegressor` from scikit-learn is the tree model; note the substitution |
| R² below the 0.88 target | report the true number, add the log target + target encoding, and explain what is missing (trim 56 % empty, engine 61 % imputed) |
| Tuning takes too long | cap at 40 randomised fits, report the budget, keep the untuned model as the baseline row |
| A sub-team stalls | the interface in §2 is the contract: the others can proceed with the artefact's stub as long as its columns are respected |
| Someone needs more data | not this week. Data changes after 10/11, then the split and every number are rebuilt once, deliberately |

