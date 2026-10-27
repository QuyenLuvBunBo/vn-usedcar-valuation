"""Normalize tinbanxe.vn into the 21-column Unified Schema -> data/processed/tinbanxe.csv.

Decisions (document them in the PR):
  * mileage_km: the site prints mileage in THOUSANDS ("đã đi 86 km" = 86,000 km). A value < 1000
    is multiplied by 1000; the description ("odo 86.000km", "7 vạn") is used when it disagrees.
  * listing_date: INFERRED from the upload timestamp inside the image path
    (image_tin_dang/2026_10/<epoch>-...), accepted only when its year/month matches the folder.
  * model: best effort from the title (the card has no model field) — improve via detail page.
  * origin / body_type / seller_type: not on the card -> Unknown.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone

from ...common import config, schema, storage
from ...common.parsing import parse_vnd_price, parse_year_text, to_int
from ..carmudi.unified import MAX_PLAUSIBLE_KM, derive_trim, engine_from, km_from_description, norm_gearbox, safe_enum
from .crawl import IMG_TS_RE

SOURCE_PLATFORM = "tinbanxe"
BRAND_NAMES = {"mercedes-benz": "Mercedes-Benz", "lynk-co": "Lynk & Co", "mg": "MG", "gac": "GAC", "byd": "BYD",
               "bmw": "BMW", "vinfast": "VinFast", "ram": "RAM", "mini": "MINI", "dongfeng": "DongFeng"}
STOP = {"bán", "xe", "cần", "số", "sàn", "tự", "động", "chính", "chủ", "một", "đời", "sản", "xuất", "full"}
log = logging.getLogger("tinbanxe_unified")


def brand_name(slug: str) -> str:
    return BRAND_NAMES.get(slug, slug.title())


def mileage_km(km_text: str | None, desc: str | None) -> int | None:
    from_desc = km_from_description(desc)
    raw = re.sub(r"\D", "", km_text or "")
    value = int(raw) if raw else None
    if value is not None and 0 < value < 1000:
        value *= 1000                      # thousands-of-km quirk
    if from_desc and value and from_desc != value and abs(from_desc - value) / max(from_desc, value) > 0.2:
        value = from_desc                  # description disagrees -> trust the text
    value = value or from_desc
    return value if value and 0 < value <= MAX_PLAUSIBLE_KM else None


def listing_date(img_src: str | None) -> str | None:
    m = IMG_TS_RE.search(img_src or "")
    if not m:
        return None
    ts = datetime.fromtimestamp(int(m.group(3)), tz=timezone.utc)
    return ts.isoformat(timespec="seconds") if (ts.year, ts.month) == (int(m.group(1)), int(m.group(2))) else None



# Curated URL aliases for model names that are often truncated by title tokenization.
# These are used only when the listing URL contains an explicit model slug.
MODEL_URL_ALIASES = {
    "Toyota": {"corolla-cross":"Corolla Cross", "yaris-cross":"Yaris Cross", "innova-cross":"Innova Cross", "corolla-altis":"Corolla Altis", "land-cruiser-prado":"Land Cruiser Prado", "land-cruiser":"Land Cruiser", "fortuner":"Fortuner", "sienna":"Sienna", "innova":"Innova", "avanza":"Avanza", "veloz":"Veloz", "raize":"Raize", "hilux":"Hilux", "camry":"Camry", "corolla":"Corolla", "vios":"Vios", "yaris":"Yaris", "wigo":"Wigo", "zace":"Zace", "rush":"Rush", "hiace":"Hiace", "alphard":"Alphard", "vellfire":"Vellfire", "vigo":"Vigo", "cross":"Corolla Cross", "altis":"Corolla Altis"},
    "Honda": {"odyssey":"Odyssey", "cr-v":"CR-V", "crv":"CR-V", "hr-v":"HR-V", "hrv":"HR-V", "br-v":"BR-V", "brv":"BR-V", "wr-v":"WR-V", "wrv":"WR-V", "accord":"Accord", "civic":"Civic", "city":"City", "jazz":"Jazz", "brio":"Brio"},
    "Hyundai": {"grand-starex":"Grand Starex", "grand-i10":"Grand i10", "santa-fe":"Santa Fe", "veracruz":"Veracruz", "veloster":"Veloster", "palisade":"Palisade", "stargazer":"Stargazer", "tucson":"Tucson", "staria":"Staria", "starex":"Starex", "accent":"Accent", "elantra":"Elantra", "creta":"Creta", "kona":"Kona", "custin":"Custin", "universe":"Universe", "verna":"Verna", "venue":"Venue", "avante":"Avante", "sonata":"Sonata", "i10":"i10", "i20":"i20", "i30":"i30", "county":"County", "solati":"Solati", "getz":"Getz"},
    "Kia": {"grand-carnival":"Grand Carnival", "grand-sedona":"Grand Sedona", "sportage":"Sportage", "sorento":"Sorento", "carnival":"Carnival", "seltos":"Seltos", "sonet":"Sonet", "carens":"Carens", "sedona":"Sedona", "cerato":"Cerato", "morning":"Morning", "forte":"Forte", "rio":"Rio", "rondo":"Rondo", "soluto":"Soluto", "picanto":"Picanto", "k5":"K5", "k3":"K3"},
    "Ford": {"ecosport":"EcoSport", "territory":"Territory", "everest":"Everest", "explorer":"Explorer", "ranger":"Ranger", "transit":"Transit", "escape":"Escape", "focus":"Focus", "fiesta":"Fiesta", "mondeo":"Mondeo", "laser":"Laser", "tourneo":"Tourneo", "raptor":"Raptor"},
    "Mazda": {"cx-30":"CX-30", "cx30":"CX-30", "cx-3":"CX-3", "cx3":"CX-3", "cx-5":"CX-5", "cx5":"CX-5", "cx-8":"CX-8", "cx8":"CX-8", "cx-9":"CX-9", "bt-50":"BT-50", "bt50":"BT-50", "mazda2":"Mazda2", "mazda3":"Mazda3", "mazda6":"Mazda6", "323":"323", "626":"626"},
    "Mitsubishi": {"pajero-sport":"Pajero Sport", "xpander-cross":"Xpander Cross", "outlander":"Outlander", "xpander":"Xpander", "triton":"Triton", "attrage":"Attrage", "pajero":"Pajero", "xforce":"Xforce", "mirage":"Mirage", "lancer":"Lancer", "jolie":"Jolie", "grandis":"Grandis", "zinger":"Zinger"},
    "Lexus": {"gx-460":"GX 460", "gx460":"GX 460", "gx-470":"GX 470", "gx470":"GX 470", "rx-450h":"RX 450h", "rx450h":"RX 450h", "rx-350":"RX 350", "rx350":"RX 350", "rx-300":"RX 300", "rx300":"RX 300", "lx-570":"LX 570", "lx570":"LX 570", "lx-600":"LX 600", "lx600":"LX 600", "es-250":"ES 250", "es250":"ES 250", "es-350":"ES 350", "es350":"ES 350", "ls-460":"LS 460", "ls460":"LS 460", "gs-300":"GS 300", "gs300":"GS 300", "nx-200t":"NX 200t", "nx200t":"NX 200t", "nx-300":"NX 300", "nx300":"NX 300"},
    "Peugeot": {"5008":"5008", "3008":"3008", "2008":"2008", "408":"408", "508":"508", "traveller":"Traveller", "partner":"Partner", "expert":"Expert", "208":"208", "308":"308"},
    "BMW": {"gran-tourer":"Gran Tourer", "active-tourer":"Active Tourer", "x1":"X1", "x2":"X2", "x3":"X3", "x4":"X4", "x5":"X5", "x6":"X6", "x7":"X7", "z4":"Z4", "318i":"318i", "320i":"320i", "325i":"325i", "330i":"330i", "420i":"420i", "430i":"430i", "520i":"520i", "523i":"523i", "525i":"525i", "528i":"528i", "530i":"530i", "535i":"535i", "730li":"730Li", "740li":"740Li", "750li":"750Li", "320gt":"320GT"},
    "Mercedes-Benz": {"sprinter":"Sprinter", "v250":"V250", "gla":"GLA", "glb":"GLB", "glc":"GLC", "gle":"GLE", "gls":"GLS", "glk":"GLK", "cla":"CLA", "c200":"C200", "c250":"C250", "c300":"C300", "e200":"E200", "e240":"E240", "e250":"E250", "e300":"E300", "s350":"S350", "s400":"S400", "s450":"S450", "s500":"S500"},
    "Chevrolet": {"trailblazer":"Trailblazer", "colorado":"Colorado", "captiva":"Captiva", "spark":"Spark", "cruze":"Cruze", "lacetti":"Lacetti", "orlando":"Orlando", "vivant":"Vivant", "aveo":"Aveo", "trax":"Trax"},
    "Isuzu": {"hi-lander":"Hi-Lander", "hilander":"Hi-Lander", "d-max":"D-Max", "dmax":"D-Max", "mu-x":"MU-X", "mux":"MU-X", "trooper":"Trooper", "qkr":"QKR"},
    "VinFast": {"vf-e34":"VF e34", "vfe34":"VF e34", "vf-9":"VF9", "vf9":"VF9", "vf-8":"VF8", "vf8":"VF8", "vf-7":"VF7", "vf7":"VF7", "vf-6":"VF6", "vf6":"VF6", "vf-5":"VF5", "vf5":"VF5", "vf-3":"VF3", "vf3":"VF3", "vf2":"VF2", "fadil":"Fadil", "limo-green":"Limo Green", "lux-sa-2-0":"Lux SA2.0", "lux-a-2-0":"Lux A2.0", "lux":"Lux"},
    "Suzuki": {"grand-vitara":"Grand Vitara", "swift":"Swift", "ertiga":"Ertiga", "xl7":"XL7", "celerio":"Celerio", "ciaz":"Ciaz", "vitara":"Vitara", "jimny":"Jimny", "wagon-r":"Wagon R", "apv":"APV", "super-carry":"Super Carry", "carry":"Carry"},
    "BYD": {"sealion-6":"Sealion 6", "sealion6":"Sealion 6", "sealion":"Sealion", "atto-3":"Atto 3", "atto3":"Atto 3", "dolphin":"Dolphin", "han":"Han", "seal":"Seal", "m6":"M6", "tang":"Tang"},
    "Porsche": {"panamera":"Panamera", "cayenne":"Cayenne", "macan":"Macan", "cayman":"Cayman", "boxster":"Boxster", "taycan":"Taycan", "911":"911"},
    "Subaru": {"forester":"Forester", "outback":"Outback", "legacy":"Legacy", "impreza":"Impreza", "xv":"XV", "brz":"BRZ"},
    "Nissan": {"x-trail":"X-Trail", "xtrail":"X-Trail", "navara":"Navara", "sunny":"Sunny", "almera":"Almera", "terra":"Terra", "kicks":"Kicks", "teana":"Teana", "livina":"Livina", "tiida":"Tiida", "bluebird":"Bluebird", "patrol":"Patrol"},
    "Volkswagen": {"teramont":"Teramont", "viloran":"Viloran", "tiguan":"Tiguan", "touareg":"Touareg", "scirocco":"Scirocco", "polo":"Polo", "passat":"Passat", "jetta":"Jetta", "golf":"Golf"},
    "Volvo": {"xc90":"XC90", "xc60":"XC60", "xc40":"XC40", "s90l":"S90L", "s90":"S90", "s60":"S60", "v60":"V60"},
}

CURATED_URL_MODEL_ALIASES = {'Toyota': {'land-cruiser-prado': 'Land Cruiser Prado', 'landcruiser-prado': 'Land Cruiser Prado', 'land-cruiser': 'Land Cruiser', 'corolla-cross': 'Corolla Cross', 'yaris-cross': 'Yaris Cross', 'innova-cross': 'Innova Cross', 'corolla-altis': 'Corolla Altis', 'fortuner': 'Fortuner', 'fortune': 'Fortuner', 'legender': 'Fortuner', 'rush': 'Rush', 'zace': 'Zace', 'sienna': 'Sienna', 'innova': 'Innova', 'avanza': 'Avanza', 'veloz': 'Veloz', 'raize': 'Raize', 'hilux': 'Hilux', 'vigo': 'Vigo', 'camry': 'Camry', 'corolla': 'Corolla', 'vios': 'Vios', 'yaris': 'Yaris', 'wigo': 'Wigo', 'hiace': 'Hiace', 'alphard': 'Alphard', 'vellfire': 'Vellfire', 'cross': 'Corolla Cross', 'altis': 'Corolla Altis', 'landcruiser': 'Land Cruiser', 'venza': 'Venza', 'highlander': 'Highlander', 'prado': 'Land Cruiser Prado'}, 'Honda': {'odyssey': 'Odyssey', 'cr-v': 'CR-V', 'crv': 'CR-V', 'hr-v': 'HR-V', 'hrv': 'HR-V', 'br-v': 'BR-V', 'brv': 'BR-V', 'wr-v': 'WR-V', 'wrv': 'WR-V', 'accord': 'Accord', 'civic': 'Civic', 'city': 'City', 'jazz': 'Jazz', 'brio': 'Brio', 'cr z': 'CR-Z'}, 'Hyundai': {'grand-starex': 'Grand Starex', 'grand-i10': 'Grand i10', 'santa-fe': 'Santa Fe', 'santafe': 'Santa Fe', 'veracruz': 'Veracruz', 'veloster': 'Veloster', 'palisade': 'Palisade', 'stargazer': 'Stargazer', 'tucson': 'Tucson', 'staria': 'Staria', 'starex': 'Starex', 'accent': 'Accent', 'elantra': 'Elantra', 'elentra': 'Elantra', 'creta': 'Creta', 'kona': 'Kona', 'custin': 'Custin', 'universe': 'Universe', 'verna': 'Verna', 'venue': 'Venue', 'avante': 'Avante', 'sonata': 'Sonata', 'i10': 'Grand i10', 'i20': 'i20', 'i30': 'i30', 'county': 'County', 'solati': 'Solati', 'getz': 'Getz', 'santex': 'Santa Fe', 'stagaze': 'Stargazer', 'stargaze': 'Stargazer'}, 'Kia': {'grand-carnival': 'Grand Carnival', 'grand-sedona': 'Grand Sedona', 'sportage': 'Sportage', 'sorento': 'Sorento', 'carnival': 'Carnival', 'cannivol': 'Carnival', 'seltos': 'Seltos', 'sonet': 'Sonet', 'carens': 'Carens', 'sedona': 'Sedona', 'cerato': 'Cerato', 'morning': 'Morning', 'moning': 'Morning', 'picanto': 'Picanto', 'forte': 'Forte', 'rio': 'Rio', 'rondo': 'Rondo', 'soluto': 'Soluto', 'k5': 'K5', 'k3': 'K3', 'canival': 'Carnival', 'grand-livina': 'Grand Livina'}, 'Ford': {'ecosport': 'EcoSport', 'territory': 'Territory', 'everest': 'Everest', 'explorer': 'Explorer', 'ranger': 'Ranger', 'transit': 'Transit', 'transin': 'Transit', 'trainsit': 'Transit', 'escape': 'Escape', 'focus': 'Focus', 'fiesta': 'Fiesta', 'mondeo': 'Mondeo', 'laser': 'Laser', 'tourneo': 'Tourneo', 'raptor': 'Ranger Raptor', 'mustang': 'Mustang', 'wildtrak': 'Ranger'}, 'Mazda': {'cx-30': 'CX-30', 'cx30': 'CX-30', 'cx-3': 'CX-3', 'cx3': 'CX-3', 'cx-5': 'CX-5', 'cx5': 'CX-5', 'cx-8': 'CX-8', 'cx8': 'CX-8', 'cx-9': 'CX-9', 'bt-50': 'BT-50', 'bt50': 'BT-50', 'mazda2': 'Mazda2', 'mazda-2': 'Mazda2', 'mazda3': 'Mazda3', 'mazda-3': 'Mazda3', 'mazda6': 'Mazda6', 'mazda-6': 'Mazda6', '323': '323', '626': '626', '2s': 'Mazda2', '3s': 'Mazda3', 'md3': 'Mazda3', 'premacy': 'Premacy'}, 'Mitsubishi': {'pajero-sport': 'Pajero Sport', 'xpander-cross': 'Xpander Cross', 'outlander': 'Outlander', 'oulander': 'Outlander', 'xpander': 'Xpander', 'triton': 'Triton', 'attrage': 'Attrage', 'pajero': 'Pajero', 'xforce': 'Xforce', 'mirage': 'Mirage', 'lancer': 'Lancer', 'jolie': 'Jolie', 'grandis': 'Grandis', 'zinger': 'Zinger', 'tsure': 'Lancer'}, 'Lexus': {'gx-550': 'GX 550', 'gx550': 'GX 550', 'gx-460': 'GX 460', 'gx460': 'GX 460', 'gx-470': 'GX 470', 'gx470': 'GX 470', 'rx-500h': 'RX 500h', 'rx500h': 'RX 500h', 'rx-450h': 'RX 450h', 'rx450h': 'RX 450h', 'rx-350': 'RX 350', 'rx350': 'RX 350', 'rx-330': 'RX 330', 'rx330': 'RX 330', 'rx-300': 'RX 300', 'rx300': 'RX 300', 'rx-400h': 'RX 400h', 'rx400h': 'RX 400h', 'lx-570': 'LX 570', 'lx570': 'LX 570', 'lx-600': 'LX 600', 'lx600': 'LX 600', 'lx-460': 'LX 460', 'lx460': 'LX 460', 'es-250': 'ES 250', 'es250': 'ES 250', 'es-350': 'ES 350', 'es350': 'ES 350', 'ls-460': 'LS 460', 'ls460': 'LS 460', 'ls430': 'LS 430', 'gs-300': 'GS 300', 'gs300': 'GS 300', 'gs430': 'GS 430', 'nx-200t': 'NX 200t', 'nx200t': 'NX 200t', 'nx-300': 'NX 300', 'nx300': 'NX 300', 'rx': 'RX', 'gx': 'GX', 'lx': 'LX', 'ls': 'LS', 'es': 'ES', 'is': 'IS'}, 'Peugeot': {'5008': '5008', '3008': '3008', '2008': '2008', '408': '408', '508': '508', 'traveller': 'Traveller', 'partner': 'Partner', 'expert': 'Expert', '208': '208', '308': '308'}, 'BMW': {'gran-tourer': 'Gran Tourer', 'active-tourer': 'Active Tourer', 'x1': 'X1', 'x2': 'X2', 'x3': 'X3', 'x4': 'X4', 'x5': 'X5', 'x6': 'X6', 'x7': 'X7', 'z4': 'Z4', '318i': '318i', '320i': '320i', '325i': '325i', '330i': '330i', '420i': '420i', '428i': '428i', '430i': '430i', '520i': '520i', '523i': '523i', '525i': '525i', '528i': '528i', '530i': '530i', '535i': '535i', '730li': '730Li', '735i': '735i', '740li': '740Li', '750li': '750Li', '320gt': '320GT', 'i8': 'i8', '218i': '218i', 'm4': 'M4', 'm2': 'M2', 'm3': 'M3', 'm5': 'M5'}, 'Mercedes-Benz': {'sprinter': 'Sprinter', 'v250': 'V250', 'gla45': 'GLA 45', 'gla': 'GLA', 'glb': 'GLB', 'glc': 'GLC', 'gle': 'GLE', 'gls': 'GLS', 'glk': 'GLK', 'cla': 'CLA', 'c200': 'C200', 'c230': 'C230', 'c250': 'C250', 'c300': 'C300', 'e200': 'E200', 'e240': 'E240', 'e250': 'E250', 'e300': 'E300', 's350': 'S350', 's400': 'S400', 's450': 'S450', 's500': 'S500', 'g63': 'G 63', 'ml400': 'ML 400', 'ml350': 'ML 350', 'glc300': 'GLC 300', 'glc coupe': 'GLC Coupe', 'amg': 'AMG'}, 'Chevrolet': {'trailblazer': 'Trailblazer', 'traiblazer': 'Trailblazer', 'colorado': 'Colorado', 'captiva': 'Captiva', 'spark': 'Spark', 'cruze': 'Cruze', 'lacetti': 'Lacetti', 'orlando': 'Orlando', 'vivant': 'Vivant', 'vivan': 'Vivant', 'aveo': 'Aveo', 'trax': 'Trax', 'gentra': 'Gentra', 'equinox': 'Equinox'}, 'Isuzu': {'hi-lander': 'Hi-Lander', 'hilander': 'Hi-Lander', 'd-max': 'D-Max', 'dmax': 'D-Max', 'mu-x': 'MU-X', 'mux': 'MU-X', 'discovery': 'Discovery', 'trooper': 'Trooper', 'qkr': 'QKR'}, 'VinFast': {'vf-e34': 'VF e34', 'vfe34': 'VF e34', 'vf-9': 'VF9', 'vf9': 'VF9', 'vf-8': 'VF8', 'vf8': 'VF8', 'vf-7': 'VF7', 'vf7': 'VF7', 'vf-6': 'VF6', 'vf6': 'VF6', 'vf-5': 'VF5', 'vf5': 'VF5', 'vf5s': 'VF5', 'vf-3': 'VF3', 'vf3': 'VF3', 'vf2': 'VF2', 'fadil': 'Fadil', 'limo-green': 'Limo Green', 'lux-sa-2-0': 'Lux SA2.0', 'lux-sa2-0': 'Lux SA2.0', 'lux-a-2-0': 'Lux A2.0', 'lux-a2-0': 'Lux A2.0', 'lux': 'Lux', 'ec-van': 'EC Van'}, 'Suzuki': {'grand-vitara': 'Grand Vitara', 'swift': 'Swift', 'ertiga': 'Ertiga', 'xl7': 'XL7', 'celerio': 'Celerio', 'ciaz': 'Ciaz', 'vitara': 'Vitara', 'jimny': 'Jimny', 'wagon-r': 'Wagon R', 'apv': 'APV', 'super-carry': 'Super Carry', 'carry': 'Carry'}, 'BYD': {'sealion-6': 'Sealion 6', 'sealion6': 'Sealion 6', 'sealion': 'Sealion', 'atto-3': 'Atto 3', 'atto3': 'Atto 3', 'dolphin': 'Dolphin', 'han': 'Han', 'seal': 'Seal', 'm6': 'M6', 'tang': 'Tang', 'bydm6': 'M6', 'fo': 'F0'}, 'Porsche': {'panamera': 'Panamera', 'cayenne': 'Cayenne', 'macan': 'Macan', 'cayman': 'Cayman', 'boxster': 'Boxster', 'taycan': 'Taycan', '911': '911'}, 'Subaru': {'forester': 'Forester', 'outback': 'Outback', 'legacy': 'Legacy', 'impreza': 'Impreza', 'xv': 'XV', 'brz': 'BRZ'}, 'Nissan': {'x-trail': 'X-Trail', 'xtrail': 'X-Trail', 'navara': 'Navara', 'sunny': 'Sunny', 'almera': 'Almera', 'terra': 'Terra', 'kicks': 'Kicks', 'teana': 'Teana', 'livina': 'Livina', 'gran-livina': 'Grand Livina', 'tiida': 'Tiida', 'bluebird': 'Bluebird', 'patrol': 'Patrol', 'presea': 'Presea', 'lavina': 'Livina', 'niisan-tiida': 'Tiida'}, 'Volkswagen': {'teramont': 'Teramont', 'terramont': 'Teramont', 'viloran': 'Viloran', 'vilorant': 'Viloran', 'tiguan': 'Tiguan', 'touareg': 'Touareg', 'scirocco': 'Scirocco', 'polo': 'Polo', 'passat': 'Passat', 'jetta': 'Jetta', 'golf': 'Golf', 'allspace': 'Tiguan Allspace'}, 'Volvo': {'xc90': 'XC90', 'xc60': 'XC60', 'xc40': 'XC40', 's90l': 'S90L', 's90': 'S90', 's60': 'S60', 'v60': 'V60'}, 'Audi': {'q2': 'Q2', 'q3': 'Q3', 'q5': 'Q5', 'q7': 'Q7', 'q8': 'Q8', 'a1': 'A1', 'a3': 'A3', 'a4': 'A4', 'a5': 'A5', 'a6': 'A6', 'a7': 'A7', 'a8': 'A8', 'tt': 'TT', 'e-tron': 'e-tron'}, 'MG': {'hs': 'HS', 'zs': 'ZS', 'rx5': 'RX5', 'mg5': 'MG5', 'mg3': 'MG3'}, 'GAC': {'gs3': 'GS3', 'gs4': 'GS4', 'gs5': 'GS5', 'gs8': 'GS8', 'm6': 'M6'}, 'Wuling': {'mini-ev': 'Mini EV', 'air-ev': 'Air EV', 'almaz': 'Almaz'}, 'Haval': {'h6': 'H6', 'jolion': 'Jolion'}, 'Jaguar': {'f-pace': 'F-Pace', 'e-pace': 'E-Pace', 'xf': 'XF', 'xe': 'XE'}}

# Additional model aliases verified from Tinbanxe URL patterns.
CURATED_URL_MODEL_ALIASES.setdefault("Lexus", {}).update({
    "es-300h": "ES 300h", "es300h": "ES 300h",
    "is-250c": "IS 250C", "is250c": "IS 250C",
    "is-250": "IS 250", "is250": "IS 250",
    "is-350": "IS 350", "is350": "IS 350",
    "ls-500h": "LS 500h", "ls500h": "LS 500h",
    "ls-600h": "LS 600h", "ls600h": "LS 600h",
    "gs-350": "GS 350", "gs350": "GS 350",
})
CURATED_URL_MODEL_ALIASES.setdefault("Mercedes-Benz", {}).update({
    "e-180": "E 180", "e180": "E 180",
    "c-180": "C 180", "c180": "C 180",
    "glb-200": "GLB 200", "glb200": "GLB 200",
    "gla-250": "GLA 250", "gla250": "GLA 250",
    "gla-45": "GLA 45", "gla45": "GLA 45",
    "ml-400": "ML 400", "ml400": "ML 400",
    "ml-350": "ML 350", "ml350": "ML 350",
    "glc-300": "GLC 300", "glc300": "GLC 300",
})
CURATED_URL_MODEL_ALIASES.setdefault("BMW", {}).update({
    "735i": "735i", "735li": "735Li", "320i": "320i",
})
CURATED_URL_MODEL_ALIASES.setdefault("GAC", {}).update({
    "gs3": "GS3", "gs4": "GS4", "gs5": "GS5", "gs8": "GS8",
    "m8": "M8", "m6": "M6",
})
CURATED_URL_MODEL_ALIASES.setdefault("Mazda", {}).update({
    "323": "323", "626": "626",
})



def derive_model_from_url_curated(url: str, brand: str) -> str | None:
    """Find the earliest, longest curated model alias in a URL slug.

    Comparing aliases on one separator-free slug avoids short aliases such as
    GX winning merely because their match position was measured before removing
    hyphens. Thus GX-460 and GX460 both resolve to GX 460.
    """
    slug = re.sub(r"^https?://[^/]+/", "", (url or "").strip(), flags=re.I)
    slug = re.sub(r"/+$", "", slug).lower()
    slug = re.sub(r"-\d{4,}$", "", slug)
    # Remove known brand prefixes before matching. Otherwise "lexus" itself
    # contains "es", which can incorrectly win over the real model "IS 350".
    brand_slug = re.sub(r"[^a-z0-9]", "", brand.lower())
    compact_slug = re.sub(r"[^a-z0-9]", "", slug)
    for prefix in (brand_slug, "xe" + brand_slug):
        if compact_slug.startswith(prefix):
            compact_slug = compact_slug[len(prefix):]
            break
    candidates = CURATED_URL_MODEL_ALIASES.get(brand, {})
    found: list[tuple[int, int, str]] = []
    for alias, canonical in candidates.items():
        compact_alias = re.sub(r"[^a-z0-9]", "", alias.lower())
        if len(compact_alias) < 2:
            continue
        match = re.search(re.escape(compact_alias), compact_slug)
        if match:
            found.append((match.start(), -len(compact_alias), canonical))
    if not found:
        return None
    found.sort(key=lambda item: (item[0], item[1]))
    return found[0][2]


def derive_model(title: str, brand: str) -> str:
    """Extract model names, preserving common multi-word models."""
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", title or "")
    text = re.sub(r"^[^\wÀ-ỹ]+", "", text)

    # Remove common sales phrases.
    text = re.sub(
        r"^\s*(?:(?:chính chủ|cần bán|bán xe|bán|xe)\s+)+",
        "",
        text,
        flags=re.I,
    )

    # Remove the brand at the start of the title.
    aliases = [brand]
    if brand == "Mercedes-Benz":
        aliases += ["Mercedes Benz", "Mercedes"]
    elif brand == "VinFast":
        aliases += ["Vin Fast", "Vinfast"]

    for alias in sorted(aliases, key=len, reverse=True):
        text = re.sub(
            rf"^\s*{re.escape(alias)}\b[\s:-]*",
            "",
            text,
            flags=re.I,
        )

    text = re.sub(r"\s+", " ", text).strip(" -–,.")

    # Match the longest known model name first.
    model_names = {
        "Toyota": [
            "Land Cruiser Prado", "Corolla Cross", "Yaris Cross",
            "Innova Cross", "Corolla Altis", "Land Cruiser",
            "Fortuner", "Highlander", "Sienna", "Innova",
            "Avanza", "Veloz", "Raize", "Hilux", "Camry",
            "Corolla", "Vios", "Yaris", "Wigo", "Zace",
        ],
        "Honda": [
            "CR-V", "HR-V", "BR-V", "WR-V", "Accord",
            "Odyssey", "Civic", "City", "Jazz", "Brio",
        ],
        "Hyundai": [
            "Grand Starex", "Grand i10", "Santa Fe",
            "Palisade", "Stargazer", "Tucson", "Staria",
            "Starex", "Accent", "Elantra", "Creta", "Kona",
        ],
        "Kia": [
            "Grand Carnival", "Grand Sedona", "Sportage",
            "Sorento", "Carnival", "Seltos", "Sonet",
            "Carens", "Sedona", "Cerato", "Morning",
        ],
        "Ford": [
            "EcoSport", "Territory", "Everest", "Explorer",
            "Ranger", "Transit", "Escape", "Focus", "Fiesta",
        ],
        "Mazda": [
            "CX-3", "CX-30", "CX-5", "CX-8", "CX-9",
            "BT-50", "Mazda2", "Mazda3", "Mazda6",
        ],
        "Mitsubishi": [
            "Pajero Sport", "Xpander Cross", "Outlander",
            "Xpander", "Triton", "Attrage", "Pajero",
        ],
        "Mercedes-Benz": [
            "GLC Coupe", "C-Class", "E-Class", "S-Class",
            "GLA", "GLB", "GLC", "GLE", "GLS", "GLK",
            "C200", "C250", "C300", "E200", "E250", "E300",
        ],
        "BMW": [
            "Gran Tourer", "Active Tourer", "Series 3",
            "Series 5", "Series 7", "X1", "X2", "X3",
            "X4", "X5", "X6", "X7",
        ],
        "Lexus": [
            "LX 570", "LX 600", "GX 460", "GX 470",
            "RX 350", "RX 450h", "RX 300", "NX 300",
            "ES 350", "ES 250", "IS 350", "IS 250",
            "LS 460", "LS 600h", "GS 350", "GS 300",
            "CT 200h", "UX 200",
        ],
    }

    # Lexus model codes commonly include a numeric/letter suffix (GX 460,
    # RX 350, NX 200t). Capture the complete code from title before fallback.
    if brand == "Lexus":
        lexus_match = re.match(
            r"^(GX|RX|LX|NX|ES|LS|GS|IS|UX|CT)\s*-?\s*(\d{3,4}[A-Za-z]{0,2}|\d{2,3}h)?\b",
            text,
            flags=re.I,
        )
        if lexus_match:
            series, suffix = lexus_match.groups()
            if suffix:
                return f"{series.upper()} {suffix}"
            return series.upper()

    candidates = model_names.get(brand, [])

    for model in sorted(candidates, key=len, reverse=True):
        if re.match(
            rf"^{re.escape(model)}(?=$|[\s,.-])",
            text,
            flags=re.I,
        ):
            return model

    # Fallback: use the first meaningful token, not a year or engine size.
    tokens = re.split(r"[\s,.\-–]+", text)
    for token in tokens:
        if (
            token
            and token.lower() not in STOP
            and re.search(r"[A-Za-zÀ-ỹ]", token)
            and not re.fullmatch(r"\d+(?:\.\d+)?[Ll]?", token)
        ):
            return token

    return "Unknown"



def normalize_model_candidate(model: str, brand: str, title: str = "", url: str = "") -> str:
    """Reject obvious title fragments and recover from curated URL/title parsing."""
    value = re.sub(r"\\s+", " ", (model or "").strip()).strip(" -–,.:")
    invalid = {
        "gia", "đình", "trắng", "đen", "bạc", "đỏ", "xanh", "vàng",
        "mec", "mer", "km", "kms", "miles", "mile", "odo", "xe", "bán",
        "cần", "chính", "chủ", "tải", "unknown", "none", "null",
    }
    if not value or value.casefold() in invalid:
        recovered = derive_model_from_url_curated(url, brand) or derive_model(title, brand)
        if recovered and recovered.casefold() not in invalid and recovered.casefold() != "unknown":
            return recovered
        return "Unknown"
    if re.fullmatch(r"\\d+(?:[.,]\\d+)?\\s*[Ll]", value, flags=re.I):
        return "Unknown"
    return value


def derive_body_type(title: str, model: str) -> str:
    """Infer body type only when title/model gives sufficient evidence."""
    text = (title or "").casefold()

    # Explicit body-type descriptions in the listing title.
    explicit_patterns = [
        (r"\b(bán tải|pickup)\b", "Pickup"),
        (r"\b(sedan)\b", "Sedan"),
        (r"\b(hatchback)\b", "Hatchback"),
        (r"\b(suv)\b", "SUV"),
        (r"\b(crossover)\b", "Crossover"),
        (r"\b(mpv|minivan)\b", "MPV"),
        (r"\b(van)\b", "Van"),
        (r"\b(xe tải|truck)\b", "Truck"),
        (r"\b(mui trần|convertible)\b", "Convertible"),
        (r"\b(wagon)\b", "Wagon"),
    ]

    for pattern, body_type in explicit_patterns:
        if re.search(pattern, text, re.I):
            return body_type

    # Conservative mapping for common models.
    model_groups = {
        "SUV": {
            "Fortuner", "Land Cruiser", "Land Cruiser Prado",
            "Highlander", "Rush", "CR-V", "HR-V", "BR-V", "WR-V", "Santa Fe", "Veracruz", "Palisade", "Tucson", "Kona", "Creta", "Venue", "Sportage", "Sorento", "Seltos", "Sonet", "Captiva", "Trailblazer", "Koleos", "Terra", "X-Trail", "Xtrail", "Teramont", "Tiguan", "Touareg", "XC40", "XC60", "XC90", "Kodiaq", "Karoq", "H6", "Jolion",
            "Tucson", "Everest", "Explorer", "Pajero Sport",
            "CX-5", "CX-8", "CX-9", "GX 460", "GX 470",
            "LX 570", "LX 600", "RX 350", "RX 450h", "RX 300",
            "NX 300", "UX 200",
        },
        "Crossover": {
            "Corolla Cross", "Yaris Cross", "Innova Cross",
            "Raize", "Xforce", "CX-3", "CX-30", "Kicks", "Trax", "Atto 3", "VF6", "VF7", "VF8", "VF9",
        },
        "MPV": {
            "Sienna", "Innova", "Avanza", "Veloz", "Alphard", "Zace", "Odyssey", "BR-V", "Ertiga", "XL7", "Stargazer", "Custin", "Viloran", "Zace", "Odyssey", "BR-V", "Ertiga", "XL7", "Stargazer", "Custin", "Viloran", "Zace", "Odyssey", "BR-V", "Ertiga", "XL7", "Stargazer", "Custin", "Viloran", "Vellfire", "Zace", "Odyssey", "BR-V", "Ertiga", "XL7", "Stargazer", "Custin", "Viloran", "Carnival", "Grand Carnival", "Sedona", "Grand Sedona", "Rondo", "Livina", "Grand Livina", "Jolie", "Grandis", "Vivant", "Orlando", "APV", "G50", "M8", "Limo",
            "Xpander", "Carnival", "Grand Carnival", "Carens",
        },
        "Sedan": {
            "Camry", "Corolla Altis", "Corolla", "Vios", "City", "Sunny", "Almera", "Teana", "Tiida", "Bluebird", "Forte", "Cerato", "Rio", "K3", "K5", "Soluto", "Ciaz", "Mondeo", "Laser", "Sonata", "Elantra", "Accent", "Avante", "Verna", "Mazda2", "Mazda3", "Mazda6",
            "ES 350", "ES 250", "IS 350", "IS 250",
            "LS 460", "LS 600h", "GS 350", "GS 300",
        },
        "Hatchback": {
            "Wigo", "Yaris", "Grand i10", "i10", "i20", "i30", "Morning",
            "Jazz", "Brio", "Mazda2", "Spark", "Fadil", "Celerio", "Swift", "Getz", "Veloster",
        },
        "Pickup": {
            "Hilux", "Ranger", "Triton", "Navara", "BT-50", "D-Max", "Dmax", "Colorado", "D-Max", "Dmax", "Colorado", "D-Max", "Dmax", "Colorado", "BT50", "D-Max", "Dmax", "MU-X", "MUX", "Colorado",
        },
        "Van": {
            "Hiace", "Transit", "Starex", "Grand Starex", "Universe", "County", "Solati", "Sprinter", "Tourneo", "Universe", "County", "Solati", "Sprinter", "Tourneo", "Universe", "County", "Solati", "Sprinter", "Tourneo", "Universe", "County", "Solati", "Sprinter", "Tourneo", "Traveller", "Expert", "Super Carry", "Carry",
        },
    }

    # Additional curated models observed in Tinbanxe listing URLs.
    model_groups["SUV"].update({
        "Rush", "Venza", "GX 550", "GX 460", "GX 470", "RX 330", "RX 400h",
        "RX 500h", "LX 460", "Q2", "Q3", "Q5", "Q7", "Q8",
        "H6", "Jolion", "HS", "RX5", "F-Pace", "E-Pace", "ML 350", "ML 400",
        "G 63", "GLA 45", "GLC 300", "Teramont", "Tiguan Allspace", "Outlander",
        "Xforce", "Forester", "Macan", "Cayenne", "Kicks", "Sealion 6",
    })
    model_groups["Crossover"].update({
        "CX-30", "CX-3", "Kicks", "EcoSport", "HR-V", "WR-V", "Raize", "VF e34", "VF e34",
        "Atto 3", "VF5", "VF6", "VF7", "VF8", "VF9",
    })
    model_groups["MPV"].update({
        "V250", "M6", "Grand Livina", "Limo Green", "M8",
    })
    model_groups["Sedan"].update({
        "LS 430", "GS 430",
        "Seal", "Han", "Lux A2.0", "MG5", "MG3", "A3", "A4", "A5", "A6",
        "A7", "A8", "C230", "E240", "735i", "218i", "428i",
    })
    model_groups["Hatchback"].update({"VF3", "VF2", "Dolphin", "Mini EV", "Air EV"})
    model_groups["Van"].update({"EC Van"})
    model_groups["Coupe"] = {"Scirocco", "Cayman", "Boxster", "911", "Z4", "TT"}

    for body_type, models in model_groups.items():
        if model in models:
            return body_type

    return "Unknown"


def normalize_tinbanxe_body(raw: str | None) -> str:
    """Normalize structured body labels, including Vietnamese or decorated values."""
    value = re.sub(r"\\s+", " ", (raw or "").strip()).casefold()
    if not value:
        return "Unknown"
    patterns = [
        (r"bán tải|pickup", "Pickup"),
        (r"sedan", "Sedan"),
        (r"hatchback", "Hatchback"),
        (r"suv|sport utility", "SUV"),
        (r"crossover", "Crossover"),
        (r"mpv|minivan", "MPV"),
        (r"van", "Van"),
        (r"xe tải|truck", "Truck"),
        (r"mui trần|convertible", "Convertible"),
        (r"wagon", "Wagon"),
        (r"coupe", "Coupe"),
    ]
    for pattern, result in patterns:
        if re.search(pattern, value, re.I):
            return result
    normalized = schema.normalize_body(raw)
    return normalized if normalized in schema.BODY_VALUES else "Unknown"


def seats_from_text(*texts: str | None) -> int | None:
    """Extract seat count only from explicit '5 chỗ' / '7 seats' wording."""
    pattern = re.compile(
        r"(?<!\d)(2|3|4|5|6|7|8|9|10|11|12|14|16|17)\s*(?:chỗ|chổ|ghế|seats?)\b",
        flags=re.I,
    )
    for text in texts:
        match = pattern.search(text or "")
        if match:
            return int(match.group(1))
    return None


def normalize_tinbanxe_province(raw: str | None) -> str:
    """Reduce Tinbanxe's full ward/district address to its province/city."""
    value = re.sub(r"\s+", " ", (raw or "").replace("\xa0", " ")).strip(" ,")
    if not value:
        return "Unknown"

    # Locations are usually comma-separated from most local to most general.
    # The final segment is the province/city (e.g. 'Phường Dĩ An, Thành phố Dĩ An, Bình Dương').
    parts = [part.strip(" ,") for part in value.split(",") if part.strip(" ,")]
    candidate = parts[-1] if parts else value

    # Clean common labels and normalize major cities consistently.
    candidate = re.sub(r"^(?:Tỉnh|TP\.?|Thành phố)\s+", "", candidate, flags=re.I).strip()
    key = candidate.casefold()
    known = {
        "hồ chí minh": "TP. Hồ Chí Minh", "tp. hồ chí minh": "TP. Hồ Chí Minh",
        "sài gòn": "TP. Hồ Chí Minh", "hà nội": "Hà Nội",
        "đà nẵng": "Đà Nẵng", "hải phòng": "Hải Phòng",
        "cần thơ": "Cần Thơ",
    }
    if key in known:
        return known[key]
    if candidate:
        return candidate
    return "Unknown"


