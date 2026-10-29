# tinbanxe.vn → Unified Schema mapping (fallback source)

Tinbanxe is used as a fallback because Carmudi does not provide enough used-car records for the project quota. Scope: used passenger cars.

## Quick run

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m tools.paging https://tinbanxe.vn/mua-ban/oto/toyota/cu/  # inspect pagination before a large crawl
python -m src.sources.tinbanxe --brands toyota --pages 2 --save-raw
python -m src.sources.tinbanxe.unified
python -m tools.validate_source_csv data/processed/tinbanxe.csv
python -m src.sources.tinbanxe.tests.smoke
```

## Findings (recon 2026-10-20; validation snapshot 2026-10-28)

- Saved raw listing HTML is server-rendered and contains cards using `div.t-x-list`; this selector is used by `crawl.py`.
- Ad links follow `https://tinbanxe.vn/<slug>-<id>/`; IDs in the saved crawl reach approximately 88,600.
- **Mileage needs careful interpretation.** Cards may say `đã đi 86 km` while the description says `odo 86.000km`. `unified.py` currently treats card values below 1,000 as thousands of km and prefers a description value when the disagreement exceeds 20%. This is an inferred site convention, not guaranteed for every listing; review outliers.
- `listing_date` is inferred from the epoch in the image path (`image_tin_dang/YYYY_MM/<epoch>-...`) and accepted only when the timestamp's year/month agrees with the folder. This is not a verified publication date.
- Some listings may be reposts with different IDs. Keep them traceable and investigate duplicates rather than removing records solely from similar attributes.
- In the saved raw HTML, the first line after the price can be `Xe cũ 2003`, not a province. The parser now prefers the first location row in `.info-2`, then the location footer, before using the fallback line-based heuristic.

## Mapping

| Unified column | Source / handling |
|---|---|
| `listing_id` | `TBX_<id>` |
| `source_platform` | `tinbanxe` |
| `brand` | Brand slug supplied to the crawler |
| `model`, `sub_model_trim` | Best-effort extraction using curated URL-slug aliases first, then title parsing, with detail metadata as fallback; model is not a dedicated field on the listing card. Validate uncommon trims and ambiguous slugs manually |
| `manufacture_year`, `price_vnd`, `raw_price_text` | Title/card; price is parsed by shared `src/common/parsing.py` |
| `mileage_km` | Card mileage plus description cross-check; inferred scaling rule above |
| `transmission`, `fuel_type` | Card specification text; values are normalized to the unified schema |
| `seats` | Parsed only when seat-count information is present and recognizable; otherwise `Unknown`/empty according to the unified output convention. Do not infer a default of 5 seats |
| `location_province` | Location row/footer, normalized by `schema.normalize_province` |
| `listing_date` | Inferred from image timestamp; nullable and not authoritative |
| `origin`, `body_type`, `seller_type` | Not consistently available or reliably extractable from listing cards; current output uses `Unknown` when a trustworthy value cannot be extracted. These columns can have 100% coverage while still containing `Unknown` values |


## Latest validation snapshot

Command:
```powershell
python -m tools.validate_source_csv data/processed/tinbanxe.csv
```

Latest reported result: **PASS** — 7,654 rows and 21 columns in the expected order.

| Column | Non-empty | Coverage | Note |
|---|---:|---:|---|
| `engine_capacity` | 1,999 / 7,654 | 26.1% | Often not supplied in the listing card or reliably recoverable from the available text; leave missing when unsupported rather than guessing |
| `seats` | 868 / 7,654 | 11.3% | Seat count is not consistently supplied or recognizable in the source text; do not assume every car has 5 seats |

The validator checks schema shape and column coverage; a `PASS` does **not** guarantee every extracted value (especially `model`, `mileage_km`, or inferred `listing_date`) is semantically correct. Review suspicious values and representative samples separately.

## Still to verify before a large crawl

- Whether the brand-level listing URL `/mua-ban/oto/<brand>/cu/` and `?page=N` pagination work consistently for all brands. Use `python -m tools.paging <url>` and compare page IDs.
- `robots.txt` and site terms have not been reviewed in this recon; check them before increasing crawl volume.
- The offline fixture is reconstructed rather than a byte-for-byte saved page. Keep it aligned with the observed `.t-x-list` structure and re-check after site markup changes.
