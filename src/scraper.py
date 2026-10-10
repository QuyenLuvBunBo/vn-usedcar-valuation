"""Template scraper hoàn chỉnh — mặc định cào https://books.toscrape.com (site luyện tập).

Chạy:  python -m src.scraper
Khi có trang thật, chỉ cần sửa START_URL, TABLE và hàm `parse_list_page`.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from lxml import html
from tqdm import tqdm

from . import config, storage
from .http_client import ScraperSession

# ----------------------------------------------------------------- cấu hình
START_URL = "https://books.toscrape.com/catalogue/page-1.html"
MAX_PAGES = 3  # giới hạn khi thử nghiệm; đặt None để cào tới hết
TABLE = "books"
COLUMNS = ["url", "title", "price"]

log = logging.getLogger("scraper")


def setup_logging() -> None:
    """Ghi log ra console và logs/scrape.log."""
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.LOGS_DIR / "scrape.log", encoding="utf-8"),
        ],
    )


# -------------------------------------------------------------------- parse
def parse_list_page(page_html: str, base_url: str) -> tuple[list[dict], str | None]:
    """Bóc dữ liệu 1 trang danh sách.

    Trả về (danh sách record, URL trang kế tiếp hoặc None nếu hết).
    Đây là hàm DUY NHẤT cần viết lại cho từng website.
    """
    tree = html.fromstring(page_html)

    rows: list[dict] = []
    for card in tree.xpath('//article[@class="product_pod"]'):
        title = card.xpath(".//h3/a/@title")
        price = card.xpath('.//p[@class="price_color"]/text()')
        href = card.xpath(".//h3/a/@href")
        if not (title and price and href):
            continue
        url = urljoin(base_url, href[0])
        rows.append(
            {
                "url": url,  # khóa duy nhất -> chống ghi trùng
                "title": title[0].strip(),
                "price": price[0].strip(),
            }
        )

    next_href = tree.xpath('//li[@class="next"]/a/@href')
    next_url = urljoin(base_url, next_href[0]) if next_href else None
    return rows, next_url


# --------------------------------------------------------------------- main
def main() -> None:
    setup_logging()

    conn = storage.open_db()
    storage.create_table(conn, TABLE, COLUMNS)
    log.info("DB hiện có %s record trong bảng '%s'", storage.count_rows(conn, TABLE), TABLE)

    url: str | None = START_URL
    page_no = 0
    all_rows: list[dict] = []

    with ScraperSession() as session:
        with tqdm(desc="Cào dữ liệu", unit=" trang") as bar:
            while url and (MAX_PAGES is None or page_no < MAX_PAGES):
                page_no += 1
                page_html = session.get_text(url, headers={"Referer": url})
                if page_html is None:
                    log.error("Không lấy được trang: %s", url)
                    break

                storage.save_raw(page_html, f"{TABLE}_page{page_no:03d}")
                rows, next_url = parse_list_page(page_html, url)
                all_rows.extend(rows)
                bar.update(1)
                bar.set_postfix_str(f"{len(rows)} record/trang")

                log.info("Trang %s -> %s record", page_no, len(rows))
                url = next_url

    inserted = storage.upsert_rows(conn, TABLE, all_rows)
    csv_path = storage.save_csv(all_rows, TABLE, COLUMNS)
    log.info("Cào xong: %s record mới, %s record trong DB", inserted, storage.count_rows(conn, TABLE))
    log.info("Đã lưu CSV: %s", csv_path)
    conn.close()


if __name__ == "__main__":
    main()
