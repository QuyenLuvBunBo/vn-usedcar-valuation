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
