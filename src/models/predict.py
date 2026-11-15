"""Serving path: one raw listing -> price, band and warnings. Reads **only** `models/<bundle>/`.

The training pipeline lives in `src/data_prep` + `src/features`; this module does not re-implement it.
It calls the same functions with statistics frozen at export time, so a prediction cannot silently
drift from training:

    raw record
      -> schema normalisation (labels outside the contract become `Unknown`)
      -> impute with `missing.fill_*` and the exported `impute_stats.json`   (train-fitted medians/modes)
      -> `build_features.add_stateless` + `apply_stats(feature_stats.json)`   (age, km/year, province group…)
      -> `extend.extend_split`                                               (engine_parsed, trim_rank, model_canonical)
      -> category alignment from `categories.json`, column order from `metadata.json`
      -> `model_point.joblib` (+ `quantiles.joblib` for P10/P90)

Nothing reads `data/master`: the only inputs are the bundle files. `tests/test_predict.py` proves it by
making every `data/master` read raise.

Run:
    python -m src.models.predict --record '{"brand":"Toyota","model":"Camry","manufacture_year":2020}'
    python -m src.models.predict --csv cars.csv --out prices.csv
    python -m src.models.predict --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import config, schema  # noqa: E402
from src.data_prep import missing  # noqa: E402
from src.features import build_features, extend  # noqa: E402

DEFAULT_BUNDLE = config.ROOT / "models" / "v2"
CATEGORICAL_FILLS = ("body_type", "transmission", "fuel_type", "origin", "seller_type")
REQUIRED = ("brand", "model", "manufacture_year")
OUTPUT_COLUMNS = ("price_vnd", "p10_vnd", "p90_vnd", "warnings")


def _int_keys(table: dict) -> dict:
    """`fill_median_by_age` expects integer age buckets; JSON turned them into strings."""
    table = dict(table)
    table["buckets"] = {int(key): value for key, value in table.get("buckets", {}).items()}
    return table


class Predictor:
    """Loads a bundle once; every call is pure (no I/O, no shared state)."""

    def __init__(self, bundle: Path):
        self.bundle = Path(bundle)
        read = lambda name: json.loads((self.bundle / name).read_text(encoding="utf-8"))
        self.metadata = read("metadata.json")
        self.categories = read("categories.json")
        self.known = read("known.json")
        self.feature_stats = read("feature_stats.json")
        self.impute = read("impute_stats.json")
        self.impute["mileage_by_age"] = _int_keys(self.impute["mileage_by_age"])
        self.impute["engine_by_age"] = _int_keys(self.impute["engine_by_age"])
        self.reference_year = int(self.impute["reference_year"])
        self.model = joblib.load(self.bundle / "model_point.joblib")
        quantile_path = self.bundle / "quantiles.joblib"
        self.quantiles = joblib.load(quantile_path) if quantile_path.exists() else None
        calibration = (self.metadata.get("quantiles") or {}).get("calibration") or {}
        self.shift_low = float(calibration.get("shift_low_log") or 0.0)
        self.shift_high = float(calibration.get("shift_high_log") or 0.0)

    @classmethod
    def load(cls, bundle: str | Path = DEFAULT_BUNDLE) -> "Predictor":
        return cls(Path(bundle))

    # ------------------------------------------------------------- raw -> row
    def _normalise(self, record: dict) -> dict:
        absent = [field for field in REQUIRED if not str(record.get(field, "")).strip()]
        if absent:
            raise ValueError(f"a prediction needs {absent} — got {sorted(record)}")
        row = {
            "listing_id": str(record.get("listing_id") or "PREDICTED"),
            "source_platform": str(record.get("source_platform") or "Unknown"),
            "brand": str(record["brand"]).strip(),
            "model": str(record["model"]).strip(),
            "sub_model_trim": record.get("sub_model_trim"),
            "manufacture_year": int(float(record["manufacture_year"])),
            "mileage_km": record.get("mileage_km"),
            "transmission": schema.normalize_transmission(record.get("transmission")),
            "fuel_type": schema.normalize_fuel(record.get("fuel_type")),
            "origin": schema.normalize_origin(record.get("origin")),
            "body_type": schema.normalize_body(record.get("body_type")),
            "engine_capacity": record.get("engine_capacity"),
            "seats": record.get("seats"),
            "location_province": schema.normalize_province(record.get("location_province")),
            "seller_type": schema.map_value(record.get("seller_type"), {}, "Unknown"),
            "price_vnd": record.get("price_vnd"),
            "imputed": "",
        }
        for key in ("mileage_km", "engine_capacity", "seats"):
            value = row[key]
            row[key] = "" if value is None or (isinstance(value, float) and np.isnan(value)) else value
        row["sub_model_trim"] = "" if row["sub_model_trim"] is None else row["sub_model_trim"]
        return row

    def _impute(self, row: dict) -> dict:
        """Same order as `missing.impute_parts`, with the exported statistics."""
        rows = [row]
        missing.fill_engine_from_trim(rows)
        for column in CATEGORICAL_FILLS:
            missing.fill_categorical(rows, self.impute["categorical"][column])
        missing.fill_seats_from_mapping(rows, self.impute["seats"])
        missing.fill_median_by_age(rows, self.impute["mileage_by_age"],
                                   reference_year=self.reference_year)
        missing.fill_median_by_group(rows, self.impute["engine_by_model"])
        missing.fill_median_by_age(rows, self.impute["engine_by_age"],
                                   reference_year=self.reference_year)
        rare = set(self.impute.get("rare_models") or [])
        for target in rows:
            value = str(target.get("model") or "")
            target["model_group"] = "Other" if (not value or value in rare) else value
        return rows[0]

    def _features(self, row: dict) -> pd.DataFrame:
        """v1 derived columns + v2 extension, exactly as the training tables were built."""
        frame = pd.DataFrame([row])
        frame["manufacture_year"] = pd.to_numeric(frame["manufacture_year"], errors="coerce")
        for column in ("mileage_km", "engine_capacity", "seats"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        prepared = build_features.apply_stats(
            build_features.add_stateless(frame, self.reference_year), self.feature_stats)
        cohort = frame[["listing_id", "model", "sub_model_trim", "engine_capacity", "imputed"]].copy()
        return extend.extend_split(cohort, prepared)

    # ----------------------------------------------------------------- predict
    def _matrix(self, prepared: pd.DataFrame) -> pd.DataFrame:
        columns = self.metadata["features"]
        absent = [column for column in columns if column not in prepared.columns]
        if absent:
            raise ValueError(f"the bundle expects {absent} — the bundle and the code disagree")
        matrix = prepared[columns].copy()
        for column, values in self.categories["categories"].items():
            if column in matrix.columns:
                series = matrix[column].astype(str)
                series = series.where(series.isin(values))       # an unseen level becomes NaN
                matrix[column] = pd.Categorical(series, categories=values)
        return matrix

    def _warnings(self, raw: dict, prepared: pd.DataFrame, asking: float | None) -> list[dict]:
        """Stable `code` + a sentence, so a UI can translate or suppress them."""
        found: list[dict] = []
        known = self.known
        combo = f"{raw['brand']}|{raw['model']}"
        count = int(known["brand_model_counts"].get(combo, 0))
        if count == 0:
            found.append({"code": "unseen_brand_model", "severity": "high",
                          "message": f"'{combo}' never appears in the training data; the estimate is a "
                                     f"segment-level guess, not a learned price."})
        elif count < 20:
            found.append({"code": "thin_group", "severity": "medium",
                          "message": f"'{combo}' has only {count} training rows; expect a wider band."})

        year = int(raw["manufacture_year"])
        if year < known["year_min"] or year > known["capture_year"]:
            found.append({"code": "implausible_year", "severity": "high",
                          "message": f"model year {year} is outside "
                                     f"{known['year_min']}..{known['capture_year']}."})

        mileage = raw.get("mileage_km")
        if mileage not in ("", None):
            value = float(mileage)
            if value <= known["placeholder_odometer_low"] or value >= known["placeholder_odometer_high"]:
                found.append({"code": "placeholder_odometer", "severity": "medium",
                              "message": f"{value:,.0f} km looks like a placeholder, not a distance; "
                                         f"the odometer was imputed for this prediction."})

        if "engine_capacity_parsed" in prepared.columns:
            engine = prepared["engine_capacity_parsed"].iloc[0]
            low, high = known["engine_range"]
            if engine is not None and not pd.isna(engine) and not (low <= float(engine) <= high):
                found.append({"code": "engine_out_of_range", "severity": "low",
                              "message": f"{float(engine)} L is outside the training range "
                                         f"{low}–{high} L."})

        if asking is not None and float(asking) > 0:
            segment = known["segment_median_vnd"].get(combo)
            baseline = float(segment) if segment else float(known["national_median_vnd"])
            ratio = float(asking) / baseline if baseline > 0 else None
            if ratio is not None and ratio < known["deposit_ratio_threshold"]:
                found.append({"code": "deposit_suspect", "severity": "high",
                              "message": f"the asking price is {ratio:.0%} of the {combo} median "
                                         f"({baseline:,.0f} VND) — the shape of a deposit ad."})
        return found

    def predict_one(self, record: dict) -> dict:
        """One raw listing -> price, band, warnings and a short trace of what was imputed/parsed."""
        raw = self._normalise(record)
        imputed = self._impute(raw)
        prepared = self._features(imputed)
        matrix = self._matrix(prepared)

        price = float(np.exp(self.model.predict(matrix)[0]))
        p10 = p50 = p90 = float("nan")
        warnings = self._warnings(raw, prepared, record.get("price_vnd"))
        if self.quantiles is None:
            warnings.append({"code": "no_band", "severity": "low",
                             "message": "this bundle was exported with --fast, so it carries no "
                                        "P10/P90 quantile models."})
        else:
            p10 = float(np.exp(self.quantiles[0.10].predict(matrix)[0] + self.shift_low))
            p50 = float(np.exp(self.quantiles[0.50].predict(matrix)[0]))
            p90 = float(np.exp(self.quantiles[0.90].predict(matrix)[0] + self.shift_high))
            p10, p90 = min(p10, p90), max(p10, p90)

        trace = {
            "imputed": [part for part in str(imputed.get("imputed") or "").split(";") if part],
            "engine_parsed": bool(prepared["engine_parsed"].iloc[0]),
            "trim_rank": str(prepared["trim_rank"].iloc[0]),
            "trim_missing": bool(prepared["trim_missing"].iloc[0]),
            "model_canonical": str(prepared["model_canonical"].iloc[0]),
            "variant_tokens": str(prepared["variant_tokens"].iloc[0]),
        }
        return {"price_vnd": int(round(price)),
                "p10_vnd": None if np.isnan(p10) else int(round(p10)),
                "p50_vnd": None if np.isnan(p50) else int(round(p50)),
                "p90_vnd": None if np.isnan(p90) else int(round(p90)),
                "warnings": warnings, "trace": trace}

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Per-row predictions for a CSV of raw listings; one bad row does not sink the batch."""
        results = []
        for _, record in frame.iterrows():
            try:
                results.append(self.predict_one(record.to_dict()))
            except (ValueError, KeyError) as exc:
                results.append({"price_vnd": None, "p10_vnd": None, "p50_vnd": None, "p90_vnd": None,
                                "warnings": [{"code": "invalid_record", "severity": "high",
                                              "message": str(exc)}], "trace": {}})
        out = frame.copy()
        for column in ("price_vnd", "p10_vnd", "p50_vnd", "p90_vnd"):
            out[column] = [item[column] for item in results]
        out["warnings"] = [";".join(warning["code"] for warning in item["warnings"])
                           for item in results]
        return out


