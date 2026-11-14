# Recon decision — what is worth crawling, and what is not

Measured 2026-11-14 on the frozen v1 IDs (`docs/recon_detail_fields.md` holds the raw table; this page
is the decision it supports). **No crawl was started**: the numbers come first, the crawl is a separate
decision.

## 1. What the sample found

Sample: 80 listings per platform, drawn at random (seed 42) from the v1 cohort rows that are **missing
at least one** of the four fields.

| Platform | Alive | 404 | "listing removed" page | HTTP 410 / error | engine | trim | seller | body |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| chotot | **0 / 80** | 0 | 68 | 12 | — | — | — | — |
| bonbanh | **80 / 80** | 0 | 0 | 0 | 81.2% | 100% | 100% | 98.8% |

Two host facts worth keeping: `bonbanh.com` (apex) times out and `www.bonbanh.com` answers; the removed
Chợ Tốt ads answer **200 with the text "Tin đăng không tồn tại"**, so a crawler that only checks the
status code would record them as alive.

## 2. Decision

### Chợ Tốt — **NO-GO for backfill**
Every sampled v1 ID is gone (68 removed pages + 12 × HTTP 410). A re-crawl cannot fill a single v1 row:
the ads the dataset refers to no longer exist. Filling `engine_capacity` / `sub_model_trim` /
`seller_type` for chotot requires crawling **new** ads, which produces **new rows**, not a backfill —
that is a different decision (a v2 snapshot) and it does not repair v1.

The site itself is still crawlable — list API 20 ads/request, detail API and detail pages answer 200,
robots allowed — but the live pages publish `body_type` (75 %) and `seller_type` (67–100 %) and **do
not publish `engine_capacity` or `trim` at all** (0/20 on both, and no displacement/trim key in the
`ad_params` union). Measurements and the three options: [`docs/recon_chotot_live.md`](recon_chotot_live.md).

### Bonbanh — **GO, limited to trim + engine + seller**
80/80 sampled pages are alive, and the fields are published: trim 100 %, seller 100 %, body 99 %,
engine 81 %. Expected effect on the frozen train split (21,159 bonbanh rows):

| Field | Rows currently standing on a statistic | Recon says the page has it | Expected rows with a *real* value |
|---|---:|---:|---:|
| `sub_model_trim` | 13,003 missing (61.5 %) | 100 % | **≈ 13,000** |
| `engine_capacity` | 2,024 imputed (9.6 %) | 81 % | **≈ 1,640** |
| `seller_type` | 3,450 imputed (16.3 %) | 100 % | **≈ 3,450** |
| `body_type` | 6 imputed (0.03 %) | 99 % | ≈ 6 (not worth the requests on its own) |

Trim is the one that matters: it is the feature that separates an LX from an EX, it was never in the
v1 feature set, and `trim_rank` (v2) already extracted what the *badge* says — a real trim column would
be the first non-statistical version of it.

Cost, at the crawler's measured 1.5 s/request + jitter: 21,159 pages ≈ **9–11 h single-threaded**, or
**1.5–2 h** across the eight runners the team already uses. Requests go to detail pages of listings that
are still advertised, robots-permitted, and the crawler is resumable (`upsert` on `url`).

## 3. Rules for the crawl, if it is approved

1. Re-sample 30 pages **on the day of the crawl**: 80/80 alive today does not promise 80/80 next week.
2. **Fill blanks only** — never overwrite `price_vnd`, `brand`, `model`, `manufacture_year`,
   `mileage_km` or any column that already has a value in v1. A backfill that changes a price changes
   the target and invalidates every number in the report.
3. Write to `data/processed/bonbanh_extra.csv` (the `_extra` convention `build_master` already reads),
   then merge into a **v2 snapshot**, never into v1.
4. Every filled cell carries an `imputed`-style provenance note (`trim_from_detail`), so a reader can
   tell a crawled value from a statistic.
5. Stop at the first sign of blocking (403/429 for more than 1 % of requests) and report the partial
   file — the crawler is resumable, so partial is fine.

## 4. What is still missing after this

`origin` (28.6 % unknown overall, mostly carmudi/tinbanxe/vucar), and every source for Chợ Tốt's
`trim`/`engine`. Both stay in `docs/data_limitations.md` as data the snapshot cannot carry.
