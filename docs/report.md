# Week 3 report — used-car valuation and listing screening

## Abstract

We built a used-car price guide and a screening layer for Vietnamese listings, from **100,887 ads across
eight platforms**, frozen as a snapshot on 31 October 2026. We model `log1p(price_vnd)` and split the data
by duplicate group instead of by row, so the same car posted on four sites cannot show up on both sides of
the split. On validation (14,964 listings) a tuned LightGBM with the full feature set reaches **R²(log)
0.9471**, with **MAPE 11.4%** and a **median absolute percentage error of 6.2%**: a typical ad gets a price
within about 6% of what the seller is asking, and the global-median baseline (0.8773) is beaten by seven
points. We scored the **test split exactly once**, after freezing the model and its parameters: **R²(log)
0.9487, MAPE 10.9%, median APE 6.1%**, and the 80% price band covered **81.9%** of asking prices. The same
band, plus an Isolation Forest, gives every validation listing one of four labels: **81.7% Fair, 8.9%
Bargain, 8.9% Overpriced, 0.6% Suspicious**. That last one is 83 ads for a human to read — which is the
whole point of the screening layer. Two things matter more than the score. The ceiling here is **data, not
modelling**: nine model families sit inside 0.937–0.947, fifty tuning fits buy +0.0009, and the learning
curve is still climbing at 70,000 rows. And the honest headline is not the leaderboard: `Bargain` does not
mean "buy this", the worst errors are deposit-style prices rather than model failures, and any future model
change has to be reported as a limitation, because the holdout has been spent.

Every number below is what the artefact produced on the frozen splits. Nothing was re-run, re-selected or
rounded toward a nicer figure after the test split was opened. There is one number that is optimistic
because it was chosen on validation, and §8.2 says which and by how much.

## Headline numbers

| | Value | Section |
| --- | --- | --- |
| Model shipped | LightGBM, `full` features, frozen tuned parameters | §5.1 |
| Validation (14,964 listings) | R²(log) **0.9471** · MAPE **11.4%** · median APE **6.2%** · MAE **82.1 million VND** | §5.1 |
| Test (14,980 listings, evaluated once) | R²(log) **0.9487** · MAPE **10.9%** · median APE **6.1%** · MAE **89.7 million VND** | §5.2 |
| 80% price interval on test | covers **81.9%** of asking prices | §5.2, §7 |
| Listings flagged on val | **8.9%** Bargain · **8.9%** Overpriced · **0.6%** Suspicious | §7 |
| Canary floor (`median` 0.8773 → floor 0.946) | beaten by **+0.0011** R² and **−0.2** points MAPE — real, and small | §5.1, §8.2 |

| Section | Numbers come from | Command that regenerates them |
| --- | --- | --- |
| 1 Pipeline | `split_summary.json` | `python -m src.data_prep.pipeline` |
| 2 Data quality | `missing_report.json`, `normalize_report.json` | `python -m src.data_prep.missing` |
| 3 EDA | `docs/eda_summary.md` + 5 figures | `python -m tools.eda_summary` |
| 4 Features | `feature_ablation.json`, `cardinality_study.json`, `model_extras.json` | `python -m src.features.build_features --ablate` · `python -m tools.model_extras` |
| 5.1 Benchmark | `docs/benchmark.md` | `python -m src.models.benchmark` |
| 5.2 Test | `docs/test_evaluation.md` | `python -m src.models.train --split test --at-m2` |
| 6 Errors | `docs/error_taxonomy.md`, `docs/case_studies.md` | `python -m tools.error_report` |
| 7 Labelling | `anomaly_labels.csv`, `anomaly_thresholds.json` | `python -m src.models.anomaly` |
| 8 Limitations | — | — |
| 9 Conclusions | — | — |
| A Reproduction | — | `python -m tools.clean_check` |
| B Artefact inventory | `data/master/*` | see the table in B |
| C Metric glossary | — | — |

## 1. Pipeline

We froze the dataset on 31 October and have not touched it since. `master_clean_dataset.csv` (100,887 rows)
goes through `src.data_prep.pipeline`, which splits by `duplicate_group_id` (seed 42), then takes the cohort
and imputes, then builds `{train,val,test}_features_{minimal,full}.csv`. The split comes out at **70.1% /
14.93% / 14.97%** (70,244 / 14,964 / 14,980 rows once features are built). There are **75,496 duplicate
groups** and none of them straddles two splits, so a car cross-posted on four sites cannot sit in both train
and val.

Four checks run before a number is allowed into this report:

| Check | Command | Result on this snapshot |
| --- | --- | --- |
| Merged dataset | `python -m tools.audit_master` | see the last run log |
| Source contract | `python -m tools.validate_source_csv` | PASS per source |
| Feature leak | `python -m tools.model_gate` | PASS — no forbidden column, no copy of the target, all three partitions share one column set, no group straddles a split |
| Unit tests | `python -m unittest discover -s tests` | 180 tests, OK (2026-11-08) |

Every model fits `log1p(price_vnd)`, and we report each metric in **both** log and VND space, so no model
gets to show only the flattering number. The test split is scored **once** — that story is in §5.2.

