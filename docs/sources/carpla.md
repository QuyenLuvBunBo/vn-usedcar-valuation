# carpla.vn

**Status:** the crawler in `src/sources/carpla/` covers the **whole sitemap** (4,181 cars), not only the
1,322 the team had. Đỗ Tuấn Anh owns the source; carpla is a dealership chain, so every row is
`Dealership/Salon`.

## 1. Recon (2026-10-29)

```
$ curl https://carpla.vn/robots.txt
User-agent: *
Disallow: *?brand=*
Disallow: */blog-car*
Disallow: */blog-pk/*
Disallow: *?new
Disallow: *?figure=*
```

Only **filter** URLs are disallowed, and this crawler never uses them.

- `/mua-xe` is a 1.4 MB JS-rendered page: no listing links in the markup and `?page=` changes nothing
  (page 1, 2, 50 and 100 return byte-identical sizes). **Paging through it is a dead end.**
- The enumeration comes from the site's own sitemap:
  `sitemap_index.xml` → `sitemap_product.xml` → **4,181** `<loc>` entries such as
  `https://carpla.vn/xe/ford-everest-2018-f8xwi`.

## 2. One detail page per car, three extraction sources

The page is a Next.js app with **no JSON-LD**, so the fields come from three places:

| Field | Where | How |
|---|---|---|
| `price_vnd` | React Server Components payload | the escaped JSON still carries the exact number: `\"price\":689000000` |
| `listing_date` | same payload | `\"postedAt\":[1777365105]` (epoch seconds), `createdAt` as fallback |
| `body_type` / `fuel_type` / `transmission` / `seats` | rendered text | specs are `label|value` pairs: `Nhiên liệu|Dầu|Kiểu dáng|SUV|Hộp số|Số tự động|Số chỗ|7` |
| `mileage_km` | payload `odo`, else the title, else the **slug** | `/xe/mitsubishi-attrage-2024---52800km-f8w9u` |
| `manufacture_year`, `brand`, `model` | `<title>` | `Bán xe Ford Everest 2018 - 102,000km` |
| `location_province` | dealer block | the field before `Xem cửa hàng` |
| `listing_id` | URL tail | `CARPLA_<SLUG>` uppercase, e.g. `CARPLA_F8W9U` |
| `seller_type` | constant | carpla only lists its own inventory → `Dealership/Salon` |

## 3. Two traps this source sets

1. **An empty spec cell shifts the pairs.** When "Kiểu dáng" has no value, the next label becomes the
   value (`body_type = "Hộp số"`). Any value that is itself a known label is therefore dropped, not
   stored.
2. **Values the contract does not have.** The site prints `CUV` (→ `Crossover`), `Van/Minibus` (→ `Van`),
   `Xe du lịch` (→ `Other`), `Xe khách` (→ `Minibus`) and `Plug-in hybrid` (→ `Hybrid`); all are mapped in
   `BODY_ALIASES` / `FUEL_ALIASES`. The Turkish dotted-I in `Transmission` values is handled by the same
   lower-casing path.

## 4. Coverage

| Column | Filled | Why |
|---|---|---|
| `price_vnd`, `manufacture_year`, `location_province`, `body_type`, `seller_type` | 100% | |
| `seats` | 99% | |
| `listing_date` | 91% | a few ads were never bumped, so only `createdAt` exists |
| `mileage_km` | 65% | ~35% of the cars are new and the page prints `-` instead of an odometer |

**Not exposed by the site:** engine displacement (`engine_capacity` stays empty for every carpla row) and
`origin` (CKD/CBU) — carpla never prints it, which is why the merged master fills `origin` from the other
sources only.
