# oto.com.vn → Unified Schema mapping (week 1)

Source: **oto.com.vn** — Asian mainstream segment (Toyota, Hyundai, Kia, Mazda, Honda,
Mitsubishi), **used cars only**.
Crawled so far: **2,706 listings** (196 listing pages + 2,706 detail pages).

## How to regenerate the files

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m src.sources.oto --group asia        # listings for the six Asian brands (~10 min)
python -m src.sources.oto --group other       # listings for the remaining brands
python -m src.sources.oto --detail-only       # detail page per listing (~1h45m)
python -m src.sources.oto.unified             # export data/processed/oto_unified.csv (21 cols)
```

## Mapping of the 16 attributes + 5 metadata columns

| # | Unified column | Where it comes from on oto.com.vn | Coverage | Notes |
|---|---|---|---|---|
| 1 | `listing_id` | card attribute `data-autoid` | 100% | Written as `OTO_23444795` (source prefix + ID) |
| 2 | `source_platform` | constant | 100% | `oto.com.vn` |
| 3 | `brand` | `data-tinrao[0]` | 100% | 6 brands |
| 4 | `model` | `data-tinrao[1]` | 100% | 103 models |
| 5 | `sub_model_trim` | parsed from the title (`h1.title-detail` / `car_name`) | 89.1% | e.g. `1.8G CVT`, `2.5Q`, `2.7 V 4X2 AT`; 296 sellers did not state a trim |
| 6 | `manufacture_year` | `data-call[4]` (or `#year`) | 100% | 1990–2026 |
| 7 | `mileage_km` | `tag-list` entry "140.000 km" | 99.9% | Raw site value; some sellers typed it wrong (e.g. `12.000.000 km`) |
| 8 | `transmission` | tag "Số tự động / Số sàn" | 100% | Mapped to `Automatic` / `Manual` / `Other` |
| 9 | `fuel_type` | tag "Máy xăng / Máy dầu / Hybrid" | 100% | Mapped to `Gasoline` / `Diesel` / `Hybrid` |
| 10 | `origin` | `data-call[3]`, falling back to the detail page's `Xuất xứ` | 100% | Mapped to `CKD` (locally assembled) / `CBU` (imported). The fallback is required because sold listings have no `data-call` |
| 11 | `body_type` | `data-call[6]`, falling back to `Kiểu dáng` on the detail page | 96.9% | Mapped to `Sedan/SUV/Crossover/MPV/Hatchback/Pickup/Van/Truck/Sports/Convertible` |
| 12 | `engine_capacity` | numeric part of the trim/title (`1.5`, `2.0`, `2.4`) | 76.9% | ⚠️ **Inferred value** — the site has no displacement field. The report allows a make/model/trim/year lookup table instead |
| 13 | `seats` | hidden input `#numberOfSeat` (detail page) | 97.3% | Not present on the listing card, so a detail crawl is needed |
| 14 | `location_province` | `Tỉnh thành` (detail) → `province` (listing) | 100% | "Thủ Đức - Tp.HCM" collapsed to `TP. Hồ Chí Minh`; 101 distinct labels |
| 15 | `seller_type` | inferred from `d_seller_url` | 100% | Own subdomain ⇒ `Dealership/Salon` (1,818) · none ⇒ `Private Individual` (888) |
| 16 | `price_vnd` (target) | hidden input `#price` (e.g. `745000000`) → `p.price` | **100%** | 222 listings had a blank price but the detail page had one ⇒ fully recovered |
| 17 | `source_url` | `h3/a @href` | 100% | Absolute URL |
| 18 | `listing_date` | `<lastmod>` in `sitemap-detail-1/2.xml` | 99.5% | ⚠️ The **publication/last-bump** date, because the site publishes no "posted on" date on the listing page. Verified: it correlates with the listing page position |
| 19 | `scraped_at` | capture time of the tool run | 100% | UTC, ISO 8601 |
| 20 | `raw_price_text` | `p.price` (listing) → `span.price` (detail) | **100%** | Unmodified text, e.g. `1 tỉ 450 triệu` |
| 21 | `price_status` | derived from the price + raw text | 100% | `full` / `negotiable` / `instalment` / `invalid`. For oto.com.vn all 2,706 are `full` |

## What oto.com.vn does **NOT** provide (report them as null)

