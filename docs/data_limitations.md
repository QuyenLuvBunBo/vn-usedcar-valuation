# Data limitations — the three that belong in §8

Every number here comes from the artefacts of the frozen snapshot, not from memory:
`missing_report.json`, `normalize_report.json`, `split_summary.json` (all in `data/master/`).

## 1. Asking price is not transaction price

The dataset records **what sellers ask**, scraped on the day of capture. No platform exposes the
agreed price, so every prediction in this project is a prediction of the **advertised** price. A car
listed at 700 million and sold at 650 million is labelled 700 million. This is the single largest
source of irreducible error and it must be the first line of §8, not a footnote.

## 2. Two columns are mostly missing, and one platform is a stub

| Column | Missing in train | Consequence |
| --- | ---: | --- |
| `engine_capacity` | **61.2%** | the model runs on a column that is absent for three cars in five; imputation adds noise, so its importance is understated and its PD curve is unreliable |
| `sub_model_trim` | **55.7%** | trim is the feature that separates an LX from an EX; half the table cannot use it |
| `seller_type` | 34.1% | dealership vs private pricing differs, but a third of rows cannot be classified |
| `origin` | 28.6% | import vs domestic is unknown for a third of the table, which is exactly the Case 3 failure mode |

Platform volume in the master table (100,887 rows): bonbanh 21,223 · oto.com.vn 20,764 · chotot
13,631 (19,428 across all splits) · tinbanxe 5,355 · muaban 4,921 · carpla 2,932 · vucar 1,515 ·
**carmudi 366**. Carmudi was effectively cut off mid-crawl; 366 rows cannot carry a platform-level
segment in §6, so any per-platform claim about it is noise.

## 3. Brand spellings needed normalising before anything could be counted

`normalize_report.json` folds **164 raw brand spellings into 146 brands** — `Hyundai`/`HYUNDAI`,
`Mercedes Benz`/`Mercedes-Benz`, `VinFast`/`Vinfast`, `LandRover`/`Land Rover`, `MITSUBISHI`/
`Mitsubishi`. Counting brands before that step overstates the catalogue, and a target encoding of
`brand|model` fitted on the raw strings would split one car into two levels.

## Also worth stating

- **19 labelled customers missing:** 100,887 master rows − 100,868 labelled = 19 rows with no usable
  price; they are dropped, not imputed, because the target cannot be imputed.
- **10,906 flagged rows** in train carry at least one `quality_flags` entry; the model sees no flags
  (they are forbidden as features), so flagged rows are learned as ordinary rows.
- **One snapshot only.** Every number refers to `scraped_at` in this snapshot; the market moves and
  the model does not.
- **Duplicate groups, not duplicate rows:** 75,496 groups for 100,887 listings means cross-posting is
  real (the same car on two platforms). The grouped split keeps a group on one side, so the val/test
  numbers are not inflated by re-listing the same car.
- **No accident, service or ownership history** exists in the source data, which is why the three
  structural failure modes (bait price, odometer manipulation, import/salvage) cannot be fixed by
  modelling — see `docs/case_studies.md`.

## 4. Four defects found while reading the worst predictions


These come from `docs/error_audit_25.md`, which reads all 25 worst val rows field by field. They are
listed here because each one changes how a number in the report should be read.

1. **Deposit-style asking prices.** 23 of the 25 worst rows ask less than a quarter of the model's
   estimate, and only **23 rows in the whole val split (0,15 %)** are that cheap — **69,6 %** of them
   from Chợ Tốt. A 2020 Mitsubishi Triton listed at 42 million is a deposit, not a price. `price_status`
   says `"full"` on **all 25**, so the column that is supposed to flag this cannot: the filter has to be
   added upstream (`deposit_suspected`: asking price below 25 % of the segment median) and applied

## 5. Chợ Tốt: the platform is crawlable, but it does not publish two of the columns

Two measurements, both on the live site (2026-11-14):

- **The old IDs are gone.** Of 80 sampled v1 ads, **0** still exist: 68 answer 200 with
  "Tin đăng không tồn tại" and 12 answer HTTP 410. A crawler that only checks the status code records
  those 68 as alive, which is why `docs/recon_detail_fields.md` counts a `dead_removed` state.
- **The live pages do not carry `engine_capacity` or `sub_model_trim`.** The page declares both labels
  (`"Dung tích động cơ", "param":"engine_capacity", "from":"product_graph"` and
  `"Phiên bản xe", "param":"option"`), but no value was rendered on **0/20** sampled live ads, and the
  union of the 23 `ad_params` keys contains no displacement or trim key at all. What the pages *do*
  publish: `cartype` (45/60 in the list payload, 13/20 on the detail page) and seller wording (20/20).

Consequence: Chợ Tốt contributes **no** engine or trim information to the model, in v1 or in any future
snapshot built from it, and its 13,631 v1 rows cannot be repaired because the ads no longer exist. The
platform's value in this dataset is volume plus `body_type`/`seller_type`, not the two columns that
carry the price signal (`docs/features_steps.md` step 3). Full probe:
[`docs/recon_chotot_live.md`](recon_chotot_live.md).

### What the bonbanh backfill did and did not add

`docs/data_quality_v2.md` records the exact fill counts. In short: `sub_model_trim` for 6,123 rows was
derived **offline** from the model string (the page title is `brand + model + trim`, so the trim was
already in the row); `engine_capacity`, `seller_type` and `body_type` can only come from the detail
pages, and the crawler was rate-limited by a 200 captcha page — so those columns are **unchanged** in
v2 until the crawl is resumed. The difference between `docs/features_steps.md` and
`docs/features_steps_v2.md` is the trim fill alone: −0.04 pp MAPE on `val_full`.

   before the split. Until then, report the error **with and without** this tail —
   `docs/benchmark.md` now carries both columns (`MAPE` and `MAPE clean`).
2. **Placeholder odometers.** 6 of the 25 carry `mileage_km ≤ 100` or `≥ 900.000`, e.g. `999.998 km` on
   a 2024 car, `1 km` on a 2026 car. `km_per_year` inherits the nonsense, and `mileage_km` is a numeric
   feature, so these rows actively mislead the model rather than merely being wrong.
3. **Impossible or missing model years.** **4 rows** carry `1025`, `2028`, `2030` or `2032`, and **9
   rows have no `manufacture_year` at all** (an earlier note in this file said 13 — that count wrongly
   folded the 9 missing values in with the impossible ones; `tools/audit_master` now prints both numbers
   separately). The year is a first-class feature, so a 1025 car teaches the model nothing useful.
4. **A duplicate pair survives into val.** `TBX_88471` and `TBX_87885` are the same Isuzu MU-X 2018 at
   33.330.000 VND with the identical prediction, but they carry different `listing_id` **and** different
   `duplicate_group_id`, so the grouped split cannot see them as one car and the tail counts the ad twice.

One more pattern in the same tail: `engine_capacity` is missing on **24 of the 25** worst rows, i.e. the
61 %-missing column is absent exactly where the error is largest.
