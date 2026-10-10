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
python -m src.oto_scraper --detail-only         # cào THÊM trang chi tiết (không cào lại listing)
python -m src.oto_scraper --detail-only --detail-limit 20   # test nhanh 20 tin
```

Kết quả: `data/processed/oto_cars.csv`, `data/processed/oto_cars.jsonl`,
bảng `oto_cars` + `oto_car_details` trong `data/scraped.db`.

### Cào thêm trang chi tiết từng xe (`--detail`)

| Thông tin | Có trên trang chi tiết? | Ghi chú |
|---|---|---|
| **Mô tả của người bán** | ✅ `div.content-description .description` | dùng cho phân tích văn bản/NLP |
| **Màu xe** | ✅ `data-tragia` (phần tử thứ 8) | tin đã bán bị gỡ nút nên mất màu |
| **Số chỗ ngồi** | ✅ input ẩn `#numberOfSeat` | listing không có |
| **Giá dạng số** | ✅ input ẩn `#price` (vd `745000000`) | dùng để kiểm chéo với giá ở listing |
| **Tên + địa chỉ + subdomain salon** | ✅ `div.box-salon` (`h3.name`, `.des p`, `.link-sub-domain`) | cá nhân bán cũng có tên/địa chỉ |
| **Toàn bộ ảnh** | ✅ ảnh `/crop/640x480/` + `#countImage` | lưu ảnh đầu + số lượng ảnh |
| **ID hãng/dòng/tỉnh/phân khúc/người bán** | ✅ `#hddMakeId`, `#hddModelId`, `#hddCityId`, `#hddSegmentId`, `#hddUserId` | khớp khóa nội bộ của site |
| **8 thông số** (Năm SX, Nhiên liệu, Kiểu dáng, Tình trạng, Km đã đi, Hộp số, Xuất xứ, Tỉnh thành) | ✅ `ul.list-info` | trùng với dữ liệu listing |
| **Ngày đăng tin** | ❌ không có | site không hiển thị ở đâu cả |
| **Lượt xem** | ❌ không có | |
| **Thông số kỹ thuật chi tiết** (động cơ, công suất, kích thước) | ❌ không có | tab "Thông số kỹ thuật" không chứa dữ liệu này |

Chi phí: **~2,4 giây/tin** ⇒ 2.706 tin mất khoảng **1,8 giờ**. Chạy lại sẽ **tiếp tục từ chỗ dừng**
(tin nào đã có trong bảng `oto_car_details` thì bỏ qua; dùng `--detail-refresh` để cào lại hết).

## Xuất Unified Schema 15 thuộc tính + 5 metadata (bàn giao Tuần 1)

```powershell
python -m src.unified_schema                 # dùng cache listing_date
python -m src.unified_schema --fetch-sitemap # tải lại listing_date từ sitemap-detail
```

Kết quả: `data/processed/oto_unified.csv` (21 cột) + `.jsonl`, kèm bảng audit độ phủ từng cột.

- Mapping từng cột → nguồn dữ liệu, độ phủ, và **những trường site không có**:
  xem [`docs/oto_unified_schema.md`](docs/oto_unified_schema.md).
- Độ phủ hiện tại: `price_vnd` / `raw_price_text` / `origin` / `seller_type` / `brand` / `model`
  / `price_status` = **100%**; `mileage_km` 99,9%; `listing_date` 99,5%; `seats` 97,3%;
  `body_type` 96,9%; `sub_model_trim` 89,1%; `engine_capacity` 76,9% (giá trị suy luận).
- `listing_date` lấy từ `<lastmod>` của `sitemap-detail-*.xml` — là **ngày đăng/đẩy tin**, không
  phải ngày đăng chính thức do site công bố (đã kiểm chứng tương quan với vị trí trang listing).

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

