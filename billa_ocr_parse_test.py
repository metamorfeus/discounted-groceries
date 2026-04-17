#!/usr/bin/env python3
"""
Parse the cached OCR batches and print extracted products — no Azure calls.
Run this after billa_ocr_test.py to verify the parser before the full pipeline.

Usage:
    python billa_ocr_parse_test.py
"""

from pathlib import Path
from billa_pdf_pipeline import load_ocr_from_directory, parse_ocr_results, extract_promo_period

ocr_dir = Path("billa_work/ocr_output")
if not any(ocr_dir.glob("*_ocr.json")):
    print(f"No cached OCR files found in {ocr_dir}")
    print("Run billa_ocr_test.py first.")
    raise SystemExit(1)

ocr_results  = load_ocr_from_directory(ocr_dir)
promo_period = extract_promo_period(ocr_results)
products     = parse_ocr_results(ocr_results, promo_period)

print(f"\nPromo period detected: {promo_period}")
print(f"Products extracted:    {len(products)}\n")
print(f"{'#':<4}  {'Category':<26}  {'Promo €':>8}  {'Regular €':>10}  Product name")
print("─" * 90)
for i, p in enumerate(products, 1):
    cat = p["product_category"] or "—"
    reg = f"{p['regular_price']:.2f}" if p["regular_price"] else "—"
    print(f"{i:<4}  {cat:<26}  {p['promo_price']:>8.2f}  {reg:>10}  {p['product_name']}")

# Summary
no_regular = sum(1 for p in products if not p["regular_price"])
print(f"\n{'─' * 90}")
print(f"Total: {len(products)} products")
print(f"  With regular price : {len(products) - no_regular}")
print(f"  Without regular    : {no_regular}  (discount % not found in those blocks)")
