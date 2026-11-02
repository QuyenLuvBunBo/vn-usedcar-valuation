"""vucar.vn source — deals-only marketplace, crawled through its public Next.js data action.

The crawler is `python -m src.sources.vucar` (raw records, 10 + 4 fields); the 21-column contract export is
`python -m src.sources.vucar.unified`. Recon, field map and the measured coverage: docs/sources/vucar.md.

Migration note: the original crawler was a Colab notebook (`vucar_scraper.py.ipynb`); it was removed from
the repository on 2026-11-02 because this package replaces it, and it stays in git history
(`git log --all -- '*vucar_scraper*'`). The package keeps the notebook's request/pagination logic
unchanged and only adds the CLI plus four raw fields the action already returns (car_brand, car_model,
car_fuel_type, created_at), so the exporter never has to guess.
"""

from __future__ import annotations

SOURCE = "vucar"
PLATFORM = "vucar.vn"
