"""Phân tích <lastmod> trong sitemap-detail: độ phủ và ý nghĩa (ngày đăng hay ngày đẩy tin).

Chạy: python -m tools.lastmod_analysis
"""

from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.http_client import ScraperSession  # noqa: E402

SITEMAPS = ("sitemap-detail-1.xml", "sitemap-detail-2.xml")
ENTRY_RE = re.compile(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>")


def load_lastmods(session: ScraperSession) -> dict[str, str]:
    """Tải các sitemap chi tiết -> dict url -> lastmod."""
    out: dict[str, str] = {}
    for name in SITEMAPS:
        text = session.get_text(f"https://oto.com.vn/{name}")
        if not text:
            print(f"  {name}: không lấy được")
            continue
        entries = ENTRY_RE.findall(text)
        print(f"  {name}: {len(text)} bytes | {len(entries)} entry")
        for url, lastmod in entries:
            out[url] = lastmod
    return out


def main() -> None:
    with ScraperSession(delay=1.0) as session:
        print("### Tải sitemap")
        lastmods = load_lastmods(session)
    print(f"Tổng URL có lastmod: {len(lastmods)}")

    if not lastmods:
        return

    # phân bố theo ngày
    days = Counter(v[:10] for v in lastmods.values())
    print(f"\n### Phân bố lastmod theo ngày (top 10)")
    for day, n in days.most_common(10):
        print(f"  {day}: {n}")
    dates = sorted(lastmods.values())
    print(f"  sớm nhất: {dates[0]}")
    print(f"  muộn nhất: {dates[-1]}")
    print(f"  số ngày khác nhau: {len(days)}")

    # đối chiếu với DB: độ phủ + tương quan với vị trí trang listing
    conn = sqlite3.connect("data/scraped.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT url, id, source_page, sold FROM oto_cars").fetchall()
    print(f"\n### Đối chiếu với {len(rows)} tin đã cào")
    hit = 0
    by_page: dict[int, list[str]] = {}
    for r in rows:
        lm = lastmods.get(r["url"])
        if not lm:
            continue
        hit += 1
        m = re.search(r"/p(\d+)", r["source_page"] or "")
        page = int(m.group(1)) if m else 1
        by_page.setdefault((page - 1) // 10 * 10 + 1, []).append(lm[:10])
    print(f"  có lastmod trong sitemap: {hit}/{len(rows)} ({hit / len(rows) * 100:.1f}%)")

    print("\n### lastmod trung vị theo nhóm trang listing (trang 1 = tin mới nhất)")
    for bucket in sorted(by_page):
        vals = sorted(by_page[bucket])
        print(f"  trang {bucket:>3}-{bucket + 9:<3}: n={len(vals):5d} | "
              f"trung vị {vals[len(vals) // 2]} | sớm {vals[0]} | muộn {vals[-1]}")
    conn.close()

    # đối chiếu với ngày chụp gần nhất (hôm nay)
    today = datetime.now().strftime("%Y-%m-%d")
    same_day = sum(1 for v in lastmods.values() if v.startswith(today))
    print(f"\n  lastmod trùng ngày chụp ({today}): {same_day} "
          f"({same_day / len(lastmods) * 100:.1f}%)")


if __name__ == "__main__":
    main()
