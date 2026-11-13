# The 25 worst val predictions — read one by one

This is the **hand pass** the plan asks for (§4.3, Tuấn Anh): `docs/error_taxonomy.md` groups the same
rows by rule, this file reads them. It is a reading of the fields the snapshot carries — a human should
spot-check the two rows marked **AMB** against the live ads before the report quotes them.

Source: `data/master/predictions_val.csv` (LightGBM `full`, tuned) joined to `data/master/val.csv` for
`price_status`, `quality_flags`, `origin`, `engine_capacity`.

## Five findings that survive the row-by-row read

1. **Every one of the 25 is one-sided**: `Δ = (ŷ − y)/y > 0` in 25/25 rows, i.e. the asking price is far
   **below** the model, never far above. The error tail is not symmetric noise; it is a single failure
   mode plus its variants.
2. **23 of 25 ask less than a quarter of the model's estimate** (`price/pred < 0.25`). Across the whole
   val split only **23 rows (0,15 %)** are that cheap, and **69,6 %** of them come from Chợ Tốt. The worst
   25 are essentially "the cheapest ads in the split".
3. **`price_status = "full"` on all 25.** The field that is supposed to flag negotiable / instalment
   prices does **not** flag deposit amounts, so the pipeline cannot filter these out with the column it
   already has.
4. **`engine_capacity` is missing on 24 of the 25** — the 61 %-missing column is absent exactly where the
   error is worst, so the model has the least information where it needs it most.
5. **A real duplicate is in the tail**: `TBX_88471` and `TBX_87885` are the same Isuzu MU-X 2018,
   1.000 km, 33.330.000 VND with the identical prediction. Cross-posting survives into val (different
   `listing_id`, different `duplicate_group_id`), so one ad is counted as two errors.

## Row by row

