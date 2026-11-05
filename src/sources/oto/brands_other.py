"""All remaining brands (European/US, luxury, Chinese and EV) — owned by Nguyễn Thế Phương.

The list comes from the brand menu on oto.com.vn. Verify or extend it with:
    python -m tools.list_brands          # harvest brand links and validate each slug

Run:  python -m src.sources.oto --group other
"""

from __future__ import annotations

BRANDS: dict[str, str] = {
    "ford": "Ford",
    "vinfast": "VinFast",
    "nissan": "Nissan",
    "mg": "MG",
    "suzuki": "Suzuki",
    "isuzu": "Isuzu",
    "mercedes-benz": "Mercedes-Benz",
    "lexus": "Lexus",
    "bmw": "BMW",
    "land-rover": "Land Rover",
    "audi": "Audi",
    "peugeot": "Peugeot",
    "volkswagen": "Volkswagen",
    "volvo": "Volvo",
    "porsche": "Porsche",
    "bentley": "Bentley",
    "acura": "Acura",
    "byd": "BYD",
    "cadillac": "Cadillac",
    "chevrolet": "Chevrolet",
    "citroen": "Citroen",
    "daewoo": "Daewoo",
    "daihatsu": "Daihatsu",
    "dongben": "Dongben",
    "fiat": "Fiat",
    "foton": "Foton",
    "geely": "Geely",
    "gmc": "GMC",
    "haval": "Haval",
    "infiniti": "Infiniti",
    "jac": "JAC",
    "jaecoo": "Jaecoo",
    "jaguar": "Jaguar",
    "jeep": "Jeep",
    # oto.com.vn exposes two slugs for the same make ("land-rover" and "landrover"): the database already
    # holds 3 ads reached through this one (the other 47 use "land-rover"), so both are crawled and both
    # normalize to "Land Rover".
    "landrover": "Land Rover",
    "lamborghini": "Lamborghini",
    "lincoln": "Lincoln",
    "lynk-co": "Lynk & Co",
    "maserati": "Maserati",
    "maybach": "Maybach",
    "mclaren": "McLaren",
    "mini": "Mini",
    "omoda": "Omoda",
    "renault": "Renault",
    "rolls-royce": "Rolls-Royce",
    "skoda": "Skoda",
    "ssangyong": "SsangYong",
    "subaru": "Subaru",
    "sym": "SYM",
    "teraco": "Teraco",
    "thaco": "Thaco",
    "tmt": "TMT",
    "veam": "Veam",
    "wuling": "Wuling",
    "zotye": "Zotye",
}