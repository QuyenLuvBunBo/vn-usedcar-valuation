"""Run: python -m unittest discover -s tests -p 'test_features.py' -v."""
import tempfile
import unittest
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline

from src.features.pipeline import (
    AGE_ORDER, FULL_CAT, FULL_NUM, CarPreprocessor, GroupTargetEncoder, attach_imputed,
)


def sample(n=50):
    data = {c: ["common"] * n for c in FULL_CAT}
    data.update({c: np.arange(n, dtype=float) + 1 for c in FULL_NUM})
    data["brand"] = ["brand-" + str(i % 3) for i in range(n)]
    data["model"] = ["model-" + str(i % 5) for i in range(n)]
    data["age_band"] = [AGE_ORDER[i % 5] for i in range(n)]
    data["listing_id"] = ["id-" + str(i) for i in range(n)]
    data["duplicate_group_id"] = ["group-" + str(i // 2) for i in range(n)]
    data["n_imputed"] = [0] * n
    data["location_province"] = ["Hanoi"] * n
    data["price_vnd"] = np.arange(n) * 1_000_000 + 100_000_000
    return pd.DataFrame(data)


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.X = sample()
        self.y = np.log1p(self.X.price_vnd)
        self.warning_context = warnings.catch_warnings()
        self.warning_context.__enter__()
        warnings.simplefilter("ignore", UserWarning)

    def tearDown(self):
        self.warning_context.__exit__(None, None, None)

    def test_unseen_pair_gets_global_training_mean(self):
        encoder = GroupTargetEncoder().fit(self.X, self.y)
        val = self.X.iloc[:1].copy()
        val["brand"], val["model"] = "unseen", "unseen"
        self.assertEqual(encoder.transform(val)[0, 0], self.y.mean())

    def test_internal_unknown_uses_fold_mean_not_full_mean(self):
        X = self.X.copy()
        X["model"] = ["unique-" + str(i) for i in range(len(X))]
        encoder = GroupTargetEncoder()
        output = encoder.fit_transform(X, self.y).ravel()
        for fold in np.unique(encoder.oof_fold_ids_):
            held = encoder.oof_fold_ids_ == fold
            np.testing.assert_allclose(output[held], self.y[~held].mean())

    def test_heldout_targets_cannot_change_their_own_encodings(self):
        first = GroupTargetEncoder()
        before = first.fit_transform(self.X, self.y)
        held = first.oof_fold_ids_ == 0
        changed = self.y.copy()
        changed.loc[held] += 10000
        after = GroupTargetEncoder().fit_transform(self.X, changed)
        np.testing.assert_allclose(before[held], after[held])

    def test_duplicate_group_never_crosses_fold(self):
        encoder = GroupTargetEncoder()
        encoder.fit_transform(self.X, self.y)
        audit = pd.DataFrame({"group": self.X.duplicate_group_id, "fold": encoder.oof_fold_ids_})
        self.assertEqual(audit.groupby("group").fold.nunique().max(), 1)
        self.assertTrue(all(f["group_overlap"] == 0 for f in encoder.fold_audit_))

    def test_integer_group_optimization_preserves_fold_assignments(self):
        encoder = GroupTargetEncoder()
        encoder.fit_transform(self.X, self.y)
        expected = np.empty(len(self.X), dtype=int)
        splitter = GroupKFold(n_splits=5, shuffle=True, random_state=42)
        for fold, (_, held) in enumerate(splitter.split(self.X, self.y, self.X.duplicate_group_id)):
            expected[held] = fold
        np.testing.assert_array_equal(encoder.oof_fold_ids_, expected)

    def test_encoder_rejects_absent_or_blank_groups(self):
        for X in [self.X.drop(columns="duplicate_group_id"),
                  self.X.assign(duplicate_group_id=""),
                  self.X.assign(duplicate_group_id="same")]:
            with self.assertRaises(ValueError):
                GroupTargetEncoder().fit_transform(X, self.y)

    def test_smoothing_formula(self):
        enc = GroupTargetEncoder(smoothing=2).fit(self.X, self.y)
        mask = (self.X.brand == self.X.brand.iloc[0]) & (self.X.model == self.X.model.iloc[0])
        expected = (self.y[mask].sum() + 2 * self.y.mean()) / (mask.sum() + 2)
        self.assertAlmostEqual(enc.transform(self.X.iloc[:1])[0, 0], expected)

    def test_pair_keys_do_not_collide_on_separator(self):
        X = pd.DataFrame({"brand": ["a|b", "a"], "model": ["c", "b|c"]})
        enc = GroupTargetEncoder(smoothing=0).fit(X, [1, 9])
        np.testing.assert_array_equal(enc.transform(X).ravel(), [1, 9])

    def test_transform_does_not_learn_validation_categories_or_stats(self):
        p = CarPreprocessor().fit(self.X, self.y)
        before = joblib.hash(p)
        val = self.X.iloc[:3].copy()
        val["brand"], val["transmission"], val["mileage_km"] = "new", "new", 1e10
        p.transform(val)
        self.assertEqual(before, joblib.hash(p))
        self.assertNotIn("new", p.onehot_.categories_[p.onehot_columns_.index("transmission")])

    def test_onehot_cutoff_40_vs_41(self):
        X = self.X.copy()
        X["body_type"] = [f"b{i % 40}" for i in range(len(X))]
        X["source_platform"] = [f"p{i % 41}" for i in range(len(X))]
        p = CarPreprocessor().fit(X, self.y)
        self.assertIn("body_type", p.onehot_columns_)
        self.assertIn("source_platform", p.frequency_columns_)

    def test_unknown_onehot_zero_and_frequency_zero(self):
        X = self.X.assign(model=[f"m{i}" for i in range(len(self.X))])
        p = CarPreprocessor().fit(X, self.y)
        val = X.iloc[:1].assign(transmission="new", model="unseen")
        result = p.transform(val).toarray()[0]
        names = p.get_feature_names_out().tolist()
        positions = [i for i, name in enumerate(names) if name.startswith("onehot__transmission_")]
        self.assertTrue((result[positions] == 0).all())
        self.assertEqual(result[names.index("frequency__model")], 0)

    def test_age_order_and_unknown(self):
        p = CarPreprocessor().fit(self.X, self.y)
        val = self.X.iloc[:7].copy()
        val["age_band"] = AGE_ORDER + ["unexpected", None]
        index = p.get_feature_names_out().tolist().index("ordinal__age_band")
        np.testing.assert_array_equal(p.transform(val).toarray()[:, index], [0, 1, 2, 3, 4, -1, -1])

    def test_target_and_ids_are_not_features(self):
        p = CarPreprocessor().fit(self.X, self.y)
        val = self.X.iloc[:3].copy()
        first = p.transform(val).toarray()
        for c in ["price_vnd", "listing_id", "duplicate_group_id", "raw_price_text", "source_url"]:
            val[c] = "changed"
        np.testing.assert_array_equal(first, p.transform(val).toarray())

    def test_price_stats_excluded_by_default(self):
        p = CarPreprocessor().fit(self.X, self.y)
        first = p.transform(self.X).toarray()
        changed = self.X.assign(brand_retention_rate=1e10, province_price_index=1e20)
        np.testing.assert_array_equal(first, p.transform(changed).toarray())

    def test_price_stats_explicit_opt_in(self):
        p = CarPreprocessor(include_frozen_price_stats=True).fit(self.X, self.y)
        self.assertIn("brand_retention_rate", p.numeric_)
        self.assertIn("province_price_index", p.numeric_)

    def test_per_column_flags_and_count_validation(self):
        X = self.X.assign(imputed="")
        X.loc[0, "imputed"] = "engine_capacity;mileage_km"
        X.loc[0, "n_imputed"] = 2
        p = CarPreprocessor(missing_policy="require").fit(X, self.y)
        result = p.transform(X).toarray()
        names = p.get_feature_names_out().tolist()
        for c in ["imputed__engine_capacity", "imputed__mileage_km", "imputed__any"]:
            self.assertEqual(result[0, names.index(c)], 1)
            self.assertEqual(result[1, names.index(c)], 0)
        with self.assertRaises(ValueError):
            p.transform(X.assign(n_imputed=0))
        with self.assertRaises(ValueError):
            p.transform(X.drop(columns="imputed"))

    def test_flags_do_not_invent_history_from_count(self):
        p = CarPreprocessor().fit(self.X.assign(n_imputed=3), self.y)
        self.assertEqual(p.missing_mode_, "aggregate_only")
        names = p.get_feature_names_out().tolist()
        self.assertIn("imputed__any", names)
        self.assertNotIn("imputed__engine_capacity", names)
        with self.assertRaises(ValueError):
            CarPreprocessor(missing_policy="require").fit(self.X, self.y)

    def test_current_missingness_independent_from_imputed_history(self):
        X = self.X.assign(imputed="")
        p = CarPreprocessor().fit(X, self.y)
        val = X.iloc[:1].copy()
        val["engine_capacity"] = np.nan
        result = p.transform(val).toarray()[0]
        names = p.get_feature_names_out().tolist()
        self.assertEqual(result[names.index("missing_now__engine_capacity")], 1)
        self.assertEqual(result[names.index("imputed__engine_capacity")], 0)
        self.assertTrue(np.isfinite(result).all())

    def test_all_missing_numeric_rejected(self):
        with self.assertRaises(ValueError):
            CarPreprocessor().fit(self.X.assign(engine_capacity=np.nan), self.y)

    def test_missing_required_column_and_infinity_rejected(self):
        p = CarPreprocessor().fit(self.X, self.y)
        for val in [self.X.drop(columns="mileage_km"), self.X.assign(mileage_km=np.inf)]:
            with self.assertRaises(ValueError):
                p.transform(val)

    def test_join_uses_listing_id_not_position(self):
        cohort = self.X[["listing_id"]].copy()
        cohort["imputed"] = ["mileage_km" if i == 0 else "" for i in range(len(cohort))]
        result = attach_imputed(self.X, cohort.iloc[::-1])
        self.assertEqual(result.imputed.iloc[0], "mileage_km")
        self.assertEqual(result.imputed.iloc[1], "")
        pd.testing.assert_index_equal(result.index, self.X.index)

    def test_join_rejects_duplicate_or_missing_listing(self):
        cohort = self.X[["listing_id"]].assign(imputed="")
        for bad in [cohort.iloc[1:], pd.concat([cohort, cohort.iloc[:1]])]:
            with self.assertRaises(ValueError):
                attach_imputed(self.X, bad)

    def test_minimal_variant(self):
        p = CarPreprocessor(variant="minimal")
        result = p.fit_transform(self.X, self.y)
        self.assertNotIn("ordinal__age_band", p.get_feature_names_out())
        self.assertEqual(result.shape[0], len(self.X))

    def test_joblib_roundtrip(self):
        p = CarPreprocessor().fit(self.X, self.y)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preprocess.joblib"
            joblib.dump(p, path)
            loaded = joblib.load(path)
            np.testing.assert_allclose(p.transform(self.X).toarray(), loaded.transform(self.X).toarray())

    def test_sklearn_clone_and_model_pipeline(self):
        p = clone(CarPreprocessor(random_state=123))
        model = Pipeline([("preprocess", p), ("model", Ridge())])
        model.fit(self.X, self.y)
        self.assertTrue(np.isfinite(model.predict(self.X.iloc[:3])).all())
        self.assertTrue(hasattr(p.target_encoder_, "oof_fold_ids_"))

    def test_description_reports_actual_mode_and_fold_audit(self):
        p = CarPreprocessor()
        p.fit_transform(self.X, self.y)
        description = p.describe()
        self.assertIn("aggregate_only", description)
        self.assertIn("Group overlap", description)
        self.assertIn(str(p.training_rows_), description)

    def test_series_target_alignment_enforced(self):
        with self.assertRaises(ValueError):
            GroupTargetEncoder().fit(self.X, self.y.iloc[::-1])


if __name__ == "__main__":
    unittest.main()
