# Review of `docs/features.md` — does the generated description match the artifact?

Owner of this note: Quyết (`docs/week3_plan.md` §4.1, second deliverable). Method: rebuilt the
preprocessor from the frozen cohort with the documented command, then compared every claim in the
generated description against the artifact itself.

```bash
python -m src.features.pipeline --features full \
  --cohort data/master/train_cohort_imputed.csv --require-imputed --describe \
  --output /tmp/pp_review/preprocess.joblib --encoded-dir /tmp/pp_review/encoded \
  --docs /tmp/pp_review/features.md
```

## Claim by claim

| Claim in `docs/features.md` | Verified | Evidence from the rebuilt artifact |
|---|---|---|
| `Variant: full`, **67 features** | ✅ | `len(get_feature_names_out()) == 67`, `metadata["output_features"] == 67` |
| `Configuration: per_column` | ✅ | `missing_mode_ == "per_column"`; 9 `imputed__*` columns (`imputed__any` + 8 per-field) |
| `optional price statistics: excluded` | ✅ | `excluded_price_stats == ["brand_retention_rate", "province_price_index"]`, `include_frozen_price_stats is False` |
| 5 internal folds, seed 42, smoothing 20, one-hot cutoff 40 | ✅ | `len(target_encoder_.fold_audit_) == 5`, every `group_overlap == 0`; `smoothing == 20.0`, `max_onehot == 40` |
| Fitted on **70,244 training rows** | ✅ | `training_rows_ == 70,244`, `training_sha256` starts `62bf8aa4` (the reference hash in `docs/data_handover.md` §5) |
| Metadata records input **basenames** | ✅ | `training_source == "train_features_full.csv"`, `cohort_source == "train_cohort_imputed.csv"` |
| "Report section 5 must identify 67/default or 69/with-price-stats" | ✅ present | the sentence is in the generated text |

Nothing in the description contradicts the artifact. The two numbers that people mix up are stated
correctly: **59** is the `aggregate_only` build (no cohort), **67** is the frozen default with the eight
per-column imputation flags, **69** adds the two price statistics by explicit opt-in.

## Three gaps worth fixing, none of them errors

1. **The description does not list the feature *groups*** used by the ablation (§4 of the report), so a
   reader cannot join `docs/features_ablation.md` to it. Fix: one sentence pointing at
   `docs/features_ablation.md` and `docs/feature_formulas.md`.
2. **No caveat about the price statistics being leakage-sensitive.** `docs/features.md` says they are
   excluded; it does not say *why* (they are built from train prices, so reusing their whole-training
   values inside an outer CV leaks the held-out fold). That sentence belongs in the description because
   it is the reason the default drops them.
3. **`docs/features.md` is regenerated on every `--describe` run**, so an edit to it is lost. Both gaps
   above therefore have to be fixed in `src/features/pipeline.py::describe()`, not in the Markdown.

## One local trap (not a repo defect)

The `models/preprocess.joblib` on this machine predates the merged metadata fix: its
`training_source` is still the string `data\master\train_features_full.csv` (a path), and its recorded
dependency versions are older than the ones in the table above. It is gitignored, so nothing in the repo
depends on it — but any number produced from that file locally is suspect. Rebuild it with the command
above before quoting anything that touches `preprocess.joblib`.

## Verdict

`docs/features.md` is trustworthy as the description of the artifact: every checkable claim holds. The
gaps are documentation completeness (groups, leakage rationale), and both are one-line changes inside
`describe()` when the next preprocessor change is made — not worth a rebuild of the frozen artifact by
themselves.
