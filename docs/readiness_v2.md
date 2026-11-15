# Readiness check — where the v2 bundle's error lives

Generated 2026-11-15T19:42:02+00:00 by `python -m tools.readiness_check`. Bundle built 2026-11-15T01:37:53+00:00 (git `988321c`), scored on `data/master/v2/val_features_full.csv` (14,964 rows). **Nothing is fitted here** and the test split is not touched.

Point and band come from `model_point.joblib` / `quantiles.joblib` with the exported category lists — the same path `Predictor.predict_one` takes (spot-checked below).

## Headline

| Slice | Rows | MAPE | median APE | MAE | R²(log) | inside P10-P90 | width / point |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| val (all) | 14,964 | 11.2% | 6.2% | 81,338,287 | 0.9470 | 81.7% | 23.0% |
| val, no quality flag | 9,644 | 9.9% | 6.1% | 79,636,034 | 0.9548 | 81.2% | 23.1% |
| val, price-quality clean | 13,920 | 9.8% | 6.0% | 79,615,804 | 0.9560 | 82.3% | 22.7% |

## By asking-price band

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| under 300M | 3,082 | 20.6% | 21.9% | 9.1% | 31,361,561 | 77.4% | 34.1% | 22.2% |
| 300-500M | 4,065 | 27.2% | 7.8% | 5.3% | 31,414,496 | 83.5% | 21.6% | 6.3% |
| 500-700M | 3,056 | 20.4% | 7.8% | 5.4% | 46,099,509 | 85.1% | 21.4% | 6.5% |
| 700M-1B | 2,000 | 13.4% | 8.1% | 5.5% | 66,987,464 | 83.0% | 23.7% | 7.1% |
| 1-2B | 1,733 | 11.6% | 10.2% | 6.6% | 144,873,857 | 77.7% | 30.2% | 13.4% |
| 2B+ | 1,028 | 6.9% | 11.4% | 6.6% | 454,152,184 | 81.6% | 37.2% | 15.6% |

## By asking-price band, price-quality clean

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| under 300M | 2,684 | 17.9% | 16.0% | 8.5% | 28,516,335 | 78.5% | 31.8% | 19.0% |
| 300-500M | 3,883 | 25.9% | 7.7% | 5.2% | 30,947,531 | 83.7% | 21.4% | 6.0% |
| 500-700M | 2,887 | 19.3% | 7.5% | 5.3% | 44,327,181 | 85.7% | 21.5% | 6.2% |
| 700M-1B | 1,873 | 12.5% | 7.9% | 5.5% | 65,992,220 | 83.9% | 23.5% | 7.0% |
| 1-2B | 1,660 | 11.1% | 10.0% | 6.4% | 142,931,715 | 78.0% | 29.8% | 13.1% |
| 2B+ | 933 | 6.2% | 11.3% | 6.6% | 453,057,062 | 81.1% | 36.6% | 15.8% |

## By training-group thickness (`brand|model` rows in train)

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unseen (0) | 337 | 2.3% | 29.8% | 21.4% | 406,442,943 | 51.0% | 51.7% | 51.6% |
| 1-9 | 1,142 | 7.6% | 17.2% | 10.7% | 163,030,388 | 79.9% | 56.4% | 26.9% |
| 10-19 | 805 | 5.4% | 9.7% | 5.8% | 114,763,841 | 75.3% | 18.3% | 11.7% |
| 20-49 | 1,390 | 9.3% | 9.5% | 5.3% | 75,837,218 | 81.7% | 22.1% | 9.1% |
| 50-199 | 3,170 | 21.2% | 11.1% | 6.0% | 82,958,381 | 81.6% | 23.0% | 10.8% |
| 200+ | 8,120 | 54.3% | 10.2% | 5.9% | 53,351,903 | 84.0% | 21.6% | 7.8% |

## By training-group thickness, price-quality clean

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unseen (0) | 313 | 2.1% | 27.9% | 21.6% | 431,694,804 | 50.8% | 51.7% | 52.1% |
| 1-9 | 1,040 | 7.0% | 15.8% | 10.1% | 163,080,054 | 80.3% | 59.8% | 24.8% |
| 10-19 | 743 | 5.0% | 8.5% | 5.4% | 107,430,038 | 76.3% | 19.0% | 9.7% |
| 20-49 | 1,320 | 8.8% | 8.2% | 5.2% | 73,930,608 | 82.0% | 22.0% | 8.3% |
| 50-199 | 2,986 | 20.0% | 10.2% | 5.7% | 80,808,063 | 82.5% | 22.2% | 9.8% |
| 200+ | 7,518 | 50.2% | 8.5% | 5.8% | 51,187,345 | 84.4% | 21.3% | 7.0% |

