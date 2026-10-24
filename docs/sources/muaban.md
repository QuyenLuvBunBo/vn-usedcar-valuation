# muaban.net — replacement for anycar.vn

**Status:** anycar.vn is offline, so the team replaced it with `muaban.net/o-to`
(same role in the plan: one more independent marketplace). Scaffold + crawl implemented
here; Nguyễn Huy Quang owns the source in the plan table.

## 1. Recon (2026-10-23)

```
$ curl https://muaban.net/robots.txt
User-agent: *
Allow: /
Disallow: /dashboard/
Disallow: /8zr2/
Sitemap: https://muaban.net/sitemaps/index.xml
```

- robots.txt allows `/o-to` (only `/dashboard/` and `/8zr2/` are disallowed) — no `Crawl-delay`,
  so we keep the shared 1.5 s delay for politeness.
- The site is a **Next.js app**: there is no server-rendered list HTML to scrape. Every page embeds
  its entire payload in

  ```html
  <script id="__NEXT_DATA__" type="application/json">{...}</script>
  ```

  so the parser reads JSON. That is much more stable than XPath on a JS site, and it also gives the
  numeric `price` (not only the display string), which removes the price-parsing risk of the other
  sources.

## 2. URLs and pagination

| What | Value |
|---|---|
| Listing page | `https://muaban.net/o-to?page=N` (N from 1) |
| Ads per page | 20 |
| Total ads in the category | ~7,500 (printed by the site as `classified.total`) |
| Detail page | `https://muaban.net/o-to/<category-slug>/<title-slug>-id<ad_id>` |

The JSON path of the data:

```
props.pageProps.classified.items[]   # listing rows (page 1..N)
props.pageProps.classified           # one ad + parameters, on a detail page
props.pageProps.classified.total     # how many ads the category holds
```

## 3. Fields the site publishes (detail page `parameters`)

Measured on 194 crawled ads (2026-10-24):

| Site label | Coverage | Unified column |
|---|---|---|
| Hãng xe | 100% | `brand` |
| Dòng xe | 100% | `model` |
| Năm sản xuất | 100% | `manufacture_year` |
| Số km đã đi | 95% | `mileage_km` (via `parse_km_text`) |
| Hộp số | 100% | `transmission` |
| Nhiên liệu | 100% | `fuel_type` |
| Số chỗ | 87% | `seats` |
| Kiểu dáng | 72% | `body_type` (`SUV/Crossover`, `Sedan`, `Hatchback`, `Pick Up`, `Van/Mini Van`) |
| Xuất xứ | 55% | `origin` (`Việt nam` → CKD, any country → CBU) |
| Màu xe | 20% | not in the contract (kept in `muaban_car_details.parameters`) |
| Tình trạng | 100% | `condition` in `muaban_car_details`; `--used-only` drops `Xe mới` |

Additionally `price` (int VND), `price_display`, `title`, `body`, `address`, `publish_at`,
`created_at`, `images[]`, `is_company`, `contact_name`.

**Not published by this site:** `sub_model_trim` (we keep the leftover title text),

## 4. Scope: what is dropped

`/o-to` also carries ads that are not a passenger car for sale. `unified.py` skips them and
reports the counts:

| Filter | Examples in the URL | Default |
|---|---|---|
| `not_for_sale` | `/cho-thue-` (rental), `/dich-vu-` (service), `phu-tung` (parts), `vay-mua` | skipped |
| `commercial` | `xe-tai`, `dau-keo`, `xe-khach`, `container`, `xe-cong-trinh` | skipped (`--include-commercial` keeps them) |
| `new_car` | `Tình trạng = Xe mới` | kept by default; `unified --used-only` drops them |

With 194 ads: 6 skipped as `not_for_sale`, 0 as `commercial`; the teammate's file (6,657 ads) still
contains 39 truck ads and 4 rental/service/parts ads.

## 5. How to run

```powershell
python -m src.sources.muaban --pages 2                 # 40 ads, ~4 s (list only)
python -m src.sources.muaban --pages 2 --details       # + 40 detail pages (~1 min)
python -m src.sources.muaban --details                 # full crawl: ALL listing pages + every detail page
python -m src.sources.muaban --details --limit 50      # only 50 detail pages (resume later)
python -m src.sources.muaban --details --refresh       # re-fetch all detail pages
python -m src.sources.muaban.unified --used-only       # data/processed/muaban.csv, used cars only
python -m tools.validate_source_csv data/processed/muaban.csv
```

Both tables are keyed on `url` (`storage.upsert_rows`), so a re-run never duplicates a row and the
detail crawl is resumable: it only fetches ads that have no detail row yet.
Full crawl cost: 375 listing pages + ~7,500 detail pages at 1.5 s ≈ **3 h**.

## 5b. Why `?page=N` alone cannot reach the whole catalogue

Measured 2026-10-24: the site stops advancing its pager after roughly 50–70 pages, then repeats one
of the last pages forever.

| query | ads reported | pages that advance |
|---|---|---|
| `/o-to?page=N` | 7,584 | ~50 (page 51+ repeat) |
| `/o-to/ban-o-to?page=N` | 7,554 | ~100 |
| `/o-to/ban-o-to-toyota?page=N` | 1,768 | ~60 |
| `/o-to/ban-o-to?car_types=627&vehicle_status_ids=526` | 1,723 | ~80 |

