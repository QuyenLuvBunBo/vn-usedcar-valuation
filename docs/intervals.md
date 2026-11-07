# Are the P10/P90 bands calibrated?

Source: `predictions_val.csv` (14,964 rows). Nominal coverage **80%**; a calibrated pair of quantile fits puts ≈10 % of the prices below P10 and ≈10 % above P90.

| Measure | Value |
| --- | ---: |
| inside the band | **71.91%** |
| price below P10 | 13.69% |
| price above P90 | 14.40% |
| median band width | 99,482,588 VND |
| median width / point estimate | 21.7% |
| median APE of the point estimate | 6.2% |

**Verdict: MISALIBRATED** (tolerance ±5% around nominal).

## Coverage by platform

| Platform | Rows | Inside | Below P10 | Above P90 |
| --- | ---: | ---: | ---: | ---: |
| carmudi | 105 | 82.9% | 8.6% | 8.6% |
| muaban.net | 1,044 | 74.4% | 14.0% | 11.6% |
| chotot | 2,874 | 73.6% | 13.7% | 12.7% |
| oto.com.vn | 4,369 | 73.1% | 11.8% | 15.1% |
| vucar.vn | 309 | 72.2% | 8.4% | 19.4% |
| tinbanxe.vn | 1,124 | 72.2% | 15.6% | 12.3% |
| bonbanh | 4,529 | 69.2% | 15.7% | 15.0% |
| carpla | 610 | 68.0% | 11.8% | 20.2% |

## Reading

- Coverage below nominal means the band is too narrow: the P10 fit is too high and the P90 fit too low, so `Bargain` / `Overpriced` labels fire less often than the definition intends.
- Coverage above nominal means the opposite: the bands are wide and the labels are conservative.
- An asymmetry between `below` and `above` is the useful signal: too many prices above P90 means the upper quantile is under-fitted, which is what a plain squared-loss model does when the price distribution has a long right tail.
- The bands are fitted with 500-tree LightGBM quantile models and **are not tuned**; the numbers here are the reason to tune them, not proof that they are fine.
