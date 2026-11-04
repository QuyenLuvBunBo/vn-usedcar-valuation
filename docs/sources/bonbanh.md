# bonbanh.com

**Status:** the crawler in `src/sources/bonbanh/` covers the **whole catalogue**, not only the part two
members originally collected: `/oto` prints `Tổng: 29,241` and the crawl ends up with 30,371 ads
(people keep posting while the pages are walked). Phạm Hải Duy owns cars from 2019, Phạm Xuân Hiếu the
1995–2018 half; both feeds are one platform.

## 1. Recon (2026-10-29)

```
$ curl https://bonbanh.com/robots.txt
User-agent: *
```

Seven lines and **no `Disallow` at all** — the listing pages, the detail pages and the pagination are all
allowed. There is no `Crawl-delay`, so the shared 1.5 s delay applies.

- Pagination: `/oto/page,2`, and the page advertises it (`rel="next"`). Verified by fetching page 1 and
  page 2: **20 distinct listing links each, 0 overlap** → the pagination really walks the whole list,
  29,241 / 20 ≈ **1,462 pages**.
- The site is server-rendered HTML (no JS payload), so lxml + XPath is enough.

## 2. The listing card already carries most fields

Each ad is a `li.car-item` block with schema.org microdata, plus a structured one-line summary:

```html
<li class="car-item row1" itemscope itemtype="http://schema.org/Car">
  <a itemprop="url" href="xe-toyota-innova-cross-2.0-cvt-2024-7030280">
    <div class="cb1">Xe cũ<br><b>2024</b></div>
    <div class="cb2_02"><h3 itemprop="name">Toyota Innova Cross 2.0 CVT - 2024</h3></div>
    <div class="cb3"><b itemprop="price" content="748000000">748 Triệu</b></div>
    <div class="cb4"><b>TP HCM</b></div>
    <div class="cb6_02">*Xe nhập khẩu, màu trắng, máy xăng 2.0 L, số tự động, 8 chỗ, đã đi 35,000 km ...</div>
```

| Field | Source | Note |
|---|---|---|
| `listing_id` | href tail | `BAN_<code>` (`7030280`) |
| `price_vnd` | `content` attribute | exact integer, **not** parsed from text |
| `raw_price_text` | element text | `748 Triệu` |
| `manufacture_year` | `h3` tail | `- 2024` |
| `location_province` | `div.cb4` | district-qualified strings are normalized |
| `origin` / `fuel_type` / `engine_capacity` / `transmission` / `seats` / `mileage_km` | the `cb6_02` summary | ", "-separated, so each field is read on its own |

One request therefore returns **20 finished records**, which is why the whole catalogue takes ~35 minutes.

## 3. Fields the card does not print — the detail pass

`body_type`, `seller_type` and `listing_date` exist only on the detail page, so they are a second,
resumable pass (one request per **new** ad, never for the ads the members already collected):

```bash
python -m src.sources.bonbanh --details --detail-limit 3000
python -m src.sources.bonbanh --reexport
python tools/bonbanh_progress.py
```

| Field | Where | How |
|---|---|---|
| `body_type` | `div.box_car_detail` → row "Kiểu dáng" | label/value rows; `Bán tải / Pickup` and `Convertible/Cabriolet` are mapped onto the contract labels |
| `origin` | same block, "Xuất xứ" | preferred over the summary when present |
| `seller_type` | `a.cname` href | a showroom gets its own subdomain (`volvolongbien.bonbanh.com`) → `Dealership/Salon`; no subdomain → `Private Individual` |
| `listing_date` | text "Đăng ngày 9/10/2026" | day and month may be **one digit** — a `\d{2}` rule silently loses 15% of the dates |

A detail page with **no spec table** is a removed ad: the parser reports nothing rather than inventing a
seller type, and the row stays `detail_done = 0` (11 ads out of 17,997).

## 4. Two traps this source set

1. **Unicode normalization.** The detail page sometimes delivers decomposed characters (`Ba` + U+0300 +
   `n`), which looks identical to `Bản` but never compares equal. Brand/body lookups go through
   `unicodedata.normalize("NFC", …)`.
2. **Two-word makes.** `Mercedes Benz …` would otherwise become brand `Mercedes` + model `Benz GLS`;
   `MULTIWORD_BRANDS` collapses it to `Mercedes-Benz`, the same canonical name `muaban` uses, so both
   sources group together in the dedupe key.

## 5. Coverage

| Column | Filled |
|---|---|
| `price_vnd`, `manufacture_year`, `location_province`, `origin` | 100% |
| `body_type`, `seller_type` | 100% / 84% |
| `listing_date` | 100% |
| `engine_capacity` | 93% |
| `mileage_km` | 76% (a new car often has no odometer yet) |

Not exposed by the site: `sub_model_trim` as a separate field (it stays inside the model string) and the
body style for ads whose detail page is gone.
