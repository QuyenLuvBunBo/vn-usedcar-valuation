# Sources and coverage

Eight marketplaces feed the snapshot. Data is collected through each site's public pages/API,
normalised to the 21-column contract in `docs/unified_schema.md`, and merged into
`data/master/master_clean_dataset.csv` (**100,887 rows**). Each source has one package in
`src/sources/`; never edit another member's package.

| Source | Master rows | Share | Route / status |
|---|---:|---:|---|
| bonbanh.com | 30,371 | 30.1 % | server-rendered `/oto/page,N`, whole catalogue |
| oto.com.vn | 29,563 | 29.3 % | reference implementation; live + archive tiers |
| chotot | 19,426 | 19.3 % | JSON gateway + website top-up |
| tinbanxe.vn | 7,654 | 7.6 % | marketplace listings |
| muaban.net | 7,022 | 7.0 % | marketplace listings |
| carpla.vn | 4,181 | 4.1 % | `sitemap_product.xml` |
| vucar.vn | 2,124 | 2.1 % | marketplace listings |
| carmudi.vn | 546 | 0.5 % | model-page crawl; small platform |

## Coverage against each site's own catalogue

Measured on 2026-10-29 with the repository user agent (the four sources with a published catalogue
size):

| Source | Site catalogue | Collected | Missing | Note |
|---|---:|---:|---:|---|
| xe.chotot.com | 29,693 | 19,426 | +10,267 | the site counter includes expired ads; the live API universe is 18,413 |
| bonbanh.com | 29,241 | 30,371 | 0 | people kept posting while pages were walked |
| carpla.vn | 4,181 | 4,181 | 0 | complete sitemap |
| carmudi.vn | 779 | 546 | +233 | a template default (`Coupe`) blocked the remaining cards |
| **four-source total** | **63,894** | **54,524** | **+10,500** | other sources were already merged |

## Split counts

| Split | Rows | bonbanh | oto.com.vn | chotot | tinbanxe | muaban | carpla | vucar | carmudi |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 70,707 | 21,223 | 20,764 | 13,631 | 5,355 | 4,921 | 2,932 | 1,515 | 366 |
| val | 15,063 | 4,547 | 4,374 | 2,907 | 1,131 | 1,055 | 635 | 309 | 105 |
| test | 15,098 | 4,601 | 4,425 | 2,885 | 1,165 | 1,033 | 614 | 300 | 75 |

## Per-source notes

- **oto.com.vn** — the complete reference crawler (`python -m src.sources.oto`), with live and archive
  tiers: 5,237 live + 24,326 archive = 29,563. All 21 columns are populated; trim is parsed from the
  title (89.1 %) and displacement is inferred from the badge (76.9 %) because the site has no
  displacement field. Robots.txt allows the crawl; detail pages are needed for seats.
- **bonbanh.com** — all 30,371 ads over 1,462 pages; robots.txt has no `Disallow`. The detail backfill
  (7,704 pages) recovered `seller_type` well, `engine_capacity` poorly (the `Động cơ` label is usually
  empty on older ads), and trim offline from the title. See `docs/evaluation.md` §5.
- **chotot** — the page crawler is historical; the scalable route is
  `src/sources/chotot/chotot_scraper.py` + `topup.py` against the JSON gateway. The platform publishes
  **no engine or trim values**; the v1 IDs are gone (0/80 sampled still live), so those cells cannot be
  repaired. Its value is volume + `body_type` / `seller_type`.
- **carmudi.vn** — only 366 train rows; `Kiểu dáng` defaulted to `Coupe` on most cards, so the source
  now writes `Unknown` and the cohort repair folds the old value. Too small for platform-level claims.
- **carpla.vn** — one request per car from `sitemap_product.xml`, complete (4,181/4,181).
- **muaban.net / tinbanxe.vn / vucar.vn** — marketplace feeds; they contribute volume and the usual
  contract fields, with the same missing-value profile as the rest of the table.

## Rules used by every crawler

- Read `robots.txt` first and respect its rules; do not crawl filtered URLs a site disallows.
- One shared `ScraperSession`: browser headers, 1.5 s delay + jitter, retry/backoff and `Retry-After`.
- Write raw HTML/JSON on the first pass so a parser fix can re-parse offline (`--from-raw`).
- Rows are idempotent (`INSERT … ON CONFLICT(url) DO UPDATE`); a re-run refreshes, not duplicates.
- Chợ Tốt's `Content-Signal` says `ai-train=no`: this project trains on the normalised price/spec
  table, not on the raw ad text, and the report should state that.

The source packages are the runnable record; the per-source Markdown recon notes were folded into this
page so the docs stay readable.
