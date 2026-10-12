"""Recon tool: check robots.txt, fetch a page, and look for hidden API/JSON endpoints.

Run:  python -m tools.recon https://oto.com.vn/mua-ban-xe
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common import config, storage  # noqa: E402
from src.common.http_client import ScraperSession  # noqa: E402

PATTERNS = {
    "api_paths": r"[\"'`/]((?:api|graphql|gql)/[A-Za-z0-9/_\-\.\{\}\$]{2,80})",
    "next_data": r"__NEXT_DATA__",
    "next_json": r"/_next/data/[A-Za-z0-9/_\-\.]+\.json",
    "json_urls": r"https?://[^\"'`\s]+?\.json[^\"'`\s]*",
    "window_vars": r"window\.__[A-Za-z0-9_]+",
    "brand_params": r"[?&](brand|brandId|make|manufacturer|carBrand|model|carType|condition|state|status|priceFrom|priceTo)=[^&\"'`\s]{0,40}",
    "pagination": r"[?&](page|pageIndex|pageSize|limit|offset|p)=\d+",
    "hydration": r"(self\.__next_f|__NUXT__|__APOLLO_STATE__|dataLayer)",
}


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://oto.com.vn/mua-ban-xe"
    config.ensure_dirs()

    with ScraperSession(delay=0.5) as session:
        # 1) robots.txt
        root = re.match(r"(https?://[^/]+)", url).group(1)
        robots = session.get_text(f"{root}/robots.txt")
        print("=" * 70)
        print("ROBOTS.TXT", root)
        print("=" * 70)
        print(robots if robots else "(could not fetch / not present)")

        # 2) fetch the page
        resp = session.get(url)
        if resp is None:
            print("FETCH FAILED:", url)
            return
        html = resp.text
        print("=" * 70)
        print(f"GET {url} -> {resp.status_code} | {len(html)} bytes | {resp.headers.get('content-type')}")
        print("=" * 70)

        raw_path = storage.save_raw(html, "recon_muabanxe")
        print("Saved raw HTML:", raw_path)

        # 3) look for API/JSON markers inside the HTML
        for name, pattern in PATTERNS.items():
            found = re.findall(pattern, html)
            if found and isinstance(found[0], tuple):
                found = [t[0] for t in found]
            unique = Counter(found)
            print(f"\n--- {name} ({len(unique)} unique) ---")
            for value, count in unique.most_common(12):
                print(f"  [{count}x] {value[:160]}")

        # 4) count listing-card markers (is the content server-rendered?)
        print("\n--- server-render evidence ---")
        for probe in ("class=\"cb-item", "oto-item", "product-item", "item-car", "car-item", "price"):
            print(f"  {probe!r}: {html.count(probe)} occurrences")


if __name__ == "__main__":
    main()
