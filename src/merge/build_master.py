"""Tuần 2: ghép 6 nguồn thành Master Dataset (`data/master/master_clean_dataset.csv`).

Chạy khi đã có đủ 6 file `data/processed/<nguồn>.csv` đúng 21 cột:

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
    """Đọc CSV từng nguồn, gắn source_platform, gộp thành một danh sách record.

    TODO (Tuần 2):
      1. Kiểm tra mỗi file trước khi gộp:  python -m tools.validate_source_csv <file>
      2. Ghi lại số dòng mỗi nguồn + tỷ lệ thiếu để đưa vào báo cáo Milestone 1.
      3. Sau khi gộp: chạy dedupe (xem src/merge/dedupe.py) rồi mới ghi master.
    """
    import csv

    rows: list[dict] = []
    for source in sources:
        path = config.DATA_PROCESSED / f"{source}.csv"
        if not path.exists():
            log.warning("chưa có file %s -> bỏ qua", path)
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            part = list(csv.DictReader(fh))
        for row in part:
            row.setdefault("source_platform", source)
        rows.extend(part)
        log.info("%-10s %6d tin", source, len(part))
    log.info("Tổng sau khi gộp: %d tin", len(rows))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gộp 6 nguồn thành Master Dataset")
    parser.add_argument("--sources", nargs="+", default=SOURCES)
    parser.add_argument("--out", default="master_clean_dataset")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.ensure_dirs()

    rows = build(args.sources)
    # TODO: rows = dedupe.duplicate_groups(rows)  (Tuần 2)
    csv_path = storage.save_csv(rows, args.out, schema.SCHEMA_COLUMNS)
    log.info("Đã ghi %s", csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