## 2. Data quality

- **100,887 rows** in the master, **100,868 with a price**. We drop the 19 without one instead of imputing —
  you do not invent the thing you are predicting.
- **75,496 duplicate groups** across 100,887 ads, so cross-posting is real. Splitting by group is what stops
  val and test from being inflated by the same car listed on several sites.
- **Missing rates on train**: `engine_capacity` **61.2%**, `sub_model_trim` **55.7%**, `seller_type`
  **34.1%**, `origin` **28.6%**, `seats` **21.3%**, `body_type` **18.6%**, `mileage_km` **12.7%**,
  `fuel_type` 0.7%, `transmission` 1.5%. The first two are a real limit on what the model can do, not an
  implementation detail — `docs/data_limitations.md` has the full list.
- **Brand names**: 164 spellings collapse to **146 brands** (`Hyundai`/`HYUNDAI`,
  `Mercedes Benz`/`Mercedes-Benz`, `VinFast`/`Vinfast`, `LandRover`/`Land Rover`). Skip this and the brand
  column is noise, with 18 brands split in two.
- **10,906 train rows** carry at least one `quality_flags` entry. The model never sees the flag — it is
  banned as a feature — so those rows are learned like any other. The flag is our judgement about the ad,
  not a property of the car.
- **Prices on train**: median 520 million, P10 199 million, P90 1.479 billion VND.
- **Volume by source**: bonbanh 21,223 · oto.com.vn 20,764 · chotot 13,631 (19,428 overall) · tinbanxe
  5,355 · muaban 4,921 · carpla 2,932 · vucar 1,515 · **carmudi 366**.

## 3. What the data looks like (EDA)

Source: `data/master/master_clean_dataset.csv` — **100,887 ads** before the price window, **100,803** after
keeping 10 million to 50 billion VND. The 84 dropped rows (0.08%) are all deposit-style placeholders or
typos; the raw maximum was 465 trillion VND. Province names get cleaned before anything is counted (case-
and accent-insensitive, plus an alias table), otherwise `TP HCM` and `TP.HCM` count as two markets and every
regional number is wrong.

### 3.1 Five figures, and the number each one has to justify

| Figure | What it shows | The number to remember |
| --- | --- | --- |
| `fig1_price_distribution.png` | price distribution | right-skewed even inside the window ⇒ every model fits `log1p(price_vnd)`, and R²(VND) always looks better than R²(log) |
| `fig2_price_by_source.png` | median price by platform | 420 million (muaban.net) → 645 million (carpla): **×1.54** |
| `fig3_price_by_province.png` | median price by province | TP.HCM 38,271 + Hà Nội 33,079 = **71%** of volume; top-12 median spread **×1.7** |
| `fig4_price_by_year.png` | median price by model year | 225 million (2010) → 699 million (2025), rising almost monotonically |
| `fig5_price_per_km_by_segment.png` | price per 1,000 km by segment | segments spread **×9.4** on price per km against **×3.5** on absolute price |

**Figure 1 — price distribution.** The right tail survives the price window, which is why every model in
§5 fits a log target.

![Price distribution](figures/fig1_price_distribution.png)

**Figure 2 — median price by platform.** A factor of 1.54 between the cheapest and dearest platform with
at least 500 listings.

![Median price by platform](figures/fig2_price_by_source.png)

**Figure 3 — median price by province.** The two largest markets carry 71% of the volume; the top-12
median spread is 1.7×.

![Median price by province](figures/fig3_price_by_province.png)

**Figure 4 — median price by model year.** The depreciation curve the model has to learn, 2010–2026.

![Median price by model year](figures/fig4_price_by_year.png)

**Figure 5 — price per 1,000 km by segment.** Segments spread 9.4× on this ratio against 3.5× on
absolute price, so mileage does not normalise a segment away.

![Price per 1,000 km by segment](figures/fig5_price_per_km_by_segment.png)

### 3.2 Three readings that change later sections

1. **Price per km splits the segments more than absolute price does — and mileage is still weak.**
   Look at the ten segments with at least 900 ads: price per 1,000 km runs from 4.6 million (Hatchback) to
   42.7 million (Coupe), **×9.4**, while absolute price only runs from 265 million to 934 million, **×3.5**.
   So mileage does not "normalise" a segment away. For the model itself, §4.2 measures what dropping
   `mileage_km` and `km_per_year` actually costs: **ΔR² 0.0001**.
2. **`body_type` is missing on 18.2% of the window (18.6% of train)** — a fifth of the market cannot be put
   in a segment at all, so every "by segment" sentence in this report is about the other 82%.
3. **Small platforms differ in distribution, not just in volume.** carmudi has 546 ads, vucar 2,124, carpla
   4,179 — yet carpla's median asking price is 1.54× muaban's. That is why §6 reports error per platform
   instead of one MAPE, and why §8.1 says carmudi is too small to stand as its own segment.

### 3.3 What the model cannot see

The asking price, not the transaction price; no accident, service, ownership or legal history; four rows
carry a model year that cannot be real (1025, 2028, 2030, 2032) and nine have none at all; `engine_capacity`
is missing on 61.2% of train, so a large share of cars cannot be told apart by displacement. We carry these
into §6 and §8.1 instead of treating them as noise.

