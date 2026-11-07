# Error taxonomy — where the model is wrong, and how often

Source: `predictions_val.csv` (14,964 rows on the frozen val split). Buckets are assigned by the explicit rules in `tools/error_report.py::bucket`, so a reader can re-derive every count; this is a **rule-based first pass**, not a hand audit. The hand pass over these 25 rows is the next step for §6 of the report.

## The 25 worst rows

| # | listing | brand | model | year | km | asking (VND) | predicted (VND) | APE | bucket |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `CHOTOT_131080054` | VinFast | Limo Green | 2026 | 6 | 42,000,000 | 598,216,229 | 1324.3% | 1_under_200tr |
| 2 | `CHOTOT_133327118` | VinFast | Limo Green | 2026 | 16 | 46,000,000 | 586,803,945 | 1175.7% | 1_under_200tr |
| 3 | `CHOTOT_135486257` | Mitsubishi | Triton | 2020 | 11000 | 42,000,000 | 495,484,028 | 1079.7% | 1_under_200tr |
| 4 | `CARPLA_F8W47` | Audi | Q5 | 2024 | 7000 | 218,000,000 | 2,157,689,143 | 889.8% | 3_import_or_salvage |
| 5 | `OTO_23421590` | VinFast | VF6 | 2025 | 39000 | 60,000,000 | 588,139,515 | 880.2% | 1_under_200tr |
| 6 | `CHOTOT_134734999` | Kia | Cerato | 2018 | 90000 | 37,500,000 | 360,785,041 | 862.1% | 1_under_200tr |
| 7 | `CHOTOT_135476379` | Mercedes-Benz | GLK-Class | 2012 | 10 | 37,900,000 | 359,159,351 | 847.7% | 1_under_200tr |
| 8 | `OTO_23440745` | Toyota | Hiace | 2022 | 130000 | 48,000,000 | 421,604,208 | 778.3% | 1_under_200tr |
| 9 | `CHOTOT_135506467` | Ford | Ranger | 2017 | 128000 | 49,500,000 | 415,623,902 | 739.6% | 1_under_200tr |
| 10 | `CHOTOT_135232904` | VinFast | Limo Green | 2026 | 30000 | 70,000,000 | 579,564,034 | 727.9% | 1_under_200tr |
| 11 | `MUA_71300944` | Mitsubishi | Jolie | 2026 | 30000 | 50,000,000 | 402,006,368 | 704.0% | 1_under_200tr |
| 12 | `CHOTOT_135218306` | Hyundai | Grand i10 | 2026 | 30000 | 60,000,000 | 402,547,568 | 570.9% | 1_under_200tr |
| 13 | `TBX_88592` | Toyota | Yaris | 2022 | 47000 | 48,000,000 | 303,888,171 | 533.1% | 1_under_200tr |
| 14 | `CHOTOT_135016208` | Mitsubishi | Attrage | 2025 | 30000 | 45,000,000 | 280,397,162 | 523.1% | 1_under_200tr |
| 15 | `CHOTOT_135132692` | Mitsubishi | Xpander | 2022 | 60000 | 69,000,000 | 429,649,670 | 522.7% | 1_under_200tr |
| 16 | `CHOTOT_134985717` | VinFast | VF6 | 2026 | 30000 | 100,000,000 | 563,539,052 | 463.5% | 1_under_200tr |
| 17 | `CHOTOT_134989809` | Aion | Y Plus | 2024 | 999998 | 200,000,000 | 1,096,472,989 | 448.2% | 2_odometer_outlier |
| 18 | `MUA_71292173` | Toyota | Yaris | 2022 | 47095 | 48,000,000 | 262,204,738 | 446.3% | 1_under_200tr |
| 19 | `CHOTOT_135233245` | VinFast | Limo Green | 2026 | 20000 | 80,000,000 | 420,603,729 | 425.8% | 1_under_200tr |
| 20 | `BAN_6921476` | Porsche | Panamera | 2010 | 98900 | 190,000,000 | 987,292,895 | 419.6% | 1_under_200tr |
| 21 | `CHOTOT_135565086` | VinFast | VF3 | 2026 | 30000 | 50,000,000 | 243,251,483 | 386.5% | 1_under_200tr |
| 22 | `CHOTOT_135092629` | VinFast | VF3 | 2026 | 1 | 60,000,000 | 274,743,814 | 357.9% | 1_under_200tr |
| 23 | `CHOTOT_135098625` | Mitsubishi | Xpander | 2025 | 50000 | 70,000,000 | 306,856,023 | 338.4% | 1_under_200tr |
| 24 | `TBX_88471` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 127,330,137 | 282.0% | 1_under_200tr |
| 25 | `TBX_87885` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 127,330,137 | 282.0% | 1_under_200tr |

## Buckets over the whole val split

| Bucket | Listings | median APE | mean Δ |
| --- | ---: | ---: | ---: |
| 1_under_200tr | 1,461 | 13.2% | +23.6% |
| 2_odometer_outlier | 118 | 11.4% | +1.5% |
| 3_import_or_salvage | 13,385 | 5.7% | -0.3% |

## Median APE by source (all val rows)

| Source | Listings | median APE | median asking price |
| --- | ---: | ---: | ---: |
| carmudi | 105 | 9.5% | 515,000,000 |
| chotot | 2,874 | 7.3% | 450,000,000 |
| muaban.net | 1,044 | 6.5% | 425,000,000 |
| tinbanxe.vn | 1,124 | 6.3% | 450,000,000 |
| carpla | 610 | 6.2% | 652,500,000 |
| oto.com.vn | 4,369 | 5.9% | 510,000,000 |
| bonbanh | 4,529 | 5.6% | 615,000,000 |
| vucar.vn | 309 | 4.7% | 590,000,000 |

## Median APE by price decile

| Decile | median APE |
| --- | ---: |
| (29999999.999, 200000000.0] | 12.8% |
| (200000000.0, 295000000.0] | 6.9% |
| (295000000.0, 380000000.0] | 5.4% |
| (380000000.0, 450000000.0] | 5.1% |
| (450000000.0, 520000000.0] | 5.0% |
| (520000000.0, 604800000.0] | 5.1% |
| (604800000.0, 735000000.0] | 5.0% |
| (735000000.0, 945000000.0] | 5.7% |
| (945000000.0, 1538000000.0] | 6.7% |
| (1538000000.0, 20200000000.0] | 7.1% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
