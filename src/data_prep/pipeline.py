"""Week 2 in one command: normalize -> impute -> EDA.

The three stages stay separate modules, because each one has its own owner and its own table in the
report. This runner only fixes the **order**, and the order is not optional:

1. `normalize` — brand/model canonicals, carmudi's template default, the regression cohort.
   It writes `*_cohort.csv`.
2. `missing`   — the audit plus the imputation, fitted on the cohort's train partition, and the
   `model_group` column. It reads `*_cohort.csv` and writes `*_cohort_imputed.csv`, because the
   imputation mode must not be fitted on a value the repair is about to remove.
3. `eda`       — descriptive statistics, the five week-2 analyses, six figures.

Every statistic is learned on train only; the split itself (`train.csv`, `val.csv`, `test.csv`) is
never rewritten. Week 3 starts from `data/master/train_cohort_imputed.csv`.

Run:
    python -m src.data_prep.pipeline                     # all three stages
    python -m src.data_prep.pipeline --from missing      # resume after a stage
    python -m src.data_prep.pipeline --steps eda         # only some stages
    python -m src.data_prep.pipeline --collapse-rare 5   # a different rare-model cutoff
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from ..common import config

log = logging.getLogger("pipeline")

STEPS = ("normalize", "missing", "eda")


def command_for(step: str, args: argparse.Namespace) -> list[str]:
    """The exact command line of one stage — printed before it runs, so the log is reproducible."""
    base = [sys.executable, "-m", f"src.data_prep.{step}"]
    if step == "normalize":
        return [*base, "--split", "all", "--write"]
    if step == "missing":
        return [*base, "--split", "all", "--input-suffix", "_cohort", "--fill",
                "--min-group", str(args.min_group),
                "--collapse-rare", str(args.collapse_rare)]
    return [*base, "--top-brands", str(args.top_brands)]


def run(step: str, args: argparse.Namespace) -> int:
    """Run one stage as a child process, so a failure is a return code, not a half-applied state."""
    command = command_for(step, args)
    print(f"\n{'=' * 78}\n$ {' '.join(command[1:])}\n{'=' * 78}", flush=True)
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(command, cwd=config.ROOT, env=environment)
    if completed.returncode != 0:
        log.error("stage '%s' failed with exit code %s — later stages not run",
                  step, completed.returncode)
    return completed.returncode


def outputs() -> list[Path]:
    """The week-2 artefacts, for the closing summary."""
    master = config.DATA_MASTER
    candidates = [master / f"{name}{suffix}.csv"
                  for name in ("train", "val", "test")
                  for suffix in ("_cohort", "_cohort_imputed")]
    candidates += [master / "missing_report.json", master / "normalize_report.json",
                   master / "eda" / "eda_summary.md"]
    return [path for path in candidates if path.exists()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run every week-2 data-preparation stage in order")
    parser.add_argument("--steps", default=",".join(STEPS),
                        help=f"comma-separated subset of {', '.join(STEPS)}")
    parser.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0],
                        help="resume at this stage (the earlier ones are assumed done)")
    parser.add_argument("--min-group", type=int, default=5,
                        help="a group thinner than this falls back to the next level")
    parser.add_argument("--collapse-rare", type=int, default=10, metavar="N",
                        help="models seen < N times in train join 'Other' in `model_group`")
    parser.add_argument("--top-brands", type=int, default=15)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    wanted = [step.strip() for step in args.steps.split(",") if step.strip()]
    unknown = [step for step in wanted if step not in STEPS]
    if unknown:
        parser.error(f"unknown step(s): {', '.join(unknown)}")
    selected = [step for step in STEPS if step in wanted
                and STEPS.index(step) >= STEPS.index(args.start)]
    if not selected:
        parser.error("nothing to do — check --steps / --from")

    for name in ("train", "val", "test"):
        if not (config.DATA_MASTER / f"{name}.csv").exists():
            log.error("missing %s.csv -> run 'python -m src.data_prep.split' first", name)
            return 1

    for step in selected:
        code = run(step, args)
        if code != 0:
            return code

    print(f"\n{'=' * 78}\nWeek 2 artefacts")
    for path in outputs():
        print(f"  {path.relative_to(config.ROOT)}  ({path.stat().st_size / 1024:,.0f} KB)")
    print("\n  Week 3 reads: data/master/train_cohort_imputed.csv"
          " (cohort + imputed values + model_group)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
