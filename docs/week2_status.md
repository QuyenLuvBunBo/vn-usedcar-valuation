# Week 2 status — what is done, what is left, and who owns it

The week-2 plan (`logs/docx_kehoach.txt`) splits the work into three sub-teams. This page is the
checklist: every row names the deliverable, the code that produces it, the command that reproduces
it, and the state it is in today (**2026-10-30**). Regenerate any number with the command in the row —
nothing here is hand-copied.

## Where the data stands

| Step | Command | Result |
|---|---|---|
| **Everything, in order** | `python -m src.data_prep.pipeline` | normalize → impute → EDA; prints each stage's command and lists the artefacts |
| Master dataset | `python -m src.merge.build_master` | **100,887 records**, 8 platforms (chotot **19,426** after the 5,884-row top-up), 21 contract columns + `tier`, `duplicate_group_id`, `quality_flags`; `tools.audit_master` → PROBLEMS 0 |
| Split, grouped and stratified | `python -m src.data_prep.split` | train **70,707** / val **15,063** / test **15,098**, 75,496 groups, no group crosses a partition |
| Brand/model normalization, repairs, cohort | `python -m src.data_prep.normalize --split all --write` | 164 → 146 brand spellings, 7,376 cells rewritten, 355 carmudi `Coupe` → `Unknown`, 531 engine + 1 seat value blanked, cohort **70,244 / 14,964 / 14,980** kept (99.3 %), exclusions counted per reason |
| Missing-value audit, imputation, cardinality | `python -m src.data_prep.missing --input-suffix _cohort --fill --collapse-rare 10` | every fillable column 0 % missing; 3,212 models → 717 `model_group` values (6,016 train rows → `Other`); every filled cell carries an `imputed` flag |
| EDA tables, descriptive statistics, figures | `python -m src.data_prep.eda` | `data/master/eda/eda_summary.md` + `.json` + 6 PNG |

Order matters: `normalize` writes `*_cohort.csv`, then `missing --input-suffix _cohort` reads that file
and writes `*_cohort_imputed.csv` — the file week 3 trains on (cohort + imputed values + `model_group`).
The repair has to happen before the imputation is *fitted*, or the mode learned for carmudi would be
the template default itself.

## Sub-team 1 — Data integration and deduplication (Quyền, Quyết, Phương)

| Deliverable | Code | State |
|---|---|---|
| Merge the source CSVs into one master | `src/merge/build_master.py` | done |
| Type and key audit of the merged file | `tools/audit_master.py` | done |
| Composite-hash + fuzzy dedupe, `duplicate_group_id` | `src/merge/dedupe.py` | done |
| Domain rules → `quality_flags` | `build_master.quality_flags` | done |
| Grouped, price-stratified train/val/test split | `src/data_prep/split.py` | done |
| **One brand/model spelling per entity** | `src/data_prep/normalize.py` | **done 30/10** — `Mercedes Benz`/`Mercedes-Benz`, `KIA`/`Kia`, `CX-5`/`CX 5`/`CX5`, bold/emoji cells |
| **Outlier filter with a reason per record (the regression cohort)** | `src/data_prep/normalize.py` | **done 30/10** — 469 train rows excluded, each attributed to one §4.3 rule |
| **A template default is not a label (carmudi `Coupe`)** | `normalize.repair_body_type` | **done 30/10** — 393 of carmudi's 406 train records said `Coupe` (528 of 546 on the platform, e.g. a 2010 Yaris); the value becomes `Unknown` and the imputation fills `body_type` from the brand+model mode (`Xpander` → MPV, `C 43` → Sedan) |
| **Implausible numbers blanked, never dropped** | `normalize.repair_implausible_numbers` | **done 30/10** — 488 engine cells (`2021` = a model year in the displacement column, 476 zeros on cars that are not electric) and 3 seat counts (`760`) → empty, then imputed; the descriptive table's `max` went from 2,021 to 8.0 L and from 760 to 47 seats |

## Sub-team 2 — Missing data and cardinality (Hiếu, Bảo, Duy)

