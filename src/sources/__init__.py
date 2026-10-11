"""Mỗi nguồn dữ liệu là một package con (oto, bonbanh, chotot, carmudi, carpla, anycar).

Cấu trúc một nguồn (copy từ `_template/`):

    src/sources/<nguồn>/
    ├─ crawl.py      # cào listing + (tuỳ chọn) trang chi tiết, CLI riêng của nguồn
    └─ unified.py    # đổi dữ liệu thô sang 21 cột Unified Schema, xuất CSV

Chạy: python -m src.sources.<nguồn>
"""
