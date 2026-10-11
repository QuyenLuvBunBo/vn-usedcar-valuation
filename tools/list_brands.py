"""Dò + xác thực danh sách HÃNG trên oto.com.vn (dùng cho brands_other.py).

Chạy: python -m tools.list_brands
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
    """Trang /mua-ban-xe-<slug> có phải trang hãng thật không? -> (hợp lệ, số tin)."""
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
    print(f"Xác thực {len(slugs)} slug...\n")
    ok, bad = [], []
    with ScraperSession(delay=1.2) as session:
        for slug in slugs:
            valid, count = verify(session, slug)
            (ok if valid else bad).append(slug)
            print(f"  {'OK ' if valid else 'SAI'} {slug:22s} {count:6,} tin")
    print(f"\nHợp lệ: {len(ok)} | không hợp lệ: {len(bad)}")
    if bad:
        print("Slug cần bỏ/ sửa trong brands_other.py:", ", ".join(bad))
    total = 0
    print("\nGợi ý cập nhật brands_other.py bằng các slug hợp lệ ở trên.")


if __name__ == "__main__":
    main()
