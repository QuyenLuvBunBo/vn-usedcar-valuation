"""Kiểm tra sitemap-detail có lastmod cho từng tin không (nguồn listing_date tiềm năng)."""

from __future__ import annotations

import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.common.http_client import ScraperSession  # noqa: E402


def main() -> None:
    with ScraperSession(delay=1.0) as session:
        for name in ("sitemap-detail-1.xml", "sitemap-mua-ban-hang-dong.xml"):
            text = session.get_text(f"https://oto.com.vn/{name}")
            if not text:
                print(name, "-> không lấy được")
                continue
            locs = re.findall(r"<loc>([^<]+)</loc>", text)
            mods = re.findall(r"<lastmod>([^<]+)</lastmod>", text)
            print(f"\n### {name}: {len(text)} bytes | {len(locs)} loc | {len(mods)} lastmod")
            for loc in locs[:3]:
                print("   loc:", loc)
            for mod in mods[:5]:
                print("   lastmod:", mod)
            blocks = re.findall(r"<url>(.*?)</url>", text, re.S)
            if blocks:
                print("   block đầu:", re.sub(r"\s+", " ", blocks[0])[:300])


if __name__ == "__main__":
    main()
