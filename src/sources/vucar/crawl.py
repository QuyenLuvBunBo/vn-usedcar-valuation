"""vucar.vn: read the catalogue from the site's public Next.js data action.

This module is the notebook `vucar_scraper.py.ipynb` turned into a package: the logic (request pacing,
robots.txt check, action-ID discovery, page parsing, save-after-every-page) is the author's, unchanged.
Two deliberate additions:

  * the raw record now also keeps `car_brand`, `car_model`, `car_fuel_type` and `created_at`, which the
    public action already returns but the notebook dropped. `unified.py` needs them to fill the contract
    columns exactly instead of splitting the display name by hand;
  * a CLI (`python -m src.sources.vucar`), so the crawler runs the same way as every other source.

Requires Python 3.10+ and `curl` (no third-party package, no browser).

    python -m src.sources.vucar --max-pages 1        # 8 cars, a quick check
    python -m src.sources.vucar                     # the whole catalogue (2,124 cars, ~266 pages)
    python -m src.sources.vucar.unified             # data/processed/vucar.csv (21 columns)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import shutil
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from ...common import config

SOURCE = "vucar"
PLATFORM = "vucar.vn"
BASE_URL = "https://vucar.vn"
CATALOGUE_URL = BASE_URL + "/mua-ban/o-to-cu"

# The notebook's ten columns plus the four the action already returns and the contract needs.
COLUMNS = [
    "model_year_name", "year", "odo_km", "car_type", "price_vnd",
    "transmission", "location", "url", "source_page", "scraped_at_utc",
    "brand_raw", "model_raw", "fuel_raw", "created_at_raw",
]



class CurlClient:
    """Ordinary HTTPS requests through curl; shell=False and TLS verification stay on."""

    def __init__(self, delay: float = 1.5, timeout: int = 60):
        self.executable = shutil.which("curl")
        if self.executable is None:
            raise RuntimeError("curl is required (it ships with Windows 10+, macOS and most Linux images).")
        self.delay = delay
        self.timeout = timeout
        self.last_request = 0.0

    def request(self, url: str, *, headers: dict | None = None, body: str | None = None) -> str:
        if urlsplit(url).scheme != "https" or urlsplit(url).netloc != "vucar.vn":
            raise ValueError("Only public HTTPS URLs on vucar.vn are supported.")
        marker = "\n__VUCAR_HTTP_STATUS__:"
        for attempt in range(3):
            time.sleep(max(0.0, self.last_request + self.delay - time.monotonic()))
            command = [
                self.executable, "--silent", "--show-error", "--compressed",
                "--connect-timeout", "15", "--max-time", str(self.timeout),
                "--write-out", marker + "%{http_code}",
            ]
            for key, value in (headers or {}).items():
                command.extend(["--header", f"{key}: {value}"])
            if body is not None:
                command.extend(["--data-binary", "@-"])
            command.append(url)
            self.last_request = time.monotonic()
            result = subprocess.run(
                command, input=body, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout + 10,
            )
            payload, separator, status_text = result.stdout.rpartition(marker)
            status = int(status_text) if separator and status_text.isdigit() else 0
            if result.returncode == 0 and status == 200:
                return payload
            if status in (401, 403, 429):
                raise RuntimeError(
                    f"Vucar returned HTTP {status}; stopping. Already collected rows are saved."
                )
            if attempt < 2 and (result.returncode != 0 or status >= 500):
                time.sleep(2 ** (attempt + 1))
                continue
            detail = result.stderr.strip() or payload[:160].replace("\n", " ")
            raise RuntimeError(f"Request failed: HTTP {status}, curl {result.returncode}: {detail}")
        raise RuntimeError("Request failed.")


class ScriptSources(HTMLParser):
    """Collect the page's own /_next/*.js URLs, where the action ID lives."""

    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        source = attributes.get("src", "")
        if tag == "script" and "/_next/" in source and ".js" in source:
            url = urljoin(BASE_URL, source)
            if urlsplit(url).netloc == "vucar.vn" and url not in self.urls:
                self.urls.append(url)


