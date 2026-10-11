"""Đếm TỒN KHO THỰC (xe cũ đang rao) của TẤT CẢ hãng trên oto.com.vn.

Chạy: python -m tools.brand_inventory
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
    """Lấy danh sách HÃNG từ sitemap-mua-ban-hang-dong.xml (các URL 1 tầng)."""
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
    print(f"Ứng viên slug: {len(slugs)}")

    total = 0
    rows: list[tuple[str, int]] = []
    with ScraperSession(delay=1.2) as session:
        for slug in slugs:
            text = session.get_text(f"{BASE}/mua-ban-xe-{slug}")
            if not text:
                print(f"  {slug:30s} -> không lấy được")
                continue
            # chỉ nhận trang HÃNG: phải có tiêu đề hãng và bộ đếm tin
            if "Kết quả" in text and "Có " not in text:
                continue
            m = COUNT_RE.search(re.sub(r"\s+", " ", text))
            if not m:
                print(f"  {slug:30s} -> không đọc được số tin (bỏ qua)")
                continue
            count = int(m.group(1).replace(".", "").replace(",", ""))
            rows.append((slug, count))
            total += count
            print(f"  {slug:30s} {count:6,} tin")

    print("\n### Kết quả")
    rows.sort(key=lambda r: -r[1])
    for slug, count in rows[:25]:
        print(f"  {slug:20s} {count:6,}")
    print(f"  tổng số trang hãng đọc được: {len(rows)}")
    print(f"  TỔNG TIN XE CŨ (mọi hãng)  : {total:,}")

    six = {"toyota", "hyundai", "kia", "mazda", "honda", "mitsubishi"}
    our_total = sum(c for s, c in rows if s in six)
    print(f"  6 hãng phổ thông châu Á    : {our_total:,}")
    print(f"  phần còn lại cho bạn Phương: {total - our_total:,}")


if __name__ == "__main__":
    main()
