# EDA summary — merged dataset

Source: `data/master/master_clean_dataset.csv`, **100,887 merged listings**. The price window **10,000,000 – 50,000,000,000 VND** keeps **100,803** rows and drops **84** (0.08%) that are placeholders, deposits or typos — the raw maximum is 465 trillion VND (`log1p` 33.8). Figures live in `docs/figures/`.

Province names are canonicalised before counting (case- and diacritic-insensitive folding plus an explicit alias table), so `TP HCM` / `TP.HCM` fold into `TP. Hồ Chí Minh` and `Đăk Lăk` / `Đắk Lăk` become one province. Without that step the largest market is split in two and every regional number is wrong.

## Volume and price by platform

| Platform | Listings | Median price (VND) | IQR P25–P75 (VND) | Median per 1000 km (VND) |
| --- | ---: | ---: | ---: | ---: |
| bonbanh | 30,368 | 600,000,000 | 380,000,000 – 1,090,000,000 | 14,500,000 |
| oto.com.vn | 29,559 | 508,000,000 | 345,000,000 – 780,000,000 | 10,111,111 |
| chotot | 19,389 | 450,000,000 | 275,000,000 – 667,000,000 | 7,800,000 |
| tinbanxe.vn | 7,643 | 445,000,000 | 285,000,000 – 660,000,000 | 7,106,382 |
| muaban.net | 6,995 | 420,000,000 | 260,000,000 – 622,500,000 | 7,115,384 |
| carpla | 4,179 | 645,000,000 | 510,000,000 – 865,000,000 | 13,720,000 |
| vucar.vn | 2,124 | 620,000,000 | 478,750,000 – 905,000,000 | 12,845,490 |
| carmudi | 546 | 562,500,000 | 360,000,000 – 1,263,500,000 | 11,667,741 |

Chợ Tốt alone contributes **19,389** listings inside the window — 19,426 before the price filter (19.2% of the window). Among platforms with at least 500 listings the median asking price runs from **420,000,000** (muaban.net) to **645,000,000** (carpla) — a factor of 1.54. §6 therefore reports error per platform instead of quoting a single MAPE.

## Median price by province (top 12 by volume)

| Province | Listings | Median price (billion VND) |
| --- | ---: | ---: |
| TP. Hồ Chí Minh | 38,271 | 0.569 |
| Hà Nội | 33,079 | 0.610 |
| Bình Dương | 4,171 | 0.395 |
| Đà Nẵng | 2,875 | 0.399 |
| Cần Thơ | 2,430 | 0.450 |
| Đồng Nai | 2,253 | 0.355 |
| Đắk Lắk | 2,105 | 0.365 |
| Hải Phòng | 1,546 | 0.466 |
| Lâm Đồng | 970 | 0.428 |
| Gia Lai | 766 | 0.380 |
| Nghệ An | 735 | 0.410 |
| Tây Ninh | 654 | 0.465 |

The top two provinces carry **71,350** of 100,803 listings (71%); across the top 12 the median price differs by **1.7×** between the cheapest and the dearest market.

## Segment (body type)

| Segment | Listings | Median price (VND) | Median per 1000 km (VND) |
| --- | ---: | ---: | ---: |
| SUV | 28,788 | 715,000,000 | 15,909,090 |
| Sedan | 22,124 | 425,000,000 | 8,181,818 |
| Unknown | 18,345 | 450,000,000 | 8,670,068 |
| Hatchback | 7,198 | 265,000,000 | 4,552,238 |
| Pickup | 6,109 | 545,000,000 | 7,937,500 |
| MPV | 6,057 | 489,000,000 | 7,788,461 |
| Crossover | 4,017 | 568,000,000 | 14,406,896 |
| Van | 3,936 | 485,000,000 | 7,064,516 |
| Other | 2,744 | 799,000,000 | 21,435,092 |
| Coupe | 942 | 934,500,000 | 42,720,000 |
| Convertible | 259 | 2,299,000,000 | 124,500,000 |
| Truck | 223 | 338,000,000 | 5,208,333 |
| Sports | 36 | 2,989,000,000 | 113,004,511 |
| Minibus | 15 | 785,000,000 | 19,800,000 |
| Wagon | 10 | 834,500,000 | 63,960,000 |

`body_type` is unknown for **18.2%** of the window — a data limitation, not a modelling choice: a fifth of the market cannot be assigned to a segment at all.

## Median price by model year

The table and figure 4 cover **2010–2026**, which is 93,615 listings. 7,175 listings are older stock (1980–2009) and sit outside that window; 4 rows carry a manufacture year that cannot be real (1025, 2028, 2030, 2032), and 9 rows have no manufacture year at all — both are excluded from this table and from figure 4.

| Year | Median price (VND) |
| ---: | ---: |
| 2010 | 225,000,000 |
| 2011 | 220,000,000 |
| 2012 | 250,000,000 |
| 2013 | 310,000,000 |
| 2014 | 330,000,000 |
| 2015 | 349,000,000 |
| 2016 | 385,000,000 |
| 2017 | 415,000,000 |
| 2018 | 430,000,000 |
| 2019 | 480,000,000 |
| 2020 | 555,000,000 |
| 2021 | 590,000,000 |
| 2022 | 610,000,000 |
| 2023 | 669,000,000 |
| 2024 | 640,000,000 |
| 2025 | 699,000,000 |
| 2026 | 676,000,000 |

## Reading

- Price is right-skewed even inside the window, which is why every model fits `log1p(price_vnd)` and why R²(VND) always looks better than R²(log).
- Platform medians differ by the factor measured above and regional medians by the ratio measured above. Both are real signal, and both are reasons to break error down by segment.
- Price per 1000 km separates the segments **more** than absolute price does (×9.4 against ×3.5 across
  the ten segments with at least 900 listings), and the two rankings happen to share their endpoints
  (Hatchback cheapest, Coupe dearest). Mileage therefore does not "normalise" a segment away, and
  mileage on its own is still a weak pricing signal — the feature ablation in §4 agrees: dropping
  `mileage_km` and `km_per_year` costs ΔR² = 0.0001.
- Figures: `fig1_price_distribution.png`, `fig2_price_by_source.png`, `fig3_price_by_province.png`, `fig4_price_by_year.png`, `fig5_price_per_km_by_segment.png`.
