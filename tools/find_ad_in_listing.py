"""Tin 'sitemap-only' có nằm trong listing theo HÃNG / theo DÒNG XE không?

Chạy: python -m tools.find_ad_in_listing <ad_id> <brand_slug> [model_slug]
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.http_client import ScraperSession  # noqa: E402

BASE = "https://oto.com.vn"


def scan(session: ScraperSession, path: str, ad_id: str, pages: int) -> None:
    """Quét vài trang listing, báo trang nào chứa tin."""
    found = []
    for page in range(1, pages + 1):
        url = f"{BASE}{path}" if page == 1 else f"{BASE}{path}/p{page}"
        text = session.get_text(url)
        if not text:
            print(f"    {path} p{page}: không lấy được")
            continue
        if ad_id in text:
            found.append(page)
        count = text.count('data-autoid=')
        print(f"    {path} p{page}: {count} thẻ tin | chứa {ad_id}: {'CÓ' if ad_id in text else 'không'}")
    if found:
        print(f"    => TÌM THẤY ở {path} trang {found}")
    else:
        print(f"    => KHÔNG thấy trong {pages} trang đầu của {path}")


def main() -> None:
    ad_id, brand = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else ""
    with ScraperSession(delay=1.2) as session:
        print(f"### Tin {ad_id} — quét listing theo hãng '{brand}'")
        scan(session, f"/mua-ban-xe-{brand}", ad_id, 4)
        if model:
            print(f"\n### Quét listing theo dòng xe '{brand}-{model}'")
            scan(session, f"/mua-ban-xe-{brand}-{model}", ad_id, 2)


if __name__ == "__main__":
    main()
