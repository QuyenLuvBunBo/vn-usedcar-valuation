"""Exercise collection, shared storage, refresh and export without live requests."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_offline import fixture_html
from src.sources.chotot.crawl import crawl
from src.common import config


class CrawlerTests(unittest.TestCase):
    def test_collect_refresh_and_robots_with_shared_apis(self):
        raw = json.loads((Path(__file__).with_name('fixtures')/'raw.jsonl').read_text(encoding='utf-8').splitlines()[0])
        seed = 'https://xe.chotot.com/mua-ban-oto-tp-ho-chi-minh'
        calls = []
        class FakeSession:
            def __init__(self, delay):
                self.delay = delay
                self.session = SimpleNamespace(headers={'User-Agent': 'TestCrawler'})
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def get(self, url):
                calls.append(url)
                if url.endswith('/robots.txt'):
                    text = 'User-agent: *\nAllow: /\nDisallow: /*page=\n'
                elif url == seed:
                    text = f'<a href="{raw["source_url"]}">Xe</a><a href="?page=2" rel="next">2</a>'
                else:
                    text = fixture_html(raw)
                return SimpleNamespace(text=text, encoding='utf-8', url=url)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = SimpleNamespace(out=root/'raw', processed_out=root/'processed', db=root/'scraped.db',
                                   urls=None, provinces='tp-ho-chi-minh', refresh=True, delay=1.5,
                                   max_pages=10, max_records=10, save_raw=True)
            with patch('src.sources.chotot.crawl.ScraperSession', FakeSession), patch.object(config, 'DATA_RAW', root/'html'):
                self.assertEqual(crawl(args), 0)
                raw['raw_price_text'] = '480.000.000 đ'
                self.assertEqual(crawl(args), 0)
            with (root/'processed/chotot_mien_nam.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['price_vnd'], '480000000')
            self.assertTrue(list((root/'html').glob('chotot_south_detail_*.html')))
            self.assertNotIn(seed + '?page=2', calls)
            self.assertEqual(calls.count(raw['source_url']), 2)

    def test_unavailable_source_exports_and_returns_failure(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = SimpleNamespace(out=root/'raw', processed_out=root/'processed', db=root/'scraped.db',
                                   urls=None, provinces='can-tho', refresh=True, delay=1.5,
                                   max_pages=10, max_records=10, save_raw=False)
            session = Mock()
            session.__enter__ = Mock(return_value=session)
            session.__exit__ = Mock(return_value=False)
            session.get.return_value = None
            with patch('src.sources.chotot.crawl.ScraperSession', return_value=session):
                self.assertEqual(crawl(args), 2)
            audit = json.loads((root/'processed/chotot_mien_nam/audit.json').read_text(encoding='utf-8'))
            self.assertEqual(audit['context']['stop_reason'], 'http_unavailable_or_access_denied')
            self.assertEqual(audit['unique_records'], 0)
