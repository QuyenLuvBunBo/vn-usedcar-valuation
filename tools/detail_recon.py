"""Deep-dive into a listing detail page: JSON-LD, spec table, description, seller.

Run: python -m tools.detail_recon <listing_url>
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.common import storage  # noqa: E402
from src.common.http_client import ScraperSession  # noqa: E402

KEYWORDS = [
    "Mã tin", "Ngày đăng", "Ngày cập nhật", "Lượt xem", "Tình trạng", "Số km", "Km đã đi",
    "Nhiên liệu", "Hộp số", "Số chỗ", "Xuất xứ", "Kiểu dáng", "Màu ngoại thất",
    "Màu nội thất", "Dẫn động", "Động cơ", "Công suất", "Hãng xe", "Dòng xe",
    "Năm sản xuất", "Mô tả", "Trang bị", "Bảo hành", "Biển số", "Thông số", "Salon",
    "Địa chỉ", "Người bán", "Giá bán", "Số điện thoại",
]


def main() -> None:
    url = sys.argv[1]
    with ScraperSession(delay=0.5) as session:
        text = session.get_text(url)
    if text is None:
        print("could not fetch", url)
        return
    storage.save_raw(text, "recon_detail2")
    print(f"GET OK | {len(text)} bytes | saved to data/raw/recon_detail2.html")

    tree = html.fromstring(text)
    body = re.sub(r"\s+", " ", tree.xpath("//body")[0].text_content())

    print("\n########## 1. JSON-LD ##########")
    for i, block in enumerate(tree.xpath('//script[@type="application/ld+json"]/text()')):
        print(f"--- block {i} ({len(block)} chars) ---")
        try:
            data = json.loads(block)
            print(json.dumps(data, ensure_ascii=False)[:1200])
        except ValueError:
            print("(invalid JSON) raw:", block.strip()[:1200])

    print("\n########## 2. Spec label keywords (site wording, Vietnamese) ##########")
    for kw in KEYWORDS:
        n = body.count(kw)
        if n:
            sample = re.search(re.escape(kw) + r"[^|]{0,60}", body)
            print(f"  [{n:2d}x] {kw:16s} -> ...{sample.group(0)[:90] if sample else ''}...")

    print("\n########## 3. Candidate spec blocks (class names) ##########")
    cls_counter: Counter = Counter()
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        for c in (el.get("class") or "").split():
            if re.search(r"(spec|thong|tech|param|info|detail|desc|box|table)", c, re.I):
                cls_counter[c] += 1
    for c, n in cls_counter.most_common(25):
        print(f"  [{n:3d}x] {c}")

    print("\n########## 4. <ul>/<li> blocks with >=4 items (likely specs) ##########")
    for ul in tree.xpath("//ul"):
        items = [" ".join(li.itertext()).strip() for li in ul.xpath("./li")]
        items = [re.sub(r"\s+", " ", i) for i in items if i.strip()]
        if len(items) >= 4 and sum(len(i) for i in items) < 900:
            cls = ul.get("class")
            print(f"  <ul class={cls!r}> {len(items)} items: {items[:8]}")

    print("\n########## 5. Label: value pairs inside <p>/<div>/<span>/<td> ##########")
    for el in tree.xpath("//p|//div|//span|//td|//li"):
        txt = re.sub(r"\s+", " ", " ".join(el.itertext())).strip()
        if 4 <= len(txt) <= 60 and re.match(
            r"^(Mã tin|Ngày đăng|Tình trạng|Số km|Nhiên liệu|Hộp số|Số chỗ|Xuất xứ|Kiểu dáng|"
            r"Màu ngoại thất|Màu nội thất|Dẫn động|Hãng|Dòng xe|Năm sản xuất|Động cơ|Công suất)\s*[::]",
            txt,
        ):
            print(f"    <{el.tag} class={el.get('class')!r}> {txt}")


if __name__ == "__main__":
    main()
