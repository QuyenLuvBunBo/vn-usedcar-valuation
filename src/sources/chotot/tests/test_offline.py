import json
import tempfile
import unittest
from html import escape
from pathlib import Path
from src.sources.chotot.html_parser import parse_detail_page, parse_list_page
from src.sources.chotot.offline import reparse_html
from src.sources.chotot.unified import normalize


def fixture_html(raw):
    html = '<h1>' + escape(raw['title']) + '</h1><b>' + escape(raw['raw_price_text']) + '</b>'
    for key, value in raw['specs'].items():
        if value:
            html += f'<span itemprop="{key}">{escape(value)}</span>'
    for link in raw['province_links']:
        html += f'<a href="{escape(link["href"])}">{escape(link["text"])}</a>'
    return html


class OfflineHTMLTests(unittest.TestCase):
    def test_same_parser_offline_and_network_preserves_vietnamese(self):
        raw = json.loads((Path(__file__).with_name('fixtures') / 'raw.jsonl').read_text(encoding='utf-8').splitlines()[0])
        html = fixture_html(raw) + '<script>document.querySelector("h1").textContent="CORRUPTED"</script>'
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            (out / 'chotot_south_detail_1.html').write_text(html, encoding='utf-8')
            (out / 'chotot_south_detail_1.json').write_text(json.dumps(raw), encoding='utf-8')
            rebuilt = reparse_html(out)
        self.assertEqual(rebuilt[0], parse_detail_page(html, raw['source_url'], raw['scraped_at']))
        self.assertEqual(rebuilt[0]['title'], raw['title'])
        row, _, _ = normalize(rebuilt[0])
        self.assertEqual(row['brand'], 'Honda')
        self.assertEqual(row['location_province'], 'TP. Hồ Chí Minh')
        self.assertEqual(row['price_vnd'], 465000000)

    def test_links_and_decoded_html_contract(self):
        base = 'https://xe.chotot.com/mua-ban-oto-can-tho'
        details, pages = parse_list_page('<a href="/mua-ban-oto-can-tho/123.htm">Xe</a><a href="?page=2" rel="next">2</a>', base)
        self.assertEqual(details, [base + '/123.htm'])
        self.assertEqual(pages, [base + '?page=2'])
        with self.assertRaises(TypeError):
            parse_detail_page(b'<html/>', base)
