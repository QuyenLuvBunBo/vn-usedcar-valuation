# Proposal: `deposit_suspected` — a flag for deposit-style asking prices

Status: **proposal, not implemented**. It touches `tools/audit_master` and the data contract, so it needs
the team's agreement, and it cannot land inside the frozen milestone (see §5 below).

## 1. The problem it solves

`docs/error_audit_25.md` reads the 25 worst val rows: **24 of them are not prices**. A 2020 Mitsubishi
Triton listed at 42 million, a 2024 Audi Q5 at 218 million, a 2026 VinFast at 46 million — those are
deposit amounts, placeholders or typos. Because they are far *below* the model's estimate, they produce
the entire right tail of the error distribution: `Δ > 0` in 25/25 rows.

The column that should catch this does not: `price_status` says **`"full"`** on all 25, and on
**566/566** of the rows the rule below would flag. So the information is not in the data; it has to be
derived.

## 2. The rule

```
segment_median(brand, model) = median(price_vnd) on train rows of that brand|model   (>= 30 rows,
                                                                                      else the national median)
deposit_suspected            = price_vnd < 0.25 * segment_median(brand, model)
```

- Uses **train** medians only, so no validation row can influence the flag.
- Categorical, cheap, and explainable in one sentence to a non-technical reader.
- Threshold is the only free parameter, which is why §3 measures four of them.

## 3. What it would flag (simulated offline on this snapshot)

| Threshold | Train rows flagged | Val rows flagged | Median asking price of flagged |
| ---: | ---: | ---: | ---: |
| 0.15 | 934 (1,33 %) | 202 (1,35 %) | 58 M |
| 0.20 | 1.627 (2,32 %) | 358 (2,39 %) | 70 M |
| **0.25** | **2.739 (3,90 %)** | **566 (3,78 %)** | **90 M** |
| 0.30 | 4.262 (6,07 %) | 902 (6,03 %) | 118 M |

At 0,25 the flagged val ads are all priced **30–129 M** (median 90 M) — the shape of a deposit, not a car
price. They are spread across every platform (Chợ Tốt 204, bonbanh 96, oto.com.vn 95, tinbanxe 87,
muaban 80, carmudi 4), so this is not a Chợ Tốt problem even though Chợ Tốt dominates the worst-25 list.

**Effect on the reported error** (current predictions, val):

| View | MAPE |
| --- | ---: |
| all 14.964 rows | 11,51 % |
| drop the 566 rows flagged at 0,25 | **9,75 %** |
| drop the 202 rows flagged at 0,15 | 10,25 % |

So the rule explains **1,8 points of the 11,5 % MAPE** — and it is the same tail `docs/benchmark.md`
now reports as the `MAPE clean` column.

## 4. The cost: false positives

At 0,25, **139 of the 566 flagged rows (24,6 %)** are old (≤ 2012) *and* high-mileage (> 150.000 km) —
cars that really can be cheap. A rule that drops them would delete genuine bargains, which is exactly the
signal the project is supposed to find. Three ways to keep that under control, in order of preference:

1. **Flag, do not drop.** Add the boolean column, keep the rows, and report metrics both ways (what
   `benchmark.py` already does). A flag is reversible; a deleted row is not.
2. **Flag on two conditions**: `price < 0.25 * segment_median` **and** (`mileage_km < 5.000` or
   `listing_date` within the last 30 days) — a deposit is usually "car not shown yet".
3. **Lower the threshold to 0.15** if the report only wants the unambiguous cases: 202 val rows, MAPE
   still improves by 1,3 points, and false positives shrink.

## 5. Why it cannot land before 10/11

`CONTRIBUTING.md` §3b freezes `data/master/*` between milestones. A flag computed **before** the split
changes the row set, which changes `duplicate_group_id` grouping and therefore the split — every number in
the report would have to be rebuilt, and T2/T3's artefacts would go stale. The rule is therefore:

- **now**: keep it as a documented, simulated proposal plus the `MAPE clean` column in the benchmark;
- **next milestone**: add `deposit_suspected` to `tools/audit_master` (it already prints
  `PROBLEMS: N` per rule), rebuild the snapshot once, and let everyone re-run from the same new split.

## 6. Where the code would go

`tools/audit_master.py` already walks the merged table rule by rule and counts problems; the flag is one
more rule there (report it as a count, not a failure, since the rows are legitimate listings). The
feature-table builder would then drop or carry the column by a `--drop-suspicious` flag, and
`benchmark.py` would read it instead of re-deriving the ratio. Nothing in `src/models/**` has to change.
