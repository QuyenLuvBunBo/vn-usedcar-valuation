# Plan — 3 → 10 November 2026: features, valuation models, anomaly screening, report

Work starts **Tuesday 3 November**; the dataset was frozen on 31 October. The teacher's report —
"Initial Results on Applying ML Models" — is due **Tuesday 10 November**. That is **7 working days**
for the modelling and one for the submission, so this plan is deliberately heavier per person than a
normal week: **each member owns a primary deliverable and a second one**, and the freeze date is a wall,
not a target.

Two rules make the extra scope safe, and they are not negotiable:

1. **The cut list in §6 decides what is dropped**, not a discussion on the last day.
2. **Nothing is re-crawled and no statistic is fitted on val/test.** A bigger workload never justifies
   a leak — a leaked model is worth less than a smaller honest one.

## 0. The input is frozen

| File | Rows | Use |
|---|---|---|
| `data/master/train_cohort_imputed.csv` | 70,244 | fit everything |
| `data/master/val_cohort_imputed.csv` | 14,964 | choose models, thresholds, feature sets |
| `data/master/test_cohort_imputed.csv` | 14,980 | **one** evaluation, at the freeze (Sat 7/11) |

26 columns: the 21 contract columns + `tier`, `duplicate_group_id`, `quality_flags`, `imputed`,
`model_group`. Forbidden in `X` (the gate in `tools/model_gate.py` enforces it): `price_vnd`,
`raw_price_text`, `price_status`, `listing_date`, `scraped_at`, `source_url`, `listing_id`,
`quality_flags`. Model `log1p(price_vnd)`; report metrics in log space **and** VND.

### 0.1 What already exists — build on it, do not rebuild it

| Already done | Proof / command |
|---|---|
| master, split, cohort, imputation, EDA | `python -m src.data_prep.pipeline` → `docs/week2_status.md` has every number |
| the data gates | `python -m tools.audit_master`, `python -m tools.validate_source_csv <csv>`, `python -m unittest discover -s tests` (115 tests) |
| the ML stack | `pip install -r requirements.txt` (sklearn, lightgbm, catboost, xgboost, joblib) |
| notebook conventions | `notebooks/README.md` — one folder per member, strip outputs before committing |
| **what this week adds** | `src/features/`, `src/models/`, `models/*.joblib`, `docs/benchmark.md`, the report |


## 1. Day-1 blocker — Tue 3/11, first hour

`requirements.txt` already lists the stack; the first person to hit a problem reports it in the chat
instead of fighting it alone:

```powershell
pip install -r requirements.txt
pip install xgboost catboost optuna shap      # optional; skip whatever will not build
python -c "import sklearn, lightgbm, joblib, matplotlib; print('ok')"
```

Wheels for CPython 3.14 were confirmed available (`scikit-learn 1.9.1`, `lightgbm 4.7.0`,
`joblib 1.6.0`), so a version change should not be needed.

## 2. Contracts — publish each artefact v1 by Wed 4/11, 18:00

| Artefact | Owner | Path | Consumer |
|---|---|---|---|
| Feature tables (v1) | Quyền | `data/master/{train,val,test}_features.csv` | TB2, TB3 |
| Fitted preprocessor | Phương | `models/preprocess.joblib` | TB2, TB3 |
| Benchmark table | Bảo | `data/master/model_results.json`, `docs/benchmark.md` | report §5 |
| Test predictions + intervals | Hiếu | `data/master/predictions_test.csv` (incl. `p10_vnd`, `p90_vnd`) | TB3 |
| Anomaly labels + thresholds | Phong | `data/master/anomaly_labels.csv`, `anomaly_thresholds.json` | report §7 |
| Feature importance | Duy | `data/master/feature_importance.csv` | report §5 |
| Error taxonomy | Tuấn Anh | `docs/error_taxonomy.md` | report §6–7 |

`predictions_test.csv` columns: `listing_id, duplicate_group_id, brand, model, manufacture_year,
mileage_km, location_province, source_platform, price_vnd, y_pred_log, y_pred_vnd, p10_vnd, p90_vnd,
residual, abs_pct_error`. TB3 does not refit a model.

## 3. Workload per person

### 3.0 Why LightGBM is the workhorse and CatBoost is a required row

