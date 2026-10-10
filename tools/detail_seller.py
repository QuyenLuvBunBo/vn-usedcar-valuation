"""Xác định khối người bán + input ẩn của TIN CHÍNH trên trang chi tiết.

Chạy: python -m tools.detail_seller [file.html] [data-autoid]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/recon_detail2.html")
    ad_id = sys.argv[2] if len(sys.argv) > 2 else None
    tree = html.fromstring(path.read_text(encoding="utf-8"))

    print("### Input ẩn trong trang")
    for inp in tree.xpath("//input[@type='hidden']"):
        iid, val = inp.get("id"), inp.get("value")
        if iid:
            print(f"  #{iid:22s} = {val!r}")

    print("\n### Nút gọi của TIN CHÍNH (data-phone) + tổ tiên 3 cấp")
    for a in tree.xpath("//a[@data-phone]"):
        pid = re.search(r"ProductId\\?\"?:(\d+)", a.get("datalayer-json") or "")
        pid = pid.group(1) if pid else "?"
        cls_chain = []
        node = a
        for _ in range(4):
            node = node.getparent()
            if node is None:
                break
            cls_chain.append(f"{node.tag}.{node.get('class')}")
        print(f"  data-phone={a.get('data-phone')} ProductId={pid} autoid={a.get('data-autoid')}")
        print(f"    tổ tiên: {' <- '.join(cls_chain)}")

    print("\n### Khối 'seller' / 'người bán' của tin chính")
    for el in tree.xpath('//*[contains(@class,"seller") or contains(@class,"nguoi-ban")]'):
        cls = el.get("class")
        txt = re.sub(r"\s+", " ", " ".join(el.itertext())).strip()[:160]
        print(f"  <{el.tag} class={cls!r}> {txt}")

    print("\n### Element chứa tên salon/công ty gần tiêu đề")
    for el in tree.xpath('//*[contains(@class,"info-title")] | //*[contains(@class,"name")]'):
        txt = re.sub(r"\s+", " ", " ".join(el.itertext())).strip()
        if txt and len(txt) < 120:
            print(f"  <{el.tag} class={el.get('class')!r}> {txt!r}")


if __name__ == "__main__":
    main()
