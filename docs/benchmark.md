# Benchmark — week-3 models on the val split

Generated 2026-11-07T04:44:26+00:00 by `python -m src.models.benchmark`. Every number is on the frozen `val` split (14,964 rows); the test split is evaluated exactly once at M2 and is **not** part of this table.

Feature tables: `data/master/{train,val}_features_{minimal,full}.csv`. Tuning budget: **90s per model** (random search, 2 grouped folds, 15k sample). Models without a budget entry use fixed parameters.

| Features | Model | R²(log) | RMSE(log) | R²(VND) | MAE (VND) | MAPE | median APE | rows | s | tuning |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| full | lightgbm+tuned | 0.9486 | 0.1876 | 0.9243 | 80,996,654 | 0.112 | 0.061 | 70,244 | 66.5 | 90s/10 trials |
| full | catboost | 0.9465 | 0.1914 | 0.9134 | 91,143,312 | 0.120 | 0.069 | 70,244 | 346.0 | fixed |
| full | lightgbm | 0.9462 | 0.1919 | 0.9213 | 82,441,420 | 0.115 | 0.063 | 70,244 | 6.6 | fixed |
| full | xgboost+tuned | 0.9440 | 0.1957 | 0.9010 | 78,041,635 | 0.110 | 0.059 | 70,244 | 97.1 | 90s/10 trials |
| full | rf | 0.9411 | 0.2008 | 0.9094 | 87,698,367 | 0.121 | 0.064 | 70,244 | 88.6 | fixed |
| full | xgboost | 0.9409 | 0.2011 | 0.8952 | 78,256,273 | 0.111 | 0.057 | 70,244 | 15.4 | fixed |
| full | ridge | 0.8970 | 0.2655 | 0.8200 | 141,897,201 | 0.180 | 0.104 | 70,244 | 3.2 | fixed |
| full | median | 0.8773 | 0.2899 | 0.8703 | 101,649,813 | 0.188 | 0.073 | 70,244 | 1.2 | fixed |
| full | elasticnet | 0.8722 | 0.2958 | 0.7458 | 174,713,377 | 0.212 | 0.134 | 70,244 | 61.6 | fixed |
| full | lasso | 0.8561 | 0.3139 | 0.7136 | 190,664,684 | 0.229 | 0.148 | 70,244 | 27.9 | fixed |
| full | knn | 0.8553 | 0.3147 | 0.7387 | 181,201,164 | 0.228 | 0.134 | 8,000 | 0.6 | fixed |
| minimal | lightgbm+tuned | 0.9460 | 0.1922 | 0.9166 | 84,128,146 | 0.116 | 0.065 | 70,244 | 70.9 | 90s/10 trials |
| minimal | lightgbm | 0.9447 | 0.1945 | 0.9151 | 84,885,802 | 0.117 | 0.064 | 70,244 | 5.5 | fixed |
| minimal | catboost | 0.9438 | 0.1961 | 0.9056 | 95,474,212 | 0.123 | 0.071 | 70,244 | 293.6 | fixed |
| minimal | xgboost+tuned | 0.9418 | 0.1996 | 0.8977 | 80,330,313 | 0.112 | 0.061 | 70,244 | 89.8 | 90s/10 trials |
| minimal | xgboost | 0.9388 | 0.2046 | 0.8914 | 80,850,994 | 0.113 | 0.060 | 70,244 | 7.1 | fixed |
| minimal | rf | 0.9370 | 0.2076 | 0.8960 | 94,182,039 | 0.126 | 0.067 | 70,244 | 81.5 | fixed |
| minimal | median | 0.8773 | 0.2899 | 0.8703 | 101,649,813 | 0.188 | 0.073 | 70,244 | 1.2 | fixed |
| minimal | ridge | 0.8746 | 0.2930 | 0.7824 | 157,731,450 | 0.206 | 0.115 | 70,244 | 7.9 | fixed |
| minimal | elasticnet | 0.8507 | 0.3198 | 0.7138 | 192,621,090 | 0.237 | 0.147 | 70,244 | 18.5 | fixed |
| minimal | knn | 0.8372 | 0.3338 | 0.7273 | 194,474,953 | 0.259 | 0.148 | 8,000 | 0.5 | fixed |
| minimal | lasso | 0.8344 | 0.3367 | 0.6868 | 207,337,967 | 0.255 | 0.162 | 70,244 | 21.5 | fixed |

Best on val: **lightgbm+tuned / full** — R²(log) 0.9486, MAPE 11.2%.

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
| median / minimal | 5.55e-117 | worse (p < 0.05) |
| median / full | 5.55e-117 | worse (p < 0.05) |
| ridge / full | 0 | worse (p < 0.05) |
| rf / minimal | 3.75e-30 | worse (p < 0.05) |
| xgboost / minimal | 0.0828 | not distinguishable (p ≥ 0.05) |
| xgboost / full | 2.89e-15 | worse (p < 0.05) |
| rf / full | 3.79e-07 | worse (p < 0.05) |
| xgboost+tuned / minimal | 0.838 | not distinguishable (p ≥ 0.05) |
| catboost / minimal | 4.54e-51 | worse (p < 0.05) |
| xgboost+tuned / full | 2.91e-06 | worse (p < 0.05) |
| lightgbm / minimal | 3.8e-22 | worse (p < 0.05) |
| lightgbm+tuned / minimal | 6.87e-19 | worse (p < 0.05) |
| lightgbm / full | 1.76e-11 | worse (p < 0.05) |
| catboost / full | 2.21e-29 | worse (p < 0.05) |

## Reading the table

- Canary floor from `tools/baseline_smoke`: R²(log) 0.946 / MAPE 11.6%. This benchmark's best is 0.9486 / 11.2%, above the floor, so the extra complexity is justified.
- R²(VND) is dominated by the price spread, so it always looks better than R²(log); MAPE and median APE are the honest per-listing numbers.
- A `rows` value below 70,244 means the model was subsampled for runtime (k-NN by design); the column makes that visible instead of hiding it.
- No test-set number appears here on purpose (plan §1: one evaluation at M2).