def detail_mileage_km(value) -> int | None:
    """Normalize mileage extracted from a detail page."""
    if value is None or str(value).strip() == "":
        return None

    raw = re.sub(r"\D", "", str(value))
    if not raw:
        return None

    km = int(raw)

    # Tinbanxe có thể hiển thị số km theo đơn vị nghìn.
    if 0 < km < 1000:
        km *= 1000

    return km if 0 < km <= MAX_PLAUSIBLE_KM else None


def build_unified(cars: list[dict], details: list[dict] | None = None,) -> tuple[list[dict], dict]:
    rows, dropped, seen = [], {"dup": 0, "no_year": 0}, set()
    details_by_url = {
        row.get("url"): row
        for row in (details or [])
        if row.get("url")
    }
    now = config.now_iso()
    for car in cars:
        lid = f"TBX_{car.get('id')}"
        if lid in seen:
            dropped["dup"] += 1
            continue
        seen.add(lid)
        detail = details_by_url.get(car.get("url"), {})

        brand = (
            detail.get("d_brand")
            or brand_name(car.get("brand") or "")
        )

        title = car.get("title") or ""
        desc = car.get("desc") or ""

        year = (
            to_int(detail.get("d_year"))
            or to_int(car.get("year_text"))
            or parse_year_text(title)
        )
        if year is None:
            dropped["no_year"] += 1
            continue
        raw_price = (car.get("price_text") or "").strip()
        price = parse_vnd_price(raw_price)
        model = (
            derive_model_from_url_curated(car.get("url", ""), brand)
            or derive_model(title, brand)
            or (detail.get("d_model") or "").strip()
        )
        model = normalize_model_candidate(model, brand, title, car.get("url", ""))
        trim = derive_trim(brand, model, title)

        raw_body = (detail.get("d_body") or "").strip()
        normalized_body = normalize_tinbanxe_body(raw_body)
        body_type = (
            normalized_body
            if normalized_body != "Unknown"
            else derive_body_type(title, model)
        )

        detail_km = detail_mileage_km(detail.get("d_mileage_km"))
        km = detail_km or mileage_km(car.get("km_text"), desc)

        detail_engine = detail.get("d_engine_capacity")
        try:
            engine_capacity = (
                float(str(detail_engine).replace(",", "."))
                if detail_engine is not None
                and str(detail_engine).strip()
                else None
            )
        except (TypeError, ValueError):
            engine_capacity = None

        if engine_capacity is None:
            engine_capacity = engine_from(trim, title)

        # Never default seats to 5. Keep a value only when explicitly present
        # in structured detail/card fields or stated in title/description.
        # d_seats is now populated by crawl.py only when visible page text
        # explicitly states a seat count (not from JSON-LD seatingCapacity).
        # Refresh detail pages after updating crawl.py so old default values in
        # SQLite are overwritten before regenerating the CSV.
        seats_candidates = (
            seats_from_text(title, desc),
            to_int(detail.get("d_seats")),
        )
        seats = next(
            (value for value in seats_candidates if value is not None and 2 <= value <= 80),
            None,
        )

        origin = detail.get("d_origin") or "Unknown"

        raw_seller_type = detail.get("d_seller_type") or ""
        seller_type_map = {
            "private": "Private Individual",
            "private individual": "Private Individual",
            "dealer": "Dealership/Salon",
            "dealership/salon": "Dealership/Salon",
            "unknown": "Unknown",
        }

        seller_type = seller_type_map.get(
            raw_seller_type.strip().casefold(),
            "Unknown",
        )
        rows.append({
            "listing_id": lid, "source_platform": SOURCE_PLATFORM, "brand": brand, "model": model, "sub_model_trim": trim,
            "manufacture_year": year, "mileage_km": float(km) if km else None,
            "transmission": norm_gearbox(detail.get("d_transmission") or car.get("gearbox")),
            "fuel_type": safe_enum(schema.normalize_fuel(detail.get("d_fuel") or car.get("fuel")),schema.FUEL_VALUES,),
            "origin": origin, "body_type": body_type, "engine_capacity": engine_capacity,
            "seats": seats, "location_province": normalize_tinbanxe_province(car.get("province")),
            "seller_type": seller_type, "price_vnd": price, "source_url": car["url"],
            "listing_date": listing_date(car.get("img_src")), "scraped_at": car.get("scraped_at") or now,
            "raw_price_text": raw_price or None, "price_status": schema.price_status(price, raw_price),
        })
    return rows, dropped


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = storage.open_db()

    try:
        cars = storage.read_rows(conn, "tinbanxe_cars")
        details = storage.read_rows(conn, "tinbanxe_car_details")

        rows, dropped = build_unified(cars, details)

    finally:
        conn.close()

    path = storage.save_csv(rows, "tinbanxe", schema.SCHEMA_COLUMNS)
    log.info("read=%s kept=%s dropped=%s -> %s", len(cars), len(rows), dropped, path)
    log.info("NEXT: python -m tools.validate_source_csv data/processed/tinbanxe.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
