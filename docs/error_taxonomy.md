# Error taxonomy — where the model is wrong, and how often

Source: `predictions_val.csv` (14,964 rows on the frozen val split). Buckets are assigned by the explicit rules in `tools/error_report.py::bucket`, so a reader can re-derive every count; this is a **rule-based first pass**, not a hand audit. The hand pass over these 25 rows is the next step for §6 of the report.

## The 25 worst rows

| # | listing | brand | model | year | km | asking (VND) | predicted (VND) | APE | bucket |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `CHOTOT_131080054` | VinFast | Limo Green | 2026 | 6 | 42,000,000 | 570,329,847 | 1257.9% | 1_under_200tr |
| 2 | `CHOTOT_133327118` | VinFast | Limo Green | 2026 | 16 | 46,000,000 | 564,985,613 | 1128.2% | 1_under_200tr |
| 3 | `CHOTOT_135486257` | Mitsubishi | Triton | 2020 | 11000 | 42,000,000 | 487,054,841 | 1059.7% | 1_under_200tr |
| 4 | `CHOTOT_134734999` | Kia | Cerato | 2018 | 90000 | 37,500,000 | 373,862,034 | 897.0% | 1_under_200tr |
| 5 | `OTO_23421590` | VinFast | VF6 | 2025 | 39000 | 60,000,000 | 592,912,222 | 888.2% | 1_under_200tr |
| 6 | `CARPLA_F8W47` | Audi | Q5 | 2024 | 7000 | 218,000,000 | 2,089,824,773 | 858.6% | 3_import_or_salvage |
| 7 | `CHOTOT_135476379` | Mercedes-Benz | GLK-Class | 2012 | 10 | 37,900,000 | 347,929,111 | 818.0% | 1_under_200tr |
| 8 | `OTO_23440745` | Toyota | Hiace | 2022 | 130000 | 48,000,000 | 405,099,323 | 744.0% | 1_under_200tr |
| 9 | `TBX_88592` | Toyota | Yaris | 2022 | 47000 | 48,000,000 | 398,255,223 | 729.7% | 1_under_200tr |
| 10 | `CHOTOT_135506467` | Ford | Ranger | 2017 | 128000 | 49,500,000 | 405,648,655 | 719.5% | 1_under_200tr |
| 11 | `CHOTOT_135232904` | VinFast | Limo Green | 2026 | 30000 | 70,000,000 | 568,538,825 | 712.2% | 1_under_200tr |
| 12 | `MUA_71292173` | Toyota | Yaris | 2022 | 47095 | 48,000,000 | 367,031,512 | 664.6% | 1_under_200tr |
| 13 | `CHOTOT_135016208` | Mitsubishi | Attrage | 2025 | 30000 | 45,000,000 | 315,245,614 | 600.5% | 1_under_200tr |
| 14 | `MUA_71300944` | Mitsubishi | Jolie | 2026 | 30000 | 50,000,000 | 342,723,898 | 585.4% | 1_under_200tr |
| 15 | `CHOTOT_135218306` | Hyundai | Grand i10 | 2026 | 30000 | 60,000,000 | 399,023,926 | 565.0% | 1_under_200tr |
| 16 | `CHOTOT_135132692` | Mitsubishi | Xpander | 2022 | 60000 | 69,000,000 | 432,588,199 | 526.9% | 1_under_200tr |
| 17 | `CHOTOT_134989809` | Aion | Y Plus | 2024 | 999998 | 200,000,000 | 1,204,486,664 | 502.2% | 2_odometer_outlier |
| 18 | `CHOTOT_134985717` | VinFast | VF6 | 2026 | 30000 | 100,000,000 | 562,311,280 | 462.3% | 1_under_200tr |
| 19 | `CHOTOT_135098625` | Mitsubishi | Xpander | 2025 | 50000 | 70,000,000 | 367,719,056 | 425.3% | 1_under_200tr |
| 20 | `TBX_88471` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 174,545,223 | 423.7% | 1_under_200tr |
| 21 | `TBX_87885` | Isuzu | MU-X | 2018 | 1000 | 33,330,000 | 174,545,223 | 423.7% | 1_under_200tr |
| 22 | `CHOTOT_134850430` | Mercedes-Benz | E Class | 2019 | 7039 | 156,000,000 | 808,684,102 | 418.4% | 1_under_200tr |
| 23 | `CHOTOT_135565086` | VinFast | VF3 | 2026 | 30000 | 50,000,000 | 250,992,645 | 402.0% | 1_under_200tr |
| 24 | `CHOTOT_135275189` | Hyundai | Stargazer | 2024 | 80000 | 50,000,000 | 236,859,309 | 373.7% | 1_under_200tr |
| 25 | `CHOTOT_135092629` | VinFast | VF3 | 2026 | 1 | 60,000,000 | 280,597,177 | 367.7% | 1_under_200tr |

## Buckets over the whole val split

| Bucket | Listings | median APE | mean Δ |
| --- | ---: | ---: | ---: |
| 1_under_200tr | 1,461 | 13.8% | +25.6% |
| 2_odometer_outlier | 118 | 7.8% | +0.8% |
| 3_import_or_salvage | 13,385 | 6.0% | -0.2% |

## Median APE by source (all val rows)

| Source | Listings | median APE | median asking price |
| --- | ---: | ---: | ---: |
| carmudi | 105 | 8.7% | 515,000,000 |
| chotot | 2,874 | 7.4% | 450,000,000 |
| muaban.net | 1,044 | 7.2% | 425,000,000 |
| carpla | 610 | 6.5% | 652,500,000 |
| tinbanxe.vn | 1,124 | 6.4% | 450,000,000 |
| bonbanh | 4,529 | 6.1% | 615,000,000 |
| oto.com.vn | 4,369 | 6.0% | 510,000,000 |
| vucar.vn | 309 | 4.8% | 590,000,000 |

## Median APE by price decile

| Decile | median APE |
| --- | ---: |
| (29999999.999, 200000000.0] | 13.8% |
| (200000000.0, 295000000.0] | 6.8% |
| (295000000.0, 380000000.0] | 5.7% |
| (380000000.0, 450000000.0] | 5.5% |
| (450000000.0, 520000000.0] | 5.4% |
| (520000000.0, 604800000.0] | 5.3% |
| (604800000.0, 735000000.0] | 5.2% |
| (735000000.0, 945000000.0] | 6.0% |
| (945000000.0, 1538000000.0] | 7.3% |
| (1538000000.0, 20200000000.0] | 7.5% |

Reading: the error is not uniform. Cheap listings and extreme odometer values carry the largest percentage error, which is why §6 must report error by segment rather than one MAPE.
