"""Live progress of the bonbanh detail crawl: how many cards still need a detail page, and the ETA.

    python tools/bonbanh_progress.py

Scope is the ads this top-up crawl added (the owners' files were crawled from detail pages already).
It only reads the SQLite table, so it is safe to run next to a crawl that is still working.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import storage
from src.sources.bonbanh.crawl import existing_ids

TABLE = "bonbanh_ad"
SECONDS_PER_PAGE = 1.7          # measured on the first 10 pages


def main(argv: list[str] | None = None) -> int:
    conn = storage.open_db()
    if not conn.execute("select name from sqlite_master where type='table' and name=?",
                        (TABLE,)).fetchone():
        print(f"table {TABLE} does not exist yet -> run: python -m src.sources.bonbanh")
        return 1

    known = existing_ids()
    rows = conn.execute(f'SELECT code, detail_done, body_detail, date_detail, seller_detail '
                        f'FROM "{TABLE}"').fetchall()
    conn.close()

    scope = [row for row in rows if f"BAN_{row['code']}" not in known]
    done = [row for row in scope if row["detail_done"] == "1"]
    failed = [row for row in scope if row["detail_done"] == "0"]
    # a row that has no posting date is still pending: it is re-fetched by the next --details run
    no_date = [row for row in done if not row["date_detail"]]
    pending = len(scope) - len(done) - len(failed) + len(no_date)
    total = len(scope)

    print(f"\nbonbanh detail crawl — {len(done):,}/{total:,} ads in scope "
          f"({len(rows) - total:,} ads skipped: already collected by their owners)")
    if total:
        filled = int(40 * len(done) / total)
        print(f"  [{'#' * filled}{'.' * (40 - filled)}] {len(done) / total * 100:5.1f}%")
    if done:
        body = sum(1 for row in done if row["body_detail"])
        date = sum(1 for row in done if row["date_detail"])
        print(f"\n  done     {len(done):>7,}   body_type {body / len(done) * 100:.0f}% · "
              f"listing_date {date / len(done) * 100:.0f}%")
        for name, count in Counter(row["seller_detail"] or "Unknown" for row in done).most_common():
            print(f"    seller {name:22s} {count:>7,}")
    print(f"  failed   {len(failed):>7,}")
    print(f"  pending  {pending:>7,}")

    if pending:
        seconds = int(pending * SECONDS_PER_PAGE)
        eta = time.strftime("%H:%M", time.localtime(time.time() + seconds))
        print(f"\n  ETA ~{timedelta(seconds=seconds)} at {SECONDS_PER_PAGE} s/request (done around {eta})")
    print("\n  next: python -m src.sources.bonbanh --details [--detail-limit N]")
    print("        python -m src.sources.bonbanh --reexport\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def main(argv: list[str] | None = None) -> int:
    conn = storage.open_db()
    exists = conn.execute("select name from sqlite_master where type='table' and name=?",
                          (TABLE,)).fetchone()
    if not exists:
        print(f"table {TABLE} does not exist yet -> run: python -m src.sources.bonbanh")
        return 1

    total_all = conn.execute(f'SELECT COUNT(*) FROM "{TABLE}"').fetchone()[0]
    done = conn.execute(f'SELECT COUNT(*) FROM "{TABLE}" '
                        f"WHERE detail_done = '1'").fetchone()[0]
    failed = conn.execute(f'SELECT COUNT(*) FROM "{TABLE}" '
                          f"WHERE detail_done = '0'").fetchone()[0]
    # only the ads this top-up crawl added need a detail page; the owners' files came from detail pages
    known_rows = conn.execute(f'SELECT code FROM "{TABLE}"').fetchall()
    conn.close()

    from src.sources.bonbanh.crawl import existing_ids
    known = existing_ids()
    total = sum(1 for row in known_rows if f"BAN_{row[0]}" not in known)
    done_scope = conn_done = 0
    conn = storage.open_db()
    for code, flag in conn.execute(f'SELECT code, detail_done FROM "{TABLE}"'):
        if f"BAN_{code}" in known:
            continue
        conn_done += 1 if flag == "1" else 0
    done_scope = conn_done
    conn.close()

    done, failed = done_scope, max(failed, 0)
    pending = max(total - done, 0)
    with_body = with_date = 0
    conn = storage.open_db()
    for body, date, flag in conn.execute(f'SELECT body_detail, date_detail, detail_done FROM "{TABLE}"'):
        pass
    conn.close()
    sellers = []

    bar_width = 40
    filled = int(bar_width * done / total) if total else 0
    print(f"\nbonbanh detail crawl — {done:,}/{total:,} cards")
    print(f"  [{'#' * filled}{'.' * (bar_width - filled)}] {done / total * 100:5.1f}%" if total else "")
    print(f"\n  done       {done:>7,}   (body_type {with_body / done * 100:.0f}%, "
          f"listing_date {with_date / done * 100:.0f}% of them)" if done else "")
    print(f"  failed     {failed:>7,}")
    print(f"  pending    {pending:>7,}")
    for name, count in sellers:
        print(f"  seller {str(name or 'Unknown'):22s} {count:>7,}")
    if pending:
        seconds = pending * 1.7                      # measured: ~1.7 s per detail page
        print(f"\n  ETA ~{timedelta(seconds=int(seconds))} at 1.7 s/request "
              f"(finished around {(time.strftime('%H:%M', time.localtime(time.time() + seconds)))})\n")
    print("  next: python -m src.sources.bonbanh --details [--detail-limit N]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
