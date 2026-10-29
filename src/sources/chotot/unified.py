"""Normalize saved Chotot captures and export the southern member's CSV."""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from src.common import config, schema, storage
from src.common.schema import SCHEMA_COLUMNS as FIELDS
from src.common.parsing import parse_year_text
from .geography import PROVINCES
from .parsing import fold, integer, mileage, price

VERSION = '3.1.0'

def now():
    return datetime.now(timezone.utc).isoformat()

def province(raw):
    # Exact province breadcrumb beats URL suffix/new merged city footers.
    for a in raw.get('province_links',[]):
        slug = urlsplit(a.get('href','')).path.removeprefix('/mua-ban-oto-').strip('/')
        if slug in PROVINCES:
            return schema.normalize_province(PROVINCES[slug])
    return 'Unknown'


def category(raw, aliases, normalizer, allowed):
    value = normalizer(aliases.get(fold(raw), raw))
    return value if value in allowed else 'Unknown'

def normalize(raw):
    s = raw.get('specs',{})
    row = dict.fromkeys(FIELDS)
    url = raw.get('source_url','')
    ident = re.search(r'/([0-9]+)\.htm$', urlsplit(url).path)
    parts = urlsplit(url)
    if not ident or parts.scheme != 'https' or parts.netloc != 'xe.chotot.com' or not parts.path.startswith('/mua-ban-oto'):
        raise ValueError('Missing valid listing ID: '+url)
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    row.update(listing_id='CHOTOT_'+ident[1],source_platform='chotot',
               source_url=url, scraped_at=raw.get('scraped_at'),
               raw_price_text=raw.get('raw_price_text'), location_province=province(raw))
    for dest,key in [('brand','carbrand'),('model','carmodel'),('sub_model_trim','option')]:
        v = s.get(key)
        row[dest] = v.strip() if v and fold(v) not in ('khac','dang cap nhat') else ('Unknown' if dest in ('brand','model') else None)
    year_text = str(s.get('mfdate') or '')
    row['manufacture_year'] = parse_year_text(year_text) if re.fullmatch(r'\d{4}', year_text) else None
    row['mileage_km'] = mileage(s.get('mileage_v2'))
    row['seats'] = integer(s.get('carseats'))
    row['transmission'] = category(s.get('gearbox'), {
        'tu dong': 'số tự động', 'so tu dong': 'số tự động',
        'so san': 'số sàn', 'ban tu dong': 'số hỗn hợp',
    }, schema.normalize_transmission, schema.TRANSMISSION_VALUES)
    row['fuel_type'] = category(s.get('fuel'), {
        'dong co hybrid': 'hybrid',
    }, schema.normalize_fuel, schema.FUEL_VALUES)
    origin_aliases = {'viet nam': 'trong nước', 'lap rap trong nuoc': 'trong nước'}
    origin_aliases.update({country: 'nhập khẩu' for country in (
        'nhap khau', 'thai lan', 'nhat ban', 'han quoc', 'my', 'duc', 'trung quoc', 'indonesia', 'nuoc khac')})
    row['origin'] = category(s.get('carorigin'), origin_aliases, schema.normalize_origin, schema.ORIGIN_VALUES)
    row['body_type'] = category(s.get('cartype'), {
        'sedan': 'Sedan', 'suv': 'SUV', 'crossover': 'Crossover',
        'suv / cross over': 'Other', 'hatchback': 'Hatchback',
        'pick-up (ban tai)': 'bán tải', 'minivan (mpv)': 'MPV', 'van': 'Van',
        'coupe (2 cua)': 'Coupe', 'mui tran': 'mui trần',
    }, schema.normalize_body, schema.BODY_VALUES)
    # A verified store link supports dealership; its absence does NOT imply private seller.
    row['seller_type'] = 'Dealership/Salon' if raw.get('has_store_link') else 'Unknown'
    # Engine capacity and exact original listing date are not observed by this parser.
    # Never infer litres from model/trim or turn a bumped relative time into publication time.
    row['price_vnd'],row['price_status'],flags = price(row['raw_price_text'],raw.get('title',''),raw.get('finance_mentions',[]))
    year = row['manufacture_year']
    captured = datetime.fromisoformat(row['scraped_at'].replace('Z','+00:00'))
    if captured.tzinfo is None:
        raise ValueError('scraped_at must contain a timezone')
    row['scraped_at'] = captured.astimezone(timezone.utc).isoformat()
    capture_year = captured.year
    reasons=[]
    if row['brand'] == 'Unknown' or row['model'] == 'Unknown': reasons.append('missing_brand_or_model')
    if row['location_province'] == 'Unknown': reasons.append('outside_or_unknown_south')
    if fold(s.get('condition_ad')) != 'da su dung': reasons.append('not_confirmed_used')
    if raw.get('new_claim'): reasons.append('new_vehicle_claim')
    if year is None or not 1995 <= year <= capture_year: reasons.append('year_out_of_scope')
    if row['price_status'] != 'full': reasons.append('non_full_price')
    if row['price_vnd'] and not 30_000_000 <= row['price_vnd'] <= 25_000_000_000:
        reasons.append('price_scope_review')
    km = row['mileage_km']
    if km is not None and (km > 1_000_000 or (year and capture_year-year > 2 and km < 100)):
        reasons.append('mileage_review')
    if row['seats'] is not None and not 2 <= row['seats'] <= 16: reasons.append('seats_scope_review')
    for field in FIELDS:
        if row[field] in (None, '', 'Unknown'): flags.append('missing_'+field)
    if fold(s.get('cartype')) == 'suv / cross over': flags.append('ambiguous_suv_crossover')
    if row['fuel_type']=='Electric': flags.append('engine_capacity_not_applicable')
    return row, sorted(set(flags+reasons)), reasons