def discover_listing_action(client: CurlClient) -> tuple[str, int | None]:
    """Find the current action ID in public page scripts; it changes on every deployment."""
    robots = RobotFileParser()
    robots.parse(client.request(BASE_URL + "/robots.txt").splitlines())
    if not robots.can_fetch("curl", CATALOGUE_URL):
        raise RuntimeError("The catalogue is disallowed by the current robots.txt.")
    client.delay = max(client.delay, float(robots.crawl_delay("curl") or 0))
    html = client.request(CATALOGUE_URL)
    total_match = re.search(r"Tìm thấy\s*<span\b[^>]*>([\d.,]+)", html)
    catalogue_total = int(re.sub(r"\D", "", total_match.group(1))) if total_match else None
    scripts = ScriptSources()
    scripts.feed(html)
    pattern = re.compile(
        r'''createServerReference\)?\(\s*["']([a-fA-F0-9]{32,64})["'][^;]{0,250}?["']fetchCarListing["']'''
    )
    for url in reversed(scripts.urls):      # route-specific scripts usually appear near the end
        if not robots.can_fetch("curl", url):
            continue
        match = pattern.search(client.request(url))
        if match:
            return match.group(1), catalogue_total
    raise RuntimeError(
        "Could not locate fetchCarListing in Vucar's public scripts. "
        "The site may have changed; update the discovery/parser before continuing."
    )



def parse_listing_response(text: str) -> dict:
    """Read the action's streamed JSON result without executing JavaScript."""
    for line in text.splitlines():
        if not re.match(r"^[0-9a-fA-F]+:", line):
            continue
        try:
            value = json.loads(line.split(":", 1)[1])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("cars"), list):
            for field in ("total", "pageCount", "limit"):
                if not isinstance(value.get(field), int) or isinstance(value[field], bool):
                    raise ValueError(f"Unexpected listing metadata: {field}.")
            if value["total"] < 0 or value["pageCount"] < 0 or value["limit"] <= 0:
                raise ValueError("Invalid pagination metadata.")
            return value
    raise ValueError(
        "No car-list JSON found in the response. The public action or response format may have changed."
    )


def fetch_listing_page(client: CurlClient, action_id: str, page: int, per_page: int = 8) -> dict:
    parameters = {
        "brandParam": None, "modelParam": None, "priceParam": None,
        "mfDateParam": None, "locationParam": None,
        "page": str(page), "per_page": str(per_page),
        "searchTerm": None, "mileage": None, "carBrands": None,
    }
    response = client.request(
        CATALOGUE_URL,
        headers={
            "Next-Action": action_id,
            "Content-Type": "text/plain;charset=UTF-8",
            "Accept": "text/x-component",
            "Origin": BASE_URL,
        },
        body=json.dumps([parameters], separators=(",", ":")),
    )
    return parse_listing_response(response)


def optional_integer(value, field: str) -> int | None:
    if value is None or value == "" or value == "$undefined":
        return None
    if isinstance(value, bool) or not re.fullmatch(r"\d+(?:\.0+)?", str(value)):
        raise ValueError(f"Unexpected numeric value in {field}: {value!r}")
    return int(str(value).split(".")[0])


def normalize_car(car: dict, page: int, timestamp: str) -> dict:
    """One API record -> the raw row this source keeps (the notebook's ten fields + four more)."""
    name, slug = car.get("display_name"), car.get("slug")
    if not name or not slug or not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise ValueError("A listing is missing a valid display_name or slug.")
    body_type = car.get("body_type")
    if body_type:
        body_type = body_type.upper() if body_type.upper() in {"SUV", "MPV", "CUV"} else body_type.title()
    return {
        "model_year_name": name.strip(),
        # Vucar spells this key 'manufactor_year'.
        "year": optional_integer(car.get("manufactor_year"), "year"),
        "odo_km": optional_integer(car.get("car_mileage"), "odo_km"),
        "car_type": body_type,
        "price_vnd": optional_integer(car.get("car_price"), "price_vnd"),
        "transmission": car.get("car_transmission"),
        "location": car.get("car_location"),
        "url": BASE_URL + "/mua-ban/" + slug,
        "source_page": page,
        "scraped_at_utc": timestamp,
        # kept so unified.py never has to guess the make/model split or the fuel label
        "brand_raw": car.get("car_brand"),
        "model_raw": car.get("car_model"),
        "fuel_raw": car.get("car_fuel_type"),
        "created_at_raw": car.get("created_at"),
    }



