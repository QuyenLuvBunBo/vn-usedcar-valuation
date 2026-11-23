# Recon — are the v1 links alive, and do the live pages carry the missing fields?

Generated 2026-11-14T06:30:41+00:00 by `python -m tools.recon_detail_fields` (sample 80 per platform, seed 42). Rows were drawn from the frozen cohort, from listings that are **missing at least one** of the four fields.

## (a) Link health

| Platform | Sampled | Alive | alive % | 404 | removed page | redirect | error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| chotot | 80 | 0 | 0.0% | 0 | 68 | 0 | 12 |
| bonbanh | 80 | 80 | 100.0% | 0 | 0 | 0 | 0 |

## (b) Field presence among the live pages

| Platform | Alive pages | engine_capacity | sub_model_trim | seller_type | body_type |
| --- | ---: | ---: | ---: | ---: | ---: |
| chotot | 0 | — | — | — | — |
| bonbanh | 80 | 81.2% | 100.0% | 100.0% | 98.8% |

## Reading it

- A field counts as present only if the page shows the **label and a value** — a page that merely mentions "SUV" in an unrelated block is not counted for `body_type`.
- `dead_removed` means the server answered 200 but the page says the listing is gone: counting only HTTP 404 would overstate the alive rate.
- `bonbanh` answers on `www.bonbanh.com`; the apex host timed out during preparation, so a `dead_error` there may be a host problem rather than a dead ad.
- **No crawl is started from this report.** A platform is worth a full re-crawl only if the alive rate and the field rates are both high enough to justify the requests.
