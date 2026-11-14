# Feature steps — what each change buys, on two fixed hold-outs

Generated 2026-11-14T07:21:22+00:00 by `python -m tools.feature_steps_eval`.
Fixed estimator (LightGBM, 300 trees); only the feature set and the row weights change between rows. `val_full` = 14,964 rows, `val_clean` = 9,644 rows (the same rows for every step).

| # | Step | Features | Train rows | R² val_full | MAPE val_full | ΔMAPE | R² val_clean | MAPE val_clean | ΔMAPE |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline | 23 | 70,244 | 0.9448 | 0.1169 |  | 0.9519 | 0.1038 |  |
| 2 | + weight_repeats | 23 | 70,244 | 0.9453 | 0.1160 | -0.0009 | 0.9527 | 0.1030 | -0.0008 |
| 3 | + engine parse & trim_rank | 30 | 70,244 | 0.9471 | 0.1125 | -0.0035 | 0.9553 | 0.0989 | -0.0041 |
| 4 | + canonical model & variants | 29 | 70,244 | 0.9476 | 0.1123 | -0.0002 | 0.9550 | 0.0989 | +0.0000 |

## Reading

- A step pays only if **both** columns improve: `val_full` is the deployment number, `val_clean` proves the gain is not the evaluation set getting easier.
- Step 3 keeps `engine_capacity` beside `engine_capacity_parsed`, so the delta is purely additive; step 4 drops `model` in favour of `model_canonical` and keeps `model_group`.
- The raw `model` column still exists in the v2 files — nothing was overwritten.
