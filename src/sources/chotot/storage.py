"""Source table adapter using the unmodified team's storage API."""
import json
import sqlite3
from src.common import storage

TABLE = 'chotot_south_raw'
QUEUE = 'chotot_south_queue'


def upsert_record(db, ident, raw):
    storage.upsert_rows(db, TABLE, [{
        'url': raw['source_url'], 'id': ident, 'raw': json.dumps(raw, ensure_ascii=False),
    }])


def init_records(db, legacy_path=None):
    storage.create_table(db, TABLE, ['id', 'raw'])
    db.execute(f'CREATE TABLE IF NOT EXISTS {QUEUE}(url TEXT PRIMARY KEY, kind TEXT, status TEXT DEFAULT "pending", error TEXT)')
    existing_urls = {row['url'] for row in storage.read_rows(db, TABLE)}
    sources = [db]
    external = None
    if legacy_path and legacy_path.exists():
        external = sqlite3.connect(legacy_path)
        sources.append(external)
    try:
        for source in sources:
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('source_records', 'records'):
                if table not in tables:
                    continue
                for ident, payload in source.execute(f'SELECT id,raw FROM {table}'):
                    raw = json.loads(payload)
                    if raw['source_url'] not in existing_urls:
                        upsert_record(db, ident, raw)
                        existing_urls.add(raw['source_url'])
            if 'queue' in tables:
                for row in source.execute('SELECT url,kind,status,error FROM queue'):
                    db.execute(f'INSERT OR IGNORE INTO {QUEUE}(url,kind,status,error) VALUES (?,?,?,?)', tuple(row))
        db.commit()
    finally:
        if external:
            external.close()
