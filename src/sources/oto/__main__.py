"""Cho phép chạy `python -m src.sources.oto` (gọi vào CLI của crawl.py)."""

import sys

from .crawl import main

if __name__ == "__main__":
    sys.exit(main())
