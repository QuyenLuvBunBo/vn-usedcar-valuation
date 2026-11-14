"""Light recon: are the v1 listing URLs still alive, and do the live pages carry the missing fields?

The question this answers, before anyone spends a day crawling: for the rows where v1 is missing
`engine_capacity`, `sub_model_trim`, `seller_type` or `body_type`, is the detail page (a) still there,
and (b) does it actually publish those fields?

Two rates per platform:

    link health     alive / dead (404, redirect away, "listing removed" page, network error)
    field presence  among the alive pages: does the HTML contain a value for each field

The sample is drawn from the frozen v1 rows (the IDs the team will actually re-crawl), seeded, and
deduplicated. Nothing is written into `data/master` except the report.

Run:
    python -m tools.recon_detail_fields --sample 100
    python -m tools.recon_detail_fields --platforms chotot bonbanh --sample 150
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import config  # noqa: E402
from src.common.http_client import ScraperSession  # noqa: E402

SPLITS = ("train", "val", "test")
FIELDS = ("engine_capacity", "sub_model_trim", "seller_type", "body_type")

# Text that means "this listing is gone" even when the server still answers 200.
REMOVED_MARKERS = (
    "tin đăng không tồn tại", "tin đăng đã hết hạn", "tin đã hết hạn", "tin không tồn tại",
    "tin đăng đã bị xoá", "tin đăng đã bị xóa", "không tìm thấy tin", "bài đăng không tồn tại",
    "listing not found", "this listing is no longer available", "tin rao không tồn tại",
)
# Field probes: someone reading the page would find the value next to one of these labels.
PROBES = {
    "engine_capacity": (re.compile(r"(dung t[ií]ch|động cơ|engine)", re.I),
                        re.compile(r"\b[0-9][.,][0-9]\s*(l|lít|lit|t|d)\b", re.I)),
    "sub_model_trim": (re.compile(r"(phi[eê]n b[aả]n|kiểu dáng|dòng xe|trim)", re.I),),
    "seller_type": (re.compile(r"(c[áa] nh[âa]n|salon|showroom|đại l[ýy]|người bán|chính chủ)", re.I),),
    "body_type": (re.compile(r"\b(sedan|suv|crossover|hatchback|mpv|b[áa]n t[aả]i|pickup|van)\b", re.I),),
}


def prepare_url(url: str) -> str:
    """`bonbanh.com` times out on the apex host; `www.` answers. Applied only to that host."""
    parts = urlsplit(url)
    if parts.netloc.lower() in ("bonbanh.com",):
        return urlunsplit((parts.scheme or "https", "www.bonbanh.com", parts.path, parts.query, ""))
    return url


def sample_rows(platform: str, sample: int, seed: int) -> pd.DataFrame:
    """Rows of the frozen cohort where at least one of the four fields is missing."""
    cohort = pd.concat([pd.read_csv(config.DATA_MASTER / f"{split}_cohort_imputed.csv",
                                    low_memory=False) for split in SPLITS], ignore_index=True)
    cohort = cohort[cohort["source_platform"].astype(str) == platform]

    history = cohort["imputed"].fillna("").astype(str)
    missing_any = (history.str.contains("engine_capacity")
                   | cohort["engine_capacity"].isna()
                   | cohort["sub_model_trim"].isna()
                   | cohort["seller_type"].astype(str).str.casefold().eq("unknown")
                   | cohort["body_type"].astype(str).str.casefold().eq("unknown"))

    pool = cohort.loc[missing_any, ["listing_id", "source_url"] + list(FIELDS)]
    pool = pool.drop_duplicates("listing_id").dropna(subset=["source_url"])
    return pool.sample(n=min(sample, len(pool)), random_state=seed).reset_index(drop=True)


def classify(resp, text: str, original_url: str) -> tuple[str, str]:
    """`(health, reason)`: alive / dead_404 / dead_removed / dead_redirect / dead_error."""
    if resp is None:
        return "dead_error", "no response"
    if resp.status_code == 404:
        return "dead_404", "http 404"
    if resp.status_code >= 400:
        return "dead_error", f"http {resp.status_code}"
    lowered = text.casefold()
    for marker in REMOVED_MARKERS:
        if marker in lowered:
            return "dead_removed", marker
    if resp.history:
        final, original = urlsplit(resp.url), urlsplit(original_url)
        if final.path.rstrip("/") != original.path.rstrip("/"):
            return "dead_redirect", f"-> {resp.url}"
    return "alive", resp.url


def has_field(text: str, field: str) -> bool:
    """A label is not enough for engine: the label and a displacement-shaped value must both appear."""
    return all(bool(probe.search(text)) for probe in PROBES[field])


def fetch_raw(session: ScraperSession, url: str):
    """One GET that keeps the status code.

    `ScraperSession.get` deliberately maps 404 to `None` for the crawlers, but this recon is *about*
    the status codes, so it uses the session's own delay and then the underlying session directly.
    """
    import requests

    session._sleep_if_needed()                       # keep the polite gap, same as the crawlers
    try:
        resp = session.session.get(url, timeout=session.timeout, allow_redirects=True)
        session._last_request_at = time.monotonic()
        return resp
    except requests.RequestException:
        return None


def write_doc(doc: Path, report: dict) -> None:
    lines = [
        "# Recon — are the v1 links alive, and do the live pages carry the missing fields?",
        "",
        f"Generated {report['generated_at']} by `python -m tools.recon_detail_fields` "
        f"(sample {report['sample']} per platform, seed {report['seed']}). Rows were drawn from the "
        f"frozen cohort, from listings that are **missing at least one** of the four fields.",
        "",
        "## (a) Link health",
        "",
        "| Platform | Sampled | Alive | alive % | 404 | removed page | redirect | error |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for platform, block in report["platforms"].items():
        health = block["health"]
        lines.append(f"| {platform} | {block['sampled']} | {block['alive']} | "
                     f"{100 * (block['alive_rate'] or 0):.1f}% | {health.get('dead_404', 0)} | "
                     f"{health.get('dead_removed', 0)} | {health.get('dead_redirect', 0)} | "
                     f"{health.get('dead_error', 0)} |")
    lines += ["", "## (b) Field presence among the live pages", "",
              "| Platform | Alive pages | engine_capacity | sub_model_trim | seller_type | body_type |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for platform, block in report["platforms"].items():
        cells = []
        for field in FIELDS:
            stats = block["field_presence_among_alive"][field]
            cells.append("—" if stats["rate"] is None else f"{100 * stats['rate']:.1f}%")
        lines.append(f"| {platform} | {block['alive']} | " + " | ".join(cells) + " |")
    lines += ["", "## Reading it", "",
              "- A field counts as present only if the page shows the **label and a value** — a page "
              "that merely mentions \"SUV\" in an unrelated block is not counted for `body_type`.",
              "- `dead_removed` means the server answered 200 but the page says the listing is gone: "
              "counting only HTTP 404 would overstate the alive rate.",
              "- `bonbanh` answers on `www.bonbanh.com`; the apex host timed out during preparation, so "
              "a `dead_error` there may be a host problem rather than a dead ad.",
              "- **No crawl is started from this report.** A platform is worth a full re-crawl only if "
              "the alive rate and the field rates are both high enough to justify the requests.", ""]
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Link health + field presence on a v1 sample")
    parser.add_argument("--platforms", nargs="+", default=["chotot", "bonbanh"])
    parser.add_argument("--sample", type=int, default=100, help="rows per platform (50-200)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--out", default=str(config.DATA_MASTER / "recon_detail_report.json"))
    parser.add_argument("--doc", default="docs/recon_detail_fields.md")
    parser.add_argument("--append", action="store_true",
                        help="merge into an existing report instead of replacing it (one platform "
                             "per call when the whole sample would run too long)")
    args = parser.parse_args(argv)

    existing = {}
    if args.append and Path(args.out).exists():
        existing = json.loads(Path(args.out).read_text(encoding="utf-8")).get("platforms", {})
    report = {"generated_at": config.now_iso(), "sample": args.sample, "seed": args.seed,
              "note": "sample drawn from the frozen v1 cohort rows missing at least one field",
              "platforms": dict(existing)}

    with ScraperSession(delay=args.delay, timeout=args.timeout) as session:
        for platform in args.platforms:
            rows = sample_rows(platform, args.sample, args.seed)
            print(f"\n{platform}: {len(rows)} sampled rows")
            health: dict[str, int] = {}
            present = {field: 0 for field in FIELDS}
            alive = 0
            examples = []
            for index, row in rows.iterrows():
                url = prepare_url(str(row["source_url"]))
                started = time.monotonic()
                try:
                    resp = fetch_raw(session, url)
                except Exception as exc:                          # noqa: BLE001 - recon must not die
                    resp = None
                    print(f"  {row['listing_id']}: error {type(exc).__name__}")
                text = ""
                if resp is not None and resp.status_code == 200:
                    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                        resp.encoding = resp.apparent_encoding
                    text = resp.text
                state, reason = classify(resp, text, url)
                health[state] = health.get(state, 0) + 1
                if state == "alive":
                    alive += 1
                    for field in FIELDS:
                        present[field] += int(has_field(text, field))
                if index < 5 or state != "alive":
                    examples.append({"listing_id": row["listing_id"], "url": url,
                                     "state": state, "reason": str(reason)[:120]})
                print(f"  {row['listing_id']:22s} {state:14s} {str(reason)[:50]} "
                      f"({time.monotonic() - started:.1f}s)")

            report["platforms"][platform] = {
                "sampled": int(len(rows)),
                "health": health,
                "alive": alive,
                "alive_rate": round(alive / len(rows), 4) if len(rows) else None,
                "field_presence_among_alive": {
                    field: {"count": present[field],
                            "rate": round(present[field] / alive, 4) if alive else None}
                    for field in FIELDS},
                "examples": examples,
            }
            print(f"  alive {alive}/{len(rows)} · "
                  + ", ".join(f"{field} {present[field]}/{alive}" for field in FIELDS))

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    doc = (Path(args.doc) if Path(args.doc).is_absolute()
           else Path(__file__).resolve().parents[1] / args.doc)
    write_doc(doc, report)
    print(f"\n  json -> {args.out}\n  doc  -> {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
