# Chotot Xe — Southern Vietnam

This crawler follows the schema and shared utilities in the team repository. Northern and Central Vietnam are outside its scope.

## Reconnaissance and limitations

- Host: `https://xe.chotot.com`.
- Seed pages: `/mua-ban-oto-<province>`; detail pages:
  `/mua-ban-oto-<location>/<id>.htm`.
- The 19 marketplace location labels in `src/sources/chotot/geography.py` are
  legacy labels, not a list of current administrative divisions.
- The saved robots snapshot disallows `/*page=`. The crawler reloads robots
  on every run, checks each URL before fetching, and only follows pagination
  links on the same path (page numbers or `rel=next`). It does not generate
  listing IDs or page URLs.
- Collection from 18 to 28 October 2026 (Vietnam time) produced **1,889 unique
  listings: 1,584 clean and 305 for review**. Exact UTC capture timestamps are
  recorded in the audit. The requests-based crawler has collected real data;
  this does not establish complete market coverage.
- All requests use the team's `ScraperSession`, with a minimum delay of
  1.5 seconds, increased when required by robots. Retries, backoff and HTTP 429
  handling use the shared implementation. Access denials or verification
  screens stop the crawl and export the data collected so far. Index pages
  without listing links are marked `unparsed` for inspection without stopping
  the entire queue.
- `src/sources/chotot/urls_mo_rong.txt` contains 286 district and brand listing
  links extracted from actual HTML of the 19 provincial index pages. URLs are
  not constructed or guessed. The crawler checks fresh robots rules before
  accessing them; inclusion in the file does not guarantee current availability.

## Source-to-schema mapping

| Field | Selector / transformation |
|---|---|
| listing_id, source_platform | `CHOTOT_<numeric ID from URL>`, `chotot` |
| brand, model, sub_model_trim | `//*[@itemprop="carbrand"]`, `carmodel`, `option` |
| manufacture_year | `mfdate` → shared `parse_year_text` |
| mileage_km | `mileage_v2` → adapter for `vạn` (10,000) / `nghìn` (1,000) → shared `parse_km_text` |
| transmission | `gearbox`; alias `Tự động` → `Số tự động`; shared `normalize_transmission` |
| fuel_type | `fuel`; alias `Động cơ hybrid` → `hybrid`; shared `normalize_fuel` |
| origin | `carorigin`; `Việt Nam` → `Trong nước`, country of origin → `Nhập khẩu`; shared `normalize_origin` |
| body_type | `cartype` → canonical label aliases → shared `normalize_body` |
| seats | `carseats` → shared `to_int` after integer validation |
| location_province | `//a[@href]` with text starting with `Ô tô ` and a recognized province slug → `normalize_province` |
| seller_type | `//*[@itemprop="seller"]//a[contains(@href,"/cua-hang/")]` → `Dealership/Salon`; otherwise `Unknown` |
| price_vnd | `//b` containing a complete price expression → shared `parse_vnd_price`, or `to_int` for numeric VND amounts |
| raw_price_text | Retain the price expression extracted from HTML; do not replace it with a normalized expression |
| price_status | Shared `schema.price_status` plus source-specific checks for down-payment evidence |
| source_url, scraped_at | Canonical HTTPS URL; capture timestamp converted to UTC ISO 8601 |
| engine_capacity, listing_date | Not directly observed; left empty |

Unknown categorical values use `Unknown`; missing numeric values are not
replaced with zero. The oto salon-subdomain helper is not used: the absence
of a Chotot store link does not prove the seller is a private individual.
Semi-automatic transmission maps to `Other`, as required by the schema.
The combined label `SUV / Cross over` maps to `Other` with the
`ambiguous_suv_crossover` flag rather than guessing between SUV and Crossover.
The enum sets in **schema code** take precedence when documentation lists
fewer values; for example, the code permits Coupe and Convertible.

The source price adapter validates the complete expression before calling
shared helpers to avoid interpreting phone numbers or years as prices.
For numeric VND prices such as `465.000.000 đ`, grouping separators are
removed before `to_int`; billion/million expressions have their unit aliases
adapted before `parse_vnd_price`. Down-payment checks only use the seller's
title and description, not the platform's automatic loan widget. A financing
offer alone does not mean the advertised amount is a down payment.

## Storage, offline parsing and cohorts

Shared `storage.open_db` uses `data/scraped.db` by default. The
`chotot_south_raw` table is keyed by URL and updated with `storage.upsert_rows`.
Raw JSON retains the original `scraped_at`; the table-level `scraped_at` is
the upsert timestamp assigned by the shared implementation. The separate
`chotot_south_queue` table does not affect other sources' tables. By default,
completed URLs are refreshed; `--resume` processes pending URLs only. Legacy
DB records are imported once per URL into the new table without overwriting
records that have already been updated.

The queue prioritizes discovered detail pages before exploring more index
pages. An index page without detail links receives `status=unparsed`, the
`empty_index_or_requires_js` error and an `index_unparsed` log event. This
does not prove that the page has no listings: it may be empty, require
JavaScript, or use changed selectors. `--resume` does not retry unparsed URLs.
Their count appears in the audit's `context.queue_status`; inspect the saved
HTML separately before attempting to process them again.

`storage.save_raw` stores HTML under `data/raw`; accompanying JSON metadata
retains the URL and capture timestamp. Network parsing and `--from-raw` use
the same `parse_detail_page` function with decoded UTF-8 strings and lxml.
Offline parsing does not execute JavaScript or make network requests.

The clean cohort retains listings confirmed as used vehicles, located in
Southern Vietnam, with a known brand/model, manufacture year from 1995 to
the capture year, a full asking price of VND 30 million–25 billion, and
mileage no greater than 1 million km. Vehicles older than two years with
less than 100 km are sent to review. Seating values outside 2–16 are also
sent to review when present. These are source-level filtering decisions,
separate from the schema gate, and may change by team agreement. Raw data
retains these listings; `review_21.csv` and `quality.csv` record the reasons.

The main CSV is `data/processed/chotot_mien_nam.csv`. Supporting files are
kept separately under `data/processed/chotot_mien_nam/`: `all_21.csv`,
`clean_21.csv` (compatibility copy), `review_21.csv`, `quality.csv` and
`audit.json`. The audit reports missing rates (counting `Unknown` as missing),
duplicate rate, province distribution, price statuses and exclusion reasons.
The latest export contains 1,889 unique listings, 1,584 clean and 305 for
review. This exceeds the local target of 1,500 clean records but does not
establish market representativeness. Engine capacity and original publication
date have not been recovered; `sub_model_trim` is also entirely missing in
this collection. See `missing_rates` for complete per-column coverage.

## Pre-PR gate

```powershell
python -m tools.validate_source_csv data/processed/chotot_mien_nam.csv
python -m tools.smoke_test
python -m unittest discover -s src/sources/chotot/tests -v
```

The validator and smoke test are existing team repository tools. The official
smoke test checks the oto parsers; the separate unittest command checks Chotot.

## Running and handover

See `src/sources/chotot/README.md` for crawling, offline export and testing.
Team defaults exclude CSV files through gitignore. For this handover, the
source owner has chosen to commit only the clean CSV using `git add -f`;
raw data, databases and logs are excluded. Audit, review and quality files
are updated locally for inspection and separate handover when needed.
