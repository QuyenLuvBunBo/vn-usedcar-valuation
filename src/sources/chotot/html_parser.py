"""Parse decoded Chotot HTML with lxml. No JavaScript or network execution."""
import re
from lxml import html
from urllib.parse import urljoin, urlsplit
from src.common import config
from src.common.parsing import clean_text, text_of

KEYS = ('mileage_v2', 'carorigin', 'condition_ad', 'carbrand', 'carmodel',
        'mfdate', 'option', 'gearbox', 'fuel', 'cartype', 'carseats')
PHONE = re.compile(r'(?:\+84|0)(?:[ .-]?\d){9,10}\b')


def tree_from_text(page_html):
    if not isinstance(page_html, str):
        raise TypeError('Pass decoded HTML text, not bytes')
    return html.fromstring(page_html)


def parse_detail_page(page_html, url, scraped_at=None):
    tree = tree_from_text(page_html)
    def field(key):
        found = tree.xpath(f'//*[@itemprop="{key}"]')
        return text_of(found[0]) if found else None
    headings = tree.xpath('//h1')
    title = text_of(headings[0]) if headings else ''
    description = field('description') or ''
    prices = [text_of(node) for node in tree.xpath('//b')]
    price = next((s for s in prices if re.fullmatch(r'\d[\d.,\s]*\s*(đ|₫|VNĐ)|th[oỏ][aả]\s*thuận', s, re.I)), None)
    links = []
    for node in tree.xpath('//a[@href]'):
        text = text_of(node)
        if text.startswith('Ô tô '):
            links.append({'text': text, 'href': urljoin(url, node.get('href'))})
    mentions = re.findall(r'(?:trả\s*trước|đặt\s*cọc|trả\s*góp)[^\n;]{0,65}', description, re.I)
    return {
        'source_url': url, 'scraped_at': scraped_at or config.now_iso(),
        'title': PHONE.sub('[REDACTED]', title), 'specs': {k: field(k) for k in KEYS},
        'raw_price_text': price, 'province_links': links[:2],
        'has_store_link': bool(tree.xpath('//*[@itemprop="seller"]//a[contains(@href,"/cua-hang/")]')),
        'finance_mentions': [PHONE.sub('[REDACTED]', s) for s in mentions[:15]],
        'new_claim': bool(re.search(r'mới\s*100\s*%|chưa\s*(?:qua\s*)?sử\s*dụng', title + ' ' + description, re.I)),
    }


def parse_list_page(page_html, base_url):
    tree = tree_from_text(page_html)
    details, pages = [], []
    for node in tree.xpath('//a[@href]'):
        url = urljoin(base_url, node.get('href'))
        if re.search(r'/\d+\.htm$', urlsplit(url).path):
            details.append(url)
        elif urlsplit(url).path == urlsplit(base_url).path and (
                text_of(node).isdigit() or 'next' in (node.get('rel') or '').split()):
            pages.append(url)
    return list(dict.fromkeys(details)), list(dict.fromkeys(pages))