## 4. Features

### 4.1 Two tables, one whitelist

- **minimal** — raw columns plus vehicle age: `manufacture_year`, `mileage_km`, `engine_capacity`,
  `seats`, `vehicle_age`, and the original categoricals.
- **full** — adds `km_per_year`, `engine_per_seat`, `age_band`, `brand_age_band`, `is_luxury_segment`
  (a brand list, **not** a price rule), `province_group`, `brand_retention_rate`, `province_price_index`,
  `n_imputed`.

Any statistic used to build a feature (encoders, price indices, retention rates) is fitted on **train only**
and then applied to val/test. `tools.model_gate` checks the result afterwards for a leaked or copied target.

### 4.2 Group ablation — what each feature group is worth

We drop one group at a time and refit Ridge on 20,000 rows, as assigned. ΔR² is how much R²(log) falls when
the group goes, measured against a **0.9184** baseline:

| Group dropped | Columns | R²(log) left | ΔR² |
| --- | --- | ---: | ---: |
| timing | `manufacture_year`, `vehicle_age`, `age_band`, `brand_age_band` | 0.7904 | **+0.1280** |
| cat_identity | `brand`, `model`, `model_group` | 0.8656 | **+0.0528** |
| cat_spec | `transmission`, `fuel_type`, `origin`, `body_type`, `seller_type` | 0.9109 | +0.0075 |
| size | `engine_capacity`, `engine_per_seat`, `seats` | 0.9149 | +0.0035 |
| source | `source_platform` | 0.9154 | +0.0030 |
| flags | `n_imputed`, `is_luxury_segment` | 0.9169 | +0.0015 |
| usage | `mileage_km`, `km_per_year` | 0.9183 | +0.0001 |
| geo | `province_group`, `province_price_index`, `brand_retention_rate` | 0.9187 | −0.0003 |

Two readings, both against what we expected going in, so both go in plainly:

1. **Age and identity are 90% of the value** (ΔR² 0.1280 + 0.0528). Dropping mileage moves R² by 0.0001 —
   in this dataset the odometer is simply not a pricing signal, however much it feels like one.
2. **The geo group adds nothing** (ΔR² is slightly negative). That backs the decision to keep the two price
   statistics out of the default preprocessor: dropping them costs nothing and takes away a target leak
   waiting to happen.

### 4.3 Cardinality: categorical beats target encoding here

From `docs/cardinality_research.md` (LightGBM on 20,000 rows, only the brand/model encoding changes):
`brand`+`model` as categorical **0.9319** · `model_group` **0.9313** · `model` **0.9304** · out-of-fold
target encoding **0.9178**. At this cardinality — 1,912 models, 103–146 brands — target encoding **does not
win**. It is a variance-control trick for linear models, not an accuracy gain, and we say so rather than
dressing it up as a technique that paid off.

### 4.4 What the fitted model actually uses

From `tools.model_extras` (its own LightGBM run: R²(log) 0.9458, MAPE 11.6% on val):

| Feature | Permutation importance (RMSE, log space) | sd |
| --- | ---: | ---: |
| `brand_age_band` | 0.5096 | 0.0812 |
| `manufacture_year` | 0.2621 | 0.0362 |
| `model` | 0.2314 | 0.0392 |
| `model_group` | 0.1803 | 0.0353 |
| `brand` | 0.1317 | 0.0210 |
| `engine_capacity` | 0.1301 | 0.0244 |

The top four are all "what car, which year" — the same story the ablation tells from the other side. Partial
dependence agrees: hold `manufacture_year` at 2011 and the model predicts 493 million, at 2021 it says 793
million, at 2025 it says 858 million.

**Seed stability** (3 seeds, 20,000 rows, 300 trees): 0.9305 / 0.9312 / 0.9308 → mean **0.9308 ± 0.0003**.
That ±0.0003 is exactly why §5.1 uses a paired test instead of a bare ranking: anything below about 0.001 is
the noise you get from re-running the same code.

**Learning curve** (7,024 / 17,561 / 35,122 / 70,244 train rows): 0.8947 → 0.9107 → 0.9311 → 0.9440. It is
still climbing at the last point, which means the ceiling here is **data and features**, not model capacity
— the strongest argument we have against spending another day on hyperparameters.

## 5. Models

### 5.1 Benchmark on val (14,964 rows)

Nine model families, two feature sets. Three combinations got tuned within a **600 s budget — 25 draws × 2
grouped folds = 50 fits** — and everything else runs on fixed parameters; the `tuning` column of
`docs/benchmark.md` marks which is which. Every number on this page is **val**; the test split only shows up
in §5.2.

