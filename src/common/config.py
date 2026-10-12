"""Shared configuration for every data-collection script.

Values are read from `.env` (see `.env.example`), then from environment variables,
then fall back to the defaults defined here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _find_root(start: Path) -> Path:
    """Locate the repository root (the folder containing requirements.txt / .git)
    so that every source shares the same data/ directory."""
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
    """Read an environment variable, returning `default` when it is not set."""
    value = os.getenv(name)
    return value if value not in (None, "") else default


# Browser-like headers, to reduce the chance of being blocked.
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

# Cookie / Authorization: copy them from DevTools -> Network -> "Copy as cURL".
COOKIE = _get("COOKIE")
AUTHORIZATION = _get("AUTHORIZATION")
PROXY_URL = _get("PROXY_URL")

# Crawl settings
REQUEST_DELAY = float(_get("REQUEST_DELAY", "1.5"))  # seconds between two requests
MAX_RETRIES = int(_get("MAX_RETRIES", "3"))
TIMEOUT = int(_get("TIMEOUT", "20"))  # seconds


def ensure_dirs() -> None:
    """Create the data and log directories if they do not exist yet."""
    for path in (DATA_RAW, DATA_PROCESSED, DATA_MASTER, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    """Current time as an ISO 8601 UTC string (used for the scraped_at column)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
