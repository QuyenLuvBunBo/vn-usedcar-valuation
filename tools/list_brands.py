"""Discover and validate the brand list of oto.com.vn (used for brands_other.py).

Run: python -m tools.list_brands [slug ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common.http_client import ScraperSession  # noqa: E402
from src.sources.oto.crawl import BASE_URL  # noqa: E402

COUNT_RE = re.compile(r"C[oó]\s*([\d\.,]+)\s*tin")


def verify(session: ScraperSession, slug: str) -> tuple[bool, int]:
    """Is /mua-ban-xe-<slug> a real brand page? -> (valid, listing count)."""
    text = session.get_text(f"{BASE_URL}/mua-ban-xe-{slug}")
    if not text:
        return False, 0
    match = COUNT_RE.search(re.sub(r"\s+", " ", text))
    return bool(match), int(match.group(1).replace(".", "").replace(",", "")) if match else 0


def main() -> None:
    slugs = sys.argv[1:]
    if not slugs:
        from src.sources.oto.brands_other import BRANDS
        slugs = list(BRANDS)
    print(f"Validating {len(slugs)} slug(s)...\n")
    ok, bad = [], []
    with ScraperSession(delay=1.2) as session:
        for slug in slugs:
            valid, count = verify(session, slug)
            (ok if valid else bad).append(slug)
            print(f"  {'OK ' if valid else 'BAD'} {slug:22s} {count:6,} listings")
    print(f"\nValid: {len(ok)} | invalid: {len(bad)}")
    if bad:
        print("Slugs to remove/fix in brands_other.py:", ", ".join(bad))
    print("\nUpdate brands_other.py with the valid slugs listed above.")


if __name__ == "__main__":
    main()