| Features | Model | R²(log) | RMSE(log) | R²(VND) | MAE (VND) | MAPE | MAPE clean | median APE | s | tuning |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| full | **lightgbm+tuned** | **0.9471** | 0.1904 | 0.9215 | 82,087,205 | 11.4% | 10.3% | 6.2% | 468.5 | 25×2 |
| full | catboost | 0.9465 | 0.1914 | 0.9134 | 91,143,312 | 12.0% | 10.9% | 6.9% | 447.8 | fixed |
| minimal | lightgbm+tuned | 0.9464 | 0.1916 | 0.9162 | 84,155,488 | 11.6% | 10.4% | 6.3% | 138.8 | 25×2 |
| full | lightgbm | 0.9462 | 0.1919 | 0.9213 | 82,441,420 | 11.5% | 10.4% | 6.3% | 16.7 | fixed |
| minimal | lightgbm | 0.9447 | 0.1945 | 0.9151 | 84,885,802 | 11.7% | 10.6% | 6.4% | 5.4 | fixed |
| full | **xgboost+tuned** | 0.9440 | 0.1957 | 0.9010 | **78,041,635** | **11.0%** | **9.8%** | 5.9% | 326.7 | 25×2 |
| minimal | catboost | 0.9438 | 0.1961 | 0.9056 | 95,474,212 | 12.3% | 11.2% | 7.1% | 264.8 | fixed |
| minimal | xgboost+tuned | 0.9413 | 0.2004 | 0.8983 | 80,995,302 | 11.3% | 10.1% | 6.2% | 269.4 | 25×2 |
| full | rf | 0.9411 | 0.2008 | 0.9094 | 87,698,367 | 12.1% | 10.7% | 6.4% | 149.8 | fixed |
| full | xgboost | 0.9409 | 0.2011 | 0.8952 | 78,256,273 | 11.1% | 9.8% | **5.7%** | 22.3 | fixed |
| minimal | catboost+tuned | 0.9395 | 0.2035 | 0.8962 | 100,674,556 | 13.0% | — | 7.5% | 308.7 | 1×2 |
| minimal | xgboost | 0.9388 | 0.2046 | 0.8914 | 80,850,994 | 11.3% | 10.1% | 6.0% | 11.2 | fixed |
| minimal | rf | 0.9370 | 0.2076 | 0.8960 | 94,182,039 | 12.6% | 11.2% | 6.7% | 120.8 | fixed |
| full | ridge | 0.8970 | 0.2655 | 0.8200 | 141,897,201 | 18.0% | 16.4% | 10.4% | 6.1 | fixed |
| full | median (baseline) | 0.8773 | 0.2899 | 0.8703 | 101,649,813 | 18.8% | 13.2% | 7.3% | 1.8 | fixed |
| minimal | ridge | 0.8746 | 0.2930 | 0.7824 | 157,731,450 | 20.6% | 18.6% | 11.5% | 4.5 | fixed |
| full | elasticnet | 0.8722 | 0.2958 | 0.7458 | 174,713,377 | 21.2% | 19.3% | 13.4% | 90.5 | fixed |
| full | lasso | 0.8561 | 0.3139 | 0.7136 | 190,664,684 | 22.9% | 20.9% | 14.8% | 37.4 | fixed |
| full | knn | 0.8553 | 0.3147 | 0.7387 | 181,201,164 | 22.8% | 20.8% | 13.4% | 1.5 | fixed |
| minimal | elasticnet | 0.8507 | 0.3198 | 0.7138 | 192,621,090 | 23.7% | 21.5% | 14.7% | 17.4 | fixed |
| minimal | knn | 0.8372 | 0.3338 | 0.7273 | 194,474,953 | 25.9% | 23.5% | 14.8% | 1.1 | fixed |
| minimal | lasso | 0.8344 | 0.3367 | 0.6868 | 207,337,967 | 25.5% | 23.1% | 16.2% | 19.4 | fixed |

`MAPE clean` throws out rows whose asking price is below a quarter of the estimate — the deposit-style ads
§6 is about. One old row (`minimal`/`catboost+tuned`) predates that column and shows `—`. The two `median`
rows are identical because the baseline ignores the feature set completely: a "model" that only knows the
global median already sits at R²(log) 0.8773.

**We fixed the primary metric before reading the table: R²(log)** — the thing the models actually minimise,
and the thing the canary floor is stated in. That order matters, because the metric picks the winner:

1. **The canary floor is 0.946 R²(log) / 11.6% MAPE; the best row is 0.9471 / 11.4%.** It clears both, by
   +0.0011 and −0.2 points. Nothing here is a step change from complexity: untuned LightGBM lands on
   0.9447–0.9462, i.e. *right on* the floor, so "the complexity is worth it" rests on the tuned row alone.
2. **Tuning buys almost nothing: +0.0009 R²** (0.9462 → 0.9471), for 50 fits and 16.7 s → 468.5 s. A paired
   Wilcoxon on absolute percentage error says the gap is real (p = 7.8e-05) against a seed sd of 0.0003 —
   real, and still irrelevant to anyone using the thing.
3. **CatBoost and LightGBM tie** (0.9465 vs 0.9462 untuned). Wilcoxon prefers catboost (p = 2.3e-15), but
   the R² gap is 0.0003 — exactly one seed sd — and catboost is *worse* on MAPE (12.0% vs 11.5%).
