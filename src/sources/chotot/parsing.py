"""Chotot format adapters and financing evidence; shared helpers do conversions."""
import re
import unicodedata
from src.common import parsing, schema


def fold(value):
    value = str(value or '').lower().replace('đ', 'd')
    return ''.join(c for c in unicodedata.normalize('NFD', value) if not unicodedata.combining(c)).strip()


def integer(text):
    value = str(text or '').strip()
    return parsing.to_int(value) if re.fullmatch(r'\d+', value) else None


def money(text):
    # Validate a complete price expression before calling the permissive team parser.
    value = fold(text)
    value = re.sub(r'\s*(?:vnd\.?|dong|₫|d)\s*$', '', value).strip()
    token = r'(\d+(?:[.,]\d+)*)\s*(ty|ti|trieu|trd|tr|k|nghin|ngan)\b'
    chunks = list(re.finditer(token, value))
    if chunks:
        if re.sub(token, '', value).strip():
            return None
        aliases = {'ty': 'tỷ', 'ti': 'tỉ', 'trieu': 'triệu', 'trd': 'tr', 'tr': 'tr',
                   'k': 'nghìn', 'nghin': 'nghìn', 'ngan': 'ngàn'}
        parts = []
        for match in chunks:
            number = match[1]
            if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+', number):
                number = number.replace('.', '').replace(',', '')
            elif not re.fullmatch(r'\d+(?:[.,]\d+)?', number):
                return None
            parts.append(number + ' ' + aliases[match[2]])
        amount = parsing.parse_vnd_price(' '.join(parts))
    else:
        if not re.fullmatch(r'\d+|\d{1,3}(?:[.,]\d{3})+', value):
            return None
        amount = parsing.to_int(value.replace('.', '').replace(',', ''))
    return amount if amount and amount > 0 else None


def mileage(text):
    value = fold(text)
    match = re.fullmatch(r'(\d+(?:[.,]\d+)*)\s*(van|nghin|ngan)?\s*(?:km)?', value)
    if not match:
        return None
    number, unit = match.groups()
    if unit:
        count = parsing.to_float(number.replace(',', '.'))
        if count is None:
            return None
        scaled = count * (10000 if unit == 'van' else 1000)
        if not scaled.is_integer():
            return None
        number = str(int(scaled))
    elif not re.fullmatch(r'\d+|\d{1,3}(?:[.,]\d{3})+', number):
        return None
    return parsing.parse_km_text(number)


def price(text, title='', mentions=()):
    raw = fold(text)
    if re.search(r'thoa thuan|thuong luong|lien he', raw):
        return None, schema.price_status(None, 'Thỏa thuận'), []
    if re.search(r'tra\s*truoc|dat\s*coc|/\s*thang|tra\s*gop', raw):
        return None, schema.price_status(None, 'trả góp'), []
    amount = money(text)
    if amount is None:
        return None, schema.price_status(None, text), ['missing_or_unparseable_price']
    marker = r'(?:tra\s*truoc|dat\s*coc|tra\s*gop)'
    for evidence in [fold(title), *(fold(t) for t in mentions)]:
        for match in re.finditer(marker + r'\s*(?:(?:chi|tu|la)\s*)?[:=]?\s*(\d+(?:[.,]\d+)*\s*(?:(?:ty|ti|trieu|tr|k|nghin|vnd|dong|d)\b)?)', evidence):
            if money(match[1]) == amount:
                return None, schema.price_status(None, 'trả góp'), ['advertised_price_matches_down_payment']
    if re.search(marker + r'|gop\s*noi|/\s*thang', fold(title)):
        return None, 'invalid', ['ambiguous_financing_title']
    return amount, schema.price_status(amount, text), []
