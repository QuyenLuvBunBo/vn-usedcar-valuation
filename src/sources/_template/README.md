# Template for a new data source

Copy this whole folder to `src/sources/<source>/` (for example `src/sources/bonbanh/`),
then follow the four steps below.

## 1. Recon the site before writing code

Use the helpers in `tools/`:

```bash
python -m tools.recon <url>            # robots.txt + fetch + discover hidden API/JSON
python -m tools.paging <url>           # find the pagination rule and the total count
python -m tools.check_pages <url>      # confirm pagination, find the last page
python -m tools.field_stats 2          # measure field coverage / price formats on a sample
```

Record the results in `docs/sources/<source>.md`: whether robots.txt allows crawling, whether the
HTML is server-rendered or JS-driven, the pagination rule, the selectors/XPaths you use, and
**which fields the site does not expose**.

## 2. Write `crawl.py`

Keep the structure of the template file; you only need to change:

- `SOURCE`, `BASE_URL`, `START_URL`, `TABLE`
- `parse_list_page(page_html, base_url)` → `(records, next_url)`
- (if needed) `parse_detail_page(page_html, url)` to fetch extra fields from each listing page
- `to_unified(raw)` → a dict with the **21 columns** from `src/common/schema.py`

Mandatory rules:

- Every request must go through `ScraperSession` (browser headers, delay, retry, 429 handling).
- Keep at least a **1.5 s delay per request** (configurable in `.env`) — no aggressive parallel runs.
- Write to SQLite with `storage.upsert_rows` (primary key = URL) so re-running never duplicates rows.
- Save raw HTML (`storage.save_raw`) wherever you expect to iterate on the parser.

## 3. Normalize to the 21 columns

Use `src/common/schema.py` and `src/common/parsing.py` — **do not re-implement**:

| Task | Helper |
|---|---|
| Vietnamese price "550 triệu", "1 tỷ 250 tr" → VND | `parse_vnd_price` |
| Mileage "140.000 km" → 140000 | `parse_km_text` |
| Transmission → Automatic/Manual | `schema.normalize_transmission` |
| Fuel → Gasoline/Diesel/Hybrid/Electric | `schema.normalize_fuel` |
| Origin → CKD/CBU | `schema.normalize_origin` |
| Body type → Sedan/SUV/Pickup/… | `schema.normalize_body` |
| Province / city | `schema.normalize_province` |
| Price interpretation status | `schema.price_status` |
| Seller salon vs. private | `schema.seller_type_from_subdomain` |

## 4. Validate, then open a pull request

```bash
python -m tools.validate_source_csv data/processed/<source>.csv
```

The script reports missing/extra columns, wrong order, wrong data types and unexpected categorical
values. **Only open a PR once it passes** — this is what lets us merge six sources in week 2
without hand-fixing anything.