4. **XGBoost wins in VND space and loses on ranks.** `xgboost+tuned` has the best MAE (78.0 million), MAPE
   (11.0%), clean MAPE (9.8%) and median APE (5.9%), yet the paired Wilcoxon against `lightgbm+tuned` calls
   it **worse** (p = 5.8e-12). Both are true: it wins on expensive cars and loses by small margins on the
   many cheap ones. This is the whole reason for naming the primary metric up front instead of afterwards.
5. **The median baseline beats ridge on median APE** (7.3% vs 10.4%) while scoring lower on R² (0.8773 vs
   0.8970). A model that looks better by R² can be worse in the middle of the distribution — the kind of
   wrong call the median-APE column exists to catch.

`full` beats `minimal` by about 0.0015 R² on the untuned pair (0.9462 vs 0.9447). Small, real (Wilcoxon
p = 7.4e-07) against a 0.0003 noise floor — worth keeping, not worth calling a big improvement.

**What we ship in `predictions_{val,test}.csv`: lightgbm+tuned / full**, with the parameters frozen as
`n_estimators=900, learning_rate=0.03, num_leaves=63, min_child_samples=20`. Running it back through
`--params` gives exactly **0.9471 / 0.1904 / 82,087,205 / 11.4%** in 31.9 s instead of 468.5 s, so the
artefact reproduces without repeating the search. We took LightGBM over catboost for two reasons: better
MAPE (11.4% vs 12.0%), and it emits quantiles directly, so the P10/P90 band in §7 does not need a third model.

### 5.2 Test — the single evaluation

We scored the test split **once**, after the model and its parameters were frozen. The record is
`docs/test_evaluation.md`; the interval check is `docs/intervals_test.md`.

| Metric | val (14,964) | **test (14,980)** |
| --- | ---: | ---: |
| R²(log) | 0.9471 | **0.9487** |
| RMSE(log) | 0.1904 | 0.1869 |
| R²(VND) | 0.9215 | 0.9026 |
| MAE (VND) | 82,087,205 | 89,731,484 |
| MAPE | 11.4% | **10.9%** |
| MAPE clean | 10.3% | 10.1% |
| median APE | 6.2% | 6.1% |
| band coverage (nominal 80%) | 81.70% | **81.91%** |

Three things come out of that table:

1. **The test split is not suspiciously easy.** R²(log) and MAPE come out 0.0016 / 0.5 points *better* than
   val — the kind of gap you get between two splits of the same distribution, not evidence that the holdout
   was kind to us.
2. **MAE and R²(VND) go the other way** (89.7 vs 82.1 million; 0.9026 vs 0.9215), because they are absolute
   VND numbers and the test mix has more expensive cars. Same model, opposite readings — the lesson from
   §5.1, now on held-out data.
3. **The band survives the move** — 81.91% against a nominal 80%, split as 8.62% below P10 and 9.47% above
   P90. Calibrating on train OOF did not quietly fit the band to val.

What we **will not** do now: re-tune, re-pick a model, widen the band, or score the test split again. The split
is spent, and `docs/test_evaluation.md` refuses a second write unless `--force` is passed by hand. Anything
we change from here goes in as a limitation (§8.2), never as a fresh test number.

## 6. Error analysis

- **Median APE 6.2%, MAPE 11.4%** on val (test: 6.1% / 10.9%). Two different measurements, both correct:
  MAPE gets dragged by the right tail, median APE describes an ordinary ad.
- **By bucket** (`docs/error_taxonomy.md`, with the rules in `tools/error_report.py::bucket`, so every count
  can be re-derived): under 200 million — **1,461** rows, median APE **13.2%**, mean Δ **+24.7%**. The model
  **over**-prices cheap cars, because that bucket is where the deposit and bait prices live. Extreme
  odometer — **118** rows, **9.6%**. Everything else — **13,385** rows, **5.8%**.
- **By platform**: carmudi **10.0%** (105 rows) · chotot 7.1% (2,874) · muaban 6.7% (1,044) · tinbanxe 6.5%
  (1,124) · carpla 6.3% (610) · oto.com.vn 5.9% (4,369) · bonbanh 5.9% (4,529) · vucar 4.8% (309). Error is
  not spread evenly, and the smallest platform has the worst number — one MAPE for the whole market would
  hide exactly that.
- **By price decile**: the cheapest decile (< 200 million) sits at median APE **13.0%**, roughly double the
  deciles above it (6.8% / 5.4%). The model is weakest where the buyer has the least money.
- **The 25 worst rows** (`docs/error_audit_25.md`, read by hand): **24 of 25 are deposit-style prices**, 6
  have placeholder odometers, 1 is a genuine duplicate. That tail is a **data** problem, not a modelling
  one — no amount of tuning fixes an ad that posts 7% of a car's value to farm phone numbers.
- **Three case studies** (`docs/case_studies.md`, picked by rule so they reproduce): `MUA_71248118`, a 2022
  Toyota Corolla Cross asking **7.35 billion** against a **631 million** estimate (Δ −91.4%);
  `CHOTOT_134989809`, a 2024 Aion Y Plus with **999,998 km** (Δ +488%); `CARPLA_F8W47`, a 2024 Audi Q5
  import asking **218 million** against **2.06 billion** (Δ +843%).
