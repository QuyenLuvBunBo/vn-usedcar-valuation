# Chợ Tốt Xe — miền Nam

Phụ trách: **Trịnh Hải Phong**, Group 14. Bám schema và common trong bản
repo nhóm tại thời điểm tích hợp. Phần Bắc/Trung không thuộc crawler này.

## Recon và giới hạn

- Host `https://xe.chotot.com`.
- Seed `/mua-ban-oto-<province>`; chi tiết `/mua-ban-oto-<location>/<id>.htm`.
- 19 nhãn địa lý marketplace trong `src/sources/chotot/geography.py`, không
  được hiểu là danh sách đơn vị hành chính hiện hành.
- Bản robots đã lưu từ đợt cũ cấm `/*page=`. Crawler tải lại robots mỗi lần
  chạy, kiểm tra URL trước khi fetch, chỉ theo link phân trang cùng path
  (số trang hoặc rel=next). Không tự sinh ID/trang.
- Dữ liệu cũ có 30 tin từ TP.HCM/Bình Dương. Selector đã có fixture và kiểm
  thử offline; chưa xác nhận HTTP requests hiện tại nhận đủ HTML từ website.
- Crawler dùng đúng `ScraperSession` của nhóm, delay ≥1.5 s, tăng theo robots;
  retry/backoff/429 theo common. Khi HTTP bị từ chối hoặc HTML chỉ là shell JS,
  dừng và xuất dữ liệu đã thu. Không tự chuyển phương thức để vượt từ chối.

## Mapping nguồn → schema

| Trường | Selector / xử lý |
|---|---|
| listing_id, source_platform | `CHOTOT_<id số trong URL>`, `chotot` |
| brand, model, sub_model_trim | `//*[@itemprop="carbrand"]`, `carmodel`, `option` |
| manufacture_year | `mfdate` → shared parse_year_text |
| mileage_km | `mileage_v2` → adapter vạn/nghìn → shared parse_km_text |
| transmission | `gearbox`, alias Tự động→Số tự động; shared normalize_transmission |
| fuel_type | `fuel`; alias Động cơ hybrid→hybrid; shared normalize_fuel |
| origin | `carorigin`; Việt Nam→Trong nước, nước xuất xứ→Nhập khẩu; shared normalize_origin |
| body_type | `cartype` → alias nhãn chuẩn → shared normalize_body |
| seats | `carseats` → shared to_int sau kiểm tra số nguyên |
| location_province | `//a[@href]` có text bắt đầu `Ô tô ` và slug tỉnh nhận diện → normalize_province |
| seller_type | `//*[@itemprop="seller"]//a[contains(@href,"/cua-hang/")]` → Dealership/Salon; còn lại Unknown |
| price_vnd | `//b` có chuỗi giá đầy đủ → shared parse_vnd_price hoặc to_int cho VND dạng số |
| raw_price_text | Giữ biểu thức giá đã lấy từ HTML; không đổi thành chuỗi chuẩn hóa |
| price_status | shared schema.price_status + kiểm tra bằng chứng khoản trả trước của nguồn |
| source_url, scraped_at | URL HTTPS chuẩn hóa, thời điểm quan sát chuyển UTC ISO 8601 |
| engine_capacity, listing_date | Chưa lấy được trực tiếp, để trống |

Trường phân loại không biết dùng `Unknown`; số thiếu không thay bằng 0.
Không dùng helper salon-subdomain của oto vì thiếu link cửa hàng Chợ Tốt
không chứng minh là người bán cá nhân. Bán tự động dùng `Other` theo schema.
Nhãn gộp `SUV / Cross over` dùng `Other` với cờ `ambiguous_suv_crossover`,
không đoán SUV hay Crossover. Danh sách enum trong **code schema** được ưu
tiên khi tài liệu mô tả ngắn hơn (ví dụ Coupe/Convertible vẫn được code cho phép).

Parser giá source kiểm tra toàn bộ biểu thức trước khi gọi shared helper để
không lấy nhầm số điện thoại/năm. Giá VND dạng `465.000.000 đ` bỏ dấu nhóm
trước to_int; biểu thức tỷ/triệu chuyển alias rồi gọi parse_vnd_price.
Chỉ kiểm tra trả trước trong tiêu đề/mô tả của người bán, không dùng widget
vay tự động của website. Không coi mọi lời mời trả góp là giá trả trước.

## Storage, offline và cohort

Shared `storage.open_db` mặc định dùng `data/scraped.db`. Bảng
`chotot_south_raw` có khóa URL, cập nhật bằng `storage.upsert_rows`.
Raw JSON giữ scraped_at gốc; scraped_at ở cấp bảng là thời điểm upsert theo
common. Queue `chotot_south_queue` riêng, không ảnh hưởng bảng nguồn khác.
Mặc định refresh URL đã xong; `--resume` chỉ lấy pending. DB cũ được nhập
một lần theo URL vào bảng mới, không ghi đè các bản đã cập nhật.

`storage.save_raw` lưu HTML trong data/raw; metadata JSON giữ URL và thời
điểm. Parser mạng và `--from-raw` dùng cùng `parse_detail_page`, nhận chuỗi
UTF-8 đã decode qua lxml, không chạy JS hoặc gọi mạng khi offline.

Clean giữ tin xác nhận đã dùng, thuộc miền Nam, có hãng/model, năm từ 1995
đến năm quan sát, giá toàn bộ 30 triệu–25 tỷ, km ≤1 triệu; xe >2 tuổi nhưng
<100 km chuyển review, chỗ ngồi ngoài 2–16 chuyển review nếu có. Đây là
quyết định lọc của nguồn, tách khỏi gate schema; có thể đổi khi nhóm thống nhất.
Raw vẫn giữ các tin này; `review_21.csv` và `quality.csv` ghi lý do.

CSV chính ở `data/processed/chotot_mien_nam.csv`. File hỗ trợ nằm riêng trong
`data/processed/chotot_mien_nam/`: `all_21.csv`, `clean_21.csv` (tương thích),
`review_21.csv`, `quality.csv`, `audit.json`. Audit có missing rate coi Unknown
là thiếu, tỷ lệ duplicate, tỉnh, trạng thái giá và lý do loại. Tái xuất từ
30 raw cũ: 27 clean, 3 review. Chưa có dung tích máy/ngày đăng gốc; chưa được
coi là bộ dữ liệu đủ độ phủ hoặc đã hoàn thành chỉ tiêu số lượng của nhóm.

## Gate trước PR

```powershell
python -m tools.validate_source_csv data/processed/chotot_mien_nam.csv
python -m tools.smoke_test
python -m unittest discover -s src/sources/chotot/tests -v
```

Validator/smoke test là các tool sẵn có của repo nhóm; smoke test chính thức
kiểm parser oto, kiểm thử Chợ Tốt nằm ở lệnh unittest riêng.

## Chạy và bàn giao

Xem `src/sources/chotot/README.md` để chạy crawler, offline export và kiểm thử.
CSV được xuất local và gitignore; không thêm raw, DB, CSV thật vào commit.
