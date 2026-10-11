# Quy ước Git của nhóm — repo `vn-usedcar-valuation`

Mục tiêu: 9 người, 6 nguồn dữ liệu, merge được với nhau mà **gần như không conflict**.

## 1. Nhánh

| Nhánh | Ai dùng | Nội dung |
|---|---|---|
| `main` | cả nhóm | luôn ở trạng thái chạy được; chỉ nhận merge từ Pull Request |
| `feat/source-<nguồn>-<phần>` | mỗi thành viên | code crawler của mình, ví dụ `feat/source-oto-asia`, `feat/source-chotot-south` |
| `feat/week2-merge`, `feat/week3-model`, `feat/week4-app` | tiểu ban | việc của các tuần sau |

Quy tắc: **tách nhánh mới từ `main` đã cập nhật**, PR nhỏ và ngắn ngày (1–3 ngày), không để nhánh sống quá lâu.

```powershell
git checkout main
git pull
git checkout -b feat/source-bonbanh-new
# ... làm việc, commit ...
git push -u origin feat/source-bonbanh-new
# rồi mở Pull Request vào main
```

## 2. Commit

- Thông điệp ngắn, có tiền tố: `feat:`, `fix:`, `data:`, `docs:`, `refactor:`, `test:`
- Ví dụ: `feat: crawler bonbanh (xe 2019-2026)`, `fix: parse giá '1 tỷ 250 tr'`
- Không commit file dữ liệu lớn, không commit `.env`.

## 3. Ranh giới file — chống conflict

| Được tự do sửa | Phải PR riêng + 2 người review |
|---|---|
| `src/sources/<nguồn-của-bạn>/**` | `src/common/**` (schema, parsing, http_client, storage, config) |
| `docs/sources/<nguồn>.md` | `docs/unified_schema.md`, `README.md`, `CONTRIBUTING.md`, `requirements.txt` |

**Tuyệt đối không sửa code của nguồn khác.** Nếu phát hiện lỗi ở `src/common/`, mở issue hoặc PR riêng.

## 4. Hợp đồng dữ liệu (bắt buộc)

Mọi nguồn xuất ra `data/processed/<nguồn>.csv` với **đúng 21 cột** trong `src/common/schema.py`:

```
listing_id, source_platform, brand, model, sub_model_trim, manufacture_year, mileage_km,
transmission, fuel_type, origin, body_type, engine_capacity, seats, location_province,
seller_type, price_vnd, source_url, listing_date, scraped_at, raw_price_text, price_status
```

Chuẩn hoá giá trị (không tự đặt nhãn riêng):

| Cột | Giá trị hợp lệ |
|---|---|
| `transmission` | `Automatic` / `Manual` / `Other` / `Unknown` |
| `fuel_type` | `Gasoline` / `Diesel` / `Hybrid` / `Electric` / `Unknown` |
| `origin` | `CKD` / `CBU` / `Unknown` |
| `body_type` | `Sedan` / `SUV` / `Crossover` / `MPV` / `Hatchback` / `Pickup` / `Van` / `Truck` / `Other` / `Unknown` |
| `seller_type` | `Dealership/Salon` / `Private Individual` / `Unknown` |
| `price_status` | `full` / `negotiable` / `instalment` / `invalid` |

Dùng hàm có sẵn trong `src/common/parsing.py` và `src/common/schema.py` — **không viết lại**.

## 5. Trước khi mở Pull Request

```powershell
python -m tools.validate_source_csv data/processed/<nguồn>.csv   # pass mới được PR
python -m tools.smoke_test                                        # test hồi quy, không cần mạng
```

Trong PR ghi rõ: nguồn nào, số tin cào được, ngày cào, những field site **không có**,
và các quyết định chuẩn hoá đặc thù (ví dụ: giá "Thỏa thuận" xử lý thế nào).

## 6. Không commit

`data/raw/**` (HTML thô), `data/*.db`, `logs/**`, `.env`, notebook đã có output.
Dữ liệu để chia sẻ giữa các thành viên: Google Drive (hoặc Git LFS nếu nhóm thống nhất).
