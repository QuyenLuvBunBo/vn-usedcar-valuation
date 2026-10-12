"""Week 2: merge the six sources into the Master Dataset (`data/master/master_clean_dataset.csv`).

Run once every `data/processed/<source>.csv` exists with the correct 21 columns:

    python -m src.merge.build_master
"""

from __future__ import annotations

import argparse
import logging
import sys

from ..common import config, schema, storage

log = logging.getLogger("build_master")

SOURCES = ["oto", "bonbanh", "chotot", "carmudi", "carpla", "anycar"]


def build(sources: list[str] = SOURCES) -> list[dict]:
    """Read each source CSV, tag source_platform, and concatenate into one record list.

    TODO (week 2):
      1. Validate every file before merging:  python -m tools.validate_source_csv <file>
      2. Record the row count and missing rate per source for the Milestone 1 report.
      3. After merging, run dedupe (see src/merge/dedupe.py) before writing the master file.
    """
    import csv

    rows: list[dict] = []
    for source in sources:
        path = config.DATA_PROCESSED / f"{source}.csv"
        if not path.exists():
            log.warning("no file yet for %s -> skipping", path)
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            part = list(csv.DictReader(fh))
        for row in part:
            row.setdefault("source_platform", source)
        rows.extend(part)
        log.info("%-10s %6d listings", source, len(part))
    log.info("Total after merging: %d listings", len(rows))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge the six sources into the Master Dataset")
    parser.add_argument("--sources", nargs="+", default=SOURCES)
    parser.add_argument("--out", default="master_clean_dataset")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.ensure_dirs()

    rows = build(args.sources)
    # TODO: rows = dedupe.duplicate_groups(rows)  (week 2)
    csv_path = storage.save_csv(rows, args.out, schema.SCHEMA_COLUMNS)
    log.info("Wrote %s", csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
