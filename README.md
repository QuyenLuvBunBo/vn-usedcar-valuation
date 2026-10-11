# vn-usedcar-valuation

Cào dữ liệu đa nguồn + chuẩn hoá Unified Schema, định giá xe cũ Việt Nam và phát hiện tin
đăng bất thường. *(Introduction to Data Science — Nhóm 14)*

## Cấu trúc repo

```
.
├─ README.md · CONTRIBUTING.md · requirements.txt · .env.example · .gitattributes
├─ docs/
│  ├─ unified_schema.md        # HỢP ĐỒNG: 21 cột dùng chung cả nhóm
│  └─ sources/oto.md           # ghi chú recon + mapping của nguồn oto.com.vn
├─ src/
│  ├─ common/                  # code dùng chung — sửa phải qua PR + review
│  │  ├─ config.py             # đường dẫn, .env, delay/retry
│  │  ├─ http_client.py        # session, header trình duyệt, retry/backoff, 429
│  │  ├─ storage.py            # raw / CSV / JSONL / SQLite (chống trùng)
│  │  ├─ parsing.py            # parse giá VND, km, năm (dùng cho mọi nguồn)
│  │  └─ schema.py             # 21 cột + bảng chuẩn hoá (hợp đồng dữ liệu)
│  ├─ sources/                 # mỗi nguồn một package, không sửa chéo
│  │  ├─ _template/            # ⭐ copy thư mục này để làm nguồn mới
│  │  └─ oto/                  # crawl.py · unified.py · brands_asia.py · brands_other.py
│  ├─ merge/                   # Tuần 2: build_master.py · dedupe.py
│  └─ data_prep/               # Tuần 2: missing.py (đo thiếu, điền khuyết)
├─ tools/                      # recon & kiểm tra (không phải code sản phẩm)
├─ notebooks/<tên-mỗi-người>/  # EDA Tuần 2 (mỗi người 1 thư mục)
└─ data/  raw/ · processed/ · master/     # KHÔNG commit dữ liệu
```

## Cài đặt

```powershell
git clone https://github.com/QuyenLuvBunBo/vn-usedcar-valuation.git
cd vn-usedcar-valuation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env     # điền cookie/proxy nếu nguồn cần
$env:PYTHONIOENCODING='utf-8'   # bắt buộc trên Windows để in tiếng Việt
```

## Chạy crawler oto.com.vn (nguồn mẫu đã hoàn chỉnh)

```powershell
python -m src.sources.oto                          # cào listing tất cả hãng
python -m src.sources.oto --group asia             # 6 hãng phổ thông châu Á (Quyền)
python -m src.sources.oto --group other            # các hãng còn lại (Phương)
python -m src.sources.oto --pages 3                # giới hạn 3 trang/hãng để thử
python -m src.sources.oto --detail-only            # cào thêm trang chi tiết từng tin
python -m src.sources.oto --detail-missing-price   # cào bù chi tiết cho tin thiếu giá
python -m src.sources.oto --from-raw               # sửa parser: parse lại HTML thô, không cào lại
python -m src.sources.oto.unified                  # xuất 21 cột Unified Schema + audit
```

Kết quả: `data/processed/oto_cars.csv` (dữ liệu thô đã bóc), `data/processed/oto_unified.csv`
(21 cột chuẩn), bảng `oto_cars` + `oto_car_details` trong `data/scraped.db`.

## Làm nguồn mới (bonbanh, chotot, carmudi, carpla, anycar)

1. Đọc `src/sources/_template/README.md` (4 bước: recon → parse → chuẩn hoá → kiểm tra).
2. Copy `src/sources/_template/` → `src/sources/<nguồn>/`, sửa `crawl.py` + `unified.py`.
3. Ghi chú recon vào `docs/sources/<nguồn>.md`.
4. Kiểm tra trước khi PR:

```powershell
python -m tools.validate_source_csv data/processed/<nguồn>.csv
python -m tools.smoke_test
```

Chi tiết quy ước nhánh/commit/ranh giới file: xem **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Tools

| Tool | Việc |
|---|---|
| `tools.validate_source_csv` | **cổng kiểm tra PR**: CSV của nguồn có đúng 21 cột + giá trị chuẩn? |
| `tools.smoke_test` | test hồi quy parser (offline, không cần mạng) |
| `tools.validate_parser` | parser vs HTML thô đã lưu (offline) |
| `tools.recon <url>` | robots.txt + tải trang + dò API/JSON ẩn |
| `tools.paging <url>` · `tools.check_pages <url>` | tìm & xác nhận quy tắc phân trang |
| `tools.field_stats [n]` | độ phủ field, định dạng giá trên mẫu nhiều trang |
| `tools.detail_recon <url>` | soi cấu trúc trang chi tiết (JSON-LD, bảng thông số, salon) |
| `tools.diag_*` | chẩn đoán lỗi parser (data-call, tin đã bán, field lạ) |
| `tools.list_brands` | dò + xác thực danh sách hãng của oto.com.vn |
| `tools.summarize_oto` | tổng hợp & kiểm tra chất lượng CSV đã cào (pandas) |
| `tools.scan_sitemap` · `tools.lastmod_analysis` | kiểm chứng quy mô nguồn + ngày đăng |

## Ghi chú kỹ thuật chung

- Mọi request đi qua `ScraperSession`: header trình duyệt, delay 1.5s (+ jitter), retry/backoff,
  tôn trọng `Retry-After`; tôn trọng `robots.txt` và điều khoản của từng site.
- Ghi dữ liệu bằng `INSERT … ON CONFLICT(url) DO UPDATE` → chạy lại **làm mới**, không nhân đôi.
- Nên dùng `--save-raw` ở lần cào đầu: sau này sửa parser chỉ cần parse lại HTML thô.
- Đọc HTML thô bằng lxml phải truyền **chuỗi đã decode** (nếu đưa bytes, lxml có thể đoán sai
  charset → mojibake tiếng Việt).
- Trên Windows luôn đặt `$env:PYTHONIOENCODING='utf-8'` trước khi chạy tool.

## Nguồn dữ liệu và quy mô (đã kiểm chứng)

Xem `docs/sources/oto.md` — gồm bảng quy mô thật (sitemap ≠ tồn kho), những field site không có,
và kết quả audit độ phủ của lần cào gần nhất.
