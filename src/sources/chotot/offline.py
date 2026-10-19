"""Reparse decoded saved detail HTML with the same parser as the crawler."""
import json
from .html_parser import parse_detail_page


def reparse_html(raw_dir):
    files = sorted(set(raw_dir.glob('chotot_south_detail_*.html')) | set((raw_dir / 'html').glob('*.html')))
    if not files:
        raise SystemExit('No saved detail HTML. Use --save-raw, or unified --input for existing JSONL.')
    records = []
    for file in files:
        metadata = json.loads(file.with_suffix('.json').read_text(encoding='utf-8'))
        records.append(parse_detail_page(file.read_text(encoding='utf-8'), metadata['source_url'], metadata['scraped_at']))
    return records
