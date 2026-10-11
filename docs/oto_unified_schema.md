# Mapping dữ liệu oto.com.vn → Unified Schema (Tuần 1)

Nguồn: **oto.com.vn** — nhóm xe phổ thông châu Á (Toyota, Hyundai, Kia, Mazda, Honda, Mitsubishi), chỉ tin **xe cũ**.
Quy mô đã cào: **2.706 tin** (196 trang listing + 2.706 trang chi tiết).

## Cách tạo lại file

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m src.oto_scraper              # cào listing (~10 phút)
python -m src.oto_scraper --detail-only   # cào trang chi tiết (~1h45m)
python -m src.unified_schema              # xuất data/processed/oto_unified.csv
```

## Bảng mapping 16 thuộc tính + 5 metadata

| # | Cột Unified Schema | Nguồn trên oto.com.vn | Độ phủ | Ghi chú |
|---|---|---|---|---|
| 1 | `listing_id` | `data-autoid` của thẻ tin | 100% | Ghi dạng `OTO_23444795` (composite prefix + ID) |
| 2 | `source_platform` | hằng số | 100% | `oto.com.vn` |
| 3 | `brand` | `data-tinrao[0]` | 100% | 6 hãng |
| 4 | `model` | `data-tinrao[1]` | 100% | 103 dòng xe |
| 5 | `sub_model_trim` | tách từ tiêu đề (`h1.title-detail` / `car_name`) | 89,1% | vd `1.8G CVT`, `2.5Q`, `2.7 V 4X2 AT`; 296 tin người bán **không ghi** trim |
| 6 | `manufacture_year` | `data-call[4]` (hoặc `#year`) | 100% | 1990–2026 |
| 7 | `mileage_km` | tag `tag-list` "140.000 km" | 99,9% | Dữ liệu gốc, có tin người bán ghi sai (vd `12.000.000 km`) |
| 8 | `transmission` | tag "Số tự động/Số sàn" | 100% | Ánh xạ → `Automatic` / `Manual` / `Other` |
| 9 | `fuel_type` | tag "Máy xăng/Máy dầu/Hybrid" | 100% | → `Gasoline` / `Diesel` / `Hybrid` |
| 10 | `origin` | `data-call[3]`, dự phòng `Xuất xứ` ở trang chi tiết | 100% | → `CKD` (trong nước) / `CBU` (nhập khẩu). **Dự phòng cần thiết** vì tin đã bán không có `data-call` |
| 11 | `body_type` | `data-call[6]`, dự phòng `Kiểu dáng` ở trang chi tiết | 96,9% | → `Sedan/SUV/Crossover/MPV/Hatchback/Pickup/Van/Truck/Sports/Convertible` |
| 12 | `engine_capacity` | tách số `1.5`/`2.0`/`2.4` từ trim/tiêu đề | 76,9% | ⚠️ **Giá trị suy luận**, không có cột "dung tích" trên site. Report cho phép dùng mapping make/model/trim/năm |
| 13 | `seats` | input ẩn `#numberOfSeat` (trang chi tiết) | 97,3% | Listing **không** có, phải cào trang chi tiết |
| 14 | `location_province` | `Tỉnh thành` (chi tiết) → `province` (listing) | 100% | Đã gom "Thủ Đức - Tp.HCM" → `TP. Hồ Chí Minh`; 101 nhãn |
| 15 | `seller_type` | suy ra từ `d_seller_url` | 100% | Có subdomain riêng ⇒ `Dealership/Salon` (1.818) · không ⇒ `Private Individual` (888) |
| 16 | `price_vnd` (target) | `#price` (input ẩn, ví dụ `745000000`) → `p.price` | **100%** | 222 tin listing để trống giá nhưng trang chi tiết có ⇒ đã lấp đủ |
| 17 | `source_url` | `h3/a @href` | 100% | URL tuyệt đối |
| 18 | `listing_date` | `<lastmod>` trong `sitemap-detail-1/2.xml` | 99,5% | ⚠️ Ngày **đăng/đẩy tin gần nhất** (site không công bố "ngày đăng" ở trang tin). Đã kiểm chứng: tương quan với vị trí trang listing |
| 19 | `scraped_at` | thời điểm chạy tool | 100% | UTC, ISO 8601 |
| 20 | `raw_price_text` | `p.price` (listing) → `span.price` (chi tiết) | **100%** | Giữ nguyên văn bản gốc, vd `1 tỉ 450 triệu` |
| 21 | `price_status` | suy ra từ giá + raw text | 100% | `full` / `negotiable` / `instalment` / `invalid`. Riêng oto.com.vn: 2.706 tin `full` |

## Những gì oto.com.vn **KHÔNG** có (để báo cáo ghi rõ là null)

| Trường | Tình trạng |
|---|---|
| Ngày đăng tin công bố chính thức | Không hiển thị ở đâu; chỉ có `lastmod` trong sitemap (xem #18) |
| Lượt xem tin | Không hiển thị |
| Dung tích động cơ (cc/L) | Không có trên trang tin; có trên trang **thông số dòng xe** (`/bang-gia-xe-o-to-<brand>-<model>-moi-nhat`) → nên làm bảng tra ở Tuần 2 |
| Thông số kỹ thuật chi tiết (công suất, kích thước) | Tab "Thông số kỹ thuật" không chứa dữ liệu |
| Số chỗ | Chỉ có qua cào trang chi tiết (`#numberOfSeat`) |
| `duplicate_group_id`, `quality_flags` | Thuộc Tuần 2 theo kế hoạch (chưa sinh) |

## Quy mô thật của nguồn oto.com.vn (đã kiểm chứng — quan trọng cho chỉ tiêu 15.000)

| Nguồn đếm | Con số | Ý nghĩa |
|---|---|---|
| Tổng URL trong `sitemap-detail-1/2.xml` | **30.900** | ⚠️ **Không phải tồn kho đang rao** — đây là kho URL lịch sử site còn giữ |
| Trong đó có hậu tố `aidxc` (xe cũ) | 29.392 | trang tin xe cũ còn truy cập được |
| URL có `lastmod` trong 90 ngày | ~7.400 | phần "còn tươi" |
| URL có `lastmod` cũ hơn 90 ngày | **23.484 (76%)** | phần lớn đã ngừng rao |
| **Số tin đang hiển thị ở listing** | **≈ 5.000** | 6 hãng phổ thông châu Á: **2.706** (khớp đúng bộ đếm của site) + các hãng còn lại ≈ 2.200 |

Bằng chứng cho kết luận "sitemap ≠ tồn kho":

1. Toyota có **5.715 URL** trong sitemap nhưng listing chỉ báo `Có 892 tin` và vét hết 60 trang cũng đúng 892 tin.
2. Lấy ngẫu nhiên 48 tin "chỉ có trong sitemap": **100% trả HTTP 200** và đủ dữ liệu, nhưng khi dò trong listing theo **hãng** và theo **dòng xe** thì **không có** ⇒ chúng đã bị bỏ khỏi danh sách rao nhưng trang vẫn sống (thường là tin đã gia hạn/đăng lại bằng id mới, hoặc hết hạn nhưng chưa xoá).
3. Trong 40 tin sitemap-only, **34 tin (85%) vẫn còn nút "Trả giá"** (dấu hiệu chưa bị đánh bán) — nhưng vẫn không nằm trong listing ⇒ **nút Trả giá chỉ cho biết trang chưa bị đánh dấu "đã bán", KHÔNG chứng minh tin đang được rao**.

**Hệ quả cho kế hoạch Tuần 1:** chỉ tiêu 15.000 tin/người cho oto.com.vn **không đạt được từ listing hiện tại** (~5.000 tin cho toàn site). Ba lựa chọn:
1. Bù bằng 5 nguồn còn lại (bonbanh, chợ tốt, carmudi, carpla, anycar) — nên ưu tiên.
2. Dùng thêm "tier lưu trữ" từ sitemap (thêm được ~26.600 tin) nhưng **phải thêm cột `in_listing`** để báo cáo tách riêng: nhóm này không đang rao, phần lớn đã cũ, và ~15% đã bán.
3. Hạ chỉ tiêu cho nguồn oto.com.vn.

Nếu dùng tier lưu trữ: crawl trực tiếp theo URL trong sitemap (không cần phân trang), sitemap **sắp giảm dần theo `lastmod`** nên lấy N URL đầu = N tin mới nhất; trang chi tiết đã đủ cả 21 cột của Unified Schema.


1. **47,8% tin là "đã bán"** (`sold` trong DB gốc) — vẫn có đủ 16 thuộc tính, nhưng giá là giá **rao bán lịch sử**, không phải giá đang chào. Nên test độ nhạy khi lọc bỏ nhóm này.
2. `listing_date` = ngày đẩy tin, **không dùng làm feature trực tiếp**; chỉ dùng để chia train/test theo thời gian.
3 `price_vnd` là **target**, không được đưa vào tập predictors (tránh leakage). Tương tự, không dùng `raw_price_text`, `price_status`, và các cột `d_price_vnd` khi huấn luyện.
4. **Không đưa thông tin liên hệ** (số điện thoại, tên/địa chỉ salon cá nhân) vào dataset công bố — report yêu cầu loại bỏ; dùng `seller_type` thay thế.
5. `engine_capacity` là giá trị suy luận: nên gắn cờ chất lượng và đối chiếu bảng tra dòng xe trước khi dùng làm predictor quan trọng.

## Gợi ý chọn thuộc tính cho mô hình (Tuần 3)

- **Target**: `price_vnd`
- **Predictors chính**: `brand`, `model`, `sub_model_trim`, `manufacture_year`, `mileage_km`, `transmission`, `fuel_type`, `origin`, `body_type`, `engine_capacity`, `seats`, `location_province`, `seller_type`
- **Feature kỹ nghệ nên tạo**: `vehicle_age = listing/capture year − manufacture_year`, `km_per_year = mileage_km / max(vehicle_age, 1)`, `geo_tier` (Hà Nội/TP.HCM vs tỉnh), `brand_retention_rate` (theo nhóm)
- **Metadata (không dùng làm feature)**: `listing_id`, `source_platform`, `source_url`, `listing_date`, `scraped_at`, `raw_price_text`, `price_status`
