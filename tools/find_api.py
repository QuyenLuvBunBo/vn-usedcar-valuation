"""Dò endpoint AJAX/phân trang trong HTML + file JS của trang listing.

Chạy: python -m tools.find_api
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.http_client import ScraperSession  # noqa: E402

PAGE = Path("data/raw/recon_brand.html")

KEYWORDS = [
    "page=", "trang", "LoadMore", "load-more", "loadMore", "Xem thêm", "xem-them",
    "ajax", "/api/", "api/", ".ashx", "/tim-kiem", "search", "GetList", "Paging",
    "offset", "skip=", "take=", "pageSize",
]


def scan(label: str, text: str) -> None:
    print(f"\n########## {label} ({len(text)} ký tự) ##########")
    for kw in KEYWORDS:
        positions = [m.start() for m in re.finditer(re.escape(kw), text)]
        if not positions:
            continue
        print(f"\n--- {kw!r}: {len(positions)} lần ---")
        for pos in positions[:3]:
            seg = text[max(0, pos - 90) : pos + 90].replace("\n", " ")
            print("   ...", re.sub(r"\s+", " ", seg), "...")


def main() -> None:
    page_text = PAGE.read_text(encoding="utf-8")
    scan("HTML trang listing", page_text)

    tree = html.fromstring(page_text.encode("utf-8"))
    scripts = sorted(set(tree.xpath("//script/@src")))
    print("\n########## FILE JS ##########")
    for s in scripts:
        print("  ", s)

    with ScraperSession(delay=0.5) as session:
        for src in scripts:
            if not src.startswith(("http", "/")):
                continue
            url = src if src.startswith("http") else "https://oto.com.vn" + src
            js = session.get_text(url)
            if js:
                scan(f"JS {url}", js[:400_000])


if __name__ == "__main__":
    main()
