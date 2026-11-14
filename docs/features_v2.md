# Feature extension (v2) — engine parsed from text, trim rank, canonical model

Generated 2026-11-14T06:21:54+00:00 by `python -m src.features.extend --write` (variant `full`). v1 tables are **not** modified: the v2 tables live in `data/master/v2/` so every week-3 number stays reproducible.

All four columns are **stateless** — each is a function of its own row — so nothing can leak from validation into training. Group statistics (medians, target encoding) stay in `src/features/pipeline.py`, which fits them inside the training fold.

| Split | Rows | Engine parsed from text | Engine available after | Trim missing | Model levels before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 70,244 | 1,062 | 70,244 | 55.7% | 3,243 → 2,238 |
| val | 14,964 | 230 | 14,964 | 54.8% | 1,547 → 1,137 |
| test | 14,980 | 209 | 14,980 | 55.4% | 1,586 → 1,170 |

## trim_rank

| Split | base | mid | top | unknown |
| --- | ---: | ---: | ---: | ---: |
| train | 1,626 | 4,738 | 6,969 | 56,911 |
| val | 347 | 929 | 1,623 | 12,065 |
| test | 337 | 977 | 1,561 | 12,105 |

## Reading

- `engine_capacity_parsed` keeps the site's value unless the column was **imputed**; only then is the badge parsed. A parsed value is a fact from the listing text, not a median.
- `trim_missing` is an indicator, not a fill: 55 % of the rows have no trim, and "unknown" must not be read as "base".
- `model_canonical` merges variant spellings; the original `model` column is kept beside it so any merge can be audited row by row.
- `variant_tokens` keeps what was stripped (displacement, gearbox, drive, fuel) so a model that wants it does not lose the information.
