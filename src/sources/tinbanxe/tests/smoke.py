"""Offline tests for src.sources.tinbanxe (fixture RECONSTRUCTED from recon, not saved site HTML)."""
from pathlib import Path
from src.sources.tinbanxe.crawl import parse_list_page
from src.sources.tinbanxe.unified import build_unified, mileage_km, listing_date

def check(label, got, exp):
    ok = got == exp; print(f"[{'PASS' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f" != {exp!r}")); return ok
cards = parse_list_page(Path(__file__).parent.joinpath("fixtures/list_page.html").read_text(encoding="utf-8"), "toyota")
rows, _ = build_unified(cards)
r = {x["listing_id"]: x for x in rows}
res = [check("cards", len(cards), 2), check("id", cards[0]["id"], "88602"), check("km_text", cards[0]["km_text"], "86"),
       check("province from location row", cards[0]["province"], "Hồ Chí Minh"),
       check("km x1000", r["TBX_88602"]["mileage_km"], 86000.0), check("km 70 vs '7 vạn'", r["TBX_87992"]["mileage_km"], 70000.0),
       check("price", r["TBX_88602"]["price_vnd"], 195_000_000), check("year", r["TBX_88602"]["manufacture_year"], 2017),
       check("trans", r["TBX_87992"]["transmission"], "Automatic"), check("seats not inferred from listing", r["TBX_88602"]["seats"], None),
       check("brand", r["TBX_88602"]["brand"], "Toyota"), check("model", r["TBX_88602"]["model"], "Vios"),
       check("date inferred", (r["TBX_88602"]["listing_date"] or "")[:10], "2026-10-19"),
       check("bad folder -> None", listing_date("image_tin_dang/2025_01/1792379660-0-x"), None),
       check("km 95000 kept", mileage_km("95000", ""), 95000)]
print(f"{sum(res)}/{len(res)} passed"); raise SystemExit(0 if all(res) else 1)
