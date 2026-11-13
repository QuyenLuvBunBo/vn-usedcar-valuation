# Label cleaning — does it help the model or only the validation set?

Generated 2026-11-13T22:04:23+00:00 by `python -m tools.label_cleaning_eval`.
Fixed estimator (LightGBM, 300 trees) on the `full` feature set; only the **training set** changes between rows.

`val_full` = 14,964 rows · `val_clean` = 9,644 rows — val rows whose flag_count == 0 in label_flags.csv (identical for every mode, so a difference is a training effect).

| Training mode | Train rows | R²(log) val_full | MAPE val_full | R²(log) val_clean | MAPE val_clean |
| --- | ---: | ---: | ---: | ---: | ---: |
| none | 70,244 | 0.9448 | 0.1169 | 0.9519 | 0.1038 |
| drop_deposit | 68,692 | 0.9338 | 0.1299 | 0.9548 | 0.1017 |
| drop_all | 45,205 | 0.9293 | 0.1357 | 0.9525 | 0.1051 |
| weight_repeats | 70,244 | 0.9453 | 0.1160 | 0.9527 | 0.1030 |

## What this run says

- `drop_deposit` (train 68,692 rows): MAPE val_full +0.0130, val_clean -0.0021 — better on the clean rows but **worse on val_full**: the gain comes from the rows it removed, so it must not be quoted as a deployment improvement.
- `drop_all` (train 45,205 rows): MAPE val_full +0.0188, val_clean +0.0013 — mixed: read the two columns separately before quoting either.
- `weight_repeats` (train 70,244 rows): MAPE val_full -0.0009, val_clean -0.0008 — within noise on both hold-outs.

## Reading it

- **val_full** is what a deployment meets; **val_clean** is the same rows for every mode.
- An improvement that appears on **both** columns is a better training set.
- An improvement that appears **only on val_full** means the flagged rows left the *evaluation* too: that is an easier test, not a better model, and quoting it alone would be dishonest.
- The estimator and its parameters are fixed on purpose: this compares training sets, not models.