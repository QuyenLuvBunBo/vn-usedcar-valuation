# carmudi.vn → Unified Schema mapping (week 1)

Owner: Nguyễn Văn Quyết · scope: passenger cars, **used only** · quota 6,000 (see "Size" — not reachable).

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m src.sources.carmudi --probe                # FIRST: print one API ad, check field names
python -m src.sources.carmudi --save-raw             # all API pages (20 ads each)
python -m src.sources.carmudi --detail --save-raw    # optional: also the HTML detail pages
python -m src.sources.carmudi.unified                # -> data/processed/carmudi.csv (21 cols)
python -m tools.validate_source_csv data/processed/carmudi.csv
```

## Size (recon 2026-10-20)
The listing page reports **807–940 active ads** (counter changes between loads) and a large share are
dealers' *new* cars. Used cars are therefore a few hundred to ~700 → the 6,000 quota is filled by the
fallback source `tinbanxe.vn` (leader's decision) — see `docs/sources/tinbanxe.md`.

## Data-quality traps (why `unified.py` cross-checks)
| Trap | Evidence | Handling |
|---|---|---|
| Unfilled ads default to `Xe mới` / `Xăng` / `Số sàn`, year `No data` | Toyota Yaris 2010 tagged "Xe mới"; its description says "165.000km" and "số tự động" | year from the **title**; transmission: title token > description > field; mileage: card > detail > description |
| "Xe mới" cannot be trusted as the new/used flag | same ad | **used** = real mileage > 0, or year < current_year−1. Recent-year ad with no real mileage ⇒ new ⇒ dropped |
| Absurd mileage | `10,000,000 km` on a 2024 Everest | > 1,000,000 km ⇒ null |
| `Kiểu dáng` is a seller dropdown | Yaris tagged `Coupe` | kept as given; low reliability |

## Mapping
| Column | Source | Note |
|---|---|---|
| listing_id | ad id in URL | `CAR_<id>` |
| brand / model | detail `Hãng xe` / `Dòng xe` | brand falls back to 1st word of title |
| sub_model_trim, engine_capacity | title | engine is **inferred** (no field) |
| manufacture_year | title | |
| mileage_km, transmission, fuel_type | see traps | |
| origin, seats | not exposed → `Unknown` / null | |
| body_type | detail `Kiểu dáng` | unreliable |
| location_province | card | normalized by `schema.normalize_province` |
| seller_type | `Đăng bởi` matches salon/showroom/auto/… ⇒ Dealership/Salon, else `Unknown` | never guessed as Private |
| price_vnd / raw_price_text / price_status | card price | |
| listing_date | detail `Ngày đăng` | date only (00:00 UTC) |

## Listing source: the site's JSON API (found via DevTools)
`POST https://api.carmudi.vn/api/v1/get-car-page?limit=20&page=N`, body `{"data": "?page=N&last_page=41"}`;
ads in `data.data.data`, pages in `data.data.meta.last_page` (41). The HTML of `/xe-o-to/` ignores `?page=N`
(verified: `?page=41` returns the same 15 ads as page 1), so HTML paging cannot be used.

## UNVERIFIED — check on the first real run
1. API field names: only `id`, `name`, `slug`, `brandName` were seen; the others are looked up through candidate names (`CANDIDATES` in `crawl.py`). Run `--probe` and fix the lists if a column is empty.
2. Whether the API needs extra headers/cookies (Origin/Referer are sent) and whether `api.carmudi.vn` is covered by robots.txt/terms.
3. `robots.txt` was not read — run `python -m tools.recon https://www.carmudi.vn/` and record the result here.
4. `python -m src.sources.carmudi.tests.smoke` is an offline regression test based on reconstructed fixtures; it is not a live-site integration test. Run it after parser changes.
5. Review `robots.txt` and site terms before increasing crawl volume; the recon did not verify them.
