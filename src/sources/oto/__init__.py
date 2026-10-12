"""oto.com.vn source — used cars, split across two owners:

    brands_asia.py   : six Asian mainstream brands (Lê Thế Quyền)
    brands_other.py  : all remaining brands / European-US and luxury (Nguyễn Thế Phương)

Run:
    python -m src.sources.oto --group asia           # listings: six Asian brands
    python -m src.sources.oto --group other          # listings: remaining brands
    python -m src.sources.oto --detail-only          # also crawl each listing detail page
    python -m src.sources.oto.unified                # export the 21-column unified CSV
"""
