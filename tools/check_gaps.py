"""Kiểm tra 3 khoảng trống so với Unified Schema: listing_date, engine_capacity, seller_type.

Chạy: python -m tools.check_gaps
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.common.http_client import ScraperSession  # noqa: E402

MODEL_PAGE = "https://oto.com.vn/bang-gia-xe-o-to-honda-cr-v-moi-nhat"


def main() -> None:
    with ScraperSession(delay=1.0) as session:
        print("=" * 70)
        print("1) SITEMAP: có lastmod cho từng tin không?")
        print("=" * 70)
        for name in ("sitemap-mua-ban.xml", "sitemap-detail.xml"):
            text = session.get_text(f"https://oto.com.vn/{name}")
            if not text:
                print(f"  {name}: không lấy được")
                continue
            urls = re.findall(r"<loc>([^<]+)</loc>", text)
            mods = re.findall(r"<lastmod>([^<]+)</lastmod>", text)
            print(f"  {name}: {len(text)} bytes | {len(urls)} <loc> | {len(mods)} <lastmod>")
            print(f"    loc[:2] = {urls[:2]}")
            print(f"    lastmod[:3] = {mods[:3]}")
            # thử xem lastmod có nằm trong block <url> kèm loc không
            blocks = re.findall(r"<url>(.*?)</url>", text, re.S)
            if blocks:
                print(f"    block <url> đầu tiên: {re.sub(chr(92) + 's+', ' ', blocks[0])[:220]}")

        print("\n" + "=" * 70)
        print("2) ENGINE CAPACITY: trang thông số dòng xe có dung tích động cơ?")
        print("=" * 70)
        page = session.get_text(MODEL_PAGE)
        if page:
            tree_text = re.sub(r"\s+", " ", page)
            for kw in ("Dung tích", "Động cơ", "1.5", "2.0", "2.4", "cc", "Lít", "lit"):
                hits = re.findall(re.escape(kw) + r"[^|<]{0,40}", tree_text)
                print(f"  {kw!r}: {len(hits)} lần | mẫu: {hits[:2]}")
            print(f"  (trang {len(page)} bytes)")


if __name__ == "__main__":
    main()