def save_csv(rows: list[dict], output: Path) -> None:
    """Write atomically, so an interrupted run never leaves a half-written CSV."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)


def scrape_vucar(
    output: str | Path, *, max_pages: int | None = None,
    per_page: int = 8, delay: float | None = None,
) -> list[dict]:
    """Collect the catalogue. max_pages=None means all pages; 1 is a quick check."""
    if per_page not in (8, 24, 72):
        raise ValueError("per_page must be one of the site's options: 8, 24, 72.")
    if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1):
        raise ValueError("max_pages must be a positive integer or None.")
    delay = config.REQUEST_DELAY if delay is None else delay
    if delay < 0:
        raise ValueError("delay must be non-negative.")

    output = Path(output)
    summary_path = output.with_suffix(".summary.json")
    rows: list[dict] = []
    seen_urls: set[str] = set()
    seen_pages: set[tuple] = set()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {
        "source": CATALOGUE_URL, "scraped_at_utc": timestamp,
        "rows": 0, "pages_fetched": 0, "reported_total": None,
        "reported_page_count": None, "duplicates_skipped": 0,
        "complete": False, "stop_reason": "starting",
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        client = CurlClient(delay=delay)
        log.info("discovering vucar's current public listing action")
        action_id, catalogue_total = discover_listing_action(client)
        log.info("action %s | catalogue total %s", action_id, catalogue_total)
        page = 1
        while True:
            data = fetch_listing_page(client, action_id, page, per_page)
            if data["limit"] != per_page:
                raise RuntimeError("Vucar returned a different page size; stopping to avoid skipped records.")
            if data["total"] == 0 and catalogue_total != 0:
                raise RuntimeError(
                    "The data action returned an empty catalogue, but the listing page did not confirm zero "
                    "cars. Try per_page=8; the site's larger page sizes may be unavailable."
                )
            summary["reported_total"] = data["total"]
            summary["reported_page_count"] = data["pageCount"]
            current = [normalize_car(car, page, timestamp) for car in data["cars"]]
            fingerprint = tuple(sorted(row["url"] for row in current))
            if fingerprint in seen_pages:
                raise RuntimeError(f"Page {page} repeated a previous page; stopping to avoid a pagination loop.")
            if not current and data["total"] > 0:
                raise RuntimeError(f"Page {page} was empty despite a nonempty catalogue.")
            seen_pages.add(fingerprint)

            new_count = 0
            for row in current:
                if row["url"] in seen_urls:
                    summary["duplicates_skipped"] += 1
                    continue
                seen_urls.add(row["url"])
                rows.append(row)
                new_count += 1
            if current and new_count == 0:
                raise RuntimeError(f"Page {page} contained no new listing URLs.")

            summary.update(rows=len(rows), pages_fetched=page, stop_reason="in_progress")
            save_csv(rows, output)
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("page %d/%d: +%d cars; %d/%d unique", page, data["pageCount"],
                     new_count, len(rows), data["total"])

            if page >= data["pageCount"]:
                summary["stop_reason"] = "catalogue_exhausted"
                summary["complete"] = len(rows) == data["total"]
                if not summary["complete"]:
                    warnings.warn("Reached the last page, but the unique count differs from Vucar's total.")
                break
            if max_pages is not None and page >= max_pages:
                summary["stop_reason"] = "max_pages_reached"
                break
            page += 1
    except BaseException as error:
        summary["stop_reason"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "error"
        summary["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        summary["rows"] = len(rows)
        summary["missing_values"] = {
            field: sum(row[field] is None or row[field] == "" for row in rows)
            for field in ("model_year_name", "year", "odo_km", "car_type", "price_vnd")
        }
        if summary["pages_fetched"]:          # never overwrite a good file when discovery failed
            save_csv(rows, output)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("saved %d cars to %s; complete=%s", len(rows), output, summary["complete"])
    return rows



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vucar.vn crawler (raw records)")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="how many pages to read (default: the whole catalogue, 266 pages)")
    parser.add_argument("--per-page", type=int, default=8, choices=(8, 24, 72))
    parser.add_argument("--delay", type=float, default=None, help="seconds between requests")
    parser.add_argument("--out", default=str(config.DATA_PROCESSED / "vucar_raw.csv"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.ensure_dirs()
    scrape_vucar(args.out, max_pages=args.max_pages, per_page=args.per_page, delay=args.delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())

log = logging.getLogger(SOURCE)
