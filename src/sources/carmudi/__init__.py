"""carmudi.vn source — passenger-car catalogue, USED cars only (Nguyễn Văn Quyết).

Run:
    python -m src.sources.carmudi --pages 1 --save-raw   # quick recon: check the parsers first
    python -m src.sources.carmudi --save-raw             # crawl listing pages + detail pages
    python -m src.sources.carmudi --from-raw             # re-parse saved HTML, no re-crawl
    python -m src.sources.carmudi.unified                # export data/processed/carmudi.csv (21 cols)
"""