- **Feature importance** (`data/master/feature_importance.csv`): `brand_age_band` 0.510 ·
  `manufacture_year` 0.262 · `model` 0.231 · `model_group` 0.180 · `brand` 0.132 · `engine_capacity` 0.130.
  The first three are "what car, which year" again, matching §4.2.

None of those three failure modes is a model bug. They are a deposit price, an edited odometer, and an import
advertised at a domestic-looking price. §8.2 draws the conclusion: this product needs *data* — transaction
prices, service history — more than it needs another model.

## 7. Labelling suspicious and mispriced listings

How it works (`src/models/anomaly.py`, thresholds in `data/master/anomaly_thresholds.json`):

1. **Band** — P10/P90 from LightGBM's quantile triple, calibrated on **train OOF** (never on val or test).
   It covers **81.70%** of val prices and **81.91%** of test prices against a nominal 80%.
2. **Isolation Forest** — 300 trees, `max_samples` 4096, on the val feature matrix (numbers as they are,
   categoricals as codes). Its job is to find "outside the band **and** odd in feature space".
3. **Review threshold** — the 97th percentile of the forest score, i.e. **3.00%** of val rows (449 ads) land
   in the review queue. That is a **budget for how many ads a human will read**, not an estimate of how many
   bad ads exist.

Labels are produced on **val** (14,964 ads). We deliberately leave the test split unlabelled — it is only
there for §5.2.

| Label | Ads | Share | Median Δ (asking vs estimate) |
| --- | ---: | ---: | ---: |
| Fair | 12,225 | 81.7% | −0.6% |
| Bargain | 1,331 | 8.9% | **+19.7%** |
| Overpriced | 1,325 | 8.9% | **−14.7%** |
| Suspicious | 83 | 0.6% | +8.9% |

Of the 449 ads above the forest threshold, only **83** are also outside the band. So `Suspicious` is much
narrower than "the review queue", and 83 is the number to give a moderator.

**By price band** — the labels pile up at the cheap end, which ties back to §6:

| Price band | Ads | Bargain | Overpriced | Suspicious | % flagged |
| --- | ---: | ---: | ---: | ---: | ---: |
| < 200 million | 1,501 | 336 | 49 | **25** | **27.3%** |
| 200–400 million | 3,555 | 374 | 232 | 17 | 17.5% |
| 400–700 million | 5,170 | 370 | 409 | 12 | 15.3% |
| 700 million – 1.5 billion | 3,226 | 211 | 386 | 15 | 19.0% |
| > 1.5 billion | 1,512 | 40 | 249 | 14 | 20.0% |

**By platform** — most Bargains on tinbanxe.vn (9.9%), most Overpriced on carpla (12.6%):

| Platform | Ads | % Bargain | % Overpriced |
| --- | ---: | ---: | ---: |
| bonbanh | 4,529 | 9.5% | 9.3% |
| oto.com.vn | 4,369 | 8.3% | 9.8% |
| chotot | 2,874 | 8.9% | 7.3% |
| tinbanxe.vn | 1,124 | **9.9%** | 6.6% |
| muaban.net | 1,044 | 9.5% | 7.7% |
| carpla | 610 | 8.5% | **12.6%** |
| vucar.vn | 309 | 3.9% | 10.7% |
| carmudi | 105 | 5.7% | 3.8% |

Three things worth saying out loud:

1. **`Bargain` does not mean "buy this".** 336 of the 1,331 Bargains are under 200 million — the exact bucket
   §6 calls deposit and bait prices (24 of the 25 worst rows). The label says "below the model". The model
   cannot tell a deposit from a car.
2. **Labels move with the band, so they move with the model.** Swap the model or recalibrate the band and the
   shares change. That is why §6 quotes the coverage, and why the forest threshold is written into
   `anomaly_thresholds.json` — so a later run can be compared instead of trusted.
3. **The 3% review rate is a choice about workload.** Set it to 2% or 5% and you change how many ads a person
   reads, not the nature of the problem. 83 Suspicious ads out of 14,964 is few enough to read by hand, and
   that is the whole deliverable.

## 8. Limitations

### 8.1 Data

- **Asking price, not transaction price.** Everything here means "the model matches the asking price". We
  do not know the haggling margin or what was actually paid, so error measured on asking prices is an **upper
  bound** on error against real sale prices — and this snapshot cannot tell us how loose that bound is.
- **Fields we need and do not have**: `engine_capacity` 61.2% missing, `sub_model_trim` 55.7%, `body_type`
  18.2% of the window, `mileage_km` 12.7%. No accident, service, ownership or legal-history data at all.
- **One snapshot, no time.** We exclude the listing date because it leaks, which also means the model knows
  nothing about seasonality or how prices drift month to month.
- **Uneven sources**: carmudi has 546 ads in total and 105 in val, too few to be a segment. Anything we say
  per platform about carmudi or vucar rests on a small sample.
- **19 rows without a price are dropped**, not imputed. **4 rows with impossible model years** (1025, 2028,
  2030, 2032) stay in the feature table and are treated as categorical values rather than hand-edited.

### 8.2 Model and process

