# vucar.vn

**Status:** migrated from the owner's Colab notebook (`vucar_scraper.py.ipynb`) into a package:
`python -m src.sources.vucar` crawls the raw records, `python -m src.sources.vucar.unified` writes the
21-column contract CSV. The request/pagination logic is the author's, unchanged.

## 1. Recon (2026-10-30)

```
$ curl https://vucar.vn/robots.txt
```

The crawler reads robots.txt itself before every run (`RobotFileParser`) and refuses to start if the
catalogue is disallowed; it also adopts the site's `Crawl-delay` when one is published.

- The catalogue is a **Next.js app**. `/mua-ban/o-to-cu` renders no listing HTML and there is no visible
  pagination, so the data comes from the site's own **server action**:
  `POST /mua-ban/o-to-cu` with `Next-Action: <id>` and the filter object as the body.
- The action ID **changes on every deployment**, so it is discovered from the page's `/_next/*.js`
  bundles (`fetchCarListing`) at the start of each run — nothing is hardcoded.
- The response is an RSC stream; the car list is the line that decodes to a dict with `cars`, `total`,
  `pageCount` and `limit`.
- Page size must be one of **8 / 24 / 72**; the crawler uses 8 and stops if the server returns another
  size (to avoid silently skipping records), and refuses to continue if a page repeats.

## 2. The API returns more than the notebook used

One record from the action:

```json
{"car_brand": "toyota", "car_model": "innova", "car_mileage": 101154, "car_price": 418000000,
 "car_location": "TP.HCM", "car_transmission": "MT", "car_fuel_type": "PETROL",
 "created_at": "2025-05-20T23:53:14.361466Z", "body_type": "MPV",
 "display_name": "Toyota Innova 2017", "manufactor_year": 2017, "is_displayed": false,
 "slug": "toyota-innova-2017-8c6be9e7", "car_exterior": ["https://…"]}
```

The notebook kept ten fields and dropped `car_brand`, `car_model`, `car_fuel_type` and `created_at`.
They are kept now, because they are what lets the export be exact instead of guessed.

## 3. Mapping to the 21 columns

| Contract column | Source | Note |
|---|---|---|
| `listing_id` | slug tail | `VUCAR_8c6be9e7` |
| `brand` + `model` | **`display_name`** | the year is stripped, then the longest make in the brand table wins: `Mercedes C Class 2016` → `Mercedes-Benz` + `C Class`, `Land Rover Range Rover` → `Land Rover` + `Range Rover`. The API's `car_brand`/`car_model` are slugs (`mercedes`, `c_class`) and re-casing a slug cannot reproduce `CR-V` or `Lux A2.0`; the slug is used only as a fallback and a cross-check |
| `manufacture_year` | `manufactor_year` (the site's spelling) | |
| `mileage_km` | `car_mileage` | |
| `transmission` | `car_transmission` | `AT` → Automatic, `MT` → Manual, other non-empty → Other |
| `fuel_type` | `car_fuel_type` | `PETROL` → Gasoline, `OIL` → Diesel, `ELECTRIC` → Electric |
| `body_type` | `body_type` | `MPV`/`SUV`/`SEDAN`/`HATCHBACK`/`PICKUP`/`CUV` (→ Crossover) |
| `location_province` | `car_location` | the site writes `TP.HCM`, `HaNoi`, `BinhDuong`, `LongAn` (no diacritics, no spaces) → canonical province names |
| `listing_date` | — | **left empty on purpose**: the action's `created_at` is a bulk-import timestamp (2,039 rows share `2025-05-20`, 85 share `2025-05-21`), not a publication date. It stays in `vucar_raw.csv` for anyone who needs it |
| `price_vnd` | `car_price` | |
| `engine_capacity`, `seats`, `origin`, `seller_type` | — | **not exposed**: left empty / `Unknown` rather than invented |

## 4. Verification against the owner's file

`vucar.csv` (2,124 rows, produced by the notebook) was compared cell by cell with this exporter on the
ids both contain. Columns that describe the car — `brand`, `model`, `manufacture_year`, `mileage_km`,
`transmission`, `body_type`, `location_province`, `price_vnd`, `source_url`, `price_status` — match
exactly. Four columns differ, and in each case the exporter is the correct side:

| Column | `vucar.csv` | this exporter | Why |
|---|---|---|---|
| `listing_date` | `10/2026` on **all 2,124 rows** | empty | the owner wrote the capture month. The action's `created_at` is no better — 2,039 rows share one date — so the column stays empty per docs/unified_schema.md |
| `fuel_type` | empty | `Gasoline` / `Diesel` / `Electric` | the action returns `car_fuel_type`; the notebook ignored it |
| `origin` | empty | `Unknown` | docs/unified_schema.md rule 1: an unrecoverable categorical is `Unknown`, never blank |
| `seller_type` | empty | `Unknown` | same rule |
| `body_type` | `Other` on 19 rows | `Coupe` | the site labels those 19 cars "Couple" — Audi TT/A5, Camaro, Mustang — so `Coupe` is the honest label |
| `model` | `VF5` on 8 rows | `VF5 Plus` | the site's `display_name` and `car_model` slug (`vf5_plus`) both say VF5 Plus; the owner shortened it. Kept faithful, and noted because `model` feeds the dedupe key |

## 5. Commands

```bash
python -m src.sources.vucar --max-pages 1      # 8 cars, a quick check
python -m src.sources.vucar                    # whole catalogue: 266 pages, ~10 min
python -m src.sources.vucar.unified            # data/processed/vucar.csv (21 columns)
python -m tools.validate_source_csv data/processed/vucar.csv
```

The crawler saves after **every page** (atomic replace) and writes `<out>.summary.json` with the
`stop_reason`, the site's reported total and the missing-value counts, so an interrupted run loses
nothing and never overwrites a good file with an empty one.