Measured on 2026-11-02 (Python 3.14.8, Windows): `lightgbm 4.7.0` (`py3-none-win_amd64`),
`xgboost 3.4.1` (`py3-none-win_amd64`) and `catboost 1.2.10` (`cp314-cp314-win_amd64`) all have
wheels, so **none of them is ruled out by installation**. The choice is about cost per experiment:

| | LightGBM | CatBoost | XGBoost |
|---|---|---|---|
| Speed per fit on 70 k × ~60 features | fastest (histogram + leaf-wise) | slowest (ordered boosting) | middle (`tree_method=hist`) |
| High-cardinality categoricals (`brand|model` = 3,212 levels) | native, needs `categorical_feature` | **best: ordered target statistics, leakage-safe by design** | weakest (needs `enable_categorical`) |
| Defaults good enough without tuning | mostly | **yes** | no, needs tuning |
| Quantile objective (P10/P90) | `objective="quantile"` | `loss_function="Quantile:alpha=…"` | `reg:quantileerror` |

So: **LightGBM is the row that is always there** because it is the cheapest to iterate with (many
models × 2 feature sets × tuning inside a 5-day modelling window), and **CatBoost is a required row**
because it is the model whose native handling matches our weakest feature block — it removes the need
for the hand-rolled K-fold target encoding that a tree on one-hot `model` would otherwise need.
XGBoost is the third row; it is the one that drops first.

Consequence for the feature table: it carries **both** variants — `v1` (encoded, for linear/k-NN) and
`v1_raw` (raw categoricals, for LightGBM/CatBoost native handling). Feeding an already
target-encoded column to CatBoost throws away its advantage, so the model decides which table to read.

Each cell is one deliverable; **P** = primary, **S** = second. §6 says which of these are cut first.

### 3.1 Sub-team 1 — features and preprocessing (Quyền, Phương, Quyết)

| Who | P — primary | S — second |
|---|---|---|
| **Quyền** (lead) | `src/features/build_features.py`: `vehicle_age`, `km_per_year`, `age_band`, `engine_per_seat`, `brand_age_band` (interaction), `is_luxury_segment` (brand list, **not** price), platform flag | `tools/model_gate.py`: fails on a forbidden column, a column-set mismatch, or a feature correlated >0.999 with the target; plus `--ablate` (Ridge on 20 k rows, drop one feature group at a time → ΔR² table for §4) |
| **Phương** | `src/features/pipeline.py`: one-hot for ≤40 categories, ordinal for `age_band`, **target encoding of `brand|model` with inner K-fold**, scaler, missingness indicators from `imputed`; dump `models/preprocess.joblib` | `tests/test_features.py` (encoder never sees val; unseen category → global mean) + `docs/features.md` generated by `--describe` (name, dtype, formula, source column) |
| **Quyết** | `brand_retention_rate` (median price at age 1–2 vs 5–6 per brand, train only), `geo_tier`, `province_price_index` (shrunk toward the global median by count) | **Cardinality study**: Ridge R² on val with `model`, `model_group`, and target-encoded `brand|model` → one table + one paragraph that decides the week-4 encoding; plus the data caveats for §2/§8 (chotot counter, carmudi template) |

### 3.2 Sub-team 2 — valuation models (Hiếu, Bảo, Duy)

| Who | P — primary | S — second |
|---|---|---|
| **Hiếu** (lead) | `src/models/train.py --model … --features minimal|v1|full --seed …`: every metric in log space and VND, one row appended to `model_results.json`, model saved as `models/<model>_<features>.joblib` | **Quantile LightGBM** (P10/P50/P90) → `p10_vnd`, `p90_vnd` in `predictions_test.csv` (TB3 turns these into interval labels) + a **learning curve** at 10/25/50/100 % of train (one figure for §5) |
| **Bảo** | Baselines + linear family: median by `brand|model|year`, Ridge, Lasso, ElasticNet, k-NN (k=25, scaled features) | `src/models/benchmark.py` → `docs/benchmark.md` (feature set, tuning budget, one test column filled at the freeze) + **Wilcoxon signed-rank** on absolute errors vs the best model, so §5 can say whether the gain is significant |
| **Duy** | Boosters: **LightGBM** (workhorse), **CatBoost** (required row — best native handling of the 3,212-level `brand|model`), XGBoost, Random Forest; tuning time-boxed 90 min per model (RandomizedSearchCV ≤60 fits or Optuna ≤80 trials), search space written down; CatBoost capped at `iterations=3000, od_type="Iter", od_wait=100` so it fits the box | **Seed stability** (3 seeds → mean ± sd of R²) + **permutation importance** + **partial dependence** for the top-3 features → one table and one figure for §5 |

