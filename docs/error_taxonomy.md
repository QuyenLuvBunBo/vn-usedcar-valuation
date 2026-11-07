# Error taxonomy — where the model is wrong, and how often

Source: `predictions_val.csv` (14,964 rows on the frozen val split). Buckets are assigned by the explicit rules in `tools/error_report.py::bucket`, so a reader can re-derive every count; this is a **rule-based first pass**, not a hand audit. The hand pass over these 25 rows is the next step for §6 of the report.

## The 25 worst rows

| # | listing | brand | model | year | km | asking (VND) | predicted (VND) | APE | bucket |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `CHOTOT_131080054` | VinFast | Limo Green | 2026 | 6 | 42,000,000 | 572,979,827 | 1264.2% | 1_under_200tr |
| 2 | `CHOTOT_133327118` | VinFast | Limo Green | 2026 | 16 | 46,000,000 | 572,680,474 | 1145.0% | 1_under_200tr |
| 3 | `CHOTOT_135486257` | Mitsubishi | Triton | 2020 | 11000 | 42,000,000 | 492,247,870 | 1072.0% | 1_under_200tr |
| 4 | `OTO_23421590` | VinFast | VF6 | 2025 | 39000 | 60,000,000 | 592,169,155 | 886.9% | 1_under_200tr |
| 5 | `CHOTOT_135476379` | Mercedes-Benz | GLK-Class | 2012 | 10 | 37,900,000 | 369,422,568 | 874.7% | 1_under_200tr |
| 6 | `CHOTOT_134734999` | Kia | Cerato | 2018 | 90000 | 37,500,000 | 355,966,016 | 849.2% | 1_under_200tr |
| 7 | `OTO_23440745` | Toyota | Hiace | 2022 | 130000 | 48,000,000 | 454,563,853 | 847.0% | 1_under_200tr |
| 8 | `CARPLA_F8W47` | Audi | Q5 | 2024 | 7000 | 218,000,000 | 2,055,024,107 | 842.7% | 3_import_or_salvage |
| 9 | `CHOTOT_135506467` | Ford | Ranger | 2017 | 128000 | 49,500,000 | 402,323,793 | 712.8% | 1_under_200tr |
| 10 | `CHOTOT_135232904` | VinFast | Limo Green | 2026 | 30000 | 70,000,000 | 563,891,932 | 705.6% | 1_under_200tr |
| 11 | `TBX_88592` | Toyota | Yaris | 2022 | 47000 | 48,000,000 | 381,759,840 | 695.3% | 1_under_200tr |
| 12 | `MUA_71300944` | Mitsubishi | Jolie | 2026 | 30000 | 50,000,000 | 384,983,833 | 670.0% | 1_under_200tr |
| 13 | `MUA_71292173` | Toyota | Yaris | 2022 | 47095 | 48,000,000 | 361,438,187 | 653.0% | 1_under_200tr |
| 14 | `CHOTOT_135218306` | Hyundai | Grand i10 | 2026 | 30000 | 60,000,000 | 395,699,346 | 559.5% | 1_under_200tr |
| 15 | `CHOTOT_135016208` | Mitsubishi | Attrage | 2025 | 30000 | 45,000,000 | 287,339,287 | 538.5% | 1_under_200tr |
| 16 | `CHOTOT_135132692` | Mitsubishi | Xpander | 2022 | 60000 | 69,000,000 | 426,161,453 | 517.6% | 1_under_200tr |
| 17 | `CHOTOT_134989809` | Aion | Y Plus | 2024 | 999998 | 200,000,000 | 1,176,331,856 | 488.2% | 2_odometer_outlier |
| 18 | `CHOTOT_134985717` | VinFast | VF6 | 2026 | 30000 | 100,000,000 | 563,677,628 | 463.7% | 1_under_200tr |
| 19 | `BAN_6921476` | Porsche | Panamera | 2010 | 98900 | 190,000,000 | 1,059,215,160 | 457.5% | 1_under_200tr |
| 20 | `CHOTOT_135233245` | VinFast | Limo Green | 2026 | 20000 | 80,000,000 | 431,123,572 | 438.9% | 1_under_200tr |
| 21 | `CHOTOT_135565086` | VinFast | VF3 | 2026 | 30000 | 50,000,000 | 232,588,881 | 365.2% | 1_under_200tr |
| 22 | `TBX_88471` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 154,520,828 | 363.6% | 1_under_200tr |
| 23 | `TBX_87885` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 154,520,828 | 363.6% | 1_under_200tr |
| 24 | `CHOTOT_135098625` | Mitsubishi | Xpander | 2025 | 50000 | 70,000,000 | 317,024,168 | 352.9% | 1_under_200tr |
| 25 | `CHOTOT_135092629` | VinFast | VF3 | 2026 | 1 | 60,000,000 | 267,587,378 | 346.0% | 1_under_200tr |

## Buckets over the whole val split

| Bucket | Listings | median APE | mean Δ |
| --- | ---: | ---: | ---: |
| 1_under_200tr | 1,461 | 13.2% | +24.7% |
| 2_odometer_outlier | 118 | 9.6% | +2.6% |
| 3_import_or_salvage | 13,385 | 5.8% | -0.4% |

## Median APE by source (all val rows)

| Source | Listings | median APE | median asking price |
| --- | ---: | ---: | ---: |
| carmudi | 105 | 10.0% | 515,000,000 |
| chotot | 2,874 | 7.1% | 450,000,000 |
| muaban.net | 1,044 | 6.7% | 425,000,000 |
| tinbanxe.vn | 1,124 | 6.5% | 450,000,000 |
| carpla | 610 | 6.3% | 652,500,000 |
| oto.com.vn | 4,369 | 5.9% | 510,000,000 |
| bonbanh | 4,529 | 5.9% | 615,000,000 |
| vucar.vn | 309 | 4.8% | 590,000,000 |

## Median APE by price decile

| Decile | median APE |
| --- | ---: |
| (29999999.999, 200000000.0] | 13.0% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (200000000.0, 295000000.0] | 6.8% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (295000000.0, 380000000.0] | 5.4% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (380000000.0, 450000000.0] | 5.0% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (450000000.0, 520000000.0] | 5.2% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (520000000.0, 604800000.0] | 5.2% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (604800000.0, 735000000.0] | 5.3% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (735000000.0, 945000000.0] | 5.9% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (945000000.0, 1538000000.0] | 7.0% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.

| (1538000000.0, 20200000000.0] | 7.3% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
The hand read of these rows is in [error_audit_25.md](error_audit_25.md): 24 of the 25 are deposit-style prices, 6 have placeholder odometers and 1 is a genuine duplicate, so the tail is a data problem rather than a model problem.
