# Nguyễn Thế Phương — preprocessing handoff

Updated: 2026-11-05. Scope: Phương's week-3 preprocessing deliverables and the
follow-up to PR #9. The original frozen feature CSV contains 70,244 training
rows and 52,417 duplicate groups. No validation/test evaluation is claimed.

## Summary for the report

1. `src/features/pipeline.py` implements one-hot encoding for at most 40 training
   categories, frequency encoding above that cutoff, ordered `age_band`, numeric
   median imputation/scaling, and smoothed `brand|model` target encoding.
2. Five internal folds keep `duplicate_group_id` disjoint. Each held-out row uses
   only the other folds' targets; unseen pairs use that fold's mean log price.
3. The available real-data rebuild is **59 features / aggregate_only**. The final
   handoff requires the original cohort: **67 features by default**, or **69**
   with the two optional price statistics. These are different configurations.
4. **29 preprocessing tests pass**, including both new PR #9 regressions. The
   dated, complete log is in [test_results.txt](test_results.txt). The independent
   verifier checked all 70,244 OOF target encodings for the 59-feature build.
5. The original `train_cohort_imputed.csv` is still required to finish the
   67-feature real-data rebuild and publish its two-run reference hashes.
   `n_imputed` cannot recover the names of the imputed fields.

## Assignment checklist

| Requirement | Status | Evidence |
| --- | --- | --- |
| One-hot routing at 40 categories | Implemented and tested | Train-only routing; cutoff test at 40/41 |
| Ordinal age encoding | Implemented and tested | 0–2, 3–5, 6–9, 10–14, 15+; unknown = -1 |
| Internal grouped target encoding | Implemented and tested | Five folds; held-out-target perturbation test |
| Numeric scaling | Implemented and tested | Train-fitted median imputer and StandardScaler |
| Per-column imputation flags | Code tested; final real-data artifact pending | Join by listing_id; --require-imputed |
| Saved preprocessor | 59-feature build verified | Fresh-process loading and independent OOF checks |
| tests/test_features.py | 29 tests pass | Complete dated log, including basename and 67/69 layout regressions |
| No learning during transform | Tested within this module | Fitted-state hash stays unchanged |
| Generated feature documentation | Regenerated for the available configuration | Explicit aggregate_only label and 59 = 67 − 8 explanation |
| Duy's cross-review | Not recorded as completed | PRs #7 and #9 were merged; merging does not establish peer review. PR #9 has no submitted GitHub review as checked on 2026-11-05. |

## Technical decisions and limitations

Categorical columns above 40 values use train-relative frequencies. The joint
brand/model target encoder uses smoothing 20. Frequency encoding is an
implementation decision, not an experimental claim of improved accuracy;
Quyết's cardinality comparison remains separate.

`brand_retention_rate` and `province_price_index` are excluded by default because
they were computed upstream from whole-training targets. Their reuse inside
outer CV leaks held-out targets. Use `--include-frozen-price-stats` only for the
frozen train/validation protocol, or recompute the statistics inside each outer
training fold. The option adds two scaled values and no missingness indicators.

Upstream imputation and category grouping were already applied to the supplied
CSV. Strict raw-data cross-validation must rebuild those operations inside each
outer training fold. These encoder tests establish this module's boundary only.

## Complete the final handoff

Obtain the original frozen `data/master/train_cohort_imputed.csv` from the team.
Verify its reference input hash in [data handover §5](data_handover.md#5-artifacts-that-git-ignores--rebuild-and-compare-the-hash-do-not-ship-the-binary).
Do not re-crawl, re-split, or replace the frozen training data.

```bash
python -m src.features.pipeline --features full \
  --cohort data/master/train_cohort_imputed.csv --require-imputed --describe
python -m tools.verify_phuong --cohort data/master/train_cohort_imputed.csv
python -m tools.check_preprocess_reproducibility \
  --cohort data/master/train_cohort_imputed.csv --expected-features 67
```

The build regenerates the matching joblib, metadata, feature names, OOF matrix,
and row map. The two-run check uses temporary directories and does not overwrite
frozen inputs. Update the single hash table in data handover §5 from its report.
Downstream models must be retrained when the preprocessor configuration changes.

## Peer-review checks

- Confirm duplicate groups never cross folds and held-out targets cannot affect
  their own target encodings.
- Train with fit_transform or the matching OOF matrix; use transform for inference.
- Record whether each experiment uses 67/default or 69/with-price-statistics.
- Check listing_id joins and availability of src.features.pipeline when loading.
- Run the tests and check integration with the training team's model code.

This correction does not claim Duy's approval or downstream model integration.
The test set remains reserved for the planned M2 evaluation on 2026-11-07.
