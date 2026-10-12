"""Allows running `python -m src.sources.oto` (delegates to crawl.py's CLI)."""

import sys

from .crawl import main

if __name__ == "__main__":
    sys.exit(main())