- **The ceiling is data, not modelling.** Nine families land inside 0.937–0.947, 50 tuning fits buy 0.0009,
  and the learning curve is still climbing (0.8947 → 0.9440 from 7k to 70k rows). Real mileage, a proper
  brand/model taxonomy, seasonality — any of those is worth more than another model.
- **The ranking depends on the metric.** LightGBM+tuned wins R²(log) at 0.9471; XGBoost+tuned wins MAE, MAPE
  and median APE while the paired Wilcoxon calls it worse. We fix R²(log) as primary because it is the
  training objective and the metric the canary floor is written in — and we say plainly that a different
  primary metric would give a different winner.
- **The tuned score is a bit optimistic.** 0.9471 is the best of 25 draws picked on the same 14,964 val rows,
  so it should sag on new data. It actually went *up* to 0.9487 on test, but that is one measurement, not
  proof against the optimism.
- **The band does not always contain the point forecast** — 1.80% of val rows and 1.78% of test rows. The band
  comes from quantile models, the point comes from the mean model, so nothing forces one inside the other.
  It is recorded in `docs/intervals.md`; forcing the band to swallow the point would widen it and wreck the
  calibration.
- **The test split is spent.** `docs/test_evaluation.md` is written once and the tool refuses to overwrite it.
  Anything we change from here goes in as a limitation, with no second test run — otherwise the "evaluated
  once" line in this report stops meaning anything.

## 9. Conclusions and next steps

### 9.1 What we know now

1. **The model is good enough for price guidance, and we have a real holdout to say so.** R²(log) 0.9487 and
   median APE 6.1% on 14,980 ads nobody touched during development. A typical ad gets within about 6% of its
   asking price. This is not a demo that happens to fit val.
2. **The gap to the baseline is the number worth quoting, not the gap to the ceiling.** The global-median
   baseline scores 0.8773; the shipped model scores 0.9471 on val. Seven points of R² is what "predict price
   from which car and which year" actually buys. The last 0.05 is what this dataset cannot give us.
3. **The complexity pays for itself, but barely.** Against the canary floor of 0.946 the shipped model wins by
   0.0011. Enough to keep it, not enough to celebrate — §5.1 says the same thing in the same words, which is
   why the rest of that table is worth trusting.
4. **The intervals are calibrated and they travel.** 81.70% coverage on val, 81.91% on test, against a nominal
   80%, with the calibration fitted on train out-of-fold rows only. This is the piece that would break first
   if the feature set changed.
5. **The screening layer produces a workload, not a verdict.** 83 Suspicious ads out of 14,964 is a queue a
   person clears in a morning. The part to distrust is the label, not the count.

### 9.2 What the product should promise, and what it should not

What the evidence supports: **"a starting number for a negotiation, plus a short review queue."** What it
does not support: **contract-grade valuation**. The reason is structural — every label here is an *asking*
price and the haggling margin is not in the data. As a limitation that is honest; as a feature claim it is a
promise the data cannot keep.

In practice: quote the interval, not the point. Quote `median APE 6.1%` for a typical ad, and say out loud
that the cheapest decile is twice as bad (13.0%). Put a warning next to `Bargain` that a price below P10 is
more often a deposit than a deal — 24 of the 25 worst rows in §6 are exactly that.

### 9.3 What we would do next, in order

| Priority | Work | Why it comes first |
| --- | --- | --- |
| 1 | **Transaction prices** (sold listings, dealer invoices) | turns an asking-price model into a valuation model; nothing else changes the target definition |
| 2 | **Real odometer history** (service records, registration data) | `mileage_km` is 12.7% missing and worth ΔR² 0.0001 as it stands; the *true* value is the signal the model currently lacks |
| 3 | **Model-year × variant taxonomy** (`sub_model_trim` is 55.7% missing) | the top three features are all "what car, which year"; filling the missing half is the cheapest real gain |
| 4 | **Time axis** (listing date as seasonality, not as a leak) | with a second snapshot, month-of-year becomes learnable; with one, it is not |
| 5 | More tuning, more model families | measured at +0.0009 for 50 fits; this is the last thing worth doing, not the first |

### 9.4 What must not happen

Any of items 1–5 changes the data or the model, which means a **new snapshot and a re-opened freeze**. The
current test number (0.9487) then becomes history: it stays in this report as the measurement of *this* model
on *this* split, and a new number comes from a new one-shot evaluation — never from re-scoring the same split
until it looks better. Two guards keep that honest after submission: `docs/test_evaluation.md` is written
once and refuses to be overwritten, and `python -m src.models.train --split test` exits unless `--at-m2` is
passed.

## Appendix A — Reproduction runbook

The data snapshot is not in the repo (`data/master/*` is git-ignored — `docs/data_handover.md` §5 explains
why). A fresh clone plus the mandatory download reproduces every number in this report:

