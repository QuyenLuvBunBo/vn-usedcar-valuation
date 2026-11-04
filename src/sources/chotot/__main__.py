"""Command line entry point for the southern Chotot member."""
import argparse
from pathlib import Path
from src.common import config
from .geography import PROVINCES


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=str(config.DATA_RAW/'chotot_mien_nam'))
    parser.add_argument('--processed-out', default=str(config.DATA_PROCESSED))
    parser.add_argument('--db', default=str(config.ROOT/'data/scraped.db'))
    parser.add_argument('--provinces', default=','.join(PROVINCES))
    parser.add_argument('--urls', help='UTF-8 text file with one public URL per line')
    parser.add_argument('--max-records', type=int, default=500)
    parser.add_argument('--max-pages', type=int, default=700)
    parser.add_argument('--delay', type=float, default=config.REQUEST_DELAY)
    parser.add_argument('--headless', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--save-raw', action='store_true', help='Save decoded detail HTML and capture metadata')
    refresh = parser.add_mutually_exclusive_group()
    refresh.add_argument('--refresh', action='store_true', dest='refresh', help='Requeue completed URLs and update stored records (default)')
    refresh.add_argument('--resume', action='store_false', dest='refresh', help='Only process pending URLs')
    parser.set_defaults(refresh=True)
    parser.add_argument('--from-raw', action='store_true', help='Reparse saved HTML offline, without Playwright')
    parser.add_argument('--raw-html-dir', type=Path, default=config.DATA_RAW)
    args = parser.parse_args(argv)
    if args.max_records < 1 or args.max_pages < 1 or args.delay < 0:
        parser.error('Limits must be positive and delay must be nonnegative')
    if args.from_raw:
        from .offline import reparse_html
        from .unified import export
        raws = reparse_html(args.raw_html_dir)
        report = export(raws, Path(args.processed_out), {'mode': 'offline_html', 'input': args.out})
        print(f"Unique={report['unique_records']}; clean={report['clean_records']}; review={report['review_records']}")
        return 2 if report['parse_failures'] else 0
    from .crawl import crawl
    return crawl(args)


if __name__ == '__main__':
    raise SystemExit(main())
