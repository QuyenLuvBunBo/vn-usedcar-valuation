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
- Verified 2026-10-24: `--brands honda mazda` → 799 ads seen, **680 new rows**;
  `--brands mercedes land-rover` → 373 seen, **320 new rows**.

## 6. Result (2026-10-24, sample)

194 rows exported (200 ads with details, 6 skipped as not for sale), contract **PASS**:

| column | filled | column | filled |
|---|---|---|---|
| brand / model / year | 100% | body_type | 74.2% |
| mileage_km | 97.9% | engine_capacity | 25.3% |
| transmission | 100% | seats | 87.1% |
| fuel_type | 98.5% | origin | 57.2% |
| price_vnd | 99.5% | sub_model_trim | 99.5% |

## 7. Comparison with the file from Quang (2026-10-23, 6,657 ads)

Same site, two independent pipelines. On the **67 ads present in both files**:

| field | agreement | note |
|---|---|---|
| location_province | 67/67 (100%) | |
| brand | 66/67 (99%) | the only difference is his placeholder `Các hãng khác` |
| manufacture_year | 65/67 (97%) | ours fills the year where his is empty |
| price_vnd | 65/67 (97%) | 2 ads were edited between the two crawls |
| model | 63/67 (94%) | `CRV` vs `CR-V` (we align with oto), placeholders |
| fuel_type | 61/67 (91%) | ours fills `Gasoline`/`Diesel` where his is `Unknown` |
| mileage_km | 60/67 (90%) | 1 ad edited; ours empty when the site drops the field |
| transmission | 58/67 (87%) | ours maps `Bán tự động` → `Other`; his calls it `Automatic` |
| engine_capacity | 54/67 (81%) | his has more coverage (likely parsed from the description) |
| origin | 53/67 (79%) | his has more coverage (same reason) |
| seats | 50/67 (75%) | his has more coverage |
| body_type | 48/67 (72%) | his has more coverage, but **inconsistent** (Innova appears as MPV 88 / Van 70 / SUV 22 / Sedan 1) |
| seller_type | 47/67 (70%) | we use the site's `is_company`; his used a keyword heuristic |

Data-quality differences on the whole files:

| check | Quang (6,657) | This crawler (194) |
|---|---|---|
| placeholder brands (`Các hãng khác`, `Xe tải, đầu kéo…`) | 63 | 0 |
| models containing `khác` | 202 | 0 |
| `mileage_km` < 1,000 km | 374 (e.g. `5 vạn` → 5.0) | 10 |
| `price_vnd` < 30 M VND | 51 (rental / instalment teasers) | 0 |
| `sub_model_trim` coverage | 40.1% | 99.5% |
| duplicate `listing_id` / `source_url` | 0 / 0 | 0 / 0 |

**Recommendation:** his file is broader (6,657 ads) but needs the mileage/price/junk fixes before it
can be merged; this crawler is the reference for *how* the fields are extracted (structured
`parameters`, numeric `price`), so the cheapest path is: take his extra ads, re-export them with this
pipeline (`--details` re-fetch), or merge his rows only after fixing the four issues above.

## 8. Known limitations

1. `body_type` / `origin` / `seats` are only present when the seller filled them; coverage is 74/57/87%
   and the missing values stay empty (never 0).
2. `engine_capacity` is inferred from the title and stays empty when the title has no displacement.
   Week 2 already plans a make/model/trim/year mapping for oto; reuse it here.
3. `sub_model_trim` is the leftover title text (the site has no grade field), capped at 40 chars.
4. `listing_date` is `publish_at` in ISO 8601 with the `+07:00` offset (the site's own bump time).

`engine_capacity` (only derived from the title when it mentions `1.5`/`2.0` style displacement).
