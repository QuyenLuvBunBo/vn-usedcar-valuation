"""HTTP client có sẵn: giữ session, header trình duyệt, retry/backoff, rate limit."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

from . import config

log = logging.getLogger(__name__)


class ScraperSession:
    """Bọc `requests.Session` với các hành vi cần thiết khi cào dữ liệu."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        delay: float | None = None,
        max_retries: int | None = None,
        timeout: int | None = None,
    ) -> None:
        self.delay = config.REQUEST_DELAY if delay is None else delay
        self.max_retries = config.MAX_RETRIES if max_retries is None else max_retries
        self.timeout = config.TIMEOUT if timeout is None else timeout

        self.session = requests.Session()
        self.session.headers.update(headers or config.DEFAULT_HEADERS)
        if config.COOKIE:
            self.session.headers["Cookie"] = config.COOKIE
        if config.AUTHORIZATION:
            self.session.headers["Authorization"] = config.AUTHORIZATION
        if config.PROXY_URL:
            self.session.proxies.update({"http": config.PROXY_URL, "https": config.PROXY_URL})

        self._last_request_at = 0.0

    # ------------------------------------------------------------------ utils
    def _sleep_if_needed(self) -> None:
        """Đảm bảo khoảng nghỉ tối thiểu giữa 2 request (+ jitter để tự nhiên hơn)."""
        elapsed = time.monotonic() - self._last_request_at
        wait = self.delay - elapsed
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.4))

    # ------------------------------------------------------------- requests
    def get(self, url: str, **kwargs: Any) -> requests.Response | None:
        """GET kèm retry + backoff. Trả về None nếu thất bại hoàn toàn."""
        for attempt in range(1, self.max_retries + 1):
            self._sleep_if_needed()
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                self._last_request_at = time.monotonic()

                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", self.delay * 5))
                    log.warning("429 Too Many Requests -> nghỉ %.1fs", wait)
                    time.sleep(wait)
                    continue
                if resp.status_code in (403, 401):
                    log.error("%s cho %s -> cần cookie/token hoặc bị chặn", resp.status_code, url)
                    return None
                if resp.status_code >= 500:
                    log.warning("Lỗi server %s cho %s", resp.status_code, url)
                    time.sleep(2**attempt)
                    continue

                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                log.warning("Lỗi lần %s/%s khi GET %s: %s", attempt, self.max_retries, url, exc)
                time.sleep(2**attempt)
        log.error("Bỏ qua URL sau %s lần thử: %s", self.max_retries, url)
        return None

    def get_text(self, url: str, **kwargs: Any) -> str | None:
        """GET và trả về HTML dạng chuỗi (ép UTF-8 nếu server khai báo sai)."""
        resp = self.get(url, **kwargs)
        if resp is None:
            return None
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text

    def get_json(self, url: str, **kwargs: Any) -> Any | None:
        """GET và trả về JSON đã parse (dùng cho API nội bộ của trang)."""
        resp = self.get(url, **kwargs)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            log.error("Response không phải JSON: %s", url)
            return None

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ScraperSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
