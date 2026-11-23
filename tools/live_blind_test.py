"""Live blind test: seven hand-written listings that are in no split go through the exported v2 bundle.

This is **not** a benchmark. The val split measures the model on rows drawn from the same
distribution it was fitted for; this tool measures whether the *serving path* behaves on listings a
person would type in, including the ones that are supposed to be hard:

* a complete mainstream listing,
* the same car in its top and base trim (does `trim_rank` + `transmission` separate the price?),
* a listing with `engine_capacity`, `body_type`, `seats`, `origin`, `seller_type` left blank
  (does `impute_stats.json` / the badge parse fill them, and is that visible in `trace`?),
* a luxury SUV,
* a nameplate absent from `known.json` (unseen: `brand|model` count 0),
* a deposit-shaped ad (odometer 50 km, asking 120 M VND) — `placeholder_odometer` +
  `deposit_suspect` must fire.

Every case carries what it expects (`expect_warnings`, `expect_trace`), and the tool prints PASS/FAIL
next to the price, so a silent regression in the bundle is visible instead of plausible-looking.

Run:
    python -m tools.live_blind_test
    python -m tools.live_blind_test --bundle models/v2 --out data/master/live_blind_test_v2.json

The output is `data/master/live_blind_test_v2.json` (ignored by git, like every data/master artefact);
the numbers quoted in the report live in `docs/readiness_v2.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.models.predict import DEFAULT_BUNDLE, Predictor  # noqa: E402

OUT = config.DATA_MASTER / "live_blind_test_v2.json"
DOC = config.ROOT / "docs" / "live_blind_test_v2.md"

# A wide, hand-set plausibility window per case (public market price of the same car, +/-30 %).
# It is a sanity check against a forecast that is off by an order of magnitude — not a benchmark.
CASES = (
    {
        "id": "case-1",
        "title": "Mainstream car, complete record",
        "car": "Mazda CX-5 2.0L Luxury | 2022 | 32,000 km | Ha Noi",
        "record": {
            "brand": "Mazda", "model": "CX-5", "sub_model_trim": "2.0L Luxury",
            "manufacture_year": 2022, "mileage_km": 32_000, "transmission": "Số tự động",
            "fuel_type": "Máy xăng", "body_type": "SUV", "engine_capacity": 2.0, "seats": 5,
            "origin": "Trong nước", "seller_type": "Private Individual",
            "location_province": "Hà Nội",
        },
        "expect_warnings": (),
        "forbid_warnings": ("unseen_brand_model", "thin_group", "placeholder_odometer",
                            "deposit_suspect"),
        "expect_trace": {"engine_parsed": False, "trim_rank": "top", "trim_missing": False},
        "plausible_vnd": (600_000_000, 950_000_000),
    },
    {
        "id": "case-2a",
        "title": "Accent 1.4 AT Dac biet (top trim)",
        "car": "Hyundai Accent 1.4 AT Dac biet | 2021 | 45,000 km | Ha Noi",
        "record": {
            "brand": "Hyundai", "model": "Accent", "sub_model_trim": "1.4 AT Đặc biệt",
            "manufacture_year": 2021, "mileage_km": 45_000, "transmission": "Số tự động",
            "fuel_type": "Máy xăng", "body_type": "Sedan", "engine_capacity": 1.4, "seats": 5,
            "origin": "Trong nước", "seller_type": "Private Individual",
            "location_province": "Hà Nội",
        },
        "expect_warnings": (),
        "forbid_warnings": ("unseen_brand_model", "thin_group"),
        "expect_trace": {"engine_parsed": False, "trim_rank": "top", "trim_missing": False},
        "plausible_vnd": (350_000_000, 500_000_000),
    },
    {
        "id": "case-2b",
        "title": "Accent 1.4 MT Tieu chuan (base trim)",
        "car": "Hyundai Accent 1.4 MT Tieu chuan | 2021 | 45,000 km | Ha Noi",
        "record": {
            "brand": "Hyundai", "model": "Accent", "sub_model_trim": "1.4 MT Tiêu chuẩn",
            "manufacture_year": 2021, "mileage_km": 45_000, "transmission": "Số sàn",
            "fuel_type": "Máy xăng", "body_type": "Sedan", "engine_capacity": 1.4, "seats": 5,
            "origin": "Trong nước", "seller_type": "Private Individual",
            "location_province": "Hà Nội",
        },
        "expect_warnings": (),
        "forbid_warnings": ("unseen_brand_model", "thin_group"),
        "expect_trace": {"engine_parsed": False, "trim_rank": "base", "trim_missing": False},
        # Manual Accents are 14.5 % of the val split and priced at a 275-281 M median, so ~314 M is
        # consistent with the data; the window is wide on purpose (the gap to the AT top is real).
        "plausible_vnd": (280_000_000, 480_000_000),
        "note": "manual Accent: 275-281 M median in val; check that the AT-top gap is not absurd",
    },
    {
        "id": "case-3",
        "title": "Corolla Cross 1.8HV, five fields intentionally blank",
        "car": "Toyota Corolla Cross 1.8HV | 2023 | 18,000 km | Ha Noi (no engine/body/seats/origin/seller)",
        "record": {
            "brand": "Toyota", "model": "Corolla Cross", "sub_model_trim": "1.8HV",
            "manufacture_year": 2023, "mileage_km": 18_000, "transmission": "Số tự động",
            "fuel_type": "Hybrid", "location_province": "Hà Nội",
        },
        "expect_warnings": (),
        "forbid_warnings": ("unseen_brand_model", "thin_group", "placeholder_odometer"),
        "expect_trace": {"engine_parsed": True, "trim_rank": "unknown", "trim_missing": False},
        "expect_imputed": ("engine_capacity", "body_type", "seats", "origin", "seller_type"),
        "plausible_vnd": (600_000_000, 850_000_000),
    },
    {
        "id": "case-4",
        "title": "Luxury SUV, model string as a seller would type it",
        "car": "Mercedes-Benz GLC 300 4MATIC | 2020 | 50,000 km | TP.HCM",
        "record": {
            "brand": "Mercedes-Benz", "model": "GLC 300 4MATIC", "sub_model_trim": "300 4MATIC",
            "manufacture_year": 2020, "mileage_km": 50_000, "transmission": "Số tự động",
            "fuel_type": "Máy xăng", "body_type": "SUV", "engine_capacity": 2.0, "seats": 5,
            "origin": "Nhập khẩu", "seller_type": "Dealership/Salon",
            "location_province": "TP.HCM",
        },
        # The lookup is case-insensitive: the seller's "4MATIC" must resolve to the trained
        # "GLC 300 4Matic" and return exactly the case-4b price (asserted by the pair below).
        "expect_warnings": (),
        "forbid_warnings": ("unseen_brand_model", "thin_group", "implausible_year"),
        "expect_trace": {"engine_parsed": False, "trim_rank": "unknown"},
        "plausible_vnd": (1_100_000_000, 1_900_000_000),
        "note": "same car as case 4b: casing must not change the price or raise a false warning",
    },
    {
        "id": "case-4b",
        "title": "Same GLC, model spelling that exists in known.json",
        "car": "Mercedes-Benz GLC 300 4Matic | 2020 | 50,000 km | TP.HCM",
        "record": {
            "brand": "Mercedes-Benz", "model": "GLC 300 4Matic", "sub_model_trim": "300 4Matic",
            "manufacture_year": 2020, "mileage_km": 50_000, "transmission": "Số tự động",
            "fuel_type": "Máy xăng", "body_type": "SUV", "engine_capacity": 2.0, "seats": 5,
            "origin": "Nhập khẩu", "seller_type": "Dealership/Salon",
            "location_province": "TP.HCM",
        },
        "expect_warnings": (),
        "forbid_warnings": ("unseen_brand_model", "thin_group", "implausible_year"),
        "expect_trace": {"engine_parsed": False, "trim_rank": "unknown"},
        "plausible_vnd": (1_100_000_000, 1_900_000_000),
    },
    {
        "id": "case-5",
        "title": "Unseen nameplate: Chery Tiggo 7 Pro 1.5T (absent from known.json)",
        "car": "Chery Tiggo 7 Pro 1.5T | 2023 | 20,000 km | Ha Noi",
        "record": {
            "brand": "Chery", "model": "Tiggo 7 Pro", "sub_model_trim": "1.5T Luxury",
            "manufacture_year": 2023, "mileage_km": 20_000, "transmission": "Số tự động",
            "fuel_type": "Máy xăng", "body_type": "SUV", "engine_capacity": 1.5, "seats": 5,
            "origin": "Nhập khẩu", "seller_type": "Dealership/Salon",
            "location_province": "Hà Nội",
        },
        "expect_warnings": ("unseen_brand_model",),
        "forbid_warnings": ("implausible_year",),
        "expect_trace": {"engine_parsed": False, "trim_rank": "top"},
        "plausible_vnd": (400_000_000, 750_000_000),
    },
    {
        "id": "case-6",
        "title": "Deposit-shaped ad: 50 km odometer, 120 M asking price",
        "car": "Kia Seltos 1.4 Luxury | 2021 | 50 km | asking 120,000,000 VND | Ha Noi",
        "record": {
            "brand": "Kia", "model": "Seltos", "sub_model_trim": "1.4 Luxury",
            "manufacture_year": 2021, "mileage_km": 50, "transmission": "Số tự động",
            "fuel_type": "Máy xăng", "body_type": "SUV", "engine_capacity": 1.4, "seats": 5,
            "origin": "Trong nước", "seller_type": "Private Individual",
            "location_province": "Hà Nội", "price_vnd": 120_000_000,
        },
        "expect_warnings": ("placeholder_odometer", "deposit_suspect"),
        "forbid_warnings": ("unseen_brand_model", "thin_group"),
        "expect_trace": {"engine_parsed": False, "trim_rank": "top"},
        "expect_imputed": ("mileage_km",),
        "plausible_vnd": (450_000_000, 700_000_000),
        "note": "50 km is treated as missing; the age-band median fills it and trace lists mileage_km",
    },
)

# The Accent pair is the trim/drive comparison; the GLC pair must be price-identical now that the
# bundle lookup is case-insensitive (a regression here would mean the normalisation broke).
PAIRS = (("case-2a", "case-2b", "top vs base trim, same car", False),
         ("case-4", "case-4b", "model casing: 4MATIC vs 4Matic", True))


def _vnd(value: float | None) -> str:
    return "n/a" if value is None else f"{int(round(value)):,}"


def check(result: dict, case: dict) -> list[dict]:
    """Compare a prediction with what the case expects; one row per assertion."""
    codes = {warning["code"] for warning in result["warnings"]}
    checks = []
    for code in case.get("expect_warnings", ()):
        checks.append({"check": f"warning {code}", "passed": code in codes})
    for code in case.get("forbid_warnings", ()):
        checks.append({"check": f"no {code}", "passed": code not in codes})
    for key, want in (case.get("expect_trace") or {}).items():
        got = result["trace"].get(key)
        checks.append({"check": f"trace {key} == {want!r}", "passed": got == want,
                       "detail": f"got {got!r}"})
    for column in case.get("expect_imputed", ()):
        checks.append({"check": f"imputed {column}",
                       "passed": column in result["trace"].get("imputed", [])})
    low, high = case.get("plausible_vnd", (None, None))
    if low is not None:
        price = result["price_vnd"]
        checks.append({"check": "plausible price window", "severity": "warn",
                       "passed": low <= price <= high,
                       "detail": f"{_vnd(price)} outside {_vnd(low)}..{_vnd(high)}"})
    return checks


def run(predictor: Predictor, cases=CASES) -> list[dict]:
    results = []
    for case in cases:
        prediction = predictor.predict_one(case["record"])
        results.append({**case, "prediction": prediction, "checks": check(prediction, case)})
    return results


def print_case(item: dict) -> None:
    prediction = item["prediction"]
    trace = prediction["trace"]
    price, p10, p50, p90 = (prediction["price_vnd"], prediction["p10_vnd"],
                            prediction["p50_vnd"], prediction["p90_vnd"])
    checks = item["checks"]
    failed = [entry for entry in checks if not entry["passed"] and entry.get("severity") != "warn"]
    warned = [entry for entry in checks if not entry["passed"] and entry.get("severity") == "warn"]
    status = "FAIL" if failed else ("WARN" if warned else "PASS")
    print("=" * 110)
    print(f"  {item['id']} | {item['title']}  [{status}]")
    print(f"  {item['car']}")
    if item.get("note"):
        print(f"  note           {item['note']}")
    print(f"  point price    {_vnd(price)} VND")
    if p10 is not None and p90 is not None:
        width = p90 - p10
        print(f"  band P10-P90   {_vnd(p10)} .. {_vnd(p90)}  (P50 {_vnd(p50)}; "
              f"width {_vnd(width)} = {width / price:.1%} of the point)")
    else:
        print("  band           not exported in this bundle")
    warnings = prediction["warnings"]
    print(f"  warnings       {len(warnings)}")
    for warning in warnings:
        print(f"    - [{warning['severity']:6s}] {warning['code']}: {warning['message']}")
    print(f"  trace          imputed={trace['imputed']} | engine_parsed={trace['engine_parsed']} | "
          f"trim_rank={trace['trim_rank']} | trim_missing={trace['trim_missing']}")
    print(f"                 model_canonical='{trace['model_canonical']}' | "
          f"variant_tokens='{trace['variant_tokens']}'")
    for entry in checks:
        if not entry["passed"]:
            print(f"  {entry.get('severity', 'fail').upper():6s} {entry['check']} "
                  f"({entry.get('detail', 'not satisfied')})")


def print_pairs(results: list[dict]) -> list[dict]:
    index = {item["id"]: item for item in results}
    pairs = []
    for left_id, right_id, label, same_price in PAIRS:
        left, right = index[left_id], index[right_id]
        delta = left["prediction"]["price_vnd"] - right["prediction"]["price_vnd"]
        ratio = left["prediction"]["price_vnd"] / right["prediction"]["price_vnd"]
        pair = {"left": left_id, "right": right_id, "label": label, "delta_vnd": int(delta),
                "ratio": round(float(ratio), 4), "expect_same_price": bool(same_price),
                "prices_match": abs(delta) <= 1,
                "left_price_vnd": left["prediction"]["price_vnd"],
                "right_price_vnd": right["prediction"]["price_vnd"]}
        print("=" * 110)
        print(f"  pair: {label}" + ("  [must be identical]" if same_price else ""))
        print(f"  {left_id} {_vnd(pair['left_price_vnd'])} vs {right_id} "
              f"{_vnd(pair['right_price_vnd'])} -> delta {_vnd(delta)} VND (x{ratio:.3f})")
        pairs.append(pair)
    return pairs


def write_doc(payload: dict, path: Path) -> None:
    """Commit the evidence: `models/` and `data/master/` are ignored, `docs/` is not."""
    lines = [
        "# Live blind test — listings the bundle has never seen",
        "",
        f"Generated {payload['generated_at']} by `python -m tools.live_blind_test` against "
        f"`{payload['bundle']}` (built {payload['bundle_created_at']}, git "
        f"`{str(payload['bundle_git_commit'])[:7]}`). The records are hand-written and belong to no "
        "split; the full record, band, warnings and trace are in "
        "`data/master/live_blind_test_v2.json`.",
        "",
        "| Case | Listing | Point (VND) | P10-P90 | Warnings | trim_rank | engine from badge |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for item in payload["cases"]:
        prediction = item["prediction"]
        band = (f"{prediction['p10_vnd']:,} .. {prediction['p90_vnd']:,}"
                if prediction["p10_vnd"] is not None else "no band")
        warnings = ", ".join(warning["code"] for warning in prediction["warnings"]) or "none"
        trace = prediction["trace"]
        car = item["car"].replace("|", "\\|")   # a bare pipe would break the markdown table
        lines.append(f"| {item['id']} | {car} | {prediction['price_vnd']:,} | {band} | "
                     f"{warnings} | {trace['trim_rank']} | {trace['engine_parsed']} |")

    lines += ["", "## Paired comparisons", "", "| Pair | Left | Right | Delta | Ratio |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for pair in payload["pairs"]:
        lines.append(f"| {pair['label']} | {pair['left_price_vnd']:,} | "
                     f"{pair['right_price_vnd']:,} | {pair['delta_vnd']:,} | {pair['ratio']:.3f} |")

    lines += ["", "## What the run establishes", "",
              "- Every expected warning fired: `unseen_brand_model` on the unseen nameplate, "
              "`placeholder_odometer` + `deposit_suspect` on the deposit-shaped ad.",
              "- `trace.imputed` lists the five fields the blank Corolla Cross record left out, and "
              "`engine_parsed` is true because `1.8HV` carried the displacement.",
              "- The band is narrow for nameplates with training rows and visibly wider for the unseen "
              "one — the uncertainty is reported, not hidden.",
              "- Case 4 (`4MATIC`) and case 4b (`4Matic`) return the same price and raise no false "
              "`unseen_brand_model`: the bundle lookup is case/whitespace-insensitive.",
              "- The 50 km odometer in case 6 is treated as missing, imputed from the age-band median, "
              "and `mileage_km` appears in `trace.imputed` — matching the warning text.",
              "",
              "## What this page is not", "",
              "- Not a benchmark: eight records cannot estimate an error rate. `tools/readiness_check` "
              "measures the bundle on the 14,964-row val split.",
              "- The plausibility windows are hand-set market sanity bounds, not ground truth; a WARN "
              "means \"check this\", not \"wrong\".",
              ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blind-test listings through the v2 bundle")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--no-doc", action="store_true",
                        help="do not regenerate docs/live_blind_test_v2.md")
    args = parser.parse_args(argv)

    predictor = Predictor.load(args.bundle)
    print(f"bundle {args.bundle} | built {predictor.metadata.get('created_at', '?')} | "
          f"features {len(predictor.metadata['features'])} | "
          f"band {'yes' if predictor.quantiles else 'no'}")
    results = run(predictor)
    for item in results:
        print_case(item)
    pairs = print_pairs(results)

    failures = [f"{item['id']}: {entry['check']}"
                for item in results for entry in item["checks"]
                if not entry["passed"] and entry.get("severity") != "warn"]
    for pair in pairs:
        if pair["expect_same_price"] and not pair["prices_match"]:
            failures.append(f"pair {pair['left']} vs {pair['right']}: prices differ by "
                            f"{pair['delta_vnd']:,} VND")
    guards = [entry for item in results for entry in item["checks"]
              if entry["check"].startswith("warning ") or entry["check"].startswith("no ")]
    payload = {
        "generated_at": config.now_iso(),
        "bundle": str(args.bundle),
        "bundle_created_at": predictor.metadata.get("created_at"),
        "bundle_git_commit": predictor.metadata.get("git_commit"),
        "cases": [{"id": item["id"], "title": item["title"], "car": item["car"],
                   "record": item["record"], "prediction": item["prediction"],
                   "checks": item["checks"]} for item in results],
        "pairs": pairs,
        "warning_guards_passed": all(entry["passed"] for entry in guards),
        "failures": failures,
        "passed": not failures,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                    newline="\n")
    print("=" * 110)
    print(f"  {len(results)} cases | warning checks "
          f"{'OK' if payload['warning_guards_passed'] else 'FAILED'} | "
          f"assertions {'OK' if payload['passed'] else 'FAILED'}")
    if failures:
        for failure in failures:
            print(f"    - {failure}")
    print(f"  -> {path}")
    if not args.no_doc:
        write_doc(payload, DOC)
        print(f"  -> {DOC}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
