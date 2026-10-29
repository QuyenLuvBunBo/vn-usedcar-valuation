"""tinbanxe.vn source — USED-car classifieds. Fallback source for Nguyễn Văn Quyết's quota,
because carmudi.vn only lists ~800-950 active ads (leader's decision).

Run:
    python -m src.sources.tinbanxe --brands toyota --pages 2 --save-raw   # quick recon
    python -m src.sources.tinbanxe --save-raw                             # all brands
    python -m src.sources.tinbanxe --from-raw
    python -m src.sources.tinbanxe.unified                                # data/processed/tinbanxe.csv
"""
