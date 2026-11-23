# Results — data, features, model and errors

One page for the numbers the report quotes. The snapshot is **100,887 listings** from eight
marketplaces, captured 2026-10-29/30; every price is an **advertised** price, not a transaction
(`docs/data_limitations.md`). Generated evidence that is not needed to read the project lives in the
repository history and in `data/master/*.json`.

## 1. Dataset and split

| Step | Rows |
|---|---:|
| Master after merge + dedupe | 100,887 |
| Labelled (usable price) | 100,868 |
| Split, grouped by `duplicate_group_id` | 70,707 / 15,063 / 15,098 |
| Modelling cohort (implausible rows removed) | **70,244 / 14,964 / 14,980** |
| Duplicate groups / brands | 75,496 / 146 (from 164 spellings) |

Missing in train: `engine_capacity` **61.2 %**, `sub_model_trim` **55.7 %**, `seller_type` 34.1 %,
`origin` 28.6 %. Nineteen rows without a usable price were dropped, never imputed.

| Platform | Master rows |
|---|---:|
| bonbanh | 30,371 |
| oto.com.vn | 29,563 |
| chotot | 19,426 |
| tinbanxe.vn | 7,654 |
| muaban.net | 7,022 |
| carpla | 4,181 |
| vucar.vn | 2,124 |
| carmudi | 546 |

## 2. Label quality and training weights

`data/master/label_flags.csv` carries four rules: deposit-suspected (asking < 25 % of the segment
median), placeholder odometer (≤ 100 km or ≥ 900,000 km), implausible year, and repeat/copy ads.

| Split | Rows | deposit | placeholder odo | repeat ads | copies | any flag |
|---|---:|---:|---:|---:|---:|---:|
| train | 70,244 | 1,552 (2.21 %) | 3,015 (4.29 %) | 21,341 | 12,887 | 25,039 (35.6 %) |
| val | 14,964 | 329 (2.20 %) | 731 (4.89 %) | 4,448 | 2,664 | 5,320 (35.5 %) |
| test | 14,980 | 322 (2.15 %) | 655 (4.37 %) | 4,542 | 2,766 | 5,358 (35.8 %) |

The adopted model uses **weight 1/k for a repeated ad** (`weight_repeats`, 18,655 train rows
down-weighted). On fixed hold-outs this is neutral-to-slightly-better and keeps every row:

| Training set | MAPE val_full | MAPE val_clean |
|---|---:|---:|
| no weighting | 11.69 % | 10.38 % |
| **1/k repeat weight** | **11.60 %** | **10.30 %** |

## 3. Features v2

The v2 table adds `engine_capacity_parsed` (badge parse when the site value was missing),
`trim_rank` (base / mid / top), `model_canonical`, and `variant_tokens`; all are stateless — nothing is
fitted, so no validation row leaks into training.

| # | Feature step | Features | R² val_full | MAPE val_full | MAPE val_clean |
|---:|---|---:|---:|---:|---:|
| 1 | baseline | 23 | 0.9448 | 11.69 % | 10.38 % |
| 2 | + 1/k repeat weight | 23 | 0.9453 | 11.60 % | 10.30 % |
| 3 | **+ engine parse & trim_rank (adopted)** | **30** | **0.9470** | **11.25 %** | **9.91 %** |
| 4 | + canonical model & variants | 29 | 0.9476 | 11.26 % | 9.89 % |

`engine_parsed` recovers **1,058 train / 230 val / 208 test** displacements from the badge.
`trim_rank` on train: base 1,626 · mid 4,738 · top 6,969 · unknown 56,911. `model_canonical` cuts
3,243 model levels to 2,238 while keeping the original `model` column beside it.


## 4. Generalisation — a nameplate the model never saw

A fixed LightGBM (300 trees) was retrained with 565 `brand|model` levels (20.1 % of train rows) removed.
Price-derived features were dropped for this test so the hidden nameplates could not leak through them.

| Slice of val | Rows | R²(log) | MAPE | median APE |
|---|---:|---:|---:|---:|
| seen combos | 11,691 | 0.9530 | 11.01 % | 6.07 % |
| **held-out combos (v1 → v2)** | 2,937 | 0.8389 | **27.5 % → 23.9 %** | 17.5 % |
| unseen combos (never in train) | 336 | 0.7507 | 32.13 % | 22.7 % |