### 3.3 Sub-team 3 — anomaly detection and tagging (Phong, Tuấn Anh, Quang)

| Who | P — primary | S — second |
|---|---|---|
| **Phong** (lead) | `src/models/anomaly.py`: Δ = (ŷ − y)/y, IsolationForest on the feature table, **thresholds calibrated on val** for a review rate of 2–5 %; write `anomaly_labels.csv` + `anomaly_thresholds.json` | **Interval rules** on Hiếu's P10/P90 (`Bargain` below P10, `Overpriced` above P90, `Fair` inside, `Suspicious` = outside the interval **and** top-1 % iso score) + a detector comparison (IsoForest vs LOF vs One-Class SVM: agreement table) |
| **Tuấn Anh** | 3 case studies with URLs and numbers: a deposit-style ad, an odometer anomaly, a salvage/import anomaly | **Proxy** confusion matrix (`quality_flags` rules × `Suspicious` label, precision/recall stated as a proxy) + **error taxonomy**: inspect the 25 worst absolute errors by hand, classify the causes (trim missing, luxury segment, modified car, price typo, platform mix) → `docs/error_taxonomy.md` |
| **Quang** | Regenerate the EDA on the 100,887-row master: price by region (chotot is now 19,426), segment split (luxury vs mainstream), price-per-km, platform gap → `eda_summary.md` | 5 figures + their captions for §3, and the "what the model cannot see" note for §6 (advertised ≠ transaction price, no condition/history field) |

**Cross-review pairs** (a PR merges only after its pair comments): Quyền ↔ Hiếu · Phương ↔ Duy ·
Quyết ↔ Bảo · Phong ↔ Tuấn Anh · Quang reviews every figure.

## 4. Coordination: parallel, with three hand-offs

The tracks are **not** sequential. They meet at three dated hand-offs, and each one has a stand-in so
nobody waits:

```
TB1 features ──(1)──► TB2 models ──(2)──► TB3 labels ──(3)──► report
      ▲                   │                    │
   stand-in: the cohort  └── stand-in:         └── stand-in: labels on the
   file's raw columns        median/Ridge          baseline can be drafted
```

| Hand-off | Date | Consumer starts earlier with |
|---|---|---|
| (1) feature tables v1 + `preprocess.joblib` | **Tue 3/11, 20:00** | the cohort's raw columns (`minimal` feature set) |
| (2) predictions from the shortlisted model | **Wed 4/11 (M1)**, refreshed **Fri 6/11** | the median-by-group baseline |
| (3) final labels + figures | **Sat 7/11, 18:00 (M2)** | draft labels from the baseline |

Two discipline points that the compressed calendar makes critical:

- **TB2 freezes its shortlist on Thu 5/11, 20:00.** TB3 re-runs labels once, on Sat 7/11. If TB2
  changes model after that, TB3's labels are stale — so the shortlist date is a wall.
- **A hand-off slipping more than 4 hours means the consumer keeps its stand-in** and the owner
  delivers by the next milestone, incomplete if necessary. A stopped track is worse than a rough
  artefact.

## 5. Day by day

| Date | What must exist by the end of the day |
|---|---|
| **Tue 3/11** | Libraries installed; branches open; TB1 features v1 (+schema published); TB2 baseline + Ridge on `minimal`; TB3 Δ on the baseline. **M0 20:00**: `*_features.csv` v1 + 2 rows in `model_results.json` |
| **Wed 4/11** | `preprocess.joblib` v1 + leakage test; RF and LightGBM v1; TB3 first `anomaly_labels.csv`. **M1 20:00: ≥ 4 benchmark rows, R² on val posted in the chat** |
| **Thu 5/11** | Tuning (time-boxed); full feature set; `--ablate` table; `docs/features.md`. **TB2 shortlist frozen 20:00** |
| **Fri 6/11** | Benchmark v1 (≥ 5 models × 2 feature sets) + Wilcoxon test; quantile intervals; error taxonomy; EDA refresh + figures |
| **Sat 7/11** | **M2 18:00 — freeze**: best model fixed, **one** test evaluation, final labels, every figure exported, `model_results.json` complete |
| **Sun 8/11** | Report complete draft: all 8 sections, figures embedded, numbers cross-checked against the JSON |
| **Mon 9/11** | Two review rounds (cross-review pairs), formatting, submission dry-run, PDF exported |
| **Tue 10/11** | **Submit before 12:00** — keep the afternoon as buffer |

