# v2 snapshot — what the backfill actually observed

Generated 2026-11-15T00:57:59+00:00 by `python -m tools.apply_backfill --write`.
Patch: `F:\Code\IntroDS\data\processed\bonbanh_backfill.csv`.

**v1 is untouched**: the same rows, the same `listing_id` order, the same split and byte-identical
`price_vnd`, `mileage_km`, `brand`, `model`, `manufacture_year` (asserted in the code, not by eye).

| Split | Rows | engine_capacity | seller_type | body_type | sub_model_trim |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 70,244 | 31 | 1,981 | 3 | 4,351 |
| val | 14,964 | 9 | 406 | 1 | 887 |
| test | 14,980 | 8 | 424 | 0 | 885 |

## Where the new cells come from

- `bonbanh_detail:<field>` — parsed from the live detail page by `tools/backfill_bonbanh.py` (engine displacement from "Động cơ", the salon subdomain for `seller_type`, "Kiểu dáng" for `body_type`).
- `model_trim` — the trim text derived from the `model` string we already had. A bonbanh title is `brand + model + trim`; the trim is what is left after the canonical model, and it is only written when the model contains a tier word. No request, no statistic.

`imputed` loses every column that is now observed, so a downstream tool can still tell a crawled value from an imputed one, and `v2_filled` says which is which per row.

## What the crawl yielded

The crawler ran to completion over the 7,704 rows where a page was the only source, with a jittered 2.5 s cadence, a 180/300/600 s cooldown ladder and a probe after each step, and no row written for a blocked request. What it found is field-specific: `seller_type` was recoverable for most rows (the page names the salon, or has no salon link at all), while `Động cơ` is printed with an **empty value** on most older bonbanh ads — the recon's 81 % counted the label and a number anywhere on the page, not a fillable cell. That is why `engine_capacity` barely moves and the ablation stays at the trim-only level (`docs/features_steps_v2.md`).

| Measure | Value |
| --- | ---: |
| pages attempted | 7,704 |
| `engine_capacity` filled | 48 |
| `seller_type` filled | 2,811 |
| `body_type` filled | 4 |
