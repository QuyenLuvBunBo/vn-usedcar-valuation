# Live blind test — listings the bundle has never seen

Generated 2026-11-15T19:41:38+00:00 by `python -m tools.live_blind_test` against `F:\Code\IntroDS\models\v2` (built 2026-11-15T01:37:53+00:00, git `988321c`). The records are hand-written and belong to no split; the full record, band, warnings and trace are in `data/master/live_blind_test_v2.json`.

| Case | Listing | Point (VND) | P10-P90 | Warnings | trim_rank | engine from badge |
| --- | --- | ---: | --- | --- | --- | --- |
| case-1 | Mazda CX-5 2.0L Luxury \| 2022 \| 32,000 km \| Ha Noi | 696,574,334 | 649,212,201 .. 728,807,095 | none | top | False |
| case-2a | Hyundai Accent 1.4 AT Dac biet \| 2021 \| 45,000 km \| Ha Noi | 406,608,289 | 374,036,304 .. 434,583,098 | none | top | False |
| case-2b | Hyundai Accent 1.4 MT Tieu chuan \| 2021 \| 45,000 km \| Ha Noi | 314,042,802 | 259,147,117 .. 354,236,896 | none | base | False |
| case-3 | Toyota Corolla Cross 1.8HV \| 2023 \| 18,000 km \| Ha Noi (no engine/body/seats/origin/seller) | 781,060,185 | 705,990,656 .. 814,298,340 | none | unknown | True |
| case-4 | Mercedes-Benz GLC 300 4MATIC \| 2020 \| 50,000 km \| TP.HCM | 1,222,686,291 | 922,251,224 .. 1,386,993,427 | none | unknown | False |
| case-4b | Mercedes-Benz GLC 300 4Matic \| 2020 \| 50,000 km \| TP.HCM | 1,222,686,291 | 922,251,224 .. 1,386,993,427 | none | unknown | False |
| case-5 | Chery Tiggo 7 Pro 1.5T \| 2023 \| 20,000 km \| Ha Noi | 494,907,861 | 426,911,784 .. 743,635,633 | unseen_brand_model | top | False |
| case-6 | Kia Seltos 1.4 Luxury \| 2021 \| 50 km \| asking 120,000,000 VND \| Ha Noi | 505,480,411 | 452,852,883 .. 544,909,977 | placeholder_odometer, deposit_suspect | top | False |

## Paired comparisons

| Pair | Left | Right | Delta | Ratio |
| --- | ---: | ---: | ---: | ---: |
| top vs base trim, same car | 406,608,289 | 314,042,802 | 92,565,487 | 1.295 |
| model casing: 4MATIC vs 4Matic | 1,222,686,291 | 1,222,686,291 | 0 | 1.000 |

## What the run establishes

- Every expected warning fired: `unseen_brand_model` on the unseen nameplate, `placeholder_odometer` + `deposit_suspect` on the deposit-shaped ad.
- `trace.imputed` lists the five fields the blank Corolla Cross record left out, and `engine_parsed` is true because `1.8HV` carried the displacement.
- The band is narrow for nameplates with training rows and visibly wider for the unseen one — the uncertainty is reported, not hidden.
- Case 4 (`4MATIC`) and case 4b (`4Matic`) return the same price and raise no false `unseen_brand_model`: the bundle lookup is case/whitespace-insensitive.
- The 50 km odometer in case 6 is treated as missing, imputed from the age-band median, and `mileage_km` appears in `trace.imputed` — matching the warning text.

## What this page is not

- Not a benchmark: eight records cannot estimate an error rate. `tools/readiness_check` measures the bundle on the 14,964-row val split.
- The plausibility windows are hand-set market sanity bounds, not ground truth; a WARN means "check this", not "wrong".
