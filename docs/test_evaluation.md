# The single test evaluation

**This is the one evaluation of the test split for the whole project** (plan §1: *one* evaluation at the freeze). Every other number in `docs/benchmark.md` is on `val`.

- Measured: 2026-11-08T05:11:09+00:00
- Model: **lightgbm+tuned / full** (seed 42)
- Parameters: `{"n_estimators": 900, "learning_rate": 0.03, "num_leaves": 63, "min_child_samples": 20}`
- Tuning: `{"budget_seconds": 0, "trials": 0, "frozen": true, "note": "hyperparameters passed via --params (frozen before the test run)"}`
- Rows: **14,980** test listings · band: calibrated on train OOF
- Predictions: `F:\Code\IntroDS\data\master\predictions_test.csv`

| Metric | Test |
| --- | ---: |
| R²(log) | 0.9487 |
| RMSE(log) | 0.1869 |
| R²(VND) | 0.9026 |
| MAE (VND) | 89,731,484 |
| MAPE | 0.109 |
| median APE | 0.061 |
| MAPE clean | 0.101 |

`MAPE clean` drops the 19 test rows whose asking price is below a quarter of the estimate — the deposit-style ads described in `docs/error_audit_25.md`. Quote both numbers or quote neither.

Do not tune, refit or re-select a model after reading this table: the split is spent.
