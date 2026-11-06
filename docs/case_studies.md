# Three case studies (plan §4.3)

Each case is picked by an explicit rule in `tools/error_report.py::pick_cases`, not by eye, so the same three rows appear every time the tool runs on this snapshot. Numbers are the frozen val split; the URL is the listing the row came from.

## Case 1 — asking price far below the model (deposit bait)

- Listing: `MUA_71248118` — Toyota Corolla Cross, 2022, 48000 km, Hà Nội
- Asking price: **7,350,000,000 VND** · model estimate **628,849,579 VND** · Δ -91.4% · APE 91.4%
- Bucket: `3_import_or_salvage` · quality flags: `nan`
- Link: https://muaban.net/o-to/ban-o-to-toyota-corolla-cross-quan-long-bien-ha-noi/toyota-corolla-cross-2022-1-8hv-48000-km-id71248118

Why it matters: The listing asks at least 45% under the model's estimate; in this dataset that pattern is what a deposit scam looks like, and it is the reason a cheap price is never a win by itself.

## Case 2 — odometer outlier

- Listing: `CHOTOT_134989809` — Aion Y Plus, 2024, 999998 km, Hưng Yên
- Asking price: **200,000,000 VND** · model estimate **1,204,486,664 VND** · Δ +502.2% · APE 502.2%
- Bucket: `2_odometer_outlier` · quality flags: `nan`
- Link: https://xe.chotot.com/134989809.htm

Why it matters: Mileage divided by vehicle age is above 60,000 km/year, three to five times the fleet median. Either the odometer was rolled back or the car really was used for long-haul work.

## Case 3 — import / salvage

- Listing: `CARPLA_F8W47` — Audi Q5, 2024, 7000 km, Hà Nội
- Asking price: **218,000,000 VND** · model estimate **2,089,824,773 VND** · Δ +858.6% · APE 858.6%
- Bucket: `3_import_or_salvage` · quality flags: `nan`
- Link: https://carpla.vn/xe/audi-q5-sline-quattro-2024---7000km-f8w47

Why it matters: `origin` is not the domestic value and the asking price is above the "suspiciously cheap" cut, so the case is about origin rather than about a placeholder price. Same predicate as bucket 3 in the taxonomy, restricted to rows Case 1 does not already own.

The point of these three is not that the model is wrong on them — it is that the three failure modes are structural (bait pricing, mileage manipulation, import status) and no amount of tuning on the frozen table fixes them. §7 of the report should say that.
