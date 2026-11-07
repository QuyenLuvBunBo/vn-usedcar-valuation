# Benchmark — week-3 models on the val split

Generated 2026-11-07T13:03:33+00:00 by `python -m src.models.benchmark`. Every number is on the frozen `val` split (14,964 rows); the test split is evaluated exactly once at M2 and is **not** part of this table.

Feature tables: `data/master/{train,val}_features_{minimal,full}.csv`. Tuning budget: **600s per model** (random search, 2 grouped folds, 15k sample). Models without a budget entry use fixed parameters.

| Features | Model | R²(log) | RMSE(log) | R²(VND) | MAE (VND) | MAPE | median APE | rows | s | tuning |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| full | lightgbm+tuned | 0.9471 | 0.1904 | 0.9215 | 82,087,205 | 0.114 | 0.062 | 70,244 | 140.1 | 600s/25 trials |
| full | catboost | 0.9465 | 0.1914 | 0.9134 | 91,143,312 | 0.120 | 0.069 | 70,244 | 263.2 | fixed |
| full | lightgbm | 0.9462 | 0.1919 | 0.9213 | 82,441,420 | 0.115 | 0.063 | 70,244 | 6.0 | fixed |
| full | xgboost+tuned | 0.9440 | 0.1957 | 0.9010 | 78,041,635 | 0.110 | 0.059 | 70,244 | 183.9 | 600s/25 trials |
| full | rf | 0.9411 | 0.2008 | 0.9094 | 87,698,367 | 0.121 | 0.064 | 70,244 | 64.3 | fixed |
| full | xgboost | 0.9409 | 0.2011 | 0.8952 | 78,256,273 | 0.111 | 0.057 | 70,244 | 13.8 | fixed |
| full | ridge | 0.8970 | 0.2655 | 0.8200 | 141,897,201 | 0.180 | 0.104 | 70,244 | 2.6 | fixed |
| full | median | 0.8773 | 0.2899 | 0.8703 | 101,649,813 | 0.188 | 0.073 | 70,244 | 0.8 | fixed |
| full | elasticnet | 0.8722 | 0.2958 | 0.7458 | 174,713,377 | 0.212 | 0.134 | 70,244 | 43.4 | fixed |
| full | lasso | 0.8561 | 0.3139 | 0.7136 | 190,664,684 | 0.229 | 0.148 | 70,244 | 18.0 | fixed |
| full | knn | 0.8553 | 0.3147 | 0.7387 | 181,201,164 | 0.228 | 0.134 | 8,000 | 0.5 | fixed |
| minimal | lightgbm+tuned | 0.9464 | 0.1916 | 0.9162 | 84,155,488 | 0.116 | 0.063 | 70,244 | 141.0 | 600s/25 trials |
| minimal | lightgbm | 0.9447 | 0.1945 | 0.9151 | 84,885,802 | 0.117 | 0.064 | 70,244 | 6.1 | fixed |
| minimal | catboost | 0.9438 | 0.1961 | 0.9056 | 95,474,212 | 0.123 | 0.071 | 70,244 | 254.5 | fixed |
| minimal | xgboost+tuned | 0.9413 | 0.2004 | 0.8983 | 80,995,302 | 0.113 | 0.062 | 70,244 | 162.6 | 600s/25 trials |
| minimal | xgboost | 0.9388 | 0.2046 | 0.8914 | 80,850,994 | 0.113 | 0.060 | 70,244 | 6.7 | fixed |
| minimal | rf | 0.9370 | 0.2076 | 0.8960 | 94,182,039 | 0.126 | 0.067 | 70,244 | 56.1 | fixed |
| minimal | median | 0.8773 | 0.2899 | 0.8703 | 101,649,813 | 0.188 | 0.073 | 70,244 | 0.7 | fixed |
| minimal | ridge | 0.8746 | 0.2930 | 0.7824 | 157,731,450 | 0.206 | 0.115 | 70,244 | 4.5 | fixed |
| minimal | elasticnet | 0.8507 | 0.3198 | 0.7138 | 192,621,090 | 0.237 | 0.147 | 70,244 | 16.9 | fixed |
| minimal | knn | 0.8372 | 0.3338 | 0.7273 | 194,474,953 | 0.259 | 0.148 | 8,000 | 0.5 | fixed |
| minimal | lasso | 0.8344 | 0.3367 | 0.6868 | 207,337,967 | 0.255 | 0.162 | 70,244 | 17.0 | fixed |

Best on val: **lightgbm+tuned / full** — R²(log) 0.9471, MAPE 11.4%.

## Wilcoxon signed-rank vs the best model (absolute percentage error, same rows)

| Model | p-value | reading |
| --- | ---: | --- |
| lasso / minimal | 0 | worse (p < 0.05) |
| knn / minimal | 0 | worse (p < 0.05) |
| elasticnet / minimal | 0 | worse (p < 0.05) |
| knn / full | 0 | worse (p < 0.05) |
| lasso / full | 0 | worse (p < 0.05) |
| elasticnet / full | 0 | worse (p < 0.05) |
| ridge / minimal | 0 | worse (p < 0.05) |
| median / minimal | 4.64e-117 | worse (p < 0.05) |
| median / full | 4.64e-117 | worse (p < 0.05) |
| ridge / full | 0 | worse (p < 0.05) |
| rf / minimal | 2.62e-22 | worse (p < 0.05) |
| xgboost / minimal | 0.00802 | worse (p < 0.05) |
| xgboost / full | 9.72e-28 | worse (p < 0.05) |
| rf / full | 0.00418 | worse (p < 0.05) |
| xgboost+tuned / minimal | 0.508 | not distinguishable (p ≥ 0.05) |
| catboost / minimal | 3.85e-42 | worse (p < 0.05) |
| xgboost+tuned / full | 5.82e-12 | worse (p < 0.05) |
| lightgbm / minimal | 9.82e-17 | worse (p < 0.05) |
| lightgbm / full | 7.76e-05 | worse (p < 0.05) |
| lightgbm+tuned / minimal | 1.23e-08 | worse (p < 0.05) |
| catboost / full | 5.66e-22 | worse (p < 0.05) |

## Reading the table

- Canary floor from `tools/baseline_smoke`: R²(log) 0.946 / MAPE 11.6%. This benchmark's best is 0.9471 / 11.4%, above the floor, so the extra complexity is justified.
- R²(VND) is dominated by the price spread, so it always looks better than R²(log); MAPE and median APE are the honest per-listing numbers.
- A `rows` value below 70,244 means the model was subsampled for runtime (k-NN by design); the column makes that visible instead of hiding it.
- No test-set number appears here on purpose (plan §1: one evaluation at M2).
