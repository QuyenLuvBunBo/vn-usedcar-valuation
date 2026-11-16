"""Backfill the fields a bonbanh detail page publishes, into a patch file — never into v1.

**Fill-only by construction.** The patch carries four columns and nothing else: `listing_id`,
`engine_capacity`, `seller_type`, `body_type` (+ provenance). There is no price, no mileage and no
brand: the merge step (`tools/apply_backfill.py`) refuses to write a column that is not in that list,
so a bug here cannot change the target.

**Which rows need a page.** Only rows where the page is the *only* source:

    engine_capacity  on a statistic (imputed)          -> page prints "Động cơ: Xăng 2.0 L"
    seller_type      on a statistic / "Unknown"        -> page exposes a salon subdomain (a.cname)
    body_type        "Unknown"                         -> page prints "Kiểu dáng"

`sub_model_trim` is **not** crawled: the page title is `brand + model + trim`, and v1's `model`
already contains that trim string ("Custin Cao Cấp 2.0T"), so it is derived offline
(`tools/apply_backfill.py`) from the model we already have. Crawling 18,464 pages for a string that is
already in the row would be 2.4x the requests for no new information.

**Resumable.** Results are flushed to `--out` every `--flush-every` pages; re-running skips the
`listing_id`s already in that file. A block rate above `--block-rate` (default 1 %) stops the run
safely and leaves the partial file in place.

Run:
    python -m tools.backfill_bonbanh --limit 50            # pilot
    python -m tools.backfill_bonbanh                       # full run, resumable
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import pandas as pd
import requests
from lxml import html

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config, schema  # noqa: E402
from src.data_prep.missing import ENGINE_RE  # noqa: E402
from src.sources.bonbanh.crawl import BODY_ALIASES  # noqa: E402

SPLITS = ("train", "val", "test")
PATCH_COLUMNS = ["listing_id", "source_url", "engine_capacity", "seller_type", "body_type",
                 "filled", "state", "fetched_at"]
FILLABLE = ("engine_capacity", "seller_type", "body_type")
SPEC_LABELS = {"Động cơ": "engine", "Kiểu dáng": "body"}
HOST_FIX = ("://bonbanh.com", "://www.bonbanh.com")


def select_rows(sample: int = 0, seed: int = 42) -> pd.DataFrame:
    """Rows where a *page* is the only source for a field, deduplicated by `listing_id`."""
    cohort = pd.concat([pd.read_csv(config.DATA_MASTER / f"{split}_cohort_imputed.csv",
                                    low_memory=False) for split in SPLITS], ignore_index=True)
    bon = cohort[cohort["source_platform"].astype(str) == "bonbanh"].copy()
    history = bon["imputed"].fillna("").astype(str)
    needs_engine = history.str.contains("engine_capacity")
    needs_seller = (history.str.contains("seller_type")
                    | bon["seller_type"].astype(str).str.casefold().eq("unknown"))
    needs_body = (history.str.contains("body_type")
                  | bon["body_type"].astype(str).str.casefold().eq("unknown"))
    needs = needs_engine | needs_seller | needs_body
    pool = bon.loc[needs, ["listing_id", "source_url", "engine_capacity", "seller_type",
                           "body_type", "imputed"]].copy()
    # value first: a row missing engine (the field that moved the score) goes before a seller-only row;
    # the oldest ads are then interleaved rather than crawled as one block, because their pages are the
    # ones that turn out to be empty stubs.
    pool["_engine"] = needs_engine[needs].to_numpy()
    pool["_seller"] = needs_seller[needs].to_numpy()
    pool = pool.sort_values(["_engine", "_seller", "listing_id"], ascending=[False, False, True])
    pool = pool.drop(columns=["_engine", "_seller"])
    pool = pool.drop_duplicates("listing_id").reset_index(drop=True)
    if sample and sample < len(pool):
        pool = pool.sample(n=sample, random_state=seed).sort_values("listing_id").reset_index(drop=True)
    return pool


def prepare_url(url: str) -> str:
    """The apex host times out from this machine; `www.` answers (docs/recon_decision.md §1)."""
    return str(url).replace(*HOST_FIX)


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    frame = pd.read_csv(path, low_memory=False)
    return set(frame["listing_id"].astype(str)) if "listing_id" in frame else set()


def worker_fetch(url: str, timeout: int, delay: float, retries: int = 2) -> tuple[int, str | None]:
    """One page, with a **jittered** delay and a small retry budget.

    The sleep is `delay * uniform(0.8, 1.4)`, not `delay + noise`: a fixed cadence is what a WAF keys
    on, and four hours of it is a pattern. Returns `(status, html|None)`.
    """
    headers = dict(config.DEFAULT_HEADERS)
    for attempt in range(retries + 1):
        time.sleep(delay * random.uniform(0.8, 1.4))
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = resp.apparent_encoding
                return resp.status_code, resp.text
            if resp.status_code in (403, 429, 503):
                return resp.status_code, None
            if 500 <= resp.status_code < 600 and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return resp.status_code, None
        except requests.RequestException:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return 0, None
    return 0, None


def keep_only_blanks(row: pd.Series, parsed: dict) -> dict:
    """Fill-only, and that includes replacing a **statistic** — but never a value the site printed.

    A cell is fillable when
      * it is empty / `Unknown` / NaN, **or**
      * the column is listed in the row's `imputed` history (the value there is an imputation, not an
        observation of this car).

    A cell with a real value and no `imputed` marker is never touched, so a page can never overwrite
    what v1 observed. The v2 snapshot records the replacement in `v2_filled` and removes the column
    from `imputed`, so a reader can tell an observed value from a statistic.
    """
    history = str(row.get("imputed") or "")
    filled = {part for part in history.split(";") if part}
    kept = {}
    for column in FILLABLE:
        value = parsed.get(column)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        blank = str(row.get(column) or "").strip().casefold() in ("", "nan", "none", "unknown")
        if blank or column in filled:
            kept[column] = value
    return kept


COOLDOWNS = (180, 300, 600)     # seconds, escalating; a probe decides whether to resume
MAX_CYCLES = 3                  # three consecutive blocked cycles -> give up for this run


class CooldownGate:
    """Pause every worker on a soft block, probe once, and resume only if the probe is a real page.

    One worker becomes the "cooldown owner": it sleeps the current step (180 -> 300 -> 600 s), fetches
    one page, and either resets the ladder (probe OK) or escalates. After three consecutive blocked
    cycles it sets `stopped`, and the run ends with the partial file intact. The other workers park on
    `wait()` for the same window instead of hammering a site that is already refusing them.
    """

    def __init__(self, fetch, probe_url: str, sleep=time.sleep):
        self.fetch = fetch
        self.probe_url = probe_url
        self.sleep = sleep
        self.lock = Lock()
        self.paused_until = 0.0
        self.cycles = 0
        self.stopped = False
        self.owner = False            # a worker is running the cooldown ladder right now
        self.events: list[dict] = []

    def wait(self) -> bool:
        """Block until the gate is open. False means the run is over."""
        while True:
            with self.lock:
                remaining = self.paused_until - time.monotonic()
                stopped = self.stopped
            if stopped:
                return False
            if remaining <= 0:
                return True
            self.sleep(min(remaining, 5))

    def block(self, listing_id: str = "") -> bool:
        """Called by a worker that received a captcha page. True = keep going, False = stop."""
        with self.lock:
            if self.stopped:
                return False
            if self.owner:
                return True                      # another worker is already cycling; it sets the state
            step = COOLDOWNS[min(self.cycles, len(COOLDOWNS) - 1)]
            self.cycles += 1
            cycle = self.cycles
            self.owner = True
            self.paused_until = time.monotonic() + step
        print(f"  SOFT BLOCK at {listing_id}: cooling down {step}s (cycle {cycle}/{MAX_CYCLES})",
              flush=True)
        ok = False
        try:
            self.sleep(step)
            status, page = self.fetch(self.probe_url)
            ok = status == 200 and not is_soft_block(page)
        finally:
            with self.lock:
                self.owner = False
                self.paused_until = 0.0
                self.events.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "cycle": cycle, "cooldown_seconds": step,
                                    "probe_ok": ok})
                if ok:
                    self.cycles = 0
                elif self.cycles >= MAX_CYCLES:
                    self.stopped = True
        return ok or not self.stopped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill bonbanh detail fields into a patch file")
    parser.add_argument("--out", default="data/processed/bonbanh_backfill.csv",
                        help="patch file (7 columns). NOT bonbanh_extra.csv — that name is the "
                             "week-2 top-up source with the 21-column contract")
    parser.add_argument("--workers", type=int, default=8, help="parallel fetchers (each keeps --delay)")
    parser.add_argument("--delay", type=float, default=1.5, help="seconds per request, per worker")
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--flush-every", type=int, default=200, help="rows between two disk flushes")
    parser.add_argument("--limit", type=int, default=0, help="stop after N pages this run (0 = all)")
    parser.add_argument("--sample", type=int, default=0, help="random pilot of N rows (0 = all)")
    parser.add_argument("--block-rate", type=float, default=0.01,
                        help="stop when 403/429/errors exceed this share (default 0.01 = 1 percent)")
    parser.add_argument("--max-minutes", type=float, default=0,
                        help="stop gracefully after N minutes (resumable)")
    parser.add_argument("--progress", default="data/processed/bonbanh_extra_progress.json")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = config.ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        existing = list(pd.read_csv(out, nrows=0).columns)
        if existing != PATCH_COLUMNS:
            raise SystemExit(
                f"{out.name} exists with a different schema ({', '.join(existing[:4])}…) — this tool "
                f"writes {len(PATCH_COLUMNS)} columns; pick another --out rather than mixing a patch "
                f"into a source file")
    done = load_done(out)
    pool = select_rows(args.sample)
    pending = pool[~pool["listing_id"].astype(str).isin(done)].reset_index(drop=True)
    if args.limit:
        pending = pending.head(args.limit)
    print(f"selected {len(pool):,} rows needing a page · {len(done):,} already in {out.name} · "
          f"{len(pending):,} to fetch now")

    started = time.monotonic()
    lock = Lock()
    results: list[dict] = []
    stats = {"attempts": 0, "ok": 0, "blocked": 0, "errors": 0, "filled": 0}
    stop = False
    probe_url = (prepare_url(str(pending.iloc[0]["source_url"])) if len(pending)
                 else "https://www.bonbanh.com/")
    gate = CooldownGate(fetch=lambda url: worker_fetch(url, args.timeout, args.delay),
                        probe_url=probe_url)

    def flush() -> None:
        nonlocal results
        if not results:
            return
        frame = pd.DataFrame(results, columns=PATCH_COLUMNS)
        frame.to_csv(out, mode="a", header=not out.exists(), index=False, lineterminator="\n")
        results = []

    def handle(row: pd.Series) -> dict | None:
        nonlocal stop
        if stop or not gate.wait():
            return None
        status, page = worker_fetch(prepare_url(row["source_url"]), args.timeout, args.delay)
        if is_soft_block(page):
            keep_going = gate.block(str(row["listing_id"]))
            with lock:
                stats["attempts"] += 1
                stats["blocked"] += 1
            if not keep_going:
                stop = True
                print("  STOP: three cooldown cycles without a real page — partial file kept", flush=True)
            return None                       # never write a row for a blocked request
        try:
            parsed = parse_fields(page) if page else {}
        except Exception as exc:                       # noqa: BLE001 - a bad page must not kill the run
            parsed = {}
            print(f"  parse error on {row['listing_id']}: {exc!r}")
        kept = keep_only_blanks(row, parsed)
        with lock:
            stats["attempts"] += 1
            if status == 200:
                stats["ok"] += 1
            elif status in (403, 429, 503):
                stats["blocked"] += 1
            else:
                stats["errors"] += 1
            stats["filled"] += 1 if kept else 0
            attempts = stats["attempts"]
            bad = stats["blocked"] + stats["errors"]
            if attempts >= 100 and bad / attempts > args.block_rate:
                stop = True
                print(f"  STOP: block/error rate {bad / attempts:.2%} above {args.block_rate:.0%} "
                      f"after {attempts} requests — partial file kept ({out.name})")
            if attempts % args.flush_every == 0:
                elapsed = time.monotonic() - started
                rate = attempts / elapsed if elapsed else 0.0
                eta = (len(pending) - attempts) / rate / 60 if rate else 0.0
                print(f"  {attempts:>5,}/{len(pending):,} ({attempts / max(len(pending), 1):.1%}) · "
                      f"ok {stats['ok']:,} · filled {stats['filled']:,} · blocked "
                      f"{stats['blocked']:,} · {rate:.2f} req/s · ETA {eta:.0f} min", flush=True)
        if not kept:
            state = "empty" if not parsed else "no-gain"
            if status == 404:
                state = "dead"
            elif status in (403, 429, 503):
                state = "blocked"
            elif status != 200:
                state = "error"
            return {"listing_id": row["listing_id"], "source_url": row["source_url"],
                    "engine_capacity": None, "seller_type": None, "body_type": None,
                    "filled": "", "state": state,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        return {"listing_id": row["listing_id"], "source_url": row["source_url"],
                **{column: kept.get(column) for column in FILLABLE},
                "filled": ";".join(sorted(kept)), "state": "filled",
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(handle, row): row["listing_id"]
                   for _, row in pending.iterrows()}
        for count, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            with lock:
                if row:
                    results.append(row)
                if len(results) >= args.flush_every:
                    flush()
                if args.max_minutes and (time.monotonic() - started) > args.max_minutes * 60:
                    stop = True
            if args.max_minutes and (time.monotonic() - started) > args.max_minutes * 60:
                stop = True
    flush()

    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "selected": int(len(pool)), "already_done": int(len(done)),
               "attempted_this_run": int(stats["attempts"]), "ok_this_run": int(stats["ok"]),
               "filled_this_run": int(stats["filled"]), "blocked": int(stats["blocked"]),
               "errors": int(stats["errors"]), "stopped_early": bool(stop),
               "cooldowns": gate.events,
               "out": str(out), "rows_in_file": int(len(load_done(out)))}
    Path(args.progress).parent.mkdir(parents=True, exist_ok=True)
    Path(args.progress).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
    print(f"\n  patch -> {out} ({payload['rows_in_file']:,} rows total)")
    print(f"  progress -> {args.progress}")
    return 0 if not stop else 2


def is_soft_block(page_html: str | None) -> bool:
    """bonbanh answers a 200 with a ~1 KB "Thông báo !!!" page when it rate-limits a client.

    Treating that page as "the ad is empty" would silently record 1,865 dead rows and skip them on
    resume (it did, once). A soft block must stop the run instead.
    """
    if not page_html:
        return True
    lowered = page_html[:4000].casefold()
    return "captcha" in lowered or ("thông báo" in lowered and len(page_html) < 5000)


def parse_fields(page_html: str) -> dict:
    """Engine displacement, body style and the salon subdomain — the three the page adds."""
    tree = html.fromstring(page_html)
    specs: dict[str, str] = {}
    for row in tree.xpath('//div[contains(@class,"box_car_detail")]//div[@class="row" or @class="row_last"]'):
        label = " ".join(row.xpath('.//div[@class="label"]//text()')).strip().rstrip(":").strip()
        value = " ".join(row.xpath('.//div[@class="txt_input"]//text()')).strip()
        key = SPEC_LABELS.get(label)
        if key and value:
            specs[key] = value

    found: dict[str, object] = {}
    if "engine" in specs:
        match = ENGINE_RE.search(specs["engine"])
        if match:
            found["engine_capacity"] = float(match.group(1).replace(",", "."))
    if "body" in specs:
        raw = specs["body"].strip()
        found["body_type"] = schema.normalize_body(BODY_ALIASES.get(raw.casefold(), raw))
    href = next(iter(tree.xpath('//a[contains(@class,"cname")]/@href')), None)
    if href:
        found["seller_type"] = schema.seller_type_from_subdomain(href)
    return found


if __name__ == "__main__":
    raise SystemExit(main())