The drop is structural: a used-car price is largely nameplate + age, so a model that has never seen the
nameplate can only use segment-level signals. This is why the serving path raises `unseen_brand_model`
and the readiness report shows a 51 % P10–P90 coverage for that slice.

## 5. Chợ Tốt recon and Bonbanh backfill

**Chợ Tốt** is crawlable again through its JSON gateway (18,413 live price-listed ads; 19,426 records in
the master), but it does **not** publish `engine_capacity` or `sub_model_trim`: the labels exist in the
page, the values are empty, and the old v1 ads are gone (0/80 sampled still live). Its value is volume
plus `body_type` / `seller_type`.

**Bonbanh backfill** ran to completion over the **7,704 pages** that were the only source:

| Field | Filled (train / val / test) | Reading |
|---|---:|---|
| `seller_type` | 1,981 / 406 / 424 | the salon subdomain, or no link → private |
| `engine_capacity` | 31 / 9 / 8 | `Động cơ` is printed with an empty value on most older ads |
| `body_type` | 3 / 1 / 0 | already observed on almost every row |
| `sub_model_trim` | 4,351 / 887 / 885 | derived offline from the `model` string, no request |

v1 is untouched: same rows, same split, byte-identical price/mileage/brand/model/year. v2 is a separate
snapshot in `data/master/v2/`.

## 6. Model, band and test result

The frozen bundle is **`models/v2/`**: LightGBM on `log1p(price_vnd)`, **30 features**, 300 trees,
learning rate 0.06, 63 leaves, `min_child_samples` 40, repeat weight 1/k.

| Slice | Rows | R²(log) | MAPE | median APE | MAE |
|---|---:|---:|---:|---:|---:|
| val_full | 14,964 | **0.9470** | **11.25 %** | 6.18 % | 81.3 M |
| val_clean (no quality flag) | 9,644 | 0.9548 | **9.91 %** | 6.13 % | 79.6 M |

P10–P90 band: **81.71 %** coverage (nominal 80 %), 9.2 % below P10, 9.1 % above P90, median width
**118.9 M VND** (23 % of the point estimate). The band is calibrated on train out-of-fold, so val stays
a holdout.

Reference points: the canary floor is R²(log) 0.946 / MAPE 11.6 %; the best v1 benchmark on val is
R²(log) 0.9471 / MAPE 11.4 % (clean 10.3 %). The **one** v1 test evaluation (14,980 rows) records
R²(log) 0.9487, MAPE **10.9 %**, clean **10.1 %**. **v2 has not been evaluated on test** — the test split
is spent once at the freeze, and these val numbers are the ones the bundle ships with.

## 7. Error analysis — where it is weak

The rule-based buckets over val (full detail in `docs/error_taxonomy.md`):

| Bucket | Listings | median APE | mean Δ |
|---|---:|---:|---:|
| asking < 200 M | 1,461 | 13.2 % | +24.7 % |
| odometer outlier | 118 | 9.6 % | +2.6 % |
| import / salvage / rest | 13,385 | 5.8 % | −0.4 % |

Three failure modes are structural and cannot be tuned away: deposit-style asking prices, odometer
manipulation, and import/salvage status (`docs/error_audit_25.md`). By price band, MAPE is
**7.8 %** in the 300–700 M mainstream bands, **21.9 %** under 300 M (16.0 % after dropping flagged ads),
and **11.4 %** at 2 B+. By group thickness it is 10.2 % for 200+ train rows and **29.8 %** for unseen
nameplates. The full slice table and the band-coverage numbers are in `docs/readiness_v2.md`.

## Reproduce

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m src.merge.build_master
python -m src.data_prep.split
python -m src.data_prep.pipeline
python -m src.features.build_features --features full
python -m src.features.extend --write --cohort-dir data/master/v2
python -m tools.model_gate --features data/master/v2/train_features_full.csv --quiet
python -m tools.live_blind_test
python -m tools.readiness_check --rows 120
python -m unittest discover -s tests -t .
```

Data files are not committed; `docs/data_handover.md` says what to download from Drive and where to put
it. The single test evaluation is `docs/test_evaluation.md`; the primary val table is
`docs/benchmark.md`.