That is why `python -m src.sources.muaban --details` reported *"7600 ads stored"* while only 25 rows
were new: 378 pages produced ~7,300 duplicate URLs and `storage.upsert_rows` (keyed on `url`) kept
the same rows. The log now prints **new rows** instead of "stored", and warns when most of the pages
were repeats.

`--by-brand` fixes it by partitioning the catalogue into brand categories, which each page further:

```powershell
python -m src.sources.muaban --by-brand --used-only                 # lists: 74 brands, ~15 min
python -m src.sources.muaban --by-brand --used-only --details       # + ~7,260 detail pages (~3 h)
python -m src.sources.muaban --by-brand --brands toyota honda       # only a few brands (test)
```
- A brand bigger than the cap (~1,200 ads) is split again by `car_fuels` (6 values).
- Brand slugs are not always `slugify(name)`: `Mercedes Benz` lives at
  `/o-to/ban-o-to-mercedes` (366 ads) while `/ban-o-to-mercedes-benz` is a 404, so the crawler falls
  back to the first word and logs brands without a usable URL.
- Partitions are idempotent (upsert on `url`), so re-running only adds what is missing.
- A brand still above the cap after the fuel split is split again by `car_types` →
  `car_seat_ids` → `vehicle_origins` (`_crawl_split`), which is what recovered the missing Toyota ads.
- Verified 2026-10-24: `--brands honda mazda` → 799 ads seen, **680 new rows**;
  `--brands mercedes land-rover` → 373 seen, **320 new rows**; `--brands toyota` after the recursive
  split → **+339 rows** (1,243 → 1,582 of the 1,781 Toyota ads).

## 6. Result — full crawl (2026-10-24)

`python -m src.sources.muaban --by-brand --used-only --details` → **7,120 ads, every one with a
detail page**, exported as **7,022 rows** (skips: 13 rental/service, 40 commercial, 45 new cars).
Contract **PASS**.

| column | filled | column | filled |
|---|---|---|---|
| manufacture_year / transmission / province / seller_type / price_vnd | 100% | seats | 73.7% |
| brand | 99.5% | body_type | 65.1% |
| sub_model_trim | 99.4% | origin | 56.3% |
| mileage_km | 98.2% | engine_capacity | 25.6% |
| model / fuel_type | 97–98% | | |

Top brands: Toyota 1,582 · Ford 844 · Kia 749 · Hyundai 641 · Mitsubishi 530 · Mazda 447 ·
Vinfast 439 · Mercedes-Benz 358 · Honda 356 · Chevrolet 255.

## 7. Comparison with the file from Quang (2026-10-23, 6,657 ads)

Same site, two independent pipelines: **7,022 vs 6,657 rows**, 5,592 ads present in both
(1,430 ads only in ours, 1,065 only in his).

| field | agreement on the 5,592 shared ads |
|---|---|
| location_province | 100.0% |
| price_vnd | 99.7% |
| brand | 99.4% |
| manufacture_year | 98.7% |
| transmission | 94.5% |
| mileage_km | 93.7% |
| model | 93.3% |
| fuel_type | 92.3% |
| seats | 76.9% |
| body_type | 66.7% |

| coverage | Quang (6,657) | This crawler (7,022) |
|---|---|---|
| sub_model_trim | 40.1% | **99.4%** |
| transmission | 93.6% | **100%** |
| seller_type | 91.3% | **100%** |
| manufacture_year | 98.6% | **100%** |
| mileage_km | 89.8% | **98.2%** |
| fuel_type | 90.8% | **98.0%** |
| seats | **89.4%** | 73.7% |
| body_type | **89.8%** | 65.1% |
| origin | **75.5%** | 56.3% |
| engine_capacity | **44.2%** | 25.6% |

| data quality | Quang | Ours |
|---|---|---|
| placeholder brands | 63 | 34 (all genuinely unknown at the source) |
| models containing `khác` | 202 | **0** |
| `mileage_km` < 1,000 | 374 | 303 |
| `price_vnd` < 30 M | 51 | 65 (teaser/instalment ads, kept for the week-2 flags) |
| duplicate `source_url` | 0 | 0 |

**Reading:** his file wins on `seats` / `body_type` / `origin` / `engine_capacity` coverage — he
clearly parsed the free-text description as a fallback, which is also why his `body_type` is
inconsistent (Innova appears as MPV 88 / Van 70 / SUV 22 / Sedan 1). Our values are the site's
structured fields, so they are consistent but less complete; the gap is the week-2 job of mapping
model → body/seats/engine, or copying his extra fields after a review.

## 8. Known limitations

1. `body_type` / `origin` / `seats` are only present when the seller filled them; coverage is 74/57/87%
   and the missing values stay empty (never 0).
2. `engine_capacity` is inferred from the title and stays empty when the title has no displacement.
   Week 2 already plans a make/model/trim/year mapping for oto; reuse it here.
3. `sub_model_trim` is the leftover title text (the site has no grade field), capped at 40 chars.
4. `listing_date` is `publish_at` in ISO 8601 with the `+07:00` offset (the site's own bump time).

`engine_capacity` (only derived from the title when it mentions `1.5`/`2.0` style displacement).
