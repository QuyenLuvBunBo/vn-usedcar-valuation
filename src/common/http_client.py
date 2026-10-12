"""Pre-configured HTTP client: persistent session, browser headers, retry/backoff, rate limiting."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

from . import config

log = logging.getLogger(__name__)


class ScraperSession:
    """Thin wrapper around `requests.Session` with the behaviour scraping needs."""

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
        """Keep a minimum gap between two requests (plus jitter to look more natural)."""
        elapsed = time.monotonic() - self._last_request_at
        wait = self.delay - elapsed
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.4))

    # ------------------------------------------------------------- requests
    def get(self, url: str, **kwargs: Any) -> requests.Response | None:
        """GET with retry and backoff. Returns None when every attempt fails."""
        for attempt in range(1, self.max_retries + 1):
            self._sleep_if_needed()
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                self._last_request_at = time.monotonic()

                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", self.delay * 5))
                    log.warning("429 Too Many Requests -> sleeping %.1fs", wait)
                    time.sleep(wait)
                    continue
                if resp.status_code in (403, 401):
                    log.error("%s for %s -> needs cookie/token, or the request was blocked",
                              resp.status_code, url)
                    return None
                if resp.status_code >= 500:
                    log.warning("Server error %s for %s", resp.status_code, url)
                    time.sleep(2**attempt)
                    continue

                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                log.warning("Attempt %s/%s failed for GET %s: %s",
                            attempt, self.max_retries, url, exc)
                time.sleep(2**attempt)
        log.error("Giving up on %s after %s attempts", url, self.max_retries)
        return None

    def get_text(self, url: str, **kwargs: Any) -> str | None:
        """GET and return the HTML as text (force a better encoding when the server lies)."""
        resp = self.get(url, **kwargs)
        if resp is None:
            return None
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text

    def get_json(self, url: str, **kwargs: Any) -> Any | None:
        """GET and return parsed JSON (useful for a site's internal API)."""
        resp = self.get(url, **kwargs)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            log.error("Response is not JSON: %s", url)
            return None

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ScraperSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
