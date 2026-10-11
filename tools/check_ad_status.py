"""Kiểm tra tình trạng thật của tin nằm trong sitemap nhưng không có trong listing.

Chạy: python -m tools.check_ad_status [so_mau]
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.common.http_client import ScraperSession  # noqa: E402
from src.sources.oto.crawl import parse_detail_page  # noqa: E402

CACHE = "data/raw/sitemap_lastmod.json"


def ad_status(session: ScraperSession, url: str) -> dict:
    """Xác định tin còn bán hay không dựa trên nút gọi CỦA CHÍNH tin đó."""
    resp = session.get(url)
    if resp is None:
        return {"url": url, "status": "lỗi"}
    if "/NotFound" in resp.url:
        return {"url": url, "status": "404"}

    html_text = resp.text
    ad_id = re.search(r"-aidx[a-z]*(\d+)$", url)
    ad_id = ad_id.group(1) if ad_id else ""
    detail = parse_detail_page(html_text, url)
    specs = json.loads(detail["d_specs"] or "{}")

    # nút gọi của chính tin: data-autoid trùng id tin và có data-phone
    own_call = re.findall(
        r'<a[^>]*class="[^"]*btn-tel[^"]*"[^>]*data-phone="(\d+)"[^>]*data-autoid="(\d+)"', html_text
    ) + re.findall(
        r'<a[^>]*data-autoid="(\d+)"[^>]*data-phone="(\d+)"', html_text
    )
    own_phone = next((p for p, i in own_call if i == ad_id), "")
    # nút gọi có thể chứa id ở attribute data-autoid hoặc trong datalayer-json ProductId
    if not own_phone:
        block = re.findall(r'data-phone="(\d+)"[^>]*datalayer-json=\'[^\']*"ProductId":(\d+)', html_text)
        own_phone = next((p for p, i in block if i == ad_id), "")

    return {
        "url": url,
        "status": resp.status_code,
        "title": detail["d_title"],
        "condition": specs.get("Tình trạng", ""),
        "price": detail["d_price_vnd"],
        "own_phone": own_phone,
        "call_btn": bool(own_phone),
        "expired_text": bool(re.search(r"(tin đã hết hạn|đã bán|Tin hết hạn|Hết hạn)", html_text)),
    }


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "8"
    conn = sqlite3.connect("data/scraped.db")
    conn.row_factory = sqlite3.Row

    if mode == "control":
        # Đối chứng: tin biết chắc còn bán (sold=0) vs đã bán (sold=1)
        avail = [r["url"] for r in conn.execute(
            "SELECT url FROM oto_cars WHERE sold=0 AND phone<>'' LIMIT 4")]
        sold = [r["url"] for r in conn.execute(
            "SELECT url FROM oto_cars WHERE sold=1 LIMIT 4")]
        conn.close()
        print("### ĐỐI CHỨNG (kỳ vọng: còn bán -> CÓ nút gọi, đã bán -> KHÔNG)\n")
        with ScraperSession(delay=1.2) as session:
            for label, urls in (("còn bán", avail), ("đã bán", sold)):
                for url in urls:
                    info = ad_status(session, url)
                    print(f"  [{label:8s}] nút gọi riêng={'CÓ' if info.get('call_btn') else 'KHÔNG'} "
                          f"({info.get('own_phone')}) | {info.get('title')!r}")
        return

    n = int(mode)
    with open(CACHE, encoding="utf-8") as fh:
        sitemap_urls = list(json.load(fh).keys())
    ours = {r[0] for r in conn.execute("SELECT url FROM oto_cars")}
    conn.close()

    extra = [u for u in sitemap_urls if u not in ours]
    sample = random.Random(7).sample(extra, min(n, len(extra)))
    print(f"Sitemap {len(sitemap_urls):,} | đã cào {len(ours):,} | thử {len(sample)} tin CHƯA cào\n")

    with ScraperSession(delay=1.5) as session:
        for url in sample:
            info = ad_status(session, url)
            print(f"  [{info.get('status')}] {info.get('title')!r} | tình trạng={info.get('condition')!r} "
                  f"| giá={info.get('price')} | nút gọi riêng={'CÓ' if info.get('call_btn') else 'KHÔNG'}"
                  f" ({info.get('own_phone')}) | text hết hạn={info.get('expired_text')}")
            print(f"        {url[:110]}")


if __name__ == "__main__":
    main()
