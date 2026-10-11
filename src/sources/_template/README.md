# Khuôn mẫu cho một nguồn dữ liệu mới

Copy cả thư mục này thành `src/sources/<nguồn>/` (ví dụ `src/sources/bonbanh/`), rồi làm 4 bước:

## 1. Khảo sát site trước khi code (đừng đoán)

Dùng các tool có sẵn ở `tools/`:

```powershell
python -m tools.recon <url>            # robots.txt + tải trang + dò API/JSON ẩn
python -m tools.paging <url>           # tìm quy tắc phân trang + tổng số tin
python -m tools.check_pages <url>      # xác nhận phân trang, trang cuối
python -m tools.field_stats 2          # đo độ phủ field / định dạng giá trên mẫu
```

Ghi lại kết quả vào `docs/sources/<nguồn>.md`: robots.txt có cho phép không, HTML tĩnh hay
render bằng JS, quy tắc phân trang, các class/xpath dùng để bóc dữ liệu, và **những field
site không có**.

## 2. Viết `crawl.py`

Giữ nguyên cấu trúc file mẫu; chỉ cần:

- `SOURCE`, `BASE_URL`, `START_URL`, `TABLE`
- `parse_list_page(page_html, base_url)` → `(records, next_url)`
- (tuỳ nguồn) `parse_detail_page(page_html, url)` nếu cần vào từng tin để lấy thêm field
- `to_unified(raw)` → dict đủ **21 cột** theo `src/common/schema.py`

Quy tắc bắt buộc:

- Mọi request đi qua `ScraperSession` (đã có header trình duyệt + delay + retry + xử lý 429).
- Delay tối thiểu **1.5s/request** (chỉnh trong `.env`), không chạy song song ồ ạt.
- Ghi vào SQLite bằng `storage.upsert_rows` (khóa chính = URL) → chạy lại không nhân đôi.
- Luôn lưu HTML thô (`storage.save_raw`) ở nơi cần sửa parser nhiều lần.

## 3. Chuẩn hoá về 21 cột

Dùng `src/common/schema.py` và `src/common/parsing.py`, **không tự viết lại**:

| Việc | Hàm dùng |
|---|---|
| Giá "550 triệu", "1 tỷ 250 tr" → VND | `parse_vnd_price` |
| Km "140.000 km" → 140000 | `parse_km_text` |
| Truyền động → Automatic/Manual | `schema.normalize_transmission` |
| Nhiên liệu → Gasoline/Diesel/Hybrid/Electric | `schema.normalize_fuel` |
| Xuất xứ → CKD/CBU | `schema.normalize_origin` |
| Loại xe → Sedan/SUV/Pickup/... | `schema.normalize_body` |
| Tỉnh/thành | `schema.normalize_province` |
| Trạng thái giá | `schema.price_status` |
| Người bán salon/cá nhân | `schema.seller_type_from_subdomain` |

## 4. Kiểm tra rồi mới PR

```powershell
python -m tools.validate_source_csv data/processed/<nguồn>.csv
```

Script sẽ báo: thiếu/ thừa cột, sai thứ tự, sai kiểu dữ liệu, giá trị categorical lạ.
**Chỉ PR khi pass** — đây là điều kiện để Tuần 2 merge 6 nguồn không phải sửa tay.
