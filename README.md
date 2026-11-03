# vn-usedcar-valuation

Multi-source web-scraping pipeline and data-science project for used-car price estimation
and listing anomaly detection in Vietnam.

*Introduction to Data Science — Group 14.*
This is a **shared team repository**: nine members collected data from eight marketplaces,
normalized it into one unified schema, and now build regression and anomaly-detection models.

## Status (2026-11-02)

| | |
|---|---|
| Dataset | `data/master/master_clean_dataset.csv` — **100,887 records**, 8 platforms, 21 contract columns |
| Split | train 70,707 / val 15,063 / test 15,098, grouped by `duplicate_group_id` |
| Modelling cohort | 70,244 / 14,964 / 14,980 rows — `data/master/*_cohort_imputed.csv` |
| Gates | `tools.audit_master` → 0 problems, `tools.validate_source_csv` → PASS, 115 unit tests green |
| Data status | [docs/week2_status.md](docs/week2_status.md) |
| Current work | week 3 (features → models → anomaly, 3–10 Nov): [docs/week3_plan.md](docs/week3_plan.md) |
| Coverage per source | [docs/crawl_gap.md](docs/crawl_gap.md) |

Data files are **not** committed (see `CONTRIBUTING.md` §6): run the commands below to rebuild them.

---

## Who does what

| Source | Task | Owner |
|---|---|---|
| oto.com.vn | Asian mainstream brands (Toyota, Hyundai, Kia, Mazda, Honda, Mitsubishi) | Lê Thế Quyền |
| oto.com.vn | Remaining brands (Ford, Mercedes-Benz, BMW, VinFast, Lexus, Audi, …) | Nguyễn Thế Phương |
| bonbanh.com | Recent cars (2019–2026) | Phạm Hải Duy |
| bonbanh.com | Older cars (1995–2018) | Phạm Xuân Hiếu |
| xe.chotot.com | Northern & Central Vietnam | Đinh Gia Bảo |
| xe.chotot.com | Southern Vietnam | Trịnh Hải Phong |
| carmudi.vn | Passenger car catalogue | Nguyễn Văn Quyết |
| carpla.vn | Dealership inventory | Đỗ Tuấn Anh |
| muaban.net | Passenger cars for sale (replacement for anycar.vn) | Nguyễn Huy Quang |
| tinbanxe.vn | Additional marketplace (added to the merge in week 2) | — |
| vucar.vn | Additional marketplace (added to the merge in week 2) | — |

Every member delivers: **one crawler script + one clean CSV** matching the unified schema
(`docs/unified_schema.md`). Merge, deduplication, modelling and the demo happen in weeks 2–4.

**[docs/crawl_gap.md](docs/crawl_gap.md)** records, per source, the site's real catalogue size against
what we collected (measured 2026-10-29) — it is the evidence behind the Milestone 1 coverage numbers.

## Repository layout

```
.
├─ README.md · CONTRIBUTING.md · requirements.txt · .env.example · .gitattributes
├─ docs/
│  ├─ unified_schema.md        # THE DATA CONTRACT: 21 shared columns
│  ├─ crawl_gap.md             # per-source catalogue size vs. what we collected
│  ├─ week2_status.md          # the current dataset: build steps, numbers, open items
│  ├─ week3_plan.md            # features → models → anomaly → report (3–10 Nov)
│  └─ sources/<source>.md      # per-source recon notes and field mapping
├─ src/
│  ├─ common/                  # shared code — changes require a reviewed PR
│  │  ├─ config.py             # paths, .env, request delay/retry settings
│  │  ├─ http_client.py        # session, browser headers, retry/backoff, 429 handling
│  │  ├─ storage.py            # raw HTML / CSV / JSONL / SQLite (idempotent upserts)
│  │  ├─ parsing.py            # Vietnamese price, mileage and year parsing (all sources)
│  │  └─ schema.py             # the 21 columns + normalization maps (data contract)
│  ├─ sources/                 # one package per source; never edit another member's package
│  │  ├─ _template/            # ⭐ copy this folder to start a new source
│  │  ├─ chotot/               # crawl.py (pages) · topup.py (API + index top-up) · chotot_scraper.py
│  │  └─ oto/                  # crawl.py · unified.py · brands_asia.py · brands_other.py
│  ├─ merge/                   # build_master.py · dedupe.py
│  └─ data_prep/               # split.py · normalize.py · missing.py · eda.py · pipeline.py
├─ tests/                      # unit tests: split integrity, dedupe, flags, normalize, EDA
├─ tools/                      # recon, diagnostics, validation gates
├─ notebooks/<member>/         # EDA and experiments — one folder per member
└─ data/  raw/ · processed/ · master/     # data is NOT committed (see CONTRIBUTING.md)
```