## By trim rank

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 347 | 2.3% | 11.5% | 6.3% | 36,434,223 | 81.3% | 24.6% | 8.6% |
| mid | 929 | 6.2% | 9.4% | 5.7% | 108,905,574 | 81.4% | 24.0% | 9.2% |
| top | 1,623 | 10.8% | 6.2% | 4.6% | 70,832,247 | 82.9% | 18.4% | 3.4% |
| unknown | 12,065 | 80.6% | 12.1% | 6.5% | 81,920,384 | 81.6% | 24.0% | 12.4% |

## By transmission

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Automatic | 12,750 | 85.2% | 10.5% | 5.8% | 88,204,214 | 81.7% | 22.7% | 10.0% |
| Manual | 2,175 | 14.5% | 15.2% | 8.8% | 40,478,143 | 82.1% | 32.5% | 18.1% |
| Other | 39 | 0.3% | 28.3% | 11.5% | 115,446,994 | 69.2% | 30.3% | 23.1% |

## By body type

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SUV | 5,509 | 36.8% | 9.6% | 5.7% | 103,609,799 | 82.0% | 22.3% | 9.8% |
| Sedan | 4,055 | 27.1% | 10.3% | 6.2% | 70,886,754 | 81.1% | 23.0% | 10.5% |
| MPV | 1,382 | 9.2% | 14.2% | 5.6% | 51,810,367 | 84.2% | 21.1% | 10.2% |
| Hatchback | 1,343 | 9.0% | 12.6% | 6.2% | 27,402,024 | 81.8% | 26.5% | 13.0% |
| Pickup | 933 | 6.2% | 14.7% | 8.3% | 69,843,423 | 81.2% | 33.8% | 14.4% |
| Van | 637 | 4.3% | 15.9% | 7.8% | 69,864,152 | 79.9% | 31.7% | 16.0% |
| Crossover | 548 | 3.7% | 9.6% | 5.3% | 57,470,977 | 82.1% | 20.0% | 8.8% |
| Other | 416 | 2.8% | 13.0% | 7.5% | 137,810,440 | 82.5% | 26.1% | 14.4% |
| Coupe | 61 | 0.4% | 16.6% | 10.9% | 417,332,263 | 72.1% | 29.2% | 27.9% |
| Convertible | 41 | 0.3% | 14.8% | 4.3% | 492,468,871 | 73.2% | 31.2% | 24.4% |
| Truck | 29 | 0.2% | 38.6% | 24.8% | 161,082,987 | 72.4% | 120.4% | 58.6% |
| Sports | 7 | 0.0% | 9.4% | 2.9% | 222,196,648 | 85.7% | 16.5% | 14.3% |
| Minibus | 2 | 0.0% | 10.4% | 10.4% | 67,301,799 | 50.0% | 58.8% | 0.0% |
| Wagon | 1 | 0.0% | 18.3% | 18.3% | 10,607,569 | 100.0% | 148.7% | 0.0% |

## By luxury brand

| Slice | Rows | Share | MAPE | median APE | MAE | inside P10-P90 | width / point | APE > 20 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| yes | 2,489 | 16.6% | 12.9% | 7.9% | 213,608,645 | 80.1% | 32.5% | 16.6% |
| no | 12,475 | 83.4% | 10.9% | 5.9% | 54,947,832 | 82.0% | 21.8% | 10.1% |

## Nameplates with at least 100 val rows

| Worst | Rows | MAPE | median APE | median price |
| --- | ---: | ---: | ---: | ---: |
| Ford\|Ranger | 373 | 15.7% | 11.0% | 560,000,000 |
| Hyundai\|Grand i10 | 173 | 14.7% | 8.5% | 226,000,000 |
| Mercedes-Benz\|C Class | 127 | 13.5% | 11.0% | 666,000,000 |
| Kia\|Cerato | 114 | 12.6% | 4.3% | 400,000,000 |
| Kia\|Morning | 213 | 12.0% | 8.4% | 165,000,000 |
| Mitsubishi\|Xpander | 270 | 11.2% | 4.5% | 455,500,000 |
| VinFast\|VF8 | 122 | 10.9% | 6.8% | 700,000,000 |
| Toyota\|Camry | 230 | 10.2% | 7.4% | 595,000,000 |
| Mercedes-Benz\|GLC | 227 | 10.1% | 8.3% | 1,399,000,000 |
| Toyota\|Innova | 342 | 10.1% | 7.6% | 355,000,000 |
| Ford\|Everest | 292 | 9.9% | 7.5% | 1,010,000,000 |
| Toyota\|Vios | 386 | 9.4% | 6.3% | 350,000,000 |

