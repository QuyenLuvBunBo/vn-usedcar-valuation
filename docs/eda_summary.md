# EDA summary — merged dataset

100,803 listings with a usable asking price (10 million – 50 billion VND), from `master_clean_dataset.csv`. Figures are in `docs/figures/`.

## Volume by source

| Source | Listings | Median price (VND) |
| --- | ---: | ---: |
| bonbanh | 30,368 | 600,000,000 |
| oto.com.vn | 29,559 | 508,000,000 |
| chotot | 19,389 | 450,000,000 |
| tinbanxe.vn | 7,643 | 445,000,000 |
| muaban.net | 6,995 | 420,000,000 |
| carpla | 4,179 | 645,000,000 |
| vucar.vn | 2,124 | 620,000,000 |
| carmudi | 546 | 562,500,000 |

The largest platform carries **30,368** listings (30% of the table); the long tail of smaller platforms is what makes a cross-platform price index possible at all.

## Price by region (top 12 by volume)

| Province | Listings | Median price (VND) |
| --- | ---: | ---: |
| TP. Hồ Chí Minh | 37,161 | 570,000,000 |
| Hà Nội | 33,079 | 610,000,000 |
| Bình Dương | 4,171 | 395,000,000 |
| Đà Nẵng | 2,875 | 399,000,000 |
| Cần Thơ | 2,430 | 450,000,000 |
| Đồng Nai | 2,253 | 355,000,000 |
| Hải Phòng | 1,546 | 466,500,000 |
| Đắk Lắk | 1,382 | 350,000,000 |
| TP HCM | 1,110 | 435,000,000 |
| Lâm Đồng | 970 | 428,500,000 |
| Gia Lai | 766 | 379,500,000 |
| Nghệ An | 735 | 410,000,000 |

## Median price by model year

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
| 2028 | 368,000,000 |
| 2030 | 1,839,000,000 |
| 2032 | 315,000,000 |

## Reading

- Price is right-skewed even after the sanity filter, which is why every model fits `log1p(price_vnd)` and why R²(VND) always looks better than R²(log).
- Regional medians differ by more than a factor of two across the top 12 provinces, so `location_province` (grouped into `province_group`) is a real feature, not noise.
- Volume is concentrated on one platform, so a per-platform error breakdown in §6 is mandatory: a single MAPE would hide the smaller platforms.
- Figures: `fig1_price_distribution.png`, `fig2_price_by_province.png`, `fig3_listings_by_source.png`, `fig4_price_by_year.png`, `fig5_price_per_km_by_tier.png`.
