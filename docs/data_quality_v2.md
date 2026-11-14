# v2 snapshot — what the backfill actually observed

Generated 2026-11-14T07:20:22+00:00 by `python -m tools.apply_backfill --write`.
Patch: `none — no page was fetched`.

**v1 is untouched**: the same rows, the same `listing_id` order, the same split and byte-identical
`price_vnd`, `mileage_km`, `brand`, `model`, `manufacture_year` (asserted in the code, not by eye).

| Split | Rows | engine_capacity | seller_type | body_type | sub_model_trim |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 70,244 | 0 | 0 | 0 | 4,351 |
| val | 14,964 | 0 | 0 | 0 | 887 |
| test | 14,980 | 0 | 0 | 0 | 885 |

## Where the new cells come from

- `bonbanh_detail:<field>` — parsed from the live detail page by `tools/backfill_bonbanh.py` (engine displacement from "Động cơ", the salon subdomain for `seller_type`, "Kiểu dáng" for `body_type`).
- `model_trim` — the trim text derived from the `model` string we already had. A bonbanh title is `brand + model + trim`; the trim is what is left after the canonical model, and it is only written when the model contains a tier word. No request, no statistic.

`imputed` loses every column that is now observed, so a downstream tool can still tell a crawled value from an imputed one, and `v2_filled` says which is which per row.

## Status of the bonbanh crawl

The crawler (`tools/backfill_bonbanh.py`) is resumable and soft-block aware: bonbanh answered a 200 captcha page after ~2,100 concurrent requests, so the run stopped and recorded nothing for those rows (`docs/recon_decision.md` §3). Re-running the command picks up exactly where it stopped.
