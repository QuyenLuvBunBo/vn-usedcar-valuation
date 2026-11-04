"""Real-time progress of the oto.com.vn archive crawl (tqdm bar from the log + DB counts).

Run:
    python -m tools.archive_progress            # one snapshot
    python -m tools.archive_progress --watch 5  # refresh every 5 s (Ctrl+C to stop)
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common import config  # noqa: E402

DEFAULT_LOG = config.LOGS_DIR / "archive_run.err"
DEFAULT_DB = config.ROOT / "data" / "scraped.db"
TABLE = "oto_archive"
BAR_RE = re.compile(r"(\d+)/(\d+) \[([\d:]+)<([\d:]+),\s+([\d.]+)(s/page|page/s)")


def last_bar(log_path: Path) -> str:
    """Return the last tqdm progress line the crawler wrote ('' if there is none yet)."""
    if not log_path.exists():
        return ""
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 40000))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    chunks = [c.strip() for c in tail.replace("\r", "\n").split("\n") if c.strip()]
    return chunks[-1] if chunks else ""


def db_stats(db_path: Path) -> tuple[int, str, str]:
    """(rows, first scraped_at, last scraped_at) of the archive table."""
    if not db_path.exists():
        return 0, "", ""
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute(
            f"SELECT COUNT(*), MIN(scraped_at), MAX(scraped_at) FROM {TABLE}"
        ).fetchone()
    except sqlite3.Error:
        return 0, "", ""
    finally:
        if conn is not None:
            conn.close()
    return int(row[0]), row[1] or "", row[2] or ""


def snapshot(log_path: Path, db_path: Path) -> None:
    """Print one progress snapshot."""
    bar = last_bar(log_path)
    rows, first, last = db_stats(db_path)

    print("-" * 74)
    print(f"crawler : {bar}" if bar else "crawler : (no progress line yet)")
    print(f"stored  : {rows:,} archive rows in {db_path.name}")

    if first and last:
        try:
            span = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds()
        except ValueError:
            span = 0
        if span > 0:
            print(f"rate    : {rows / span * 60:.1f} rows/min")

    match = BAR_RE.search(bar)
    if match:
        done, total = int(match.group(1)), int(match.group(2))
        if match.group(6) == "page/s":
            seconds_left = (total - done) / max(float(match.group(5)), 0.01)
        else:
            seconds_left = (total - done) * float(match.group(5))
        eta = time.strftime("%H:%M:%S", time.gmtime(seconds_left))
        print(f"progress: {done:,}/{total:,} = {done / total * 100:.1f}%  |  ETA {eta} (hh:mm:ss)")

    print("resume  : python -m src.sources.oto.archive     (skips already-crawled pages)")
    print("stop    : Stop-Process -Id <pid>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Progress viewer for the archive crawl")
    parser.add_argument("--watch", type=float, default=None, metavar="SECONDS",
                        help="keep refreshing every N seconds (Ctrl+C to stop)")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="crawler stderr log file")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database file")
    args = parser.parse_args()

    log_path, db_path = Path(args.log), Path(args.db)
    if args.watch:
        print(f"Watching {log_path} every {args.watch:g}s — press Ctrl+C to stop.")
        try:
            while True:
                snapshot(log_path, db_path)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nstopped.")
        return 0

    snapshot(log_path, db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
