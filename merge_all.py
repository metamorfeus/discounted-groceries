#!/usr/bin/env python3
"""
Merge script: combines all scraped sources into bulgarian_promo_prices_merged.json
  1. Load master JSON
  2. Replace Billa records with fresh billa_products_2026-03-31.json (971 items)
  3. Replace Fantastico Direct records with OCR-parsed items from fantastico_work/ocr_output/
  4. Deduplicate
  5. Save

Usage: python merge_all.py
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
MASTER = BASE / "bulgarian_promo_prices_merged.json"
BILLA_FILE = BASE / "billa_products_2026-03-31.json"
FANTASTICO_OCR_DIR = BASE / "fantastico_work" / "ocr_output"

# ── Load master ──
with open(MASTER, encoding="utf-8") as f:
    master = json.load(f)

print(f"Master loaded: {len(master)} records")
by_source = {}
for r in master:
    k = r.get("source_store", "?")
    by_source[k] = by_source.get(k, 0) + 1
print(f"  Before: {by_source}")

# ── Strip old Billa Direct and Fantastico Direct ──
master = [
    r for r in master
    if not (r["source_store"] == "Billa" and r["source_channel"] == "Direct")
    and not (r["source_store"] == "Fantastico" and r["source_channel"] == "Direct")
]
print(f"  After stripping old Billa Direct + Fantastico Direct: {len(master)} records")

# ── Load fresh Billa ──
# billa_products file is a merged file (all sources + new Billa).
# Extract ONLY the Billa Direct records from it.
with open(BILLA_FILE, encoding="utf-8") as f:
    billa_raw = json.load(f)
billa = [r for r in billa_raw
         if r.get("source_store") == "Billa" and r.get("source_channel") == "Direct"]
print(f"Billa loaded: {len(billa_raw)} total in file, {len(billa)} Billa Direct records extracted")

# ── Load + parse Fantastico OCR ──
sys.path.insert(0, str(BASE))
from fantastico_ocr_pipeline import load_ocr_from_directory, parse_ocr_to_products, validate_products

ocr_results = load_ocr_from_directory(str(FANTASTICO_OCR_DIR))
fantastico_products = parse_ocr_to_products(ocr_results)
fantastico_clean, fantastico_removed = validate_products(fantastico_products)
print(f"Fantastico OCR parsed: {len(fantastico_products)} total, {len(fantastico_clean)} clean, {len(fantastico_removed)} removed")

# ── Merge all ──
merged = master + billa + fantastico_clean

# ── Global dedup ──
seen = set()
deduped = []
for r in merged:
    key = (
        r.get("source_store", "")[:15],
        r.get("source_channel", ""),
        r.get("product_name", "")[:40].lower(),
        r.get("promo_price"),
    )
    if key not in seen:
        seen.add(key)
        deduped.append(r)

dupes = len(merged) - len(deduped)
print(f"After dedup: {len(deduped)} records ({dupes} duplicates removed)")

by_source = {}
for r in deduped:
    k = r.get("source_store", "?")
    by_source[k] = by_source.get(k, 0) + 1
print(f"  Final breakdown: {by_source}")

# ── Save ──
with open(MASTER, "w", encoding="utf-8") as f:
    json.dump(deduped, f, ensure_ascii=False, indent=2)
print(f"\nSaved: {MASTER}")
print(f"Total records: {len(deduped)}")
