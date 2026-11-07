# Error taxonomy — where the model is wrong, and how often

Source: `predictions_val.csv` (14,964 rows on the frozen val split). Buckets are assigned by the explicit rules in `tools/error_report.py::bucket`, so a reader can re-derive every count; this is a **rule-based first pass**, not a hand audit. The hand pass over these 25 rows is the next step for §6 of the report.

## The 25 worst rows

| # | listing | brand | model | year | km | asking (VND) | predicted (VND) | APE | bucket |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `CHOTOT_131080054` | VinFast | Limo Green | 2026 | 6 | 42,000,000 | 576,687,327 | 1273.1% | 1_under_200tr |
| 2 | `CHOTOT_133327118` | VinFast | Limo Green | 2026 | 16 | 46,000,000 | 576,138,493 | 1152.5% | 1_under_200tr |
| 3 | `CHOTOT_135486257` | Mitsubishi | Triton | 2020 | 11000 | 42,000,000 | 473,554,262 | 1027.5% | 1_under_200tr |
| 4 | `OTO_23440745` | Toyota | Hiace | 2022 | 130000 | 48,000,000 | 516,122,495 | 975.3% | 1_under_200tr |
| 5 | `CARPLA_F8W47` | Audi | Q5 | 2024 | 7000 | 218,000,000 | 2,141,083,539 | 882.1% | 3_import_or_salvage |
| 6 | `OTO_23421590` | VinFast | VF6 | 2025 | 39000 | 60,000,000 | 587,524,683 | 879.2% | 1_under_200tr |
| 7 | `CHOTOT_134734999` | Kia | Cerato | 2018 | 90000 | 37,500,000 | 357,240,331 | 852.6% | 1_under_200tr |
| 8 | `CHOTOT_135476379` | Mercedes-Benz | GLK-Class | 2012 | 10 | 37,900,000 | 351,311,131 | 826.9% | 1_under_200tr |
| 9 | `MUA_71300944` | Mitsubishi | Jolie | 2026 | 30000 | 50,000,000 | 428,907,377 | 757.8% | 1_under_200tr |
| 10 | `CHOTOT_135506467` | Ford | Ranger | 2017 | 128000 | 49,500,000 | 406,809,091 | 721.8% | 1_under_200tr |
| 11 | `CHOTOT_135232904` | VinFast | Limo Green | 2026 | 30000 | 70,000,000 | 570,795,315 | 715.4% | 1_under_200tr |
| 12 | `TBX_88592` | Toyota | Yaris | 2022 | 47000 | 48,000,000 | 365,808,827 | 662.1% | 1_under_200tr |
| 13 | `MUA_71292173` | Toyota | Yaris | 2022 | 47095 | 48,000,000 | 353,614,613 | 636.7% | 1_under_200tr |
| 14 | `CHOTOT_135016208` | Mitsubishi | Attrage | 2025 | 30000 | 45,000,000 | 312,668,433 | 594.8% | 1_under_200tr |
| 15 | `CHOTOT_135218306` | Hyundai | Grand i10 | 2026 | 30000 | 60,000,000 | 390,290,915 | 550.5% | 1_under_200tr |
| 16 | `CHOTOT_135132692` | Mitsubishi | Xpander | 2022 | 60000 | 69,000,000 | 426,107,227 | 517.5% | 1_under_200tr |
| 17 | `CHOTOT_134989809` | Aion | Y Plus | 2024 | 999998 | 200,000,000 | 1,211,693,660 | 505.8% | 2_odometer_outlier |
| 18 | `CHOTOT_134985717` | VinFast | VF6 | 2026 | 30000 | 100,000,000 | 575,659,258 | 475.7% | 1_under_200tr |
| 19 | `BAN_6921476` | Porsche | Panamera | 2010 | 98900 | 190,000,000 | 1,017,399,638 | 435.5% | 1_under_200tr |
| 20 | `CHOTOT_135565086` | VinFast | VF3 | 2026 | 30000 | 50,000,000 | 257,980,019 | 416.0% | 1_under_200tr |
| 21 | `CHOTOT_135233245` | VinFast | Limo Green | 2026 | 20000 | 80,000,000 | 367,783,829 | 359.7% | 1_under_200tr |
| 22 | `CHOTOT_134850430` | Mercedes-Benz | E Class | 2019 | 7039 | 156,000,000 | 707,015,334 | 353.2% | 1_under_200tr |
| 23 | `CHOTOT_135092629` | VinFast | VF3 | 2026 | 1 | 60,000,000 | 268,252,795 | 347.1% | 1_under_200tr |
| 24 | `TBX_87885` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 148,702,815 | 346.2% | 1_under_200tr |
| 25 | `TBX_88471` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 148,702,815 | 346.2% | 1_under_200tr |

## Buckets over the whole val split

| Bucket | Listings | median APE | mean Δ |
| --- | ---: | ---: | ---: |
| 1_under_200tr | 1,461 | 13.3% | +25.1% |
| 2_odometer_outlier | 118 | 10.0% | +2.8% |
| 3_import_or_salvage | 13,385 | 5.9% | -0.3% |

## Median APE by source (all val rows)

| Source | Listings | median APE | median asking price |
| --- | ---: | ---: | ---: |
| carmudi | 105 | 10.0% | 515,000,000 |
| chotot | 2,874 | 7.2% | 450,000,000 |
| muaban.net | 1,044 | 6.6% | 425,000,000 |
| tinbanxe.vn | 1,124 | 6.6% | 450,000,000 |
| carpla | 610 | 6.5% | 652,500,000 |
| bonbanh | 4,529 | 6.0% | 615,000,000 |
| oto.com.vn | 4,369 | 6.0% | 510,000,000 |
| vucar.vn | 309 | 5.0% | 590,000,000 |

## Median APE by price decile

| Decile | median APE |
| --- | ---: |
| (29999999.999, 200000000.0] | 13.2% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (200000000.0, 295000000.0] | 6.8% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (295000000.0, 380000000.0] | 5.6% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (380000000.0, 450000000.0] | 5.3% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (450000000.0, 520000000.0] | 5.5% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (520000000.0, 604800000.0] | 5.3% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (604800000.0, 735000000.0] | 5.4% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (735000000.0, 945000000.0] | 5.8% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (945000000.0, 1538000000.0] | 6.8% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (1538000000.0, 20200000000.0] | 7.2% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.
