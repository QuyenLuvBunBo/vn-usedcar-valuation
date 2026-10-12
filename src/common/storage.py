"""Data storage: raw HTML/JSON, JSONL, CSV and a deduplicating SQLite writer."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from . import config


# ------------------------------------------------------------------ raw data
def save_raw(content: str | bytes, name: str) -> Path:
    """Store a raw HTML/JSON response under data/raw so it can be re-parsed later."""
    config.ensure_dirs()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "page"
    path = config.DATA_RAW / f"{safe}.html"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def save_json(records: Iterable[dict], name: str) -> Path:
    """Write a list of records to JSON together with a capture timestamp."""
    config.ensure_dirs()
    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": None,
        "records": list(records),
    }
    payload["count"] = len(payload["records"])
    path = config.DATA_PROCESSED / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_jsonl(records: Iterable[dict], name: str, append: bool = False) -> Path:
    """Write one JSON object per line.

    Pass append=True to continue an existing file (large datasets). The default overwrites,
    so every export is a clean file without duplicated records.
    """
    config.ensure_dirs()
    path = config.DATA_PROCESSED / f"{name}.jsonl"
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def save_csv(records: Sequence[dict], name: str, fieldnames: Sequence[str] | None = None) -> Path:
    """Write CSV as UTF-8 with BOM so Excel opens Vietnamese text correctly."""
    config.ensure_dirs()
    path = config.DATA_PROCESSED / f"{name}.csv"
    if not records:
        path.write_text("", encoding="utf-8-sig")
        return path
    fields = list(fieldnames or records[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return path


# ---------------------------------------------------------------------- sqlite
def open_db(path: Path | str = "data/scraped.db") -> sqlite3.Connection:
    """Open (creating it if needed) the project SQLite database."""
    config.ensure_dirs()
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = config.ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_table(conn: sqlite3.Connection, table: str, columns: Sequence[str]) -> None:
    """Create a table whose `url` column is the PRIMARY KEY, so writes never duplicate."""
    cols_sql = ", ".join(f'"{c}" TEXT' for c in columns if c != "url")
    conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{table}" ('
        f'"url" TEXT PRIMARY KEY, {cols_sql}, '
        f'"scraped_at" TEXT)'
    )
    conn.commit()


def ensure_columns(conn: sqlite3.Connection, table: str, columns: Sequence[str]) -> None:
    """Add any missing columns to an existing table (a lightweight SQLite migration)."""
    existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    for column in columns:
        if column not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" TEXT')
    conn.commit()


def upsert_rows(conn: sqlite3.Connection, table: str, rows: Sequence[dict]) -> int:
    """Insert or refresh records, keyed on url.

    ON CONFLICT DO UPDATE (rather than INSERT OR IGNORE) means that re-running after a parser
    fix refreshes stale rows instead of keeping the old, wrong values forever.
    """
    if not rows:
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = list(rows[0].keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    names = ", ".join(f'"{c}"' for c in cols)
    updates = ", ".join(f'"{c}"=excluded."{c}"' for c in cols if c != "url")
    payload = [{**r, "scraped_at": now} for r in rows]
    cur = conn.executemany(
        f'INSERT INTO "{table}" ({names}, "scraped_at") VALUES ({placeholders}, :scraped_at) '
        f'ON CONFLICT("url") DO UPDATE SET {updates}, "scraped_at"=excluded."scraped_at"',
        payload,
    )
    conn.commit()
    return cur.rowcount


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    """Return the number of records currently stored in a table."""
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def read_rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Read a whole table into list[dict] (used to re-export CSV/JSONL without re-crawling)."""
    cursor = conn.execute(f'SELECT * FROM "{table}"')
    return [dict(row) for row in cursor.fetchall()]
