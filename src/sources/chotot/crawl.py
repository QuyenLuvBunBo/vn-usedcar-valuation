"""Southern Chotot crawler using the team's HTTP and storage APIs unchanged."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from src.common import config, storage
from src.common.http_client import ScraperSession
from .geography import PROVINCES
from .html_parser import parse_detail_page, parse_list_page
from .robots import BASE, Robots, canonical
from .storage import TABLE, QUEUE, init_records, upsert_record
from .unified import export, normalize, now


class StopCrawl(RuntimeError):
    pass


def to_unified(raw):
    return normalize(raw)[0]


def save_page(page_html, url, captured, kind):
    ident = re.search(r'/(\d+)\.htm$', urlsplit(url).path) if kind == 'detail' else None
    name = 'chotot_south_detail_' + ident[1] if ident else 'chotot_south_index_' + urlsplit(url).path.strip('/')
    path = storage.save_raw(page_html, name)
    path.with_suffix('.json').write_text(json.dumps({
        'source_url': url, 'scraped_at': captured,
    }), encoding='utf-8')
    return path


def crawl(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = storage.open_db(args.db)
    init_records(db, out / 'progress.sqlite')
    reason, fetched, collected = 'queue_exhausted', 0, 0
    session_started = now()

    def log(event, **values):
        item = {'time': now(), 'event': event, **values}
        with (out / 'crawl_log.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')
        print(json.dumps(item, ensure_ascii=False), flush=True)

    def enqueue(url, kind):
        url = canonical(url)
        if url:
            db.execute(f'INSERT OR IGNORE INTO {QUEUE}(url,kind) VALUES (?,?)', (url, kind))

    if args.urls:
        for url in Path(args.urls).read_text(encoding='utf-8-sig').splitlines():
            url = url.strip()
            if url and not url.startswith('#'):
                if canonical(url) is None:
                    raise ValueError('URL outside source scope: ' + url)
                enqueue(url, 'detail' if re.search(r'/\d+\.htm$', urlsplit(url).path) else 'index')
    else:
        for slug in args.provinces.split(','):
            slug = slug.strip()
            if slug not in PROVINCES:
                raise ValueError('Unknown province slug: ' + slug)
            enqueue(BASE + '/mua-ban-oto-' + slug, 'index')
    if args.refresh:
        db.execute(f'UPDATE {QUEUE} SET status="pending",error=NULL WHERE status IN ("done","unavailable")')
    db.commit()
    try:
        with ScraperSession(delay=max(1.5, args.delay)) as session:
            def fetch(url):
                nonlocal fetched
                fetched += 1
                response = session.get(url)
                if response is None:
                    raise StopCrawl('http_unavailable_or_access_denied')
                if not response.encoding or response.encoding.lower() == 'iso-8859-1':
                    response.encoding = response.apparent_encoding
                return response

            response = fetch(BASE + '/robots.txt')
            robots_text = response.text
            if 'user-agent:' not in robots_text.lower():
                raise StopCrawl('invalid_robots_response')
            (out / 'robots_observed.txt').write_text(robots_text, encoding='utf-8')
            robots = Robots(robots_text, agent=session.session.headers.get('User-Agent', config.USER_AGENT))
            session.delay = max(session.delay, robots.delay)
            while fetched < args.max_pages:
                if collected >= args.max_records:
                    reason = 'record_limit'
                    break
                item = db.execute(f'SELECT url,kind FROM {QUEUE} WHERE status="pending" ORDER BY rowid LIMIT 1').fetchone()
                if item is None:
                    break
                url, kind = item
                if not robots.allowed(url):
                    db.execute(f'UPDATE {QUEUE} SET status="blocked",error="robots_disallow" WHERE url=?', (url,))
                    db.commit()
                    log('robots_disallow', url=url)
                    continue
                log('fetch', kind=kind, url=url)
                response = fetch(url)
                current = canonical(response.url)
                if current is None or not robots.allowed(current):
                    raise StopCrawl('unexpected_redirect')
                page_html = response.text
                captured = config.now_iso()
                if args.save_raw:
                    save_page(page_html, current, captured, kind)
                if re.search(r'verify you are human|checking your browser|access denied', page_html, re.I):
                    raise StopCrawl('verification_or_security_screen')
                if kind == 'detail':
                    raw = parse_detail_page(page_html, current, captured)
                    if not raw['title'] or not raw['specs'].get('carbrand'):
                        raise StopCrawl('detail_requires_js_or_schema_changed')
                    row = to_unified(raw)
                    raw['source_url'] = row['source_url']
                    upsert_record(db, row['listing_id'], raw)
                    collected += 1
                else:
                    details, pages = parse_list_page(page_html, current)
                    if not details:
                        raise StopCrawl('empty_index_or_requires_js')
                    for detail in details:
                        enqueue(detail, 'detail')
                    for page in pages:
                        enqueue(page, 'index')
                db.execute(f'UPDATE {QUEUE} SET status="done",error=NULL WHERE url=?', (url,))
                db.commit()
            else:
                reason = 'page_limit'
    except KeyboardInterrupt:
        reason = 'interrupted'
        log('stopped', reason=reason)
    except Exception as exc:
        reason = str(exc)
        log('stopped', reason=reason)
    finally:
        try:
            raws = [json.loads(row['raw']) for row in storage.read_rows(db, TABLE)]
            with (out / 'raw.jsonl').open('w', encoding='utf-8') as stream:
                for raw in raws:
                    stream.write(json.dumps(raw, ensure_ascii=False) + '\n')
            statuses = dict(db.execute(f'SELECT status,COUNT(*) FROM {QUEUE} GROUP BY status'))
            report = export(raws, Path(args.processed_out), {
                'mode': 'crawler', 'session_started': session_started, 'stop_reason': reason,
                'http_get_calls_this_run': fetched, 'queue_status': statuses,
                'requested_max_records': args.max_records, 'database': str(args.db),
                'not_a_coverage_guarantee': True,
            })
        finally:
            db.close()
    print(f"Unique={report['unique_records']}; clean={report['clean_records']}; review={report['review_records']}; stop={reason}")
    return 0 if reason in ('queue_exhausted', 'record_limit', 'page_limit', 'interrupted') and not report['parse_failures'] else 2
