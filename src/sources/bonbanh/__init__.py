"""bonbanh.com source — top-up crawl of the part of the catalogue we never collected.

Why this exists: `bonbanh_new.csv` (7,374 ads, 2019+) and `bonbanh_oldcars.csv` (exactly 5,000 ads,
1995–2018 — a hard cap, not the end of the list) hold 12,374 of the **29,241** ads bonbanh prints on
`/oto`. This crawler walks the listing pages for whatever is missing and writes only the new ids.

The listing page is enough: every card carries schema.org microdata (price, province) plus a structured
one-line summary — "Xe nhập khẩu, màu trắng, máy xăng 2.0 L, số tự động, 8 chỗ, đã đi 35,000 km" — so
origin, fuel, engine, transmission, seats and odometer all come from the page we already fetched.
No detail request is needed, which keeps the whole top-up at ~20 ads per request.

`robots.txt` is 7 lines with no `Disallow` at all. Pagination verified: `/oto/page,N` returns 20 distinct
ads per page with no overlap, ≈1,462 pages for the full catalogue.

The listing card does **not** print three fields — body style, seller type and posting date. They are on
the detail page, which is one more request per ad, so it is a separate, resumable step:

    python -m src.sources.bonbanh --details            # + body_type / seller_type / listing_date
    python -m src.sources.bonbanh --details --detail-limit 3000   # chunk it across several runs
    python -m src.sources.bonbanh --reexport           # rebuild the CSV from the DB (no requests)
    python tools/bonbanh_progress.py                   # progress, coverage and ETA

Crawl (adds only the ads no existing bonbanh file has):
    python -m src.sources.bonbanh --pages 3            # quick sample, 3 listing pages
    python -m src.sources.bonbanh                     # the whole catalogue (~1,462 pages)
    python -m src.sources.bonbanh --from-page 600     # resume from page 600
    python -m src.sources.bonbanh --include-existing  # keep the ads we already have too

Export: data/processed/bonbanh_extra.csv (21 columns) — merge it with
    python -m src.merge.build_master

Recon: docs/crawl_gap.md.
"""
