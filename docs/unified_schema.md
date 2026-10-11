# Unified Schema — hợp đồng dữ liệu của nhóm

**Nguồn chân lý là code, không phải tài liệu này**: `src/common/schema.py`.
File này giải thích ý nghĩa từng cột để viết báo cáo.

## 16 thuộc tính + 5 metadata

| # | Cột | Kiểu | Ý nghĩa / miền giá trị |
|---|---|---|---|
| 1 | `listing_id` | string | Mã tin duy nhất, có tiền tố nguồn (`OTO_23444795`, `BAN_...`) |
| 2 | `source_platform` | enum | `oto.com.vn`, `bonbanh`, `chotot`, `carmudi`, `carpla`, `anycar` |
| 3 | `brand` | string | Hãng: `Toyota`, `Hyundai`, `Ford`, … |
| 4 | `model` | string | Dòng xe: `Vios`, `Accent`, `CX-5`, … |
| 5 | `sub_model_trim` | string | Phiên bản: `1.8G CVT`, `2.5Q`, `2.7 V 4X2 AT` (rỗng nếu người bán không ghi) |
| 6 | `manufacture_year` | int | Năm sản xuất, scope đề xuất 1995–nay |
| 7 | `mileage_km` | float | Số km đã đi (dữ liệu gốc, có thể sai do người bán nhập) |
| 8 | `transmission` | enum | `Automatic` / `Manual` / `Other` / `Unknown` |
| 9 | `fuel_type` | enum | `Gasoline` / `Diesel` / `Hybrid` / `Electric` / `Unknown` |
| 10 | `origin` | enum | `CKD` (lắp ráp trong nước) / `CBU` (nhập khẩu) / `Unknown` |
| 11 | `body_type` | enum | `Sedan` / `SUV` / `Crossover` / `MPV` / `Hatchback` / `Pickup` / `Van` / `Truck` / `Other` |
| 12 | `engine_capacity` | float | Dung tích (L): 1.5, 2.0, 2.4 — nhiều nguồn phải suy luận từ tên phiên bản |
| 13 | `seats` | int | Số chỗ ngồi |
| 14 | `location_province` | string | Tỉnh/thành đã chuẩn hoá (`Hà Nội`, `TP. Hồ Chí Minh`, …) |
| 15 | `seller_type` | enum | `Dealership/Salon` / `Private Individual` / `Unknown` |
| 16 | `price_vnd` | int (target) | **Giá rao bán** (VND); rỗng/`invalid` nếu không có giá xác định |
| 17 | `source_url` | string | URL gốc để truy vết |
| 18 | `listing_date` | datetime (nullable) | Ngày đăng/đẩy tin, ISO 8601; nguồn không có thì để trống |
| 19 | `scraped_at` | datetime | Thời điểm cào (UTC, ISO 8601) |
| 20 | `raw_price_text` | string | **Nguyên văn** biểu thức giá: `1 tỷ 250 tr`, `550 triệu` |
| 21 | `price_status` | enum | `full` / `negotiable` / `instalment` / `invalid` |

## Nguyên tắc

1. **Null phải để trống**, không thay bằng 0 hay `Unknown` một cách tuỳ tiện; cột phân loại
   không xác định được thì dùng `Unknown` (đúng như report yêu cầu).
2. `price_vnd` là **target** — khi huấn luyện mô hình **không** đưa nó vào tập predictors,
   và cũng không dùng `raw_price_text`, `price_status`, `listing_date` làm feature.
3. Chuẩn hoá **chỉ** bằng hàm trong `src/common/parsing.py` và `src/common/schema.py`.
4. Trước khi PR: `python -m tools.validate_source_csv data/processed/<nguồn>.csv` phải PASS.

## Kiểm tra nhanh sau khi gộp (Tuần 2)

- Trùng `listing_id` / `source_url` = 0.
- `duplicate_group_id` (Tuần 2) phải giữ mọi bản ghi cùng một xe trong **cùng một tập** train/val/test.
- Báo cáo cần ghi: số dòng mỗi nguồn, tỷ lệ thiếu từng cột, tỷ lệ trùng, số dòng bị loại
  và lý do (Milestone 1).
