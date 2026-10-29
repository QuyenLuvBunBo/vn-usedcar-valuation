"""
Step 2: fill `brand`, `model` and `sub_model_trim` using a local Qwen model via Ollama.

Setup (once):
    ollama pull qwen2.5:14b-instruct      # ~9 GB at Q4, fits in 16 GB VRAM
    (smaller/faster option: qwen2.5:7b-instruct)

Input : bonbanh_titles.csv  (written by the scraper)
Output: bonbanh_models.csv  (source_url, brand, model, sub_model_trim)  -- resumable
        bonbanh_final.csv   (bonbanh.csv with brand / model / sub_model_trim merged in)
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

TITLES_FILE = "bonbanh_titles.csv"
MODELS_FILE = "bonbanh_models.csv"
MAIN_FILE = "bonbanh.csv"
FINAL_FILE = "bonbanh_final.csv"

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:14b-instruct"
BATCH_SIZE = 10  # local models are more reliable with small batches
WORKERS = 2  # Ollama queues requests; raise with OLLAMA_NUM_PARALLEL
MAX_RETRIES = 3

COLUMNS = [
    "listing_id",
    "source_platform",
    "brand",
    "model",
    "sub_model_trim",
    "manufacture_year",
    "mileage_km",
    "transmission",
    "fuel_type",
    "origin",
    "body_type",
    "engine_capacity",
    "seats",
    "location_province",
    "seller_type",
    "price_vnd",
    "source_url",
    "listing_date",
    "scraped_at",
    "raw_price_text",
    "price_status",
]

SYSTEM = """You normalize Vietnamese used-car listings.
Input: JSON {"listings": [{"i", "crumb_brand", "crumb_model", "raw_title", "year"}, ...]}
Output: JSON {"results": [{"i", "brand", "model", "sub_model_trim"}, ...]} with one result per listing.

Rules:
- brand: the car maker in canonical spelling, e.g. "Toyota", "Mercedes-Benz", "Land Rover", "BMW",
  "VinFast", "Rolls-Royce", "MINI", "MG", "BYD", "Ssangyong", "Infiniti". Prefer crumb_brand when sensible,
  otherwise read it from raw_title. Never null.
- model: base model name only, canonical form (e.g. "RX", "Camry", "CX-5", "C-Class", "Civic").
  Prefer crumb_model when sensible; only fix casing/spelling/hyphenation.
  Never include the brand or the year.
- sub_model_trim: the variant / grade / engine badge after the model
  (e.g. "300", "2.5Q", "350 Luxury", "1.5 RS", "Wildtrak 2.0L 4x4 AT").
  Never include brand, model, year, transmission (AT/MT/số tự động/số sàn), fuel, colour, price or location.
  Use null if the title has no trim. Never invent a trim that is not in the title.
- Output JSON only.

Example input:
{"listings": [
 {"i": 0, "crumb_brand": "Lexus", "crumb_model": "RX", "raw_title": "Lexus RX 2021 300", "year": 2021},
 {"i": 1, "crumb_brand": "Toyota", "crumb_model": "Camry", "raw_title": "Toyota Camry 2.5Q", "year": 2017},
 {"i": 2, "crumb_brand": "Mercedes Benz", "crumb_model": "C class", "raw_title": "Mercedes Benz C class C200", "year": 2015}]}
Example output:
{"results": [
 {"i": 0, "brand": "Lexus", "model": "RX", "sub_model_trim": "300"},
 {"i": 1, "brand": "Toyota", "model": "Camry", "sub_model_trim": "2.5Q"},
 {"i": 2, "brand": "Mercedes-Benz", "model": "C-Class", "sub_model_trim": "C200"}]}"""


def call_llm(user_text):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "stream": False,
                    "format": "json",  # forces valid JSON output
                    "keep_alive": "30m",  # keep weights in VRAM between batches
                    "options": {"temperature": 0, "num_ctx": 4096},
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user_text},
                    ],
                },
                timeout=180,
            )
            r.raise_for_status()
            return r.json()["message"]["content"]
        except (requests.RequestException, KeyError) as e:
            print(f"   LLM attempt {attempt}/{MAX_RETRIES} failed: {e}")
            time.sleep(3 * attempt)
    return None


def parse_results(text):
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        data = data.get("results")
    return data if isinstance(data, list) else None


def clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return None if v.lower() in ("", "null", "none", "n/a") else v


def nn(v):
    """NaN -> None so it serializes as null."""
    return None if pd.isna(v) else v


def process_batch(batch):
    """batch: list of dict rows. Returns result rows (only valid ones)."""
    payload = {
        "listings": [
            {
                "i": i,
                "crumb_brand": nn(r.get("crumb_brand")),
                "crumb_model": nn(r.get("crumb_model")),
                "raw_title": nn(r.get("raw_title")),
                "year": nn(r.get("manufacture_year")),
            }
            for i, r in enumerate(batch)
        ]
    }
    # numpy ints -> plain ints for json
    text = call_llm(json.dumps(payload, ensure_ascii=False, default=int))
    data = parse_results(text)
    if data is None:
        print("   bad / empty response, batch will be retried next run")
        return []

    out, seen_idx = [], set()
    for item in data:
        try:
            idx = int(item["i"])
            src = batch[idx]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        if idx in seen_idx:
            continue
        seen_idx.add(idx)
        out.append(
            {
                "source_url": src["source_url"],
                "brand": clean(item.get("brand")),
                "model": clean(item.get("model")),
                "sub_model_trim": clean(item.get("sub_model_trim")),
            }
        )
    return out


def fill_models():
    titles = pd.read_csv(TITLES_FILE).drop_duplicates("source_url")

    done = set()
    if os.path.exists(MODELS_FILE):
        done = set(pd.read_csv(MODELS_FILE, usecols=["source_url"])["source_url"])

    todo = titles[~titles["source_url"].isin(done)].to_dict("records")
    print(f"{len(done)} done, {len(todo)} to do")
    batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]

    with ThreadPoolExecutor(WORKERS) as pool:
        for n, rows in enumerate(pool.map(process_batch, batches), 1):
            if rows:
                pd.DataFrame(rows).to_csv(
                    MODELS_FILE,
                    mode="a",
                    index=False,
                    header=not os.path.exists(MODELS_FILE),
                    encoding="utf-8-sig",
                )
            print(f"batch {n}/{len(batches)}: +{len(rows)}")


def merge():
    df = pd.read_csv(MAIN_FILE)
    m = pd.read_csv(MODELS_FILE).drop_duplicates("source_url", keep="last")
    df = df.drop(columns=["brand", "model", "sub_model_trim"], errors="ignore")
    df = df.merge(
        m[["source_url", "brand", "model", "sub_model_trim"]],
        on="source_url",
        how="left",
    )
    df = df[COLUMNS]
    df.to_csv(FINAL_FILE, index=False, encoding="utf-8-sig")
    print(
        f"wrote {FINAL_FILE}: {len(df)} rows, "
        f"{df['brand'].notna().sum()} with brand, "
        f"{df['model'].notna().sum()} with model, "
        f"{df['sub_model_trim'].notna().sum()} with trim"
    )


if __name__ == "__main__":
    fill_models()
    merge()