def write_csv(path, rows, fields):
    if rows:
        storage.save_csv(rows, str(path.resolve().with_suffix('')), fields)
    else:
        # Shared save_csv writes a BOM-only file when empty; retain the contract header.
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()

def export(raws, out, context=None):
    def capture_key(raw):
        try:
            stamp = datetime.fromisoformat(raw['scraped_at'].replace('Z', '+00:00'))
            return stamp.timestamp() if stamp.tzinfo else float('-inf')
        except (ValueError, TypeError, KeyError, AttributeError):
            return float('-inf')
    raws = sorted(raws, key=capture_key, reverse=True)
    out.mkdir(parents=True,exist_ok=True)
    diagnostics = out / 'chotot_mien_nam'
    diagnostics.mkdir(parents=True, exist_ok=True)
    all_rows=[]; clean=[]; review=[]; quality=[]; seen=set(); duplicates=0; errors=[]
    for raw in raws:
        try: row,flags,reasons=normalize(raw)
        except (ValueError,KeyError,TypeError,AttributeError) as e:
            errors.append({'source_url':raw.get('source_url'),'error':str(e)}); continue
        if row['listing_id'] in seen:
            duplicates+=1; continue
        seen.add(row['listing_id']); all_rows.append(row)
        (review if reasons else clean).append(row)
        quality.append({'listing_id':row['listing_id'],'quality_flags':';'.join(flags),
                        'exclusion_reasons':';'.join(reasons),'cohort':'review' if reasons else 'clean'})
    for name,rows,fields in [('chotot_mien_nam.csv',clean,FIELDS),('all_21.csv',all_rows,FIELDS),('clean_21.csv',clean,FIELDS),
            ('review_21.csv',review,FIELDS),
            ('quality.csv',quality,['listing_id','cohort','quality_flags','exclusion_reasons'])]:
        destination = out if name == 'chotot_mien_nam.csv' else diagnostics
        write_csv(destination/name,rows,fields)
    n=len(all_rows)
    report={'parser_version':VERSION,'generated_at':now(),'raw_records':len(raws),
        'unique_records':n,'duplicate_captures':duplicates,'parse_failures':errors,
        'duplicate_rate':duplicates/len(raws) if raws else None,
        'clean_records':len(clean),'review_records':len(review),
        'capture_start':min((r['scraped_at'] for r in all_rows),default=None),
        'capture_end':max((r['scraped_at'] for r in all_rows),default=None),
        'province_counts':dict(Counter(r['location_province'] or 'Unknown' for r in all_rows)),
        'price_status_counts':dict(Counter(r['price_status'] for r in all_rows)),
        'non_full_price_rate':sum(r['price_status']!='full' for r in all_rows)/n if n else None,
        'missing_rates':{k:sum(r[k] in (None, '', 'Unknown') for r in all_rows)/n if n else None for k in FIELDS},
        'exclusion_counts_nonexclusive':dict(Counter(x for q in quality for x in q['exclusion_reasons'].split(';') if x)),
        'schema_verification':'team_repository_src_common_schema',
        'context':context or {}}
    (diagnostics/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default=str(config.DATA_RAW/'chotot_mien_nam/raw.jsonl'))
    parser.add_argument('--out', default=str(config.DATA_PROCESSED))
    args = parser.parse_args(argv)
    raws = [json.loads(line) for line in Path(args.input).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    report = export(raws, Path(args.out), {'mode': 'offline_normalization', 'input': str(args.input)})
    print(f"Unique={report['unique_records']}; clean={report['clean_records']}; review={report['review_records']}")
    return 2 if report['parse_failures'] else 0

if __name__ == '__main__':
    raise SystemExit(main())