| Best | Rows | MAPE | median APE | median price |
| --- | ---: | ---: | ---: | ---: |
| VinFast\|Fadil | 107 | 4.7% | 3.4% | 285,000,000 |
| Toyota\|Veloz Cross | 103 | 4.9% | 3.9% | 505,000,000 |
| Hyundai\|Tucson | 105 | 5.4% | 4.7% | 645,000,000 |
| Honda\|CR-V | 157 | 5.6% | 4.4% | 678,000,000 |
| Kia\|Carnival | 201 | 6.1% | 4.8% | 1,099,000,000 |
| Mazda\|3 | 192 | 6.3% | 4.6% | 462,500,000 |
| Honda\|City | 127 | 6.6% | 4.4% | 395,000,000 |
| Mazda\|CX-5 | 232 | 6.7% | 4.1% | 620,500,000 |
| Toyota\|Fortuner | 332 | 7.2% | 5.3% | 619,000,000 |
| Hyundai\|Accent | 201 | 7.2% | 5.1% | 375,000,000 |
| Hyundai\|Santa Fe | 193 | 7.4% | 6.2% | 780,000,000 |
| Toyota\|Corolla Cross | 123 | 7.6% | 4.3% | 689,000,000 |

## Baselines on the same rows

| Predictor | MAPE | median APE |
| --- | ---: | ---: |
| national median | 75.0% | - |
| brand\|model median | 35.1% | - |
| **v2 bundle** | **11.2%** | **6.2%** |

## Serving parity

`Predictor.predict_one` on 120 raw val rows (stratified over 6 price bands, from a pool of 2,788 rows that the v2 cohort did not impute and whose province the feature table kept) vs the same rows' exported feature vector: max |ratio-1| **2.02e-09**, mean **4.54e-10**.

Excluded from the pool: 1,302 backfilled, 10,504 rows with a build-time imputation, 19 with a province outside `provinces_kept`, 351 with a placeholder odometer.

Rows the v2 cohort imputed are **not** a serving-parity test: `impute_stats.json` is fitted on `train_cohort.csv`, while the v2 cohort's build-time imputation is a different snapshot for a few groups — e.g. Honda|CR-V's engine median is 1.75 L in the bundle and 2.0 L in the v2 cohort. That is an artefact mismatch to track separately, not a serving failure.

## Checks

| Check | Value | Result |
| --- | ---: | --- |
| val MAPE <= 11.6% | 0.1125 | PASS |
| median APE <= 8.0% | 0.0618 | PASS |
| band coverage in 75%-85% | 0.8173 | PASS |
| serving parity <= 1e-03 | 0.0000 | PASS |

## Reading (generated from the tables)

- Error is lowest in the 500-700M band (MAPE 7.8%, 3,056 rows) and highest in under 300M (MAPE 21.9%, 3,082 rows).
- Thin groups are the weak spot: unseen 29.8%; 1-9 train rows 17.2%; 200+ train rows 10.2%.
- Median APE is 6.2% while MAPE is 11.2%; 11.2% of val rows are off by more than 20 % and 2.1% by more than 50 %.
- Baselines on the same rows: national median MAPE 75.0%, brand|model median 35.1%, model 11.2%.
- Without rows flagged deposit/placeholder/implausible-year: MAPE 9.8% on 13,920 rows (93.0% of val).
- In the under-300M band MAPE moves from 21.9% (all rows) to 16.0% after those flags are dropped — part of the cheap-car error is ad quality, not valuation skill.
- Luxury brands: MAPE 12.9% on 2,489 rows; mainstream 10.9% on 12,475 rows.
- Manual: MAPE 15.2% on 2,175 rows; automatic 10.5% on 12,750 rows.
- By trim rank: base 11.5% (347 rows); mid 9.4% (929 rows); top 6.2% (1,623 rows); unknown 12.1% (12,065 rows).

## What this page does and does not say

- It measures **advertised prices**, not transaction prices (`docs/data_limitations.md` §1).
- A row whose asking price is a deposit makes the model look wrong; the clean slice drops rows carrying a label flag, and `docs/error_audit_25.md` reads the tail by hand.
- The band's coverage is measured on val; the conformal shift itself was fitted on train OOF, so val is still a holdout.
- The test split is **not** used here: plan §1 allows one evaluation at the freeze.
