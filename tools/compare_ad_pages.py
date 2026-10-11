"""So sánh trang chi tiết tin CÒN BÁN vs ĐÃ BÁN để tìm dấu hiệu phân biệt thật.

Chạy: python -m tools.compare_ad_pages
"""

from __future__ import annotations

import re
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.http_client import ScraperSession  # noqa: E402

MARKERS = ("tel:", "data-phone", "btn-tel", "icon-phone", "btn-call",
           "Hết hạn", "hết hạn", "Đã bán", "đã bán", "sold", "Sold")


def inspect(session: ScraperSession, label: str, url: str, phone: str) -> None:
    resp = session.get(url)
    text = resp.text if resp is not None else ""
    print("=" * 76)
    print(f"### {label} | {url[:95]}")
    print(f"    HTTP {getattr(resp, 'status_code', None)} | {len(text)} bytes | "
          f"DB phone = {phone!r}")
    print("    --- đếm dấu hiệu ---")
    for marker in MARKERS:
        print(f"      {marker!r}: {text.count(marker)}")

    print("    --- nơi chứa số điện thoại (nếu có) ---")
    for m in re.finditer(re.escape(phone), text) if phone else []:
        seg = re.sub(r"\s+", " ", text[max(0, m.start() - 220): m.end() + 60])
        print(f"      ...{seg}...")
        break

    print("    --- phần tử có 'tel'/'phone'/'call' trong class ---")
    for m in re.finditer(r"<(\w+)[^>]*class=\"([^\"]*(?:tel|phone|call)[^\"]*)\"[^>]*>", text):
        attrs = m.group(0)
        attrs = re.sub(r"\s+", " ", attrs)[:150]
        print(f"      {attrs}")
        if len(attrs) > 3000:
            break

    print("    --- khối giá + nút cạnh giá (400 ký tự) ---")
    box = re.search(r'<div class="box-price">(.{0,700})', text, re.S)
    print("      ", re.sub(r"\s+", " ", box.group(1)) if box else "(không thấy box-price)")

    print("    --- khối box-salon (400 ký tự) ---")
    salon = re.search(r'<div class="box-salon">(.{0,650})', text, re.S)
    print("      ", re.sub(r"\s+", " ", salon.group(1)) if salon else "(không thấy box-salon)")


def main() -> None:
    conn = sqlite3.connect("data/scraped.db")
    conn.row_factory = sqlite3.Row
    avail = conn.execute(
        "SELECT url, phone FROM oto_cars WHERE sold=0 AND phone<>'' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    sold = conn.execute(
        "SELECT url, phone FROM oto_cars WHERE sold=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    with ScraperSession(delay=1.0) as session:
        inspect(session, "CÒN BÁN", avail["url"], avail["phone"] or "")
        inspect(session, "ĐÃ BÁN", sold["url"], sold["phone"] or "")


if __name__ == "__main__":
    main()
