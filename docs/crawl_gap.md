# Collection gap — what is still available at each source

Measured on **2026-10-29** with `ScraperSession` (1.5 s delay, robots.txt checked first). Every number
below is a figure the site itself prints or a URL count taken from its own sitemap, so it is reproducible
— re-run the probe before planning a top-up crawl, catalogues move daily.

This answers one question for the Milestone 1 report: **how far is each member's file from the site's
real catalogue?**

## Summary

| Source | Site catalogue | We have | Missing | Reachable how |
|---|---|---|---|---|
| xe.chotot.com | **29,693** cars | 13,542 | +16,151 | region pages + `sitemap-oto-model-*.xml` (79,040 URLs) |
| bonbanh.com | **29,241** ads | 30,371 | 0 | `/oto/page,N` — 20 ads/page, **1,462 pages** |
| carpla.vn | **4,181** | 4,181 | 0 | `sitemap_product.xml` (plain `<loc>` list) |
| carmudi.vn | **779** | 546 | +233 | `sitemap/model/sitemap-index-models.xml` + per-model pages |
| **Total** | **63,894** | 48,640 | **+16,384** | |

Two of the four gaps are now closed: bonbanh was topped up to its full catalogue and carpla was crawled
to the end of its sitemap. What is left is chotot (the national catalogue is bigger than any one region
export) and carmudi (233 ads).

## Per source

### xe.chotot.com — the regional gap is closed, the volume gap is not

Two exports now exist, and the second one covers the whole country:

| File | Rows | Provinces | Region |
|---|---|---|---|
| `chotot_mien_nam.csv` (Phong) | 1,584 | 19 | southern half only |
| `chotot_mua_ban_oto.csv` (Bảo) | 12,986 | **63** | nationwide |

They overlap on 1,028 ids, which `build_master` now drops by `listing_id`, so the platform contributes
**13,542** unique ads: Hà Nội 2,240 · Đà Nẵng 589 · Hải Phòng 142 · Thanh Hóa 90 · Nghệ An 83 — the
northern and central half is no longer missing, so region-level analysis is no longer biased.

What remains is volume: the site prints **29,693** cars nationally, so ~16,151 are still uncollected.

- Enumeration: `https://xe.chotot.com/sitemap-index.xml` → 9 sitemaps → `sitemap-xe-oto.xml` →
  `sitemap-oto-model-1.xml` (**50,000** URLs) + `sitemap-oto-model-2.xml` (**29,040** URLs)

**robots.txt is safe for us.** `Disallow: /` appears only under `User-agent: ImagesiftBot`; the wildcard
block is `Allow: /` plus a `Sitemap:` line. Two rules still constrain the crawler:

- `Disallow: /*carbrand=` / `/*carmodel=` / `/*carorigin=` — **do not** crawl filtered URLs, so the
  "partition by brand" trick used for muaban.net is not available here. Walk the pagination/sitemap
  instead, or fetch unfiltered region pages.
- `Content-Signal: search=yes, ai-input=yes, ai-train=no` — fine for this project (no model is trained on
  the raw ads), but it must be mentioned in the report.

**Data-quality notes for `chotot_mua_ban_oto.csv`:** `raw_price_text` is empty and `price_status` was
written as `Unknown` for 12,983 rows. `price_status` is a derived column, so `build_master` recomputes it
from `price_vnd` (`full` when a price exists, `invalid` when it does not) — but the exporter should emit
it directly, otherwise the file keeps failing `tools.validate_source_csv`.

### bonbanh.com — closed

- `/oto` prints `Tổng: 29,241`; `rel="next"` points to `/oto/page,2`.
- Verified: page 1 and page 2 each return **20** distinct listing links with **0** overlap → the
  pagination works to the end, 29,241 / 20 ≈ **1,462 pages**.
