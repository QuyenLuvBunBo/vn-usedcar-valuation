# Feature-group ablation

Baseline R²(log) **0.9184** with 23 features, 20,000 train rows, estimator **ridge** (35.3s total).

Relative value only: a fixed estimator, one group removed at a time. This is not the benchmark table and does not replace it.

| Group dropped | Columns | R²(log) without it | ΔR² |
| --- | --- | ---: | ---: |
| timing | `manufacture_year`, `vehicle_age`, `age_band`, `brand_age_band` | 0.7904 | +0.1280 |
| cat_identity | `brand`, `model`, `model_group` | 0.8656 | +0.0528 |
| cat_spec | `transmission`, `fuel_type`, `origin`, `body_type`, `seller_type` | 0.9109 | +0.0075 |
| size | `engine_capacity`, `engine_per_seat`, `seats` | 0.9149 | +0.0035 |
| source | `source_platform` | 0.9154 | +0.0030 |
| flags | `n_imputed`, `is_luxury_segment` | 0.9169 | +0.0015 |
| usage | `mileage_km`, `km_per_year` | 0.9183 | +0.0001 |
| geo | `province_group`, `province_price_index`, `brand_retention_rate` | 0.9187 | -0.0003 |

ΔR² is the drop in R²(log) when the group is removed: a large ΔR² means the group carries weight, a near-zero or negative ΔR² means this estimator does not need it.
