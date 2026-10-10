# IntroDS — Web Scraping

Bộ khung cào dữ liệu web (Python 3.14 trên Windows) + scraper thực tế cho
**oto.com.vn** (xe cũ nhóm phổ thông châu Á).

## Cấu trúc

```
.
├─ .venv/                # môi trường ảo (không commit)
├─ requirements.txt
├─ .env.example          # copy thành .env rồi điền token/cookie/proxy
├─ data/
│  ├─ raw/               # HTML/JSON thô -> luôn lưu trước khi parse
│  └─ processed/         # CSV/JSONL đã làm sạch
├─ logs/                 # log chạy
├─ src/                  # code cào + parse
│  ├─ config.py          # cấu hình đọc từ .env
│  ├─ http_client.py     # session + retry/backoff + rate limit
│  ├─ storage.py         # lưu raw/CSV/JSONL/SQLite (chống trùng)
│  ├─ scraper.py         # scraper mẫu (books.toscrape.com)
│  └─ oto_scraper.py     # scraper oto.com.vn
└─ tools/                # script recon & kiểm tra parser
```

## Cài đặt

```powershell
cd f:\Code\IntroDS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium   # chỉ cần khi phải render JavaScript
```

## Scraper oto.com.vn (xe cũ: Toyota, Hyundai, Kia, Mazda, Honda, Mitsubishi)

```powershell
python -m src.oto_scraper                       # cào cả 6 hãng
python -m src.oto_scraper --brands toyota kia   # chỉ 1 vài hãng
python -m src.oto_scraper --pages 3             # giới hạn 3 trang/hãng (test nhanh)
python -m src.oto_scraper --include-new         # lấy cả tin "Xe mới"
python -m src.oto_scraper --exclude-sold        # bỏ tin đã bán
python -m src.oto_scraper --save-raw            # lưu thêm HTML thô từng trang
python -m src.oto_scraper --from-raw            # sửa parser xong: parse lại HTML thô, không cào lại
python -m src.oto_scraper --from-db             # chỉ xuất lại CSV/JSONL từ DB
```

Kết quả: `data/processed/oto_cars.csv`, `data/processed/oto_cars.jsonl`,
bảng `oto_cars` trong `data/scraped.db`.

### Cách site hoạt động (kết quả recon)

| Đặc điểm | Phát hiện |
|---|---|
| robots.txt | `User-agent: *` → `Allow: /`; `/mua-ban-xe*` **không** bị chặn |
| Kiểu render | HTML tĩnh, server-render (~330 KB/trang, không cần JS) |
| Listing | `https://oto.com.vn/mua-ban-xe-<brand>`, 15 tin/trang |
| Phân trang | `/p<N>` (vd `/mua-ban-xe-toyota/p2`) |
| Trang vượt giới hạn | KHÔNG 404 — trả "0 tin" + rơi về danh sách trang 1 → phải dừng theo tổng số |
| Tổng số tin | đọc từ text `Có N tin bán xe ...` |
| Nguồn cấu trúc | `data-tinrao` = `hãng.model.tình trạng.id.viptype`; `data-call` = `hãng.model.tình trạng.xuất xứ.năm.giá.loại xe.màu.listtype.viptype.id` |
| Tin **đã bán** | tin cũ (từ ~trang 15 trở đi) bị thêm class `sold` và site gỡ nút "Gọi ngay" → mất `phone`, `xuất xứ`, `loại xe`, `màu`, `listtype`. Cột `sold` đánh dấu để lọc |
| Trang chi tiết | không có ngày đăng/JSON-LD Product → bỏ qua để tiết kiệm request |

## Các field cào được

`id, url, brand, model, car_name, title, condition, sold, origin, year, price_text,
price_vnd, km, gearbox, fuel, body_type, color, province, seller_name, phone,
vip_type, listing_type, image_url, source_page`

> `sold = 1` là tin đã bán: vẫn có giá/năm/km nhưng thiếu `origin`, `body_type`,
> `color`, `listing_type`, `phone` (site đã gỡ nút gọi). Dùng `--exclude-sold`
> nếu chỉ muốn xe đang bán.

## Kết quả lần cào gần nhất (11/10/2026)

| Chỉ số | Giá trị |
|---|---|
| Tổng tin | **2.706** (đã loại trùng theo url) |
| Theo hãng | Toyota 892 · Hyundai 534 · Kia 505 · Mazda 379 · Mitsubishi 203 · Honda 193 |
| Tin đã bán (`sold=1`) | 1.294 (47,8%) |
| Tin đang bán | 1.412 |
| Có giá | 2.484 / 2.706 (91,8%) — trung vị **555 triệu**, thấp nhất 30 triệu, cao nhất 5,47 tỷ |
| Giá trung vị theo hãng | Toyota 585 · Mazda 586 · Kia 562 · Honda 548 · Hyundai 542 · Mitsubishi 474 (triệu đồng) |
| Năm sản xuất | 1990 – 2026, trung vị 2021 |
| Số km | trung vị 58.140 km |
| Tỉnh/thành | Hà Nội 1.548 · Tp.HCM 588 · Hưng Yên 113 |

