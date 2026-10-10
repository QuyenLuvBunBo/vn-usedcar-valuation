# IntroDS — Web Scraping

Bộ khung cào dữ liệu web (Python 3.14 trên Windows).

## Cấu trúc

```
.
├─ .venv/                # môi trường ảo (không commit)
├─ requirements.txt
├─ .env.example          # copy thành .env rồi điền token/cookie/proxy
├─ data/
│  ├─ raw/               # HTML/JSON thô -> luôn lưu trước khi parse
│  └─ processed/         # CSV/Parquet đã làm sạch
├─ logs/                 # log chạy
└─ src/                  # code cào + parse
```

## Cài đặt

```powershell
cd f:\Code\IntroDS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium   # chỉ cần khi phải render JavaScript
```

## Ghi chú kỹ thuật

- Luôn lưu **dữ liệu thô** (`data/raw/`) trước, parse sau — sai parser thì không phải cào lại.
- Mọi request đi qua `requests.Session` + header giống trình duyệt + delay 1–3s.
- Chống trùng bằng cột UNIQUE (URL/id) và ghi kiểu `INSERT OR IGNORE`.
- Tôn trọng `robots.txt`, ToS của trang và header `Retry-After` khi bị 429.