- Collected: 12,374 (the owners' two files) + **17,997** from the top-up crawl = 30,371 rows. The crawl
  ran past the printed total because new ads are posted while the pages are being walked.
- `body_type`, `seller_type` and `listing_date` come from a **second pass** over the detail pages (one
  request per new ad, resumable via `--details`), because the listing card does not print them.
- robots.txt is 7 lines with **no** `Disallow` at all.

### carpla.vn — closed

- `https://carpla.vn/sitemap_index.xml` → 9 sitemaps; `sitemap_product.xml` lists **4,181** vehicle pages
  in a plain `<loc>` list (`https://carpla.vn/xe/ford-everest-2018-f8xwi`).
- Collected: 1,322 + **2,859** = 4,181 rows, i.e. the whole sitemap.
- The HTML catalogue `/mua-xe` is a 1.4 MB JS-rendered page: no listing links and no `?page=` handling in
  the markup, so **do not** try to page through it — use the sitemap plus detail pages.
- robots.txt blocks only `*?brand=*` style filters.

### carmudi.vn — smallest gap, and the site is nearly dead

- Home page prints **779 tin**; our 546 is ~70% of the live catalogue.
- `https://www.carmudi.vn/sitemap.xml` → `sitemap/model/sitemap-index-models.xml` (model index) and
  `sitemap/sitemap1.xml` (static pages only — the listings are *not* there).
- The catalogue is reached per model: `/xe-o-to-<brand>-<model>` returns 15 listings.
- Note for the report: carmudi's own listing pages default `body_type` to `Coupe` (528/546 rows) and
  `transmission` to `Manual`, so a bigger crawl would not fix that column — it is a template default.

## What this means for the deliverables

1. **Nothing blocks the week-2 deliverables.** 62,189 records are enough for merge, dedupe, the
   train/val/test split and EDA. A top-up crawl is an improvement, not a prerequisite.
2. **Chợ Tốt is the only gap that changes a conclusion**, because it is regional: the master currently
   under-represents the north and centre. Any "price by province" or "price by region" finding must be
   stated with that caveat until the northern/central half is crawled.
3. The report must record, per source, the catalogue size, the number collected and the reason for the
   difference (report §2.2: *"Record unsuccessful sources and any changes to collection targets"*).
   The table above is that record.

## Top-up crawlers that already exist

Two sources can be topped up **now**, with a crawler in this repository. Both write a separate
`_extra.csv` containing only the ids the team does not have yet, so nothing is counted twice.

```bash
# bonbanh.com: ~16,867 ads missing, 20 ads per request (~1,462 pages, ~35 min at 1.5 s/request)
python -m src.sources.bonbanh --pages 3        # smoke test: 3 pages
python -m src.sources.bonbanh                  # the whole catalogue -> data/processed/bonbanh_extra.csv

# bonbanh, second step: body_type / seller_type / listing_date only exist on the detail page.
# One request per NEW ad (17,997), resumable, ~8.5 h — chunk it with --detail-limit if you prefer.
python -m src.sources.bonbanh --details --detail-limit 3000   # repeat until progress hits 100%
python -m src.sources.bonbanh --reexport                       # rebuild the CSV from SQLite (no requests)
python tools/bonbanh_progress.py                               # progress + ETA

# carpla.vn: ~2,859 cars missing, one request per car (~4,181 sitemap URLs, ~1 h 45)
python -m src.sources.carpla --limit 5         # smoke test: 5 cars
python -m src.sources.carpla                   # the whole sitemap -> data/processed/carpla_extra.csv

# then re-merge, re-split, and validate
python -m tools.validate_source_csv data/processed/bonbanh_extra.csv
python -m tools.validate_source_csv data/processed/carpla_extra.csv
python -m src.merge.build_master
python -m src.data_prep.split
```

Both crawlers are resumable through the SQLite table (`data/scraped.db`, upsert on url): re-running
refreshes rows instead of duplicating them, and `--from-page` (bonbanh) or `--limit` (carpla) continue
where a stopped run left off.

**Why the detail step matters.** The bonbanh listing card carries price, province, origin, fuel, engine,
transmission, seats and odometer, but not body style, seller type or posting date. Merging the 17,997
top-up ads without the detail step leaves `body_type` at `Unknown` for all of them, which drags the
master's coverage from 84% down to 66%. With the step, all three fields reach ~100% on the new ads.

**Still needed from the owners** (no crawler in the repo yet):

| Source | Missing | Why it matters |
|---|---|---|
| xe.chotot.com | ~28,109 | the entire northern/central half — regional analysis is biased until this is crawled |
| carmudi.vn | ~233 | smallest gap; the `body_type = Coupe` template default is the bigger problem |

