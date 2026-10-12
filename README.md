# vn-usedcar-valuation

Multi-source web-scraping pipeline and data-science project for used-car price estimation
and listing anomaly detection in Vietnam.

*Introduction to Data Science — Group 14.*
This is a **shared team repository**: nine members collect data from six marketplaces,
normalize it into one unified schema, then build regression and anomaly-detection models.

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
| anycar.vn | Inspected inventory | Nguyễn Huy Quang |

Every member delivers: **one crawler script + one clean CSV** matching the unified schema
(`docs/unified_schema.md`). Merge, deduplication, modelling and the demo happen in weeks 2–4.

## Repository layout

```
.
├─ README.md · CONTRIBUTING.md · requirements.txt · .env.example · .gitattributes
├─ docs/
│  ├─ unified_schema.md        # THE DATA CONTRACT: 21 shared columns
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
│  │  └─ oto/                  # crawl.py · unified.py · brands_asia.py · brands_other.py
│  ├─ merge/                   # week 2: build_master.py · dedupe.py
│  └─ data_prep/               # week 2: missing.py (missing-value audit and imputation)
├─ tools/                      # recon, diagnostics and validation helpers
├─ notebooks/<member>/         # week 2 EDA — one folder per member
└─ data/  raw/ · processed/ · master/     # data is NOT committed (see CONTRIBUTING.md)
```

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

## Adding your source (bonbanh, chotot, carmudi, carpla, anycar…)

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
```

Outputs: `data/processed/oto_cars.csv` (parsed listing fields), `data/processed/oto_unified.csv`
(21 unified columns), tables `oto_cars` + `oto_car_details` in `data/scraped.db`.

## Shared documentation

| Document | Contents |
|---|---|
| [docs/unified_schema.md](docs/unified_schema.md) | the 21 columns, allowed values, normalization rules |
| [CONTRIBUTING.md](CONTRIBUTING.md) | branches, commits, file ownership, PR checklist |
| [docs/sources/oto.md](docs/sources/oto.md) | oto.com.vn recon, field mapping, coverage audit, verified source size |
| [src/sources/_template/README.md](src/sources/_template/README.md) | step-by-step guide for a new source |

## Tools

| Tool | Purpose |
|---|---|
| `tools.validate_source_csv` | **PR gate**: does a source CSV match the 21-column schema? |
| `tools.smoke_test` | offline regression tests for the parsers |
| `tools.validate_parser` | parser vs. previously saved raw HTML (offline) |
| `tools.recon <url>` | robots.txt, page fetch, hidden API/JSON discovery |
| `tools.paging <url>` · `tools.check_pages <url>` | find and verify the pagination rule |
| `tools.field_stats [n]` | field coverage and price formats over a multi-page sample |
| `tools.detail_recon <url>` | inspect a detail page (JSON-LD, spec table, seller block) |
| `tools.list_brands` | discover and verify oto.com.vn brand slugs |
| `tools.summarize_oto` | pandas summary + quality checks of a crawled CSV |
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

| Week | Focus | Deliverable |
|---|---|---|
| 1 | Collect and normalize from 6 sources | one crawler script + one clean CSV per member |
| 2 | Merge, deduplicate, quality audit, EDA | `data/master/master_clean_dataset.csv`, train/val/test split, EDA notebook |
| 3 | Feature engineering, regression, anomaly detection | model files, benchmark table, anomaly labelling |
| 4 | Pipeline packaging, web demo, report and slides | Streamlit demo, final report, slides |

