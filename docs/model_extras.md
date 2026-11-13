# Model extras — importance, partial dependence, seed stability, learning curve

LightGBM on `full` features. Baseline on val: R²(log) 0.9458, MAPE 11.6%. Reproduce with `python -m tools.model_extras`.

## Permutation importance (top 12, RMSE in log space)

| Feature | Importance | sd |
| --- | ---: | ---: |
| `brand_age_band` | 0.5096 | 0.0812 |
| `manufacture_year` | 0.2621 | 0.0362 |
| `model` | 0.2314 | 0.0392 |
| `model_group` | 0.1803 | 0.0353 |
| `brand` | 0.1317 | 0.0210 |
| `engine_capacity` | 0.1301 | 0.0244 |
| `transmission` | 0.1152 | 0.0254 |
| `body_type` | 0.0990 | 0.0242 |
| `vehicle_age` | 0.0759 | 0.0165 |
| `source_platform` | 0.0759 | 0.0231 |
| `mileage_km` | 0.0706 | 0.0160 |
| `seats` | 0.0653 | 0.0213 |

## Partial dependence (mean predicted price while the feature is fixed)

| Feature | Value | Mean prediction (VND) | share of val ≤ value |
| --- | ---: | ---: | ---: |
| `brand_age_band` | Toyota|3-5 | 655,938,170 | 0.05 |
| `brand_age_band` | Toyota|6-9 | 616,340,697 | 0.05 |
| `brand_age_band` | Toyota|0-2 | 716,938,907 | 0.04 |
| `brand_age_band` | VinFast|0-2 | 587,589,857 | 0.04 |
| `brand_age_band` | Kia|3-5 | 624,648,561 | 0.03 |
| `manufacture_year` | 2011.0 | 492,762,388 | 0.10 |
| `manufacture_year` | 2017.0 | 642,982,153 | 0.27 |
| `manufacture_year` | 2021.0 | 793,193,865 | 0.55 |
| `manufacture_year` | 2023.0 | 840,015,193 | 0.75 |
| `manufacture_year` | 2025.0 | 857,557,133 | 0.93 |
| `model` | Vios | 650,721,476 | 0.03 |
| `model` | Ranger | 707,805,284 | 0.02 |
| `model` | Innova | 717,721,681 | 0.02 |
| `model` | Fortuner | 769,109,481 | 0.02 |
| `model` | Everest | 782,891,111 | 0.02 |

## Seed stability (3 seeds, 20k rows, 300 trees)

| Seed | R²(log) |
| ---: | ---: |
| 42 | 0.9305 |
| 43 | 0.9312 |
| 44 | 0.9308 |

Mean 0.9308 ± 0.0003. A spread above ~0.002 would mean model comparisons in §5 need the paired Wilcoxon test rather than a ranking by R².

## Learning curve

| Train rows | R²(log) |
| ---: | ---: |
| 7,024 | 0.8947 |
| 17,561 | 0.9107 |
| 35,122 | 0.9311 |
| 70,244 | 0.9440 |

If the last two points are within noise, more rows will not help and the report should say the ceiling is the feature set, not the sample size.