| # | Listing | Car | km | Asking | Model | APE | Reading |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `CHOTOT_131080054` | VinFast Limo Green 2026 | 6 | 42.000.000 | 598.216.230 | 13,2× | **DEP** + **KM** (6 km) |
| 2 | `CHOTOT_133327118` | VinFast Limo Green 2026 | 16 | 46.000.000 | 586.803.946 | 11,8× | **DEP** + **KM** (16 km) |
| 3 | `CHOTOT_135486257` | Mitsubishi Triton 2020 | 11.000 | 42.000.000 | 495.484.028 | 10,8× | **DEP** — a 2020 Triton at 42 M is a deposit, not a price |
| 4 | `CARPLA_F8W47` | Audi Q5 2024 | 7.000 | 218.000.000 | 2.157.689.143 | 8,9× | **AMB** — 218 M for a 2024 Q5 is ~10 % of market; check the ad |
| 5 | `OTO_23421590` | VinFast VF6 2025 | 39.000 | 60.000.000 | 588.139.516 | 8,8× | **DEP** |
| 6 | `CHOTOT_134734999` | Kia Cerato 2018 | 90.000 | 37.500.000 | 360.785.042 | 8,6× | **DEP** |
| 7 | `CHOTOT_135476379` | Mercedes GLK 2012 | 10 | 37.900.000 | 359.159.352 | 8,5× | **DEP** + **KM** (10 km), already flagged `low_mileage_older_car` |
| 8 | `OTO_23440745` | Toyota Hiace 2022 | 130.000 | 48.000.000 | 421.604.208 | 7,8× | **DEP** |
| 9 | `CHOTOT_135506467` | Ford Ranger 2017 | 128.000 | 49.500.000 | 415.623.903 | 7,4× | **DEP** |
| 10 | `CHOTOT_135232904` | VinFast Limo Green 2026 | 30.000 | 70.000.000 | 579.564.034 | 7,3× | **DEP** |
| 11 | `MUA_71300944` | Mitsubishi Jolie 2026 | 30.000 | 50.000.000 | 402.006.368 | 7,0× | **DEP** + **IMP** + **YR**: a Jolie was discontinued long before 2026 |
| 12 | `CHOTOT_135218306` | Hyundai Grand i10 2026 | 30.000 | 60.000.000 | 402.547.568 | 5,7× | **DEP** |
| 13 | `TBX_88592` | Toyota Yaris 2022 | 47.000 | 48.000.000 | 303.888.172 | 5,3× | **DEP** |
| 14 | `CHOTOT_135016208` | Mitsubishi Attrage 2025 | 30.000 | 45.000.000 | 280.397.163 | 5,2× | **DEP** + **IMP** |
| 15 | `CHOTOT_135132692` | Mitsubishi Xpander 2022 | 60.000 | 69.000.000 | 429.649.670 | 5,2× | **DEP** |
| 16 | `CHOTOT_134985717` | VinFast VF6 2026 | 30.000 | 100.000.000 | 563.539.053 | 4,6× | **DEP** + **IMP** |
| 17 | `CHOTOT_134989809` | Aion Y Plus 2024 | 999.998 | 200.000.000 | 1.096.472.989 | 4,5× | **DEP** + **KM** (odometer placeholder) |
| 18 | `MUA_71292173` | Toyota Yaris 2022 | 47.095 | 48.000.000 | 262.204.738 | 4,5× | **DEP** |
| 19 | `CHOTOT_135233245` | VinFast Limo Green 2026 | 20.000 | 80.000.000 | 420.603.730 | 4,3× | **DEP** |
| 20 | `BAN_6921476` | Porsche Panamera 2010 | 98.900 | 190.000.000 | 987.292.896 | 4,2× | **AMB** — the only row with `engine_capacity` (4.8); a 2010 Panamera at 190 M may be real |
| 21 | `CHOTOT_135565086` | VinFast VF3 2026 | 30.000 | 50.000.000 | 243.251.484 | 3,9× | **DEP** + **IMP** |
| 22 | `CHOTOT_135092629` | VinFast VF3 2026 | 1 | 60.000.000 | 274.743.815 | 3,6× | **DEP** + **KM** (1 km) |
| 23 | `CHOTOT_135098625` | Mitsubishi Xpander 2025 | 50.000 | 70.000.000 | 306.856.023 | 3,4× | **DEP** |
| 24 | `TBX_88471` | Isuzu MU-X 2018 | 1.000 | 33.330.000 | 127.330.138 | 2,8× | **DEP** + **KM** + **DUP** |
| 25 | `TBX_87885` | Isuzu MU-X 2018 | 1.000 | 33.330.000 | 127.330.138 | 2,8× | **DEP** + **KM** + **DUP** (same ad as #24) |

Legend — **DEP** deposit/placeholder price · **KM** placeholder odometer (≤ 100 km or ≥ 900.000 km) ·
**IMP** mileage imputed (`missing_mileage` flag, so `km_per_year` is invented) · **YR** impossible model
year · **DUP** duplicate ad · **AMB** ambiguous without the ad text.

Counts: DEP **24**, KM **6**, IMP **4**, YR **1**, DUP **1 pair**, AMB **2**.
By source: Chợ Tốt 16 · tinbanxe 3 · oto.com.vn 2 · muaban 2 · carpla 1 · bonbanh 1.

## What this means for the model, and what it does not

- The model is **not** wrong about the market price of a 2020 Triton; it is wrong about a 42 M ad for
  one. These rows are a **data** problem, so a MAPE that includes them measures the ad quality of the
  cheapest listings, not the valuation skill.
- Nothing here can be fixed by tuning. `price_status` would be the natural filter, but it says `"full"`
  on all 25, so the fix is upstream: a rule such as *"asking price below 25 % of the segment median ⇒
  flag `deposit_suspected`"* in `build_features` / `audit_master`, applied **before** the split, then
  excluded from the modelling table and reported separately.
- Two improvements that need no change to the frozen data:
  a) report MAPE / median APE **with and without** the `price < pred/4` rows (23 rows, 0,15 %) so §6
     shows both numbers instead of hiding the tail;
  b) count the duplicate pair (`TBX_88471` / `TBX_87885`) once when quoting the size of the tail.
- The `KM` placeholders argue for one more rule in `tools/audit_master`: `mileage_km ∈ {1, 999999…}` is a
  sentinel, not a measurement — `999.998 km` on a 2024 car is a filled-in form, not a used car.
