# Proposal: `deposit_suspected` — a flag for deposit-style asking prices

> **Update 2026-11-13 — implemented.** The rule now lives in `src/data_prep/quality.py` and writes a
> **side table** (`data/master/label_flags.csv`) instead of changing the snapshot, so the frozen v1
> numbers stay reproducible. The simulated counts below (2,739 train / 566 val) are **not**
> reproducible with the rule as written; the measured counts are 1,552 / 329. See §7 for the
> correction, the measurement, and why "flag, do not drop" is now the evidence-backed choice.

Status of the original text: **proposal**, written before the milestone closed. It touches
`tools/audit_master` and the data contract, so it needed the team's agreement, and it could not land
inside the frozen milestone (see §5 below). That is still true of any change *to the dataset* — which
is why the implemented version is a side table.

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

## 6. Where the code went

`src/data_prep/quality.py` (the production rule) and `tools/model_gate.py` (the flag columns are
forbidden as features). `tools/audit_master.py` keeps its diagnostic printout; it was not changed,
because it runs on the master and its counts are a different question (§7.2). The feature-table
builder was **not** given a `--drop-suspicious` flag: the flag became a *weight* instead, measured in
`docs/label_cleaning.md`, because dropping the rows turned out to hurt (see §7.3).

## 7. Implemented 2026-11-13 — and what the numbers say

### 7.1 The counts are different from §3

| Rule as written | Train | Val |
|---|---:|---:|
| §3 simulation | 2,739 (3.90%) | 566 (3.78%) |
| **reproducible** (`quality.py`, threshold 0.25, ≥30-row segment, national fallback) | **1,552 (2.21%)** | **329 (2.20%)** |

Re-running the rule on `train.csv` gives 1,783; on `train_cohort.csv` and `train_cohort_imputed.csv`
it gives 1,552. None of the three gives 2,739, so the §3 figure came from a variant the text does not
state. The reproducible numbers are in `docs/label_flags.md` and in `label_flags_report.json`; quote
those.

### 7.2 Why the audit tool prints a third number

`tools/audit_master` reports 2,465 deposit rows **on the master** (100,887 rows) and 24,575 repeated
rows. The side table reports 2,203 deposits and 30,331 rows in repeat groups over the 100,188 cohort
rows. The deposit gap is the 469 rows the cohort excludes; the repeat gap is a comparison-type
difference (the audit compares CSV **strings**, the side table compares parsed **numbers**), which is
documented in `docs/label_flags.md` §3.

### 7.3 Dropping the flagged rows makes the *deployment* number worse

Measured with a fixed LightGBM, on `val_full` (all 14,964 val rows) and on a fixed `val_clean`
(9,644 rows with no flag), `docs/label_cleaning.md`:

| Training mode | MAPE val_full | MAPE val_clean |
|---|---:|---:|
| none (all rows) | **0.1169** | 0.1038 |
| drop_deposit | 0.1299 | **0.1017** |
| drop_all | 0.1357 | 0.1051 |
| weight_repeats (1/k) | 0.1160 | 0.1030 |

Reading: removing deposit rows improves the **clean** rows by 0.21 points but *worsens* the full val
set by 1.30 points, because the model stops learning the cheap end of the market that the removed rows
were the only evidence for. The "MAPE 11.5 % → 9.75 %" in §3 was an **evaluation-set** effect — those
566 rows were removed from the test set, not from the training set — which is exactly why the new
protocol reports both columns. The only mode that does not hurt is `weight_repeats`, and its gain is
within noise.

