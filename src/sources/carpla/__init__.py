"""carpla.vn source — top-up crawl of the dealership catalogue.

Why this exists: `carpla.csv` holds 1,322 cars, while carpla's own `sitemap_product.xml` lists **4,181**
vehicle pages. `/mua-xe` is a 1.4 MB JS-rendered page with no working `?page=` handling, so the sitemap
is the only reliable enumeration: one `<loc>` list of detail URLs, no pagination to guess.

The detail page is a Next.js app with no JSON-LD. Two extractions are therefore combined:

  * the rendered text, where the specs sit as "label|value" pairs —
    "Nhiên liệu|Dầu|Kiểu dáng|SUV|Hộp số|Số tự động|Số chỗ|7";
  * the RSC payload, where the escaped JSON still carries the exact numbers —
    `\"price\":689000000`, `\"odo\":102000`, `\"postedAt\":[1777365105]`.

`robots.txt` blocks only filter URLs (`*?brand=*`, `*?new`, `*?figure=*`), which this crawler never uses.

Crawl (adds only the cars no existing carpla file has):
    python -m src.sources.carpla --limit 3             # quick sample
    python -m src.sources.carpla                       # the whole sitemap (~4,181 pages)
    python -m src.sources.carpla --include-existing    # keep the cars we already have too

Export: data/processed/carpla_extra.csv (21 columns) — merge it with
    python -m src.merge.build_master

Recon: docs/crawl_gap.md. Not exposed by the site: engine displacement, origin (CKD/CBU), mileage per
year. `seller_type` is always Dealership/Salon — carpla only lists its own inventory.
"""
