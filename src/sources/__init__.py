"""One sub-package per data source (oto, bonbanh, chotot, carmudi, carpla, anycar).

Layout of a source (copy it from `_template/`):

    src/sources/<source>/
    ├─ crawl.py      # crawls listings (+ optionally detail pages), source-specific CLI
    └─ unified.py    # maps raw data to the 21 unified columns and exports CSV

Run:  python -m src.sources.<source>
"""