## Rebuilding the dataset (week 2 in four commands)

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m src.merge.build_master    # every data/processed/*.csv -> master_clean_dataset.csv
python -m src.data_prep.split       # grouped, price-stratified train/val/test
python -m src.data_prep.pipeline    # normalize -> impute -> EDA (one command, in that order)
```

`pipeline` writes `*_cohort.csv`, `*_cohort_imputed.csv` (the file week 3 trains on),
`normalize_report.json`, `missing_report.json` and `data/master/eda/eda_summary.md` + 6 figures.

## Week 3 — features, models, anomaly

```powershell
python -m src.features.build_features --features full   # {train,val,test}_features_full.csv + feature_stats.json
python -m src.features.build_features --features minimal # raw columns only, for the baseline
python -m src.features.build_features --ablate           # drop one feature group at a time → ΔR² table
python -m tools.model_gate                               # leakage gate: must print PASS
python -m tools.baseline_smoke                            # canary: median vs untuned LightGBM on val
```

`model_gate` fails on a forbidden column (price text, dates, URL, review flags), on a numeric feature
that is a copy of the target, on partitions whose columns drifted, and on a `duplicate_group_id` that
appears in two partitions. `baseline_smoke` writes `data/master/baseline_smoke.json` — it is a canary,
not the benchmark; the benchmark table is the modelling sub-team's `model_results.json`.

`--ablate` answers "which feature group earns its place": it drops one group of `ABLATION_GROUPS` at a
time and reports `ΔR² = baseline − without`, fitting a fixed small LightGBM on `--ablate-rows` (20 k)
train rows and writing `data/master/feature_ablation.json`. It is a **relative** diagnostic for report
§4, not a benchmark number to quote — the parameters are fixed on purpose so the comparison is fair.



## Quick start

```bash
git clone https://github.com/QuyenLuvBunBo/vn-usedcar-valuation.git
cd vn-usedcar-valuation

python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env         # fill in cookie/proxy only if a source requires it