**Chất lượng dữ liệu** (đã kiểm chứng bằng tool, không phải phỏng đoán):

- 0 tin trùng `url`/`id`.
- 1.427 tin có `data-call` (tin đang bán) → bóc thành công 1.427/1.427 (100%).
- Toàn bộ `origin`/`phone`/`listing_type` rỗng = đúng 1.294 tin đã bán (site gỡ nút
  "Gọi ngay"), không phải lỗi parser.
- 43 tin (3%) thiếu `body_type`/`color` vì chính `data-call` của site sai định dạng
  (giá bị thêm `...`, vd `2010.268 triệu...F0`).
- 222 tin không có giá → 221 trong đó là tin đã bán.
- Vài tin có `km` rất lớn (12.000.000 km) là do **site ghi vậy** trong tag
  (`tag-list = ['12.000.000 km', ...]`), parser giữ nguyên đúng dữ liệu gốc.
- **Bẫy giá đã xử lý**: site ghi lẫn lộn `tỷ` / `tỉ` (`4 tỉ 390 triệu`). Bản parser
  đầu chỉ nhận `tỷ` nên 258 tin bị hụt giá (đọc 390 triệu thay vì 4,39 tỷ) —
  đã sửa và **parse lại từ HTML thô** bằng `--from-raw` (không tốn request nào).



## Ghi chú kỹ thuật

- Cào lại an toàn: bảng SQLite dùng `url` làm khóa chính +
  `ON CONFLICT DO UPDATE` → chạy lại sẽ **làm mới** dữ liệu (không nhân đôi,
  không giữ bản ghi lỗi cũ). Sửa parser xong chạy lại là dữ liệu tự đúng.
- Nên dùng `--save-raw` ở lần cào đầu để giữ HTML thô: lần sau sửa parser có thể
  thử lại bằng `python -m tools.validate_parser` (**offline**, không cần mạng).
- Mọi request đi qua `requests.Session` + header trình duyệt + delay 1.5s (chỉnh qua `.env`).
- Khi đọc HTML thô bằng `lxml` phải truyền chuỗi đã decode (hoặc `HTMLParser(encoding="utf-8")`),
  nếu đưa bytes vào lxml có thể tự đoán sai charset → mojibake tiếng Việt.
- Tôn trọng `robots.txt`, ToS của trang và header `Retry-After` khi bị 429.


| Tool | Việc |
|---|---|
| `python -m tools.recon <url>` | robots.txt, tải trang, dò API/JSON ẩn |
| `python -m tools.inspect_items` | soi cấu trúc 1 item + link lọc/phân trang |
| `python -m tools.paging <url>` | dò khối phân trang + tổng số tin |
| `python -m tools.check_pages <url>` | xác nhận quy tắc phân trang, trang cuối |
| `python -m tools.test_paging_urls` | thử các dạng URL phân trang khả thi |
| `python -m tools.field_stats [n]` | độ phủ field + định dạng giá/tag theo hãng |
| `python -m tools.validate_parser` | parser vs HTML thô (offline, không cần mạng) |
| `python -m tools.find_api` | dò endpoint AJAX trong HTML + JS |
| `python -m tools.diag_data_call` | tìm tin bị từ chối khi bóc `data-call` |
| `python -m tools.diag_sold <brand> <p...>` | tỷ lệ tin đã bán và field bị mất |
| `python -m tools.diag_item <url> <id>` | in HTML thô 1 tin theo id |
| `python -m tools.inspect_db` | cột nào rỗng nhiều + mẫu row bất thường |
| `python -m tools.summarize_oto` | tổng hợp & kiểm tra chất lượng dữ liệu (pandas) |
| `python -m tools.smoke_test` | regression offline cho parser (36 assert, không cần mạng) |

## Ghi chú kỹ thuật

- Cào lại an toàn: bảng SQLite dùng `url` làm khóa chính +
  `ON CONFLICT DO UPDATE` → chạy lại sẽ **làm mới** dữ liệu (không nhân đôi,
  không giữ bản ghi lỗi cũ). Sửa parser xong chạy lại là dữ liệu tự đúng.
- Nên dùng `--save-raw` ở lần cào đầu để giữ HTML thô: lần sau sửa parser có thể
  thử lại bằng `python -m tools.validate_parser` (**offline**, không cần mạng).
- Mọi request đi qua `requests.Session` + header trình duyệt + delay 1.5s (chỉnh qua `.env`).
- Khi đọc HTML thô bằng `lxml` phải truyền chuỗi đã decode (hoặc `HTMLParser(encoding="utf-8")`),
  nếu đưa bytes vào lxml có thể tự đoán sai charset → mojibake tiếng Việt.
- Tôn trọng `robots.txt`, ToS của trang và header `Retry-After` khi bị 429.