SELFTEST_RECORDS = (
    {"brand": "Toyota", "model": "Camry", "manufacture_year": 2020, "mileage_km": 45_000,
     "transmission": "Số tự động", "fuel_type": "Xăng", "body_type": "Sedan",
     "location_province": "Hà Nội", "sub_model_trim": "2.5Q"},
    {"brand": "BrandThatDoesNotExist", "model": "Ghost", "manufacture_year": 2021,
     "mileage_km": 1, "location_province": "Nowhere"},
    {"brand": "Honda", "model": "CR-V", "manufacture_year": 2018, "mileage_km": 999_998,
     "price_vnd": 30_000_000},
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Price a raw listing from the exported v2 bundle")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--record", default="", help="one JSON object, e.g. '{\"brand\":\"Toyota\",...}'")
    parser.add_argument("--csv", default="", help="CSV of raw listings (one row per car)")
    parser.add_argument("--out", default="", help="where to write the CSV predictions")
    parser.add_argument("--selftest", action="store_true",
                        help="price three built-in records and assert the warnings fire")
    args = parser.parse_args(argv)

    predictor = Predictor.load(args.bundle)
    print(f"bundle {args.bundle} · features {len(predictor.metadata['features'])} · "
          f"band {'yes' if predictor.quantiles else 'no (--fast)'}")

    if args.selftest:
        expected = (None, "unseen_brand_model", "placeholder_odometer")
        for record, want in zip(SELFTEST_RECORDS, expected):
            result = predictor.predict_one(record)
            codes = {warning["code"] for warning in result["warnings"]}
            if want and want not in codes:
                raise SystemExit(f"selftest failed: {want} not raised for {record['brand']} "
                                 f"{record['model']} (got {sorted(codes)})")
            print(f"  {record['brand']:24s} {record['model']:8s} -> {result['price_vnd']:>13,} VND "
                  f"[{(result['p10_vnd'] if result['p10_vnd'] is not None else 0):,} .. "
                  f"{(result['p90_vnd'] if result['p90_vnd'] is not None else 0):,}] {sorted(codes)}")
        print("  selftest OK")
        return 0

    if args.record:
        print(json.dumps(predictor.predict_one(json.loads(args.record)), ensure_ascii=False, indent=1))
        return 0

    if args.csv:
        frame = pd.read_csv(args.csv, low_memory=False)
        out = predictor.predict_frame(frame)
        if args.out:
            out.to_csv(args.out, index=False, lineterminator="\n")
            print(f"  wrote {len(out):,} rows -> {args.out}")
        else:
            print(out[list(OUTPUT_COLUMNS)].head(20).to_string())
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

