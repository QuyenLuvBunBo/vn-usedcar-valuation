"""Count the ACTUAL inventory (used cars currently advertised) of every brand on oto.com.vn.

Run: python -m tools.brand_inventory
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.common.http_client import ScraperSession  # noqa: E402

BASE = "https://oto.com.vn"
COUNT_RE = re.compile(r"C[oó]\s*([\d\.,]+)\s*tin")


def brand_slugs() -> list[str]:
    """Read the BRAND list from sitemap-mua-ban-hang-dong.xml (single-segment URLs)."""
    import re as _re

    from src.common.http_client import ScraperSession as _S

    with _S(delay=0.8) as session:
        text = session.get_text("https://oto.com.vn/sitemap-mua-ban-hang-dong.xml") or ""
    locs = _re.findall(r"<loc>([^<]+)</loc>", text)
    slugs = set()
    for loc in locs:
        path = loc.replace("https://oto.com.vn/", "").strip("/")
        parts = path.split("/")
        if len(parts) == 1 and path.startswith("mua-ban-xe-"):
            slug = path[len("mua-ban-xe-"):]
            if slug and slug != "moi":
                slugs.add(slug)
    return sorted(slugs)


def main() -> None:
    slugs = brand_slugs()
    print(f"Candidate slugs: {len(slugs)}")

    total = 0
    rows: list[tuple[str, int]] = []
    with ScraperSession(delay=1.2) as session:
        for slug in slugs:
            text = session.get_text(f"{BASE}/mua-ban-xe-{slug}")
            if not text:
                print(f"  {slug:30s} -> could not fetch")
                continue
            # only accept BRAND pages: they carry a brand title and the listing counter
            if "Kết quả" in text and "Có " not in text:
                continue
            m = COUNT_RE.search(re.sub(r"\s+", " ", text))
            if not m:
                print(f"  {slug:30s} -> could not read the counter (skipped)")
                continue
            count = int(m.group(1).replace(".", "").replace(",", ""))
            rows.append((slug, count))
            total += count
            print(f"  {slug:30s} {count:6,} listings")

    print("\n### Result")
    rows.sort(key=lambda r: -r[1])
    for slug, count in rows[:25]:
        print(f"  {slug:20s} {count:6,}")
    print(f"  brand pages read successfully : {len(rows)}")
    print(f"  TOTAL USED-CAR LISTINGS       : {total:,}")

    six = {"toyota", "hyundai", "kia", "mazda", "honda", "mitsubishi"}
    our_total = sum(c for s, c in rows if s in six)
    print(f"  six Asian mainstream brands   : {our_total:,}")
    print(f"  remaining brands (Phương)     : {total - our_total:,}")


if __name__ == "__main__":
    main()
