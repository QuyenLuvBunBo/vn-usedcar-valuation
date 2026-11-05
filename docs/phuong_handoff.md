# Nguyễn Thế Phương — preprocessing handoff

Updated: 2026-11-05. Final verified configuration: **67 features / per_column /
price statistics excluded**, fitted on 70,244 frozen training rows and 52,417
duplicate groups. No validation or test set was evaluated.

## Summary for the report

1. The preprocessor uses train-only one-hot/frequency routing, ordered age bands,
   numeric median imputation/scaling, and smoothed brand/model target encoding.
2. Five folds keep duplicate_group_id disjoint. Every held-out row uses mappings
   and a prior fitted only on the other folds.
3. The final real-data matrix has **70,244 × 67** entries in its shape. A separate
   optional price-statistic build produced **69** features and passed the same
   independent OOF verification; the reference hashes describe 67 only.
4. The original frozen cohort is now available and its hash matches the team's
   reference. All eight history flags come from that cohort, joined by listing_id;
   53,134 rows have nonempty histories and their token counts match n_imputed.
5. Two independent 67-feature builds produced identical bytes for the joblib,
   metadata, feature names, OOF matrix and row map. All 70,244 OOF target encodings
   were independently checked in each run. **30 preprocessing tests** and
   **160 tests under tests/** passed.

## Assignment checklist

| Requirement | Status | Evidence |
| --- | --- | --- |
| One-hot routing at 40 categories | Implemented and tested | Train-only routing; 40/41 cutoff test |
| Ordinal age encoding | Implemented and tested | Ordered bands; unknown = -1 |
| Internal grouped target encoding | Verified on original training data | Five disjoint folds; all OOF values checked |
| Numeric scaling | Implemented and tested | Train-fitted median imputer and StandardScaler |
| Per-column imputation flags | Verified with original cohort | Hash-matched input; listing_id join; counts match |
| Saved preprocessor | Final 67-feature build verified | Two fresh-process builds, byte-identical outputs |
| Regression tests | 30 passed | Complete dated test_results.txt |
| Full tests/ suite | 160 passed | Complete dated full_test_results.txt |
| Generated documentation | Matches final 67-feature configuration | Same verified build produced docs and reports |
| Source provenance | Clean committed code, preserved in bundle | Push the supplied branch before remote review |
| Peer approval | Not claimed | A merged PR or passing tests do not establish peer review |

## Runtime and reproducibility

Python 3.12.14 / sklearn 1.8.0 / NumPy 2.3.5 / pandas 3.0.3 / SciPy 1.17.0 /
joblib 1.5.3. All direct requirements constraints are satisfied; see
[runtime_requirements.json](runtime_requirements.json).

[artifact_reproducibility.json](artifact_reproducibility.json) is the only
reference hash table. [Data handover §5](data_handover.md#5-artifacts-that-git-ignores--rebuild-and-compare-the-hash-do-not-ship-the-binary)
records the source commit, exact generation command, original-cohort provenance,
and publication steps. The checker requires a clean checkout and produces the
feature description and both verification reports together.

```bash
python -m tools.check_preprocess_reproducibility --cohort data/master/train_cohort_imputed.csv --expected-features 67 --artifacts-dir models/handoff
```

Commit source changes first, run verification, then commit generated evidence.
Keep frozen inputs unchanged. A source text hash normalizes CRLF to LF; raw data
and artifact hashes retain exact-byte semantics.

## Technical decisions and limitations

Columns above 40 training categories use relative frequencies. The joint
brand/model target encoder uses smoothing 20. These are implementation choices,
not claims of improved prediction accuracy.

brand_retention_rate and province_price_index are excluded by default because
they derive from whole-training targets. For outer CV, recompute them within
each outer training fold before enabling them. The optional configuration adds
two scaled values without missingness indicators; use separate experiment paths
so it cannot overwrite the default evidence.

Upstream imputation and category grouping were already applied to the supplied
feature CSV. Strict raw-data CV requires rebuilding those operations inside each
outer fold. These tests establish the new encoder's boundary, not every upstream
step. Train on fit_transform or the matching OOF matrix; use transform for
inference after joining the original imputation history.

The separate crawler smoke test remains blocked by existing merge markers in
src/sources/oto/brands_other.py. Downstream model integration and peer approval
are not claimed here. The test set remains reserved for the planned M2 evaluation
on 2026-11-07.
