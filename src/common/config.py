"""Cấu hình dùng chung cho các script cào dữ liệu.

Đọc giá trị từ file `.env` (xem `.env.example`), fallback về biến môi trường,
sau đó tới giá trị mặc định trong code.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _find_root(start: Path) -> Path:
    """Tìm thư mục gốc repo (nơi có requirements.txt / .git) để mọi nguồn dùng chung data/."""
    for parent in (start, *start.parents):
        if (parent / "requirements.txt").exists() or (parent / ".git").exists():
            return parent
    return start


ROOT = _find_root(Path(__file__).resolve().parent)
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_MASTER = ROOT / "data" / "master"
LOGS_DIR = ROOT / "logs"

load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    """Đọc biến môi trường, trả về default nếu chưa khai báo."""
    value = os.getenv(name)
    return value if value not in (None, "") else default


# Header giả lập trình duyệt thật để hạn chế bị chặn.
USER_AGENT = _get(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Cookie / Authorization lấy từ DevTools -> Network -> Copy as cURL.
COOKIE = _get("COOKIE")
AUTHORIZATION = _get("AUTHORIZATION")
PROXY_URL = _get("PROXY_URL")

# Tham số cào
REQUEST_DELAY = float(_get("REQUEST_DELAY", "1.5"))  # giây giữa 2 request
MAX_RETRIES = int(_get("MAX_RETRIES", "3"))
TIMEOUT = int(_get("TIMEOUT", "20"))  # giây


def ensure_dirs() -> None:
    """Tạo sẵn các thư mục dữ liệu nếu chưa tồn tại."""
    for path in (DATA_RAW, DATA_PROCESSED, DATA_MASTER, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    """Thời điểm hiện tại dạng ISO 8601 UTC (dùng cho cột scraped_at)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