| Deliverable | Code | State |
|---|---|---|
| Missing-rate measurement | `missing.measure_missing` | done (now also per platform) |
| Cardinality audit, rare categories → `Other` | `missing.cardinality`, `rare_values`, `apply_rare`, `group_rare_models` | **done 30/10** — `model_group` marks the models seen <10 times in train as `Other` (3,514 models → 717 groups); fit on train, applied elsewhere, and the raw `model` is kept for target encoding |
| Mode within brand/model, then brand, then global | `missing.fit_categorical` / `fill_categorical` | **done 30/10** |
| Median by vehicle-age band for `mileage_km` | `missing.fit_median_by_age` / `fill_median_by_age` | **done 30/10** — an odometer is age-driven, so the band is the right level here (and the wrong one for the engine, see below) |
| `seats` from a make/model mapping | `missing.fill_seats_from_mapping` | **done 30/10**; a group thinner than `--min-group` stays empty on purpose (§4.4) |
| Engine displacement, in three steps | `missing.fill_engine_from_trim` → `fit_median_by_group` → `fit_median_by_age` | **done 30/10** — parse the trim badge first (38,335 train cells), then the brand+model median (a Vios → 1.5, a Camry → 2.5), and only then the age band; the plan's age-band-only rule would have written 2.0 into 46,000 rows |
| Imputation indicator | `imputed` column | **done 30/10** — one `;`-joined list per row |

## Sub-team 3 — Exploratory data analysis (Phong, Tuấn Anh, Quang)

| Deliverable | Code | State |
|---|---|---|
| Descriptive statistics table | `eda.summary_stats` | **done 30/10** — count / missing rate / mean / std / min / p25 / median / p75 / max per numeric column |
| Price distribution, by platform | `eda.price_overview` | **done 30/10** — p90/p10 per platform (4–11×) justifies a log target |
| Price vs model year | `eda.by_year` | **done 30/10** |
| Price vs odometer | `eda.by_mileage` | **done 30/10** — deciles, not fixed bins |
| Depreciation by brand | `eda.depreciation_by_brand` | **done 30/10** — value lost to age 5, with the cross-sectional caveat |
| Price gap between platforms | `eda.platform_gap` | **done 30/10** — matched on brand+model+year, leave-one-out |
| 6 figures + a paste-ready table set | `eda.figures`, `eda_summary.md` | **done 30/10** |
| EDA notebook | `notebooks/eda/week2_eda.ipynb` | **done 30/10** — calls the module (so it cannot drift from the data), contains the descriptive-statistics table and displays all six figures |

## Closed during week 2, and what is still open

| Item | Owner | Note |
|---|---|---|
| Top-up crawl of xe.chotot.com | Bảo, Phong | **done 30/10 — source saturated, data merged** — `chotot_extra.csv` = **5,884 rows** (21 columns, `validate_source_csv` PASS, 0 ids shared with either member file). Two enumeration passes: `chotot_scraper.py ids` (price slices, 13,469 ids) then `topup --seed-api` (price × year, 270 cells, +12,896 ids, because paging a live list had duplicated 4,944 ads). `--filter-ids` → 5,905 genuinely new → 5,652 details at 2.7/s, all HTTP 200. Wired into `build_master`: master 95,003 → **100,887**, chotot 13,542 → **19,426**. The API's own live universe (18,413 price-listed ads) is now fully covered; the site's 29,693 counter includes expired listings. Evidence + the `ad_id` trap in `docs/crawl_gap.md` |
| Stop emitting `Coupe` at the *source* | Quyết | **done 30/10** — `src/sources/carmudi/unified.py` now writes `Unknown` for the `Kiểu dáng` template default (`body_type_of`, smoke test 29/29); `normalize.repair_body_type` stays as the repair for files collected before the change |
| Update the README roadmap row for week 2 | whole team | `README.md` needs a reviewed PR (see `CONTRIBUTING.md` §3) |

## Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m src.data_prep.pipeline               # normalize -> impute -> EDA, in that order
python -m unittest discover -s tests -v        # 115 tests, including the leakage and template-default cases
python -m tools.smoke_test                     # parser regression suite
python -m tools.audit_master                   # type/enum/key gate of the merged dataset
```

Every statistic in this page is fitted on **train only** and then applied unchanged to val/test:
imputation modes and medians, brand/model canonicals, rare-value sets, cohort cutoffs. The split
itself (`train.csv`, `val.csv`, `test.csv`) is never overwritten — the derived files sit beside it
(`*_imputed.csv`, `*_cohort.csv`).

## Next

Week 3 (features, valuation models, anomaly screening) is assigned per person in
[week3_plan.md](week3_plan.md); the input is `data/master/train_cohort_imputed.csv`
(70,244 rows).
