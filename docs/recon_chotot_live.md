# Chợ Tốt, live check — crawlable again, but it cannot fill `engine_capacity` or `trim`

Measured 2026-11-14 against the live site, from this machine, with the repository's user agent.
No crawl was started and nothing was written into `data/`.

## 1. Is it crawlable? Yes

| Probe | Result |
|---|---|
| `https://xe.chotot.com/robots.txt` | **200**, 1,813 bytes — `Allow: /`, disallows `/user/`, `/*chatroom*`, `/nhan/`, and a list of filter parameters |
| `https://gateway.chotot.com/robots.txt` | 404 (`no Route matched`) — the API host publishes no rules |
| List API `GET gateway.chotot.com/v1/public/ad-listing?cg=2010&limit=20` | **200**, 114 KB JSON, **20 ads**, fields `ad_id`, `price`, `mfdate`, `carbrand_name`, `carmodel_name`, `mileage`, `cartype`, `company_ad`, … |
| Detail API `GET …/ad-listing/{id}` | **200**, 9.4 KB JSON — keys `ad`, `ad_params`, `parameters`, `params` |
| Detail page `https://xe.chotot.com/{id}.htm` | **200**, ~200–255 KB, `__NEXT_DATA__` present |

Volume: the list endpoint reports `total: 10000`, which is the API's per-query cap — the week-2
enumeration already worked around it with price × year slices and found **18,413** price-listed ads
(the site counter said 29,693, which includes expired ads). Nothing here contradicts that.

## 2. Can it fill the four missing fields? Only two of them

**List payload** (60 ads, three pages) — no detail request needed:

| Field | Present | Maps to |
|---|---:|---|
| `cartype` | 45/60 (75 %) | `body_type` (`SUV / Cross over`, `Sedan`, `Minivan (MPV)`, `Van`) |
| `company_ad` | 40/60 (67 %) | `seller_type` (business vs individual) |
| `mileage` / `mileage_v2` | 43/60 · 54/60 | `mileage_km` |
| `mfdate` | 60/60 | `manufacture_year` |
| `gearbox`, `fuel` | 60/60 | `transmission`, `fuel_type` |
| `carseats` | 56/60 | `seats` |
| `carorigin` | 36/60 (60 %) | `origin` |

**Detail page** (20 ads): `Kiểu dáng`/`cartype` rendered on **13/20**, seller wording
(`chính chủ` / `cá nhân` / `showroom`) on **20/20** — but:

- `engine_capacity`: **0/20**. The page *declares* the label `"Dung tích động cơ", "param":"engine_capacity", "from":"product_graph"`,
  yet no value is rendered for any of the 20 ads, and the union of the 23 `ad_params` keys across the
  sampled ads contains **no displacement key at all**.
- `sub_model_trim`: **0/20**. Same shape: `"Phiên bản xe", "param":"option", "from":"product_graph"`,
  no rendered value. `carmodel` carries the base name (`Fortuner`, `VF7`, `GLC`), not the trim.

So Chợ Tốt's structure is exactly what v1 already shows: `engine_capacity` 100 % missing, `trim` 80 %
missing. A new crawl does not change that — the information is not on the page for these listings.

## 3. What a fresh Chợ Tốt crawl would and would not buy

| | New rows | Fills `body_type` | Fills `seller_type` | Fills `engine` | Fills `trim` | Repairs v1 rows |
|---|---|---|---|---|---|---|
| List-only (~20/page) | yes | 75 % | 67 % (`company_ad`) | no | no | **no** |
| + detail pages | yes | ~65 % | ~100 % (seller wording) | no | no | **no** |

Cost: 18–30 k ads ÷ 20 per request = **1,000–1,500 list requests ≈ 25–40 min** at 1.5 s; adding detail
pages costs **20–30 k requests ≈ 8–12 h** (or 1.5–2 h across eight runners) and buys only a better
`seller_type` and a slightly worse `body_type` rate.

And the hard constraint from `docs/recon_decision.md` stands: **0 of 80 sampled v1 ads still exist**
(68 "Tin đăng không tồn tại" pages that answer 200, 12 × HTTP 410), so no crawl can repair a v1 row.
Any Chợ Tốt crawl produces **new rows**, which means a **v2 snapshot with a new split** and every
week-3 number rebuilt.

## 4. Options

| Option | What it buys | Cost | Consequence |
|---|---|---|---|
| **A. Skip Chợ Tốt** | nothing; the limitation is documented | 0 | v2 keeps 13,631 chotot rows with the same gaps |
| **B. List-only refresh** | +body_type, +seller_type, +20–30 k fresh rows (more chotot volume, currently 13 % of the dataset) | ~30 min | new snapshot; chotot still has no engine/trim |
| **C. Refresh + detail** | B plus `seller_type` at ~100 % | +8–12 h (or 1.5–2 h parallel) | same as B, better seller column |

Recommendation: **B**, not C. The detail pass costs a day for one column that is already 34 % missing
overall and contributes ΔR² 0.0102 as a *group* (`docs/features_ablation.md` lists it with four other
spec columns), while `engine`/`trim` — the two that actually moved the score — cannot be obtained here
at all.

## 5. What this does **not** change

`www.bonbanh.com` remains the only source that can fill `trim` (100 % of sampled live pages) and
`engine` (81 %). The bonbanh backfill in `docs/recon_decision.md` §2 is unaffected by this probe.
