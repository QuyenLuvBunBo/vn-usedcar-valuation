# Chợ Tốt Xe — miền Nam

Trịnh Hải Phong, Group 14. Package này chỉ thu thập miền Nam; sử dụng common
và schema hiện có của repo. Không cần Playwright hoặc dependency bổ sung
ngoài requests, lxml, python-dotenv đã có trong requirements nhóm.

Chạy các lệnh tại root `vn-usedcar-valuation`, với Python trong môi trường
đã cài thư viện. PowerShell: `$env:PYTHONIOENCODING = 'utf-8'`.

```powershell
# Thử tối đa 5 tin tại TP.HCM, có lưu raw HTML
python -m src.sources.chotot --provinces tp-ho-chi-minh --max-records 5 --max-pages 10 --save-raw

# Cả 19 nhãn tỉnh/thành miền Nam, giới hạn số tin/trang
python -m src.sources.chotot --max-records 500 --max-pages 700 --save-raw

# Chỉ tiếp tục queue pending; mặc định chạy lại refresh URL đã xong
python -m src.sources.chotot --resume --save-raw

# Khám phá thêm quận/huyện và hãng; cùng DB để cập nhật/chống trùng
python -m src.sources.chotot --urls src/sources/chotot/urls_mo_rong.txt --resume --max-records 1500 --max-pages 2500 --save-raw

# Xuất lại JSONL, không truy cập mạng
python -m src.sources.chotot.unified

# Dữ liệu từ folder standalone cũ: truyền đúng đường dẫn trên máy của bạn
python -m src.sources.chotot.unified --input "C:/Python Project/data science/chotot_mien_nam/data/raw/chotot_mien_nam/raw.jsonl"

# Sửa selector xong: đọc HTML đã lưu bằng cùng parser, không gọi mạng
python -m src.sources.chotot --from-raw

# Gate nhóm và kiểm thử riêng
python -m tools.validate_source_csv data/processed/chotot_mien_nam.csv
python -m tools.smoke_test
python -m unittest discover -s src/sources/chotot/tests -v
```

CSV bàn giao: `data/processed/chotot_mien_nam.csv` (21 cột). File hỗ trợ
`all_21.csv`, `clean_21.csv`, `review_21.csv`, `quality.csv`, `audit.json` nằm
riêng trong `data/processed/chotot_mien_nam/`, tránh trùng kết quả nguồn khác.
Raw JSONL/log ở `data/raw/chotot_mien_nam/`; HTML + metadata ở `data/raw/`
với tiền tố `chotot_south_`. DB mặc định `data/scraped.db`, chỉ dùng bảng
`chotot_south_raw` và `chotot_south_queue`.

`--out` đặt thư mục JSONL/log, `--processed-out` đặt thư mục xuất CSV,
`--db` đặt DB, `--urls` đọc danh sách URL từ file, `--raw-html-dir` đặt nơi
đọc HTML offline. Không chạy hai tiến trình trên cùng DB/output.

Raw cũ chỉ được nhập DB khi `<out>/progress.sqlite` tồn tại; có thể chuẩn hóa
JSONL cũ trực tiếp bằng `--input` mà không di chuyển DB. Fixture sáu tin nhỏ
trong tests chỉ phục vụ regression, không đại diện độ phủ nguồn.

Crawler ưu tiên thu chi tiết đã tìm được. Trang danh sách không có link tin
được đánh dấu unparsed và ghi log, rồi tiếp tục queue; không coi đó là bằng
chứng trang hết tin. Khi HTTP bị từ chối/màn hình xác minh, crawler vẫn dừng.
Giới hạn tin không bảo đảm số thu được. Đợt mới có 1.889 tin duy nhất,
1.584 clean và 305 review, thu từ 18/10 đến 28/10/2026 theo giờ Việt Nam.
Không tự suy luận dung tích máy/ngày đăng khi thiếu. sub_model_trim hiện cũng
thiếu toàn bộ trong đợt mới; chi tiết trong audit.
Recon, mapping và quy tắc review: [docs/sources/chotot.md](../../../docs/sources/chotot.md).

Theo CONTRIBUTING, dữ liệu/DB/log được gitignore. Người phụ trách chọn push
riêng CSV sạch trong lần bàn giao này: `git add -f data/processed/chotot_mien_nam.csv`.
Không commit raw/DB/log. Nhánh làm việc hiện tại: `feat/source-chototxe-southern`.
