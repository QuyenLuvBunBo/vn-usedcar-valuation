# Feature-group ablation

Baseline R²(log) **0.9448** with 23 features, 70,244 train rows, estimator **lgbm** (36.2s total).

Relative value only: a fixed estimator, one group removed at a time. This is not the benchmark table and does not replace it.

| Group dropped | Columns | R²(log) without it | ΔR² |
| --- | --- | ---: | ---: |
| timing | `manufacture_year`, `vehicle_age`, `age_band`, `brand_age_band` | 0.9306 | +0.0142 |
| cat_identity | `brand`, `model`, `model_group` | 0.9309 | +0.0139 |
| cat_spec | `transmission`, `fuel_type`, `origin`, `body_type`, `seller_type` | 0.9346 | +0.0102 |
| size | `engine_capacity`, `engine_per_seat`, `seats` | 0.9394 | +0.0054 |
| source | `source_platform` | 0.9422 | +0.0026 |
| usage | `mileage_km`, `km_per_year` | 0.9436 | +0.0012 |
| flags | `n_imputed` | 0.9441 | +0.0007 |
| luxury | `is_luxury_segment` | 0.9447 | +0.0001 |
| price_stats | `brand_retention_rate`, `province_price_index` | 0.9448 | +0.0000 |
| geo | `province_group` | 0.9451 | -0.0003 |

ΔR² is the drop in R²(log) when the group is removed: a large ΔR² means the group carries weight, a near-zero or negative ΔR² means this estimator does not need it.
