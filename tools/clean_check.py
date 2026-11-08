"""Prove the committed tree is enough: extract HEAD into a temp dir and rebuild the artefacts there.

This is the plan's §7 test — *"chạy được từ bản clone sạch: build_features rồi train"* — turned into
one command. It never touches the working tree: `git archive HEAD` gives exactly the committed files
(no gitignored leftovers), the frozen inputs are copied in from `data/master`, and the chain runs with
that directory as cwd.

Run:
    python -m tools.clean_check
    python -m tools.clean_check --keep          # leave the temp dir for inspection
    python -m tools.clean_check --features full --model lightgbm
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# Everything the chain needs that git does not carry: only the **mandatory** snapshot folder
# (`01_week3_mandatory/` in docs/data_handover.md §1). If a step ever needs more than this, the claim
# "one folder is enough to train" is broken and this check should fail rather than paper over it.
FROZEN_INPUTS = (
    "train_cohort_imputed.csv", "val_cohort_imputed.csv", "test_cohort_imputed.csv",
)


def run(label: str, command: list[str], cwd: Path) -> None:
    print(f"== {label}", flush=True)
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {result.returncode}")
    print("   ok", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the artefacts from a clean HEAD extract")
    parser.add_argument("--features", default="full", choices=("minimal", "full"))
    parser.add_argument("--model", default="lightgbm")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)

    source = config.DATA_MASTER
    missing = [name for name in FROZEN_INPUTS if not (source / name).exists()]
    if missing:
        raise SystemExit(f"missing frozen inputs in {source}: {', '.join(missing)}")

    target = Path(tempfile.mkdtemp(prefix="clean-check-"))
    try:
        print(f"== git archive HEAD -> {target}")
        archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=zip", "HEAD"],
                                 capture_output=True, check=True)
        buffer = io.BytesIO(archive.stdout)
        with zipfile.ZipFile(buffer) as bundle:
            bundle.extractall(target)
        destination = target / "data" / "master"
        destination.mkdir(parents=True, exist_ok=True)
        for name in FROZEN_INPUTS:
            shutil.copyfile(source / name, destination / name)
        print(f"   {len(FROZEN_INPUTS)} frozen inputs copied", flush=True)

        run("build_features", [sys.executable, "-m", "src.features.build_features",
                               "--features", args.features, "--split", "all"], target)
        run(f"train {args.model}", [sys.executable, "-m", "src.models.train",
                                    "--model", args.model, "--features", args.features,
                                    "--quantiles"], target)
        run("model gate", [sys.executable, "-m", "tools.model_gate"], target)
        if not args.skip_tests:
            run("unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"], target)

        ledger = destination / "model_results.json"
        if ledger.exists():
            print(f"\n   ledger written inside the clean tree: {ledger}")
        print("\nCLEAN CHECK PASSED — the committed tree rebuilds the artefacts on its own.")
        return 0
    finally:
        if args.keep:
            print(f"   kept: {target}")
        else:
            shutil.rmtree(target, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
