# Are the P10/P90 bands calibrated?

Source: `predictions_val.csv` (14,964 rows). Nominal coverage **80%**; a calibrated pair of quantile fits puts ≈10 % of the prices below P10 and ≈10 % above P90.

| Measure | Value |
| --- | ---: |
| inside the band | **81.70%** |
| price below P10 | 9.19% |
| price above P90 | 9.12% |
| median band width | 122,737,220 VND |
| median width / point estimate | 26.0% |
| median APE of the point estimate | 6.3% |

**Verdict: PASS** (tolerance ±5% around nominal).

## Coverage by platform

| Platform | Rows | Inside | Below P10 | Above P90 |
| --- | ---: | ---: | ---: | ---: |
| carmudi | 105 | 88.6% | 5.7% | 5.7% |
| vucar.vn | 309 | 85.4% | 3.9% | 10.7% |
| chotot | 2,874 | 83.0% | 9.5% | 7.6% |
| muaban.net | 1,044 | 82.7% | 9.6% | 7.8% |
| tinbanxe.vn | 1,124 | 82.4% | 10.5% | 7.1% |
| oto.com.vn | 4,369 | 81.6% | 8.5% | 9.9% |
| bonbanh | 4,529 | 80.6% | 9.8% | 9.6% |
| carpla | 610 | 78.2% | 8.5% | 13.3% |

## Reading

- Coverage below nominal means the band is too narrow: the P10 fit is too high and the P90 fit too low, so `Bargain` / `Overpriced` labels fire less often than the definition intends.
- Coverage above nominal means the opposite: the bands are wide and the labels are conservative.
- An asymmetry between `below` and `above` is the useful signal: too many prices above P90 means the upper quantile is under-fitted, which is what a plain squared-loss model does when the price distribution has a long right tail.
- The bands are fitted with 500-tree LightGBM quantile models and **are not tuned**; the numbers here are the reason to tune them, not proof that they are fine.
