"""Tuần 2: kiểm toán giá trị thiếu, xử lý cardinality, điền khuyết theo nhóm.

Nguyên tắc trong report: mọi thống kê điền khuyết chỉ được học từ tập TRAIN rồi áp nguyên
trạng vào validation/test (tránh leakage). Không thay giá trị thiếu bằng 0.
"""

from __future__ import annotations

from collections import Counter

from ..common import schema


def measure_missing(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Đo tỷ lệ thiếu từng cột (Milestone 1 cần báo cáo)."""
    total = len(rows) or 1
    report: dict[str, dict[str, float]] = {}
    for col in schema.SCHEMA_COLUMNS:
        missing = sum(1 for r in rows if r.get(col) in (None, "", "Unknown"))
        report[col] = {"missing": missing, "rate": round(missing / total, 4)}
    return report


def cardinality(rows: list[dict], column: str) -> list[tuple[str, int]]:
    """Đếm số lần xuất hiện từng giá trị — dùng để tìm dòng xe hiếm (<10 tin)."""
    return Counter(str(r.get(column)) for r in rows).most_common()


def collapse_rare(rows: list[dict], column: str, min_count: int = 10, label: str = "Other") -> list[dict]:
    """Gom giá trị xuất hiện dưới `min_count` lần vào nhãn `label` (kế hoạch Tuần 2)."""
    counts = Counter(str(r.get(column)) for r in rows)
    for row in rows:
        value = str(row.get(column))
        if counts[value] < min_count:
            row[column] = label
    return rows


# TODO (Tuần 2 — tiểu ban Missing Data):
#   - fill_categorical_mode(train_rows, target_rows, column)   # mode theo nhóm hãng/dòng
#   - fill_mileage_median(train_rows, target_rows)             # median theo nhóm tuổi xe
#   - fill_seats_from_mapping(...)                             # bảng tra model/trim/năm
