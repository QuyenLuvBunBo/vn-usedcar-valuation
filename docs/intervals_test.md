# Are the P10/P90 bands calibrated?

Source: `predictions_test.csv` (14,980 rows). Nominal coverage **80%**; a calibrated pair of quantile fits puts ≈10 % of the prices below P10 and ≈10 % above P90.

| Measure | Value |
| --- | ---: |
| inside the band | **81.91%** |
| price below P10 | 8.62% |
| price above P90 | 9.47% |
| median band width | 121,004,494 VND |
| median width / point estimate | 25.8% |
| median APE of the point estimate | 6.1% |
| point estimate outside its own band | 1.78% (267 rows) |

**Verdict: PASS** (tolerance ±5% around nominal).

## Coverage by platform

| Platform | Rows | Inside | Below P10 | Above P90 |
| --- | ---: | ---: | ---: | ---: |
| muaban.net | 1,014 | 84.8% | 8.9% | 6.3% |
| chotot | 2,853 | 83.9% | 8.3% | 7.8% |
| tinbanxe.vn | 1,147 | 83.3% | 8.9% | 7.8% |
| oto.com.vn | 4,415 | 82.5% | 8.2% | 9.3% |
| bonbanh | 4,586 | 80.0% | 9.1% | 10.9% |
| vucar.vn | 300 | 79.3% | 8.0% | 12.7% |
| carpla | 590 | 77.1% | 9.2% | 13.7% |
| carmudi | 75 | 74.7% | 6.7% | 18.7% |

## Reading

- Coverage below nominal means the band is too narrow: the P10 fit is too high and the P90 fit too low, so `Bargain` / `Overpriced` labels fire less often than the definition intends.
- Coverage above nominal means the opposite: the bands are wide and the labels are conservative.
- An asymmetry between `below` and `above` is the useful signal: too many prices above P90 means the upper quantile is under-fitted, which is what a plain squared-loss model does when the price distribution has a long right tail.
- `point estimate outside its own band` is **not** a defect and not a rounding artefact: the point forecast comes from the mean model while P10/P90 come from separate quantile models fitted on the same rows, so nothing forces the mean to fall inside them. `train.py` only enforces `p10 ≤ P50 ≤ P90` *within* the quantile triple. Forcing the band to swallow the point forecast would widen it and silently destroy the calibration measured above.
- The bands are fitted with 500-tree LightGBM quantile models and **are not tuned**; the numbers here are the reason to tune them, not proof that they are fine.
