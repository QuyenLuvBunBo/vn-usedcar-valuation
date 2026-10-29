import copy
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.sources.chotot.storage import init_records, upsert_record, TABLE
from src.common.schema import SCHEMA_COLUMNS, TRANSMISSION_VALUES, FUEL_VALUES, ORIGIN_VALUES, BODY_VALUES, SELLER_VALUES
from src.sources.chotot.unified import export, normalize
from tools.validate_source_csv import validate

FIXTURE = Path(__file__).with_name('fixtures') / 'raw.jsonl'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(FIXTURE.read_text(encoding='utf-8').splitlines()[0])

    def test_legacy_migration_and_url_refresh(self):
        with sqlite3.connect(':memory:') as db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TABLE records(id TEXT PRIMARY KEY, raw TEXT)')
            db.execute('INSERT INTO records VALUES (?,?)', ('CHOTOT_test', json.dumps(self.raw)))
            init_records(db)
            changed = dict(self.raw, raw_price_text='480 triệu')
            upsert_record(db, 'CHOTOT_test', changed)
            init_records(db)  # legacy snapshot cannot overwrite refreshed records
            rows = db.execute(f'SELECT raw FROM {TABLE}').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0][0])['raw_price_text'], '480 triệu')

    def test_latest_capture_wins_across_timezones(self):
        older = dict(self.raw, scraped_at='2026-10-17T10:00:00+07:00')
        newer = dict(self.raw, scraped_at='2026-10-17T04:00:00Z', raw_price_text='480 triệu')
        with tempfile.TemporaryDirectory() as folder:
            report = export([older, newer], Path(folder))
            self.assertEqual(report['duplicate_captures'], 1)
            with (Path(folder) / 'chotot_mien_nam.csv').open(encoding='utf-8-sig', newline='') as f:
                self.assertEqual(list(csv.DictReader(f))[0]['price_vnd'], '480000000')
            self.assertEqual(validate(Path(folder) / 'chotot_mien_nam.csv'), 0)

    def test_invalid_input_is_reported_and_missing_brand_reviewed(self):
        invalid = dict(self.raw, scraped_at='bad timestamp')
        foreign = dict(self.raw, source_url='https://other.example/mua-ban-oto/123.htm')
        missing = copy.deepcopy(self.raw)
        missing['specs']['carbrand'] = None
        with tempfile.TemporaryDirectory() as folder:
            report = export([invalid, foreign, missing], Path(folder))
            self.assertEqual(len(report['parse_failures']), 2)
            self.assertEqual(report['clean_records'], 0)
            self.assertEqual(report['review_records'], 1)

    def test_validator_rejects_twenty_columns_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'chotot_mien_nam.csv'
            export([self.raw], Path(folder))
            with path.open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.reader(f))
            with path.open('w', encoding='utf-8-sig', newline='') as f:
                csv.writer(f).writerows(rows + [rows[1]])
            self.assertGreater(validate(path), 0)
            with path.open('w', encoding='utf-8-sig', newline='') as f:
                csv.writer(f).writerows([r[:-1] for r in rows])
            self.assertGreater(validate(path), 0)

    def test_team_categorical_values_and_column_order(self):
        raw = copy.deepcopy(self.raw)
        raw['specs'].update(gearbox='Bán tự động', cartype='SUV / Cross over', fuel=None, carorigin=None)
        raw['has_store_link'] = False
        row, flags, _ = normalize(raw)
        self.assertEqual(row['transmission'], 'Other')
        self.assertEqual(row['body_type'], 'Other')
        self.assertIn('ambiguous_suv_crossover', flags)
        self.assertEqual(row['fuel_type'], 'Unknown')
        self.assertEqual(row['origin'], 'Unknown')
        self.assertEqual(row['seller_type'], 'Unknown')
        self.assertEqual(list(row), SCHEMA_COLUMNS)
        self.assertLess(SCHEMA_COLUMNS.index('listing_date'), SCHEMA_COLUMNS.index('scraped_at'))
        for key, allowed in [('transmission', TRANSMISSION_VALUES), ('fuel_type', FUEL_VALUES),
                             ('origin', ORIGIN_VALUES), ('body_type', BODY_VALUES), ('seller_type', SELLER_VALUES)]:
            self.assertIn(row[key], allowed)


if __name__ == '__main__':
    unittest.main()
