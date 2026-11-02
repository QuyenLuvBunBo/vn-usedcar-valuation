# Team Git workflow — `vn-usedcar-valuation`

Goal: nine members, eight data sources, merging each other's work **without conflicts**.

## 1. Branches

| Branch | Used by | Contents |
|---|---|---|
| `main` | everyone | always runnable; only receives reviewed pull requests |
| `feat/source-<source>-<part>` | each member | your crawler, e.g. `feat/source-oto-asia`, `feat/source-chotot-south` |
| `feat/week2-merge`, `feat/week3-model`, `feat/week4-app` | sub-teams | later weeks |

Rules: branch off an up-to-date `main`; keep pull requests small (1–3 days); never let a branch live for weeks.

```bash
git checkout main
git pull
git checkout -b feat/source-bonbanh-new
# ... work, commit ...
git push -u origin feat/source-bonbanh-new
# then open a Pull Request into main
```

## 2. Commits

- Short subject with a prefix: `feat:`, `fix:`, `data:`, `docs:`, `refactor:`, `test:`
- Examples: `feat: bonbanh crawler (cars 2019-2026)`, `fix: parse price '1 tỷ 250 tr'`
- Do not commit large data files or `.env`.

## 3. File ownership — how we avoid conflicts

| You may edit freely | Needs a separate PR + 2 reviewers |
|---|---|
| `src/sources/<your-source>/**` | `src/common/**` (schema, parsing, http_client, storage, config) |
| `docs/sources/<your-source>.md` | `docs/unified_schema.md`, `README.md`, `CONTRIBUTING.md`, `requirements.txt` |

**Never edit another source's code.** If you find a bug in `src/common/`, open an issue or a dedicated PR.

Team-wide files that are nobody's package still need a reviewer from another sub-team:
`src/data_prep/**` (split, normalize, missing, eda, pipeline), `src/merge/**`, `tests/**`,
`docs/week*.md` and `docs/crawl_gap.md`.

## 3b. Data is frozen between milestones

`data/master/*` is a snapshot: `train.csv`, `val.csv`, `test.csv` and `*_cohort_imputed.csv` are what
every number in the report refers to. While a milestone is open:

- **do not re-crawl and do not re-run `split`** — a new crawl changes `duplicate_group_id`, so the
  report's numbers stop matching the data;
- improvements to a source go to `data/processed/<source>_extra.csv`, which `build_master` picks up on
  its next run, and the rebuild happens once, on purpose, with everyone told;
- if a rebuild happens, every table in the report is regenerated in the same commit range.


## 4. Data contract (mandatory)

Every source writes `data/processed/<source>.csv` with **exactly these 21 columns**, in this order
(defined in `src/common/schema.py`):

```
listing_id, source_platform, brand, model, sub_model_trim, manufacture_year, mileage_km,
transmission, fuel_type, origin, body_type, engine_capacity, seats, location_province,
seller_type, price_vnd, source_url, listing_date, scraped_at, raw_price_text, price_status
```

Use these normalized values (never invent your own labels):

| Column | Allowed values |
|---|---|
| `transmission` | `Automatic` / `Manual` / `Other` / `Unknown` |
| `fuel_type` | `Gasoline` / `Diesel` / `Hybrid` / `Electric` / `Unknown` |
| `origin` | `CKD` / `CBU` / `Unknown` |
| `body_type` | `Sedan` / `SUV` / `Crossover` / `MPV` / `Hatchback` / `Pickup` / `Van` / `Truck` / `Other` / `Unknown` |
| `seller_type` | `Dealership/Salon` / `Private Individual` / `Unknown` |
| `price_status` | `full` / `negotiable` / `instalment` / `invalid` |

Import the helpers from `src/common/parsing.py` and `src/common/schema.py` — **do not re-implement them**.

## 5. Before opening a pull request

```bash
python -m tools.validate_source_csv data/processed/<source>.csv   # must PASS
python -m tools.smoke_test                                        # offline regression tests
```

In the PR description state: the source, how many listings were collected, the collection date,
which fields the site **does not** expose, and any source-specific normalization decision
(for example how you handled "Thỏa thuận" prices).

## 6. Never commit

`data/raw/**` (raw HTML), `data/*.db`, `logs/**`, `.env`, notebooks with outputs.
Share datasets between members through Google Drive (or Git LFS if the team agrees).
