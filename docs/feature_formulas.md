# Feature formulas — what each column is, and where the leak could hide

Owner of this note: Quyết (`docs/week3_plan.md` §4.1). Everything below is read from
`src/features/build_features.py` and `data/master/feature_stats.json`, so it describes the code that
actually produced the frozen tables rather than an intention.

Reproduce: `python -m src.features.build_features --features full --split all`.

## 1. Two kinds of column

`build_features.py` splits every derived column into two families, and the split is the whole
leak-control argument:

| Family | Depends on | Fitted where | Safe to compute per split? |
|---|---|---|---|
| **stateless** | only the row itself | nowhere | yes — train, val and test give the same value for the same row |
| **fitted** | other rows | **train only**, then applied unchanged | no — it must be learned once, on train |

## 2. Stateless columns (row-local)

Reference year is the **latest capture year in the data** (2026), not today's date, so the numbers do
not drift when the project is re-run later:

```
vehicle_age      = clip(reference_year − manufacture_year, lower = 0)
km_per_year      = mileage_km / max(vehicle_age, 1)
engine_per_seat  = engine_capacity / seats            (seats = 0 → missing)
n_imputed        = number of `;`-separated tokens in `imputed`
is_luxury_segment= "yes" if brand ∈ LUXURY_BRANDS else "no"
age_band         = 0-2 → "0-2" · 3-5 → "3-5" · 6-9 → "6-9" · 10-14 → "10-14" · 15+ → "15+" · else "unknown"
brand_age_band   = f"{brand}|{age_band}"
```

Two deliberate choices:

- **`is_luxury_segment` is a brand list, never a price threshold.** Defining "luxury" by price would put
  the target on both sides of the model. The 20 brands are in `LUXURY_BRANDS` (Mercedes-Benz, BMW, Audi,
  Lexus, Porsche, Land Rover, Jaguar, Volvo, Infiniti, Acura, Cadillac, Tesla, Maserati, Bentley,
  Rolls-Royce, Ferrari, Lamborghini, McLaren, Genesis, MINI).
- **`km_per_year` divides by `max(vehicle_age, 1)`**, so a brand-new car does not divide by zero and a
  car "aged 0" is treated as one year old rather than as an infinite rate.

## 3. Fitted columns (train only, applied unchanged to val/test)

### 3.1 `province_group` — a frequency bucket, not a geography

Provinces with **≥ 50 train rows** keep their own label; every other province becomes `"Other"`.
The cut is a property of the *train* frequency, so a thin test row cannot change the grouping.

Result on the frozen snapshot: **50 provinces kept**, the long tail folded into `Other`.

### 3.2 `brand_retention_rate` — how much of its price a brand keeps with age

```
young_median(brand) = median(price_vnd | vehicle_age ∈ [1, 2])
older_median(brand) = median(price_vnd | vehicle_age ∈ [5, 6])
retention(brand)    = clip(older_median / young_median, 0.05, 1.0)
```

A brand needs **≥ 20 rows in both age bands**; otherwise it receives the global rate, which is
`older_median / young_median` over all train rows.

Result: **21 brands learned**, global default **0.8815**, observed range **0.5229 – 1.0000**
(BMW 1.0000, VinFast 0.9787, MG 0.9749, Toyota 0.9504, Nissan 0.9301). Unseen brand → global rate.

### 3.3 `province_price_index` — a province's price level relative to the country

```
global_log      = median(log(price_vnd))                     over all train rows
province_log(n) = median(log(price_vnd))                     over the province's train rows, n of them
shrunk(n)       = (province_log(n) · n + global_log · 50) / (n + 50)
index(province) = exp(shrunk(n) − global_log)
```

The shrink term (`SHRINK_K = 50`) pulls a thin province toward the national level: with n = 50 the
province keeps half of its own signal. Only the provinces kept by `province_group` get an index; every
other province gets **1.0**.

Result: **50 provinces**, range **0.5329 – 1.1727** (Hà Nội 1.1727, Quảng Ninh 1.1172,
TP. Hồ Chí Minh 1.0960, Kon Tum 0.9962, Long An 0.9503). Unseen province → 1.0.

## 4. Why these are leak-safe, and where they are not

- All three fitted columns are learned on **train only** and applied to val/test without refitting, so
  no validation row can influence its own feature.
- `province_price_index` and `brand_retention_rate` are computed from **prices on train**, i.e. from the
  target. That is legitimate as a train-fitted statistic, but it is exactly why the preprocessor treats
  the two price-statistic columns as **excluded by default** (`--include-frozen-price-stats` must be an
  explicit choice): inside an outer cross-validation loop, a statistic built on the whole training set
  would leak the held-out fold's prices into its own features.
- Nothing here repairs upstream decisions: imputation and category grouping already happened before the
  cohort reached this repository, so a strictly inside-each-outer-fold CV would have to rebuild them.

## 5. `geo_tier` — named in the plan, never built

`docs/week3_plan.md` §4.1 assigns `province_price_index`, **`geo_tier`** and the cardinality study.
`geo_tier` appears in no source file and in no frozen table; the only other mention is a proposal in
`docs/sources/oto.md` ("Hà Nội/TP.HCM vs provinces"). What exists and covers the same intent is:

- `province_group` — the train-frequency bucket (§3.1), a categorical;
- `province_price_index` — the shrunk price level (§3.3), a numeric.

Recommendation: **do not add `geo_tier` now.** The feature tables are frozen for the milestone, so a new
column would force every partner to rebuild and invalidate their numbers. Record the substitution in the
report §4 (one sentence) instead, and if the team still wants a three-level tier, add it as
`geo_tier ∈ {hanoi_hcm, other_kept, other}` in the **next** milestone together with a rebuilt split.