## 6. Cut list — what goes first if a day is lost

In this order (the last item is the first to drop). This list is the answer to "we are behind", so
nobody has to renegotiate scope at 23:00 on 9/11:

1. XGBoost (fallback: LightGBM + CatBoost stay — CatBoost is *not* on this list)
2. Partial dependence + seed stability (Duy)
3. Learning curve (Hiếu)
4. k-NN + ElasticNet (Bảo)
5. LOF / One-Class SVM comparison (Phong)
6. Feature ablation (Quyền)
7. Cardinality study (Quyết)
8. Third case study + error taxonomy narrowed to the worst 10 (Tuấn Anh)

**Never cut**: features v1/v1_raw + `preprocess.joblib`, the benchmark with median/Ridge/RF/LightGBM/
**CatBoost**, the single test evaluation, Δ labels + one case study, the EDA refresh, the report.

## 7. Definition of done

1. `python -m src.features.build_features && python -m src.models.train --model lgbm` runs from a clean
   checkout and writes the artefacts in §2.
2. `docs/benchmark.md` compares ≥ 5 models on val, states the feature set and the tuning budget, and
   has exactly one test column filled — at M2.
3. `anomaly_labels.csv` + thresholds + 3 case studies + the proxy matrix + `docs/error_taxonomy.md`.
4. `tools/model_gate.py` and the unit tests pass; a leak fails the gate instead of producing a score.
5. Every number in the report can be regenerated by a command in this repository.

## 8. Report: one writer per sub-team, one editor

Nine authors was too many: nine sections written by nine people in two days means nine voices and a
rewrite. **Three writers** — one per sub-team — assemble the text; everyone else still owns their own
numbers and hands over a five-line summary plus the table or figure by the writer's draft date.

| Writer | Sections | Draft by | Numbers come from |
|---|---|---|---|
| **Quyền** (TB1) | §1 pipeline recap, §2 data quality, §4 features | Fri 6/11 | `split_summary.json`, `normalize_report.json`, `missing_report.json`, `docs/features.md` |
| **Hiếu** (TB2) | §5 benchmark, §6 error analysis | Sat 7/11 (after M2) | `model_results.json`, `docs/benchmark.md`, `feature_importance.csv`, `docs/error_taxonomy.md` |
| **Phong** (TB3) | §3 EDA, §7 anomaly, §8 limitations | Sat 7/11 | `eda_summary.md` + figures, `anomaly_labels.csv`, `anomaly_thresholds.json`, `docs/error_taxonomy.md` |
| **Quyết** (editor) | one voice, one layout, cross-references, the PDF, the form | Mon 9/11 | — |

If a writer is short of a number, the owner hands it over the same day — silence is not an input.

## 9. Risks in a 7-day window

| Risk | Fallback |
|---|---|
| A library will not build on a teammate's machine | wheels were verified for CPython 3.14 (`lightgbm 4.7`, `xgboost 3.4`, `catboost 1.2.10`); if one still fails, `HistGradientBoostingRegressor` covers the tree row and the substitution is stated in §5 |
| R² below the 0.88 target | report the real number, explain what is missing (trim 56 % empty, engine 61 % imputed), and show the ablation that proves the features were tried |
| Tuning eats a day | the 90-minute time box per model is a rule, not a suggestion; the untuned model stays as its own row |
| A sub-team loses a day | §6 cut list, applied in order, no discussion |
| Report written in one night | impossible by design: §2–§4 are due Fri 6/11, before the freeze |
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

## 11. After the submission (week 4, not graded by this deadline)

The teacher's deadline is the report. What is left for the following week, in this order, and it needs
an owner assigned on Tue 10/11 — not before:

1. `src/models/predict.py` — one function `predict(vehicle_specs) -> price + label`, loading
   `models/preprocess.joblib` and the frozen model, so the pipeline is reproducible without a notebook.
2. Slides: 8–10 slides, one figure per claim, the benchmark table on one slide.
3. The web demo (Streamlit) — **optional**: only if 1 and 2 are finished; it is expensive to build and
   the report does not depend on it.
4. Data improvements that were deliberately deferred: chotot's remaining inventory, carmudi's 233 ads,
   and any new source. Each one requires the full rebuild: `build_master → split → pipeline`, then every
   number in the report regenerated.




