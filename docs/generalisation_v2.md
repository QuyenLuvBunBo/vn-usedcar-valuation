# Generalisation — what the score looks like on a nameplate the model never saw

Generated 2026-11-14T07:21:53+00:00 by `python -m tools.generalisation_check` (features `v2`, share 20%, seed 42).

**565 `brand|model` levels (14,084 train rows, 20.1% of train) were removed from training.** The estimator is a fixed LightGBM (300 trees); nothing else changed.

Price-derived features dropped: **True** (`brand_retention_rate`, `province_price_index`) — they were fitted on the full train partition, so on a leave-combo-out test they would carry information about the hidden nameplates. The hold-out itself is chosen from `brand|model` strings and row counts only.

| Slice of the val split | Rows | R²(log) | MAPE | median APE |
| --- | ---: | ---: | ---: | ---: |
| val-seen-combos | 11,691 | 0.9532 | 0.1101 | 0.0604 |
| val-heldout-combos | 2,937 | 0.8407 | 0.2387 | 0.1790 |
| val-unseen-combos | 336 | 0.7426 | 0.3215 | 0.2215 |

Reference — the same estimator trained on **all** train rows, scored on all 14,964 val rows: R²(log) 0.9463, MAPE 0.1133.

## Reading

- The reference is scored on **all** val rows, including the hard slices below, so it is lower than `val-seen-combos`: that gap is composition, not damage. Compare the slices with each other.
- `val-seen-combos` is the honest version of the headline number for a nameplate the model knows.
- `val-heldout-combos` is the stress test: no row of that nameplate was ever in training.
- `val-unseen-combos` is the strongest test in the snapshot — those nameplates are absent from train even before the hold-out.
- The drop is **not** a bug: a used-car price is largely a nameplate-and-age lookup (`docs/data_limitations.md`), and a model that has never seen the nameplate can only use segment-level signals (engine, body, year, platform).
- `--features v2` repeats the same test on the extended table (engine parsed from the badge, trim rank, canonical model), which is where a better generalisation would show up first.
