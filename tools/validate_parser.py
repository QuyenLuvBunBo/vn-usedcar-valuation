"""Kiểm tra parser trên HTML thô đã lưu: số record vs số thẻ tin, độ phủ field.

Chạy: python -m tools.validate_parser            # quét mọi file data/raw/oto_*.html
      python -m tools.validate_parser <file.html>
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lxml import html  # noqa: E402

from src.sources.oto.crawl import COLUMNS, ITEM_XPATH, parse_list_page  # noqa: E402


def check(path: Path) -> tuple[int, int, Counter, Counter]:
    text = path.read_text(encoding="utf-8")
    tree = html.fromstring(text.encode("utf-8"))
    raw_count = len(tree.xpath(ITEM_XPATH))
    records = parse_list_page(text, path.name)

    coverage: Counter = Counter()
    coverage_onsale: Counter = Counter()
    for rec in records:
        on_sale = not rec["sold"]
        for key, value in rec.items():
            if value not in (None, "", 0):
                coverage[key] += 1
                if on_sale:
                    coverage_onsale[key] += 1

    status = "OK " if len(records) == raw_count else "LỆCH"
    sold = sum(1 for r in records if r["sold"])
    print(f"[{status}] {path.name}: HTML {raw_count} thẻ | parser {len(records)} record | đã bán {sold}")
    return raw_count, len(records), coverage, coverage_onsale


def main() -> None:
    if len(sys.argv) > 1:
        files = [Path(sys.argv[1])]
    else:
        raw = Path("data/raw")
        files = sorted(raw.glob("oto_*_p*.html")) + sorted(raw.glob("diag_*.html")) + sorted(
            raw.glob("recon_brand.html")
        )
    if not files:
        print("Không có file HTML thô nào trong data/raw (chạy scraper với --save-raw trước).")
        return

    total_html = total_parsed = total_onsale = 0
    coverage: Counter = Counter()
    coverage_onsale: Counter = Counter()
    for path in files:
        if not path.exists():
            print("bỏ qua (không tồn tại):", path)
            continue
        raw_count, parsed, cov, cov_on = check(path)
        total_html += raw_count
        total_parsed += parsed
        total_onsale += cov_on.get("url", 0)
        coverage.update(cov)
        coverage_onsale.update(cov_on)

    print("\n################ TỔNG ################")
    print(f"HTML: {total_html} thẻ | parser: {total_parsed} record "
          f"({'KHỚP' if total_html == total_parsed else 'LỆCH!'})")
    print(f"Trong đó đang bán (sold=0): {total_onsale} | đã bán: {total_parsed - total_onsale}")

    print("\n################ ĐỘ PHỦ FIELD ################")
    print(f"{'field':14s} {'tất cả':>16s} {'chỉ tin đang bán':>20s}")
    for col in COLUMNS:
        if col == "sold":
            continue  # cờ 0/1, không phải field có/không
        n, n_on = coverage[col], coverage_onsale[col]
        pct = n / total_parsed * 100 if total_parsed else 0
        pct_on = n_on / total_onsale * 100 if total_onsale else 0
        flag = "" if pct_on >= 99 else "  <-- xem lại parser"
        print(f"  {col:14s} {n:5d} ({pct:5.1f}%) {n_on:8d} ({pct_on:5.1f}%){flag}")


if __name__ == "__main__":
    main()
