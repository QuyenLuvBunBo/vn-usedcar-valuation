"""Đo các trường hợp data-call của site bị lỗi định dạng (vd giá chứa '...').

Chạy: python -m tools.diag_ellipsis
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.oto_scraper import ITEM_XPATH, parse_data_call  # noqa: E402


def main() -> None:
    files = sorted(Path("data/raw").glob("oto_*_p*.html"))
    print(f"Quét {len(files)} file HTML thô\n")

    total = parsed_ok = empty_body = with_ellipsis = 0
    samples: list[str] = []

    for path in files:
        text = path.read_text(encoding="utf-8")
        tree = html.fromstring(text.encode("utf-8"))
        for item in tree.xpath(ITEM_XPATH):
            # chỉ xét tin đang bán (tin đã bán không có data-call)
            dc = item.xpath('.//a[contains(@class,"btn-tel")]/@data-call')
            if not dc:
                continue
            dc = dc[0]
            total += 1
            if ".." in dc:
                with_ellipsis += 1
            info = parse_data_call(dc)
            if info:
                parsed_ok += 1
                if not info["body_type"]:
                    empty_body += 1
                    if len(samples) < 6:
                        samples.append(dc)

    print(f"Tin có data-call           : {total}")
    print(f"Bóc thành công             : {parsed_ok} ({parsed_ok / total * 100:.1f}%)")
    print(f"data-call chứa '..' (lỗi)  : {with_ellipsis} ({with_ellipsis / total * 100:.1f}%)")
    print(f"Bóc được nhưng body_type rỗng: {empty_body} ({empty_body / total * 100:.1f}%)")
    print("\nMẫu data-call có body_type rỗng:")
    for s in samples:
        print("  ", s)


if __name__ == "__main__":
    main()