# Windows only: make Vietnamese output printable in the console
set PYTHONIOENCODING=utf-8            # cmd
$env:PYTHONIOENCODING='utf-8'         # PowerShell
```

## Adding your source (bonbanh, chotot, carmudi, carpla, muaban…)

1. Read `src/sources/_template/README.md` — 4 steps: recon → parse → normalize → validate.
2. `git checkout -b feat/source-<source>` and copy `src/sources/_template/` to
   `src/sources/<source>/`, then edit `crawl.py` and `unified.py`.
3. Document your recon in `docs/sources/<source>.md` (robots.txt, pagination rule, selectors,
   fields the site does **not** expose).
4. Run the PR gate before opening a pull request:

```bash
python -m tools.validate_source_csv data/processed/<source>.csv
python -m tools.smoke_test
```

Workflow rules (branches, commit messages, file ownership): see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Topping up a source that is short of its catalogue

`bonbanh` and `carpla` have a crawler in this repository, so their gap can be closed without waiting for
the owner. Both write `data/processed/<source>_extra.csv` with only the ids we do not have yet.

```bash
python -m src.sources.bonbanh --pages 3     # bonbanh: 20 ads/request; full catalogue ≈ 1,462 pages
python -m src.sources.bonbanh
python -m src.sources.bonbanh --details     # + body_type / seller_type / listing_date (1 request/ad, ~8.5 h)
python tools/bonbanh_progress.py            # progress + ETA of the detail step
python -m src.sources.carpla --limit 5      # carpla: one request per car, driven by sitemap_product.xml
python -m src.sources.carpla
```

Numbers, evidence and what is still missing: **[docs/crawl_gap.md](docs/crawl_gap.md)**.

## Reference implementation: oto.com.vn

The `oto` source is complete and serves as the worked example for everyone else.

```bash
python -m src.sources.oto                          # crawl listings, all brands
python -m src.sources.oto --group asia             # six Asian mainstream brands (Quyền)
python -m src.sources.oto --group other            # remaining brands (Phương)
python -m src.sources.oto --pages 3                # limit to 3 pages per brand (quick test)
python -m src.sources.oto --exclude-sold           # skip sold listings
python -m src.sources.oto --detail-only            # also crawl each listing detail page
python -m src.sources.oto --detail-missing-price   # back-fill detail pages for price-less ads
python -m src.sources.oto --from-raw               # parser changed: re-parse saved HTML, no re-crawl
python -m src.sources.oto.unified                  # export the 21-column unified CSV + audit
python -m src.sources.oto.archive --limit 50       # archive tier: sitemap URLs no longer listed
python -m src.sources.oto.archive --summary        # what the archive tier holds so far
python -m src.sources.oto.unified --include-archive  # + oto_archive_unified.csv (separate file)
python -m src.sources.oto.unified --out oto --include-archive --combine  # oto.csv = both tiers, 28,428 rows
```

Outputs: `data/processed/oto_cars.csv` (parsed listing fields), `data/processed/oto_unified.csv`
(21 unified columns, live tier, 5,237 rows), `data/processed/oto_archive_unified.csv` (archive tier
only, 24,326 rows), `data/processed/oto.csv` (both tiers concatenated, 29,563 rows — a single-file
hand-off for exploration; the week-2 merge reads the two per-tier files above, because `tier` is
assigned per file), tables `oto_cars` + `oto_car_details` + `oto_archive` in `data/scraped.db`.

## Merging into the Master Dataset (week 2)

```bash
python -m src.merge.build_master                     # every source file that exists yet
python -m src.merge.build_master --sources oto oto_archive   # subset -> master_partial_oto_oto_archive.csv
```

It reads every `data/processed/<source>.csv` that exists (a missing source is skipped with a warning),
refuses a file whose header does not match the 21-column contract, then adds three columns:

| Column | Meaning |
|---|---|
| `tier` | `listed` (advertised when captured) / `archived` (page still served, no longer advertised) |
| `duplicate_group_id` | candidate same-vehicle key: brand + model + trim + year + province + ± mileage |
| `quality_flags` | report §4.3 review reasons (`missing_mileage`, `low_mileage_older_car`, …) |

`SOURCE_FILES` maps an internal key to **one file per key**, so a source that two members crawled gets two
keys sharing one platform (`bonbanh_new` + `bonbanh_old` → `bonbanh`, `chotot_nam` → `chotot`). The
platform written to `source_platform` is always the contract enum, never the internal key
(`canonical_platform()`), so `tinbanxe.csv` (which writes `tinbanxe`) still lands as `tinbanxe.vn`.

Nothing is deleted or merged away: a group is a review candidate, so the flags and the group id travel
with every record to the modelling stage. The run also prints the Milestone 1 numbers — records per
source, missing rate per source, duplicate rate, flag counts — and writes
`data/master/master_clean_dataset.csv` (21 columns + the three above).

## Shared documentation

| Document | Contents |
|---|---|
| [docs/unified_schema.md](docs/unified_schema.md) | the 21 columns, allowed values, normalization rules |
| [docs/crawl_gap.md](docs/crawl_gap.md) | per-source catalogue size vs. collected, and how to reach the rest |
| [CONTRIBUTING.md](CONTRIBUTING.md) | branches, commits, file ownership, PR checklist |
| [docs/sources/oto.md](docs/sources/oto.md) | oto.com.vn recon, field mapping, coverage audit, verified source size |
| [src/sources/_template/README.md](src/sources/_template/README.md) | step-by-step guide for a new source |

## Tools

| Tool | Purpose |
|---|---|
| `tools.validate_source_csv` | **PR gate**: does a source CSV match the 21-column schema? |
| `tools.audit_master` | **gate before the split**: types, enums and keys of the merged dataset |
| `tools.repair_price_status` | recompute the derived `price_status` column of a contract CSV |
| `tools.model_gate` | **gate before training**: forbidden columns, target copies, partition drift, group leakage |
| `tools.baseline_smoke` | canary: does training run here, and what must a model beat (median vs untuned LightGBM) |
| `tools.smoke_test` | offline regression tests for the parsers |
| `tools.validate_parser` | parser vs. previously saved raw HTML (offline) |
| `tools.recon <url>` | robots.txt, page fetch, hidden API/JSON discovery |
| `tools.paging <url>` · `tools.check_pages <url>` | find and verify the pagination rule |
| `tools.field_stats [n]` | field coverage and price formats over a multi-page sample |
| `tools.detail_recon <url>` | inspect a detail page (JSON-LD, spec table, seller block) |
| `tools.list_brands` | discover and verify oto.com.vn brand slugs |
| `tools.summarize_oto` | pandas summary + quality checks of a crawled CSV |
| `tools.archive_progress` | live progress + ETA of the archive crawl (log bar + DB counts) |
| `tools.bonbanh_progress` | live progress, coverage and ETA of the bonbanh detail crawl |
| `tools.compare_tiers` | live tier vs archive tier: size, price, age, mileage, sellers, quality flags |
| `tools.scan_sitemap` · `tools.lastmod_analysis` | verify source size and listing dates |

## General technical notes

- Every request goes through `ScraperSession`: browser headers, 1.5 s delay (+ jitter),
  retry/backoff and `Retry-After` handling. Respect each site's `robots.txt`, terms and rate limits.
- Rows are written with `INSERT … ON CONFLICT(url) DO UPDATE`, so re-running **refreshes** data
  instead of duplicating it.
- Use `--save-raw` on the first crawl: after a parser fix you can re-parse saved HTML offline
  instead of re-crawling thousands of pages.
- When parsing saved HTML with lxml, pass a **decoded string** (passing bytes lets lxml guess the
  charset and can produce mojibake for Vietnamese text).
- On Windows always set `PYTHONIOENCODING=utf-8` before running any tool.

## Roadmap

| Week | Focus | Deliverable | Status |
|---|---|---|---|
| 1 | Collect and normalize from the sources | one crawler script + one clean CSV per member | done; coverage per source in [docs/crawl_gap.md](docs/crawl_gap.md) |
| 2 | Merge, deduplicate, quality audit, EDA | `data/master/master_clean_dataset.csv` (100,887 records, 8 platforms), train/val/test split, EDA notebook | **done** — see [docs/week2_status.md](docs/week2_status.md) |
| 3 | Feature engineering, regression, anomaly detection | model files, benchmark table, anomaly labelling | **in progress 3–10 Nov** — assignments, hand-offs and the cut list in [docs/week3_plan.md](docs/week3_plan.md) |
| 4 | Packaging the pipeline, report and slides | `predict()` wrapper, report PDF, slides (the web demo only if time allows) | — |