| Field | Status |
|---|---|
| An officially published listing date | Not shown anywhere; only the sitemap `lastmod` exists (see #18) |
| View count | Not shown |
| Engine displacement (cc/L) | Not on the listing page; it appears on the **model spec page** (`/bang-gia-xe-o-to-<brand>-<model>-moi-nhat`) → build a lookup table in week 2 |
| Detailed technical specs (power, dimensions) | The "Thông số kỹ thuật" tab contains no data |
| Seats | Only available by crawling the detail page (`#numberOfSeat`) |
| `duplicate_group_id`, `quality_flags` | Planned for week 2 (not generated yet) |

## Verified size of the oto.com.vn source (important for the 15,000 target)

| Measurement | Number | Meaning |
|---|---|---|
| URLs in `sitemap-detail-1/2.xml` | **30,900** | ⚠️ **Not the current inventory** — this is the historical URL archive the site keeps |
| Of those, `aidxc` suffix (used cars) | 29,392 | still-reachable used-car listing pages |
| URLs whose `lastmod` is within 90 days | ~7,400 | the "fresh" part |
| URLs whose `lastmod` is older than 90 days | **23,484 (76%)** | mostly no longer advertised |
| **Listings actually shown in the listings** | **≈ 5,000** | six Asian brands: **2,706** (matches the site's own counter) + remaining brands ≈ 2,200 |

Evidence that "sitemap ≠ inventory":

1. Toyota has **5,715 URLs** in the sitemap, yet the listing page reports `Có 892 tin` and
   crawling all 60 pages yields exactly 892 listings.
2. A random sample of 48 sitemap-only listings returned **HTTP 200 with full data**, but searching
   the listings by **brand** and by **model** did not find any of them ⇒ they were removed from the
   advertised set while the page stays online (usually an ad that was renewed/reposted under a new
   id, or one that expired without being deleted).
3. Of 40 sitemap-only listings, **34 (85%) still show the "Trả giá" (price-proposal) button**
   (i.e. not marked as sold) — yet they are still absent from the listings ⇒ that button only means
   the page was not marked sold, it does **not** prove the car is still advertised.

**Consequence for the week-1 plan:** a target of 15,000 listings per person is **not reachable from
the current oto.com.vn listings** (~5,000 listings site-wide). Three options:

1. Make it up from the other five sources (bonbanh, chotot, carmudi, carpla, anycar) — the preferred route.
2. Add an "archive tier" from the sitemap (about 26,600 more listings) but **add an `in_listing`
   column** so the report keeps them separate: they are not currently advertised, most are old, and
   roughly 15% are sold.
3. Lower the target for this source.

If the archive tier is used: crawl straight from the sitemap URLs (no pagination needed). The
sitemap is **sorted by `lastmod` descending**, so the first N URLs are the N newest listings, and a
detail page already carries all 21 unified columns.

## Archive tier (optional, extra data beyond the listings)

`sitemap-detail-*.xml` lists ~30,900 URLs but only ~5,000 listings are currently advertised, so the
rest is an archive of pages the site still serves (renewed under a new id, expired, or sold). These
pages are normal detail pages and carry all 21 unified columns, but the car is **not currently
listed**, so they are stored and exported separately.

```powershell
python -m src.sources.oto.archive --limit 50         # quick sample (~2 min)
python -m src.sources.oto.archive                    # everything, resumable (~16-18h)
python -m src.sources.oto.archive --summary          # coverage/price stats of what was crawled
python -m tools.archive_progress                     # live progress + rate + ETA (one snapshot)
python -m tools.archive_progress --watch 5           # refresh every 5 s, Ctrl+C to stop
python -m src.sources.oto.unified --include-archive  # -> data/processed/oto_archive_unified.csv
python -m src.sources.oto.unified --out oto --include-archive --combine  # -> data/processed/oto.csv (both tiers)
python -m src.sources.oto.unified --check-derivation # validate brand/model extraction
python -m tools.compare_tiers                        # live tier vs archive tier, side by side
```

The crawler writes a tqdm bar to `logs/archive_run.err`, so the raw bar can also be watched with
`Get-Content logs\archive_run.err -Tail 1` (or `-Wait` for a scrolling log).

### Result (2026-10-13)

| Tier | Rows | File | Definition |
|---|---|---|---|
| Live | 2,713 | `data/processed/oto_unified.csv` | advertised in the listings right now |
| Archive | 25,715 | `data/processed/oto_archive_unified.csv` | page still served, no longer advertised |
| **Both** | **28,428** | **`data/processed/oto.csv`** | week-1 hand-off for the merge (both tiers) |

`python -m tools.validate_source_csv data/processed/oto.csv` → **PASS** (21 columns, no duplicate
`listing_id`/`source_url`, all categorical values inside the contract).

Why two columns stay sparse (the validator's "mostly empty" warning):

- `engine_capacity` 25.3% — oto publishes displacement neither on the listing cards nor in the archive
  spec table; it is inferred from the trim/title ("1.5", "2.0"), so it is filled only when the seller
  wrote it. Week 2 uses a make/model/trim/year mapping instead of imputing one global value.
- `sub_model_trim` 37.9% (archive tier) — private sellers write free-text titles with no grade; the
  live tier fills this from the site's own `data-tinrao` blob.

Data facts worth a line in the report:

- `price_status = full` for all 28,428 rows: oto always publishes a definite price (no "Thỏa thuận"),
  so the target needs no negotiation filtering for this source.
- The archive holds the old/cheap long tail: median asking price 495 M vs 555 M live, median year 2020
  vs 2021, private sellers 83.5% vs 33% (dealers keep their ads visible by bumping them).
- 17 of 25,729 crawled pages (0.07%) are unusable and are dropped at export: 7 served without a listing
  payload (ad deleted at the source) and 7 duplicate a live ad reached through a sitemap URL with an
  empty slug (`.../mua-ban-xe-<brand>-<city>/-aidxcNNNN`).
- Outlier review for week 2: 4 implausible asking prices (180 / 162 / 159 / 52 billion VND),
  5 rows above the report's 25-billion rule, 476 rows with < 100 km on a car older than 2 years,
  15 rows above 1,000,000 km, 6 rows outside 1995–present. Flag, do not delete.

How it stays honest:

- Rows live in their own table (`oto_archive`) and carry `in_listing = 0`, `ad_id`, `listing_date`
  (sitemap `lastmod`) and `sold_marker` (1 when the price-proposal button is still present).
- URLs already in the listings are skipped, so the two tiers do not overlap. Seven ads still got in
  through a second sitemap URL whose slug is empty (`.../mua-ban-xe-<brand>-<city>/-aidxcNNNN`); the
  export drops those, so `oto.csv` and `oto_archive_unified.csv` are disjoint by construction.
- `--skip-recent-days 30` (default) ignores URLs bumped in the last 30 days: those are probably
  still in the listings.
- The archive CSV has the same 21 columns but is **not** part of the week-1 deliverable — merge it
  into a dataframe only when you want the extra history, and keep the `in_listing` distinction.

Because an archive page has no listing card, brand/model come from the title. That extraction was
validated against the 2,706 crawled listings (whose brand/model the site publishes directly in
`data-tinrao`): **brand matches 100%**, **model matches 95.6%** (the remainder are titles with extra
grade words such as "Land Cruiser **V6**", "Alphard **Executive Lounge**"). Run
`--check-derivation` to reproduce those numbers.

## Important notes when using the data

1. **47.8% of the listings are "sold"** (the `sold` flag in the raw table). They still have all 16
   attributes, but the price is a **historical asking price**, not a current one. Run the model both
   with and without them to test sensitivity.
2. `listing_date` is a bump date: **do not use it as a feature**; use it only to split train/test by time.
3. `price_vnd` is the **target**: never feed it to the predictors (leakage). Do not use
   `raw_price_text`, `price_status` or the `d_price_vnd` column for training either.
4. **Do not publish contact information** (phone numbers, individual sellers' names/addresses) — the
   report requires removing it. Use `seller_type` instead.
5. `engine_capacity` is inferred: attach a quality flag and validate it against the model-spec lookup
   before treating it as an important predictor.

## Suggested column selection for modelling (week 3)

- **Target**: `price_vnd`
- **Main predictors**: `brand`, `model`, `sub_model_trim`, `manufacture_year`, `mileage_km`,
  `transmission`, `fuel_type`, `origin`, `body_type`, `engine_capacity`, `seats`,
  `location_province`, `seller_type`
- **Engineered features to build**: `vehicle_age = listing/capture year − manufacture_year`,
  `km_per_year = mileage_km / max(vehicle_age, 1)`, `geo_tier` (Hà Nội/TP.HCM vs provinces),
  `brand_retention_rate` (by group)
- **Metadata — never used as features**: `listing_id`, `source_platform`, `source_url`,
  `listing_date`, `scraped_at`, `raw_price_text`, `price_status`

