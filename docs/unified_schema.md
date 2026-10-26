# Unified Schema — the team's data contract

**The source of truth is code, not this document**: `src/common/schema.py`.
This file explains each column for the written report.

## 16 attributes + 5 metadata columns

| # | Column | Type | Meaning / allowed values |
|---|---|---|---|
| 1 | `listing_id` | string | Unique listing id, prefixed by source (`OTO_23444795`, `BAN_…`, `MUA_71297868`) |
| 2 | `source_platform` | enum | `oto.com.vn`, `bonbanh`, `chotot`, `carmudi`, `carpla`, `anycar`, `muaban.net` (anycar.vn is offline; muaban.net replaces it) |
| 3 | `brand` | string | Manufacturer: `Toyota`, `Hyundai`, `Ford`, … |
| 4 | `model` | string | Model designation: `Vios`, `Accent`, `CX-5`, … |
| 5 | `sub_model_trim` | string | Engine trim / grade: `1.8G CVT`, `2.5Q`, `2.7 V 4X2 AT` (empty if the seller omitted it) |
| 6 | `manufacture_year` | int | Manufacture year; proposed scope 1995–present |
| 7 | `mileage_km` | float | Cumulative odometer reading in km (raw site value; sellers can mistype) |
| 8 | `transmission` | enum | `Automatic` / `Manual` / `Other` / `Unknown` |
| 9 | `fuel_type` | enum | `Gasoline` / `Diesel` / `Hybrid` / `Electric` / `Unknown` |
| 10 | `origin` | enum | `CKD` (locally assembled) / `CBU` (imported) / `Unknown` |
| 11 | `body_type` | enum | `Sedan` / `SUV` / `Crossover` / `MPV` / `Hatchback` / `Pickup` / `Van` / `Truck` / `Other` |
| 12 | `engine_capacity` | float | Displacement in litres (1.5, 2.0, 2.4); often inferred from the trim name |
| 13 | `seats` | int | Registered seating capacity |
| 14 | `location_province` | string | Normalized province/city (`Hà Nội`, `TP. Hồ Chí Minh`, …) |
| 15 | `seller_type` | enum | `Dealership/Salon` / `Private Individual` / `Unknown` |
| 16 | `price_vnd` | int (target) | **Advertised asking price** in VND; empty/`invalid` if there is no definite price |
| 17 | `source_url` | string | Original listing URL, for traceability |
| 18 | `listing_date` | datetime (nullable) | Publication/bump date, ISO 8601; leave empty when the source does not expose it |
| 19 | `scraped_at` | datetime | Capture time (UTC, ISO 8601) |
| 20 | `raw_price_text` | string | **Unmodified** price expression: `1 tỷ 250 tr`, `550 triệu` |
| 21 | `price_status` | enum | `full` / `negotiable` / `instalment` / `invalid` |

## Rules

1. **Nulls stay null** — do not silently replace them with 0. For categorical columns that cannot be
   recovered, use `Unknown` (as the project report requires).
2. `price_vnd` is the **target**: never use it as a predictor, and never use `raw_price_text`,
   `price_status` or `listing_date` as model features (leakage / not a real predictor).
3. Normalize **only** with the helpers in `src/common/parsing.py` and `src/common/schema.py`.
4. Before opening a PR: `python -m tools.validate_source_csv data/processed/<source>.csv` must PASS.

## Checks after merging (week 2)

`python -m src.merge.build_master` adds three columns and prints these checks:

| Column | Meaning |
|---|---|
| `tier` | `listed` / `archived` — was the car advertised when we captured it? |
| `duplicate_group_id` | coarse candidate vehicle key: brand + model + trim + year + province + ± mileage |
| `quality_flags` | report §4.3 review reasons; flagged, never deleted |

- Zero duplicate `listing_id` / `source_url` after merging.
- Duplicate rate: candidate groups and the records that share one (the key is coarse on purpose, so the
  audit also prints the count for a **stricter** signal — same key *and* same asking price, which is
  what a renewed ad looks like).
- `duplicate_group_id` must keep all records of the same vehicle inside the **same** train/val/test
  partition (the split is fitted per group, and all learned statistics stay train-only).
- The report must state: record count per source, missing rate per column, duplicate rate,
  and how many records were excluded (with reasons) — Milestone 1 requirements. The build prints the
  first three; exclusions are the flags plus `missing_price` (no definite price → not a regression row).
