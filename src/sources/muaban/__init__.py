"""muaban.net source — replacement for anycar.vn (that site is offline).

Crawl (JSON payload, no HTML scraping):
    python -m src.sources.muaban --pages 2             # quick sample (20 ads/page)
    python -m src.sources.muaban --pages 2 --details   # + one detail page per ad
    python -m src.sources.muaban --details             # every stored ad (resumable)

Export:
    python -m src.sources.muaban.unified               # data/processed/muaban.csv (21 columns)

Recon notes: docs/sources/muaban.md
"""