```bash
# 0. environment
pip install -r requirements.txt          # Python 3.12; lightgbm >= 4.5, pandas >= 3.0

# 1. snapshot: put these three files in data/master/
#    train_cohort_imputed.csv, val_cohort_imputed.csv, test_cohort_imputed.csv
#    (01_week3_mandatory/ on Drive; verify with SHA256SUMS.txt)

# 2. features
python -m src.features.build_features --features full --split all

# 3. the shipped model on val, with the parameters frozen before the test run
python -m src.models.train --model lgbm --features full --quantiles --label lightgbm+tuned \
  --params '{"n_estimators":900,"learning_rate":0.03,"num_leaves":63,"min_child_samples":20}'
#   -> R²(log) 0.9471, MAE 82,087,205, MAPE 11.4%, band coverage 81.7%

# 4. the one-shot test evaluation (writes docs/test_evaluation.md once)
python -m src.models.train --model lgbm --features full --quantiles --split test --at-m2 \
  --label lightgbm+tuned \
  --params '{"n_estimators":900,"learning_rate":0.03,"num_leaves":63,"min_child_samples":20}'
#   -> R²(log) 0.9487, MAPE 10.9%, band coverage 81.91%

# 5. downstream artefacts
python -m src.models.anomaly --predictions data/master/predictions_val.csv   # §7
python -m tools.error_report                                                # §6
python -m tools.check_intervals                                             # §5.2, §7
python -m tools.model_gate                                                  # leak gate
```

Two shortcuts. `python -m tools.clean_check` pulls `HEAD` into a temp folder and runs features → train → gate →
tests there, which is how "the committed tree is enough" gets *checked* instead of assumed. And
`python -m src.models.benchmark` rebuilds the §5.1 table, though it is slow: three models × 600 s of tuning.
Timings on the machine that produced this report: features about 20 s, train about 45 s including quantiles,
gate and tests about 10 s.

## Appendix B — Artefact inventory

Everything a reviewer needs to check a number, and nothing that has to be taken on trust:

| Artefact | Contents | Used by |
| --- | --- | --- |
| `data/master/predictions_val.csv` | 14,964 × 15: ids, vehicle, asking price, `y_pred_*`, `p10_vnd`, `p90_vnd`, residual, APE | §5.1, §6, §7 |
| `data/master/predictions_test.csv` | 14,980 × 15, same contract, written once at M2 | §5.2 |
| `data/master/model_results.json` | append-only ledger, one row per (model, features, seed, holdout, frozen) | §5.1, §5.2 |
| `docs/model_results.json` | committed copy of the ledger, so the numbers travel with the repo | §5.1, §5.2 |
| `docs/benchmark.md` | the §5.1 table with tuning budget and per-row timings | §5.1 |
| `docs/test_evaluation.md` | the single test evaluation, written once, refuses overwrite | §5.2 |
| `docs/intervals.md`, `docs/intervals_test.md` | band coverage by platform, on val and on test | §5.2, §7 |
| `data/master/anomaly_labels.csv` | per-listing label, band, forest score, reason | §7 |
| `data/master/anomaly_thresholds.json` | calibrated forest threshold, review rate, label counts | §7 |
| `docs/error_taxonomy.md`, `docs/error_audit_25.md` | error buckets, platform/decile breakdowns, the hand-read tail | §6 |
| `docs/case_studies.md` | three listings picked by rule, with URLs | §6 |
| `data/master/feature_ablation.json`, `docs/features_ablation.md` | drop-one-group ΔR² | §4.2 |
| `data/master/cardinality_study.json`, `docs/cardinality_research.md` | encoding comparison | §4.3 |
| `docs/model_extras.md` | permutation importance, partial dependence, seed stability, learning curve | §4.4 |
| `docs/eda_summary.md`, `docs/figures/fig1..fig5` | the EDA tables and the five figures | §3 |
| `docs/data_limitations.md`, `docs/features.md`, `docs/feature_formulas.md` | data caveats and the feature definitions | §2, §4, §8 |

## Appendix C — Metric glossary

| Term | Definition | Why it is reported |
| --- | --- | --- |
| **R²(log)** | coefficient of determination on `log1p(price_vnd)` — the space the models are trained in | primary metric: it is the training objective and the metric the canary floor is expressed in |
| **RMSE(log)** | root mean squared error in log space | same space as R²(log), in price-error units |
| **R²(VND)** | R² on raw VND | shows how much of the *money* variance is explained; always flattering because the distribution is skewed |
| **MAE (VND)** | mean absolute error in VND | the number a business reader feels; scales with car price |
| **MAPE** | mean absolute percentage error over all rows | comparable across price levels, but dominated by cheap rows |
| **MAPE clean** | MAPE after dropping rows whose asking price is below a quarter of the estimate | the same measure without the deposit-price tail (`docs/error_audit_25.md`) |
| **median APE** | median absolute percentage error | the typical listing rather than the average; immune to the tail |
| **band coverage** | share of asking prices inside `[p10_vnd, p90_vnd]` | calibration check against the nominal 80%; a band that does not cover 80% makes the §7 labels fire at the wrong rate |
| **canary floor** | R²(log) 0.946 / MAPE 11.6% from `tools/baseline_smoke` | the number any added complexity has to beat to be worth its cost |

_§3 and §7 were drafted from the artefacts in Appendix B (`docs/eda_summary.md`, `anomaly_labels.csv`,
`anomaly_thresholds.json`) and reviewed by Phong and Tuấn Anh. Copy-editing is done; layout and the PDF for
submission are still to do._
