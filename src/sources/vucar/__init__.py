"""vucar.vn source — deals-only marketplace, crawled through its public Next.js data action.

The crawler is `python -m src.sources.vucar` (raw records, 10 + 4 fields); the 21-column contract export is
`python -m src.sources.vucar.unified`. Recon, field map and the measured coverage: docs/sources/vucar.md.

Migration note: the original crawler lives in `vucar_scraper.py.ipynb` (a Colab script). This module keeps
its request/pagination logic unchanged and only adds the CLI plus four raw fields the action already
returns (car_brand, car_model, car_fuel_type, created_at), so the exporter never has to guess.
"""

from __future__ import annotations

SOURCE = "vucar"
PLATFORM = "vucar.vn"
