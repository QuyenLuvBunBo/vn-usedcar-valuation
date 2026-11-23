# Data limitations

Six things a reader must know before quoting a number. Every count comes from the frozen snapshot
(`missing_report.json`, `normalize_report.json`, `split_summary.json`).

## 1. Asking price is not transaction price

The data records **what sellers ask**, captured on one day. No platform exposes the agreed price, so
every prediction is an **advertised-price** prediction. This is the largest irreducible error and the
first line of the report's limitations.

## 2. Two columns are mostly missing, and one platform is a stub

| Column | Missing in train | Consequence |
|---|---:|---|
| `engine_capacity` | 61.2 % | imputation adds noise; importance is understated |
| `sub_model_trim` | 55.7 % | trim is what separates an LX from an EX; half the table cannot use it |
| `seller_type` | 34.1 % | dealership vs private pricing differs |
| `origin` | 28.6 % | import vs domestic is unknown for a third of rows |

Platform volume is uneven: bonbanh and oto.com.vn carry ~60 % of the master, while **carmudi has 546
rows** (366 train) and cannot support a platform-level claim. Full table: `docs/sources.md`.

## 3. Brand spellings had to be normalised

`normalize_report.json` folds **164 raw spellings into 146 brands** (`Hyundai`/`HYUNDAI`,
`Mercedes Benz`/`Mercedes-Benz`, `CX-5`/`CX 5`/`CX5`). Counting before that step overstates the
catalogue and splits one car into two target-encoding levels.

## 4. Four defects found by reading the worst predictions

The hand read is `docs/error_audit_25.md`; the full 25-row table is there.

1. **Deposit-style asking prices.** 23 of the 25 worst rows ask less than a quarter of the model's
   estimate; only **23 val rows (0.15 %)** are that cheap, **69.6 %** from Chợ Tốt. `price_status`
   says `"full"` on all 25, so the flag had to be added upstream (`deposit_suspected`: asking < 25 %
   of the segment median).
2. **Placeholder odometers.** 6 of 25 have `mileage_km ≤ 100` or `≥ 900,000` (e.g. 999,998 km on a
   2024 car). `km_per_year` inherits the nonsense; serving now treats these as missing and imputes the
   age median (`docs/inference.md` §4).
3. **Impossible/missing years.** 4 rows carry 1025/2028/2030/2032 and 9 have no year. The year is a
   first-class feature, so those rows teach the model nothing useful.
4. **A duplicate pair survives into val.** `TBX_88471`/`TBX_87885` are the same 2018 Isuzu MU-X at
   33,330,000 VND with different `listing_id` and `duplicate_group_id`; the grouped split cannot see
   them as one car, so the tail counts the ad twice.

`engine_capacity` is missing on **24 of the 25** worst rows: the 61 %-missing column is absent exactly
where the error is largest.

## 5. Chợ Tốt cannot fill engine or trim

Two live measurements (2026-11-14):

- **Old IDs are gone.** 0/80 sampled v1 ads still exist (68 answer 200 with “Tin đăng không tồn tại”,
  12 answer HTTP 410). A status-code-only crawler would mark those 68 alive.
- **The live pages do not carry `engine_capacity` or `sub_model_trim`.** The labels exist in the page,
  but no value was rendered on 0/20 sampled ads and the `ad_params` union has no displacement/trim key.

Chợ Tốt therefore contributes **no engine or trim** in v1 or any future snapshot; its 13,631 v1 rows
cannot be repaired because the ads no longer exist. Its value is volume + `body_type`/`seller_type`.
Full probe: `docs/sources.md`.

## 6. The Bonbanh backfill helped less than expected

The crawl ran to completion over **7,704 pages**:

| Field | Filled (train / val / test) | Reading |
|---|---:|---|
| `seller_type` | 1,981 / 406 / 424 | salon subdomain, or no link → private |
| `engine_capacity` | 31 / 9 / 8 | `Động cơ` is printed with an empty value on most older ads |
| `body_type` | 3 / 1 / 0 | already observed |
| `sub_model_trim` | 4,351 / 887 / 885 | derived offline from the `model` string |

The “engine 81 %” in the recon counted a label plus a number anywhere on the page, not a fillable
cell. Effect on the score: none measurable — step 3 stays at MAPE 11.25 % / 9.91 %, and held-out
nameplate error is 23.9 % vs 24.1 % for trim-only. `seller_type` is one of five columns in the
`cat_spec` group; replacing 2,811 imputations with observations does not move a tree model that
already has brand, model and year.

## Also worth stating

- **One snapshot only:** every number refers to `scraped_at` in this snapshot; the market moves, the
  model does not.
- **19 rows without a usable price** were dropped, not imputed.
- **Duplicate groups, not duplicate rows:** 75,496 groups for 100,887 listings. The grouped split keeps
  a group on one side, so val/test are not inflated by re-listing the same car.
- **No accident, service or ownership history** exists in the source data. The three structural
  failure modes (bait price, odometer manipulation, import/salvage) cannot be fixed by modelling.
- The headline is an **advertised-price** model; `docs/evaluation.md` and `docs/readiness_v2.md` state
  where it is weakest.
