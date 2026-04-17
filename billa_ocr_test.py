#!/usr/bin/env python3
"""
Billa OCR test — splits the PDF and OCRs the first 2 batches (4 pages).
Run this before the full pipeline to verify OCR output format.

Usage:
    python billa_ocr_test.py
    python billa_ocr_test.py --pdf "path/to/brochure.pdf"
    python billa_ocr_test.py --batches 3   # OCR first 3 batches instead of 2
"""

import json
import sys
import argparse
from pathlib import Path

# ── Resolve PDF path ──────────────────────────────────────────────────────────
DEFAULT_PDF = next(
    iter(sorted(Path(".").glob("BILLA Bulgaria*.pdf"))),
    None,
)

parser = argparse.ArgumentParser(description="Billa OCR test run")
parser.add_argument("--pdf",     default=str(DEFAULT_PDF) if DEFAULT_PDF else None,
                    help="Path to Billa PDF (auto-detected if omitted)")
parser.add_argument("--batches", type=int, default=2,
                    help="Number of 2-page batches to OCR (default: 2 = 4 pages)")
args = parser.parse_args()

if not args.pdf:
    print("ERROR: No Billa PDF found in current directory.")
    print("Pass the path explicitly: python billa_ocr_test.py --pdf path/to/brochure.pdf")
    sys.exit(1)

pdf_path = Path(args.pdf)
if not pdf_path.exists():
    print(f"ERROR: PDF not found: {pdf_path}")
    sys.exit(1)

print(f"PDF: {pdf_path}")
print(f"Will OCR first {args.batches} batches ({args.batches * 2} pages)\n")

# ── Import pipeline helpers ───────────────────────────────────────────────────
try:
    from billa_pdf_pipeline import split_pdf, ocr_all_batches, AZURE_ENDPOINT
except ImportError as e:
    print(f"ERROR: Could not import billa_pdf_pipeline: {e}")
    sys.exit(1)

try:
    import secrets as _s
    azure_key = _s.AZURE_KEY
except ImportError:
    print("ERROR: secrets.py not found — add AZURE_KEY to secrets.py")
    sys.exit(1)

if "your-azure" in azure_key:
    print("ERROR: AZURE_KEY in secrets.py is still a placeholder — set your real key")
    sys.exit(1)

# ── Step 1: Split PDF ─────────────────────────────────────────────────────────
work_dir  = Path("billa_work")
batch_dir = work_dir / "pdf_batches"
ocr_dir   = work_dir / "ocr_output"
work_dir.mkdir(exist_ok=True)

print("Step 1: Splitting PDF into 2-page batches...")
all_batches = split_pdf(pdf_path, batch_dir)
test_batches = all_batches[: args.batches]
print(f"  Total batches: {len(all_batches)}, testing first {len(test_batches)}\n")

# ── Step 2: OCR ───────────────────────────────────────────────────────────────
print(f"Step 2: Sending {len(test_batches)} batches to Azure Document Intelligence...")
results = ocr_all_batches(test_batches, ocr_dir, AZURE_ENDPOINT, azure_key)

# ── Step 3: Print raw OCR text ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("RAW OCR OUTPUT (full_text from each batch)")
print("=" * 70)

for i, res in enumerate(results):
    print(f"\n{'─' * 60}")
    print(f"BATCH {i+1}  |  source: {Path(res.get('source_file', '?')).name}")
    print(f"{'─' * 60}")
    full_text = res.get("full_text", "")
    if not full_text:
        full_text = "\n".join(
            pg.get("text", "") for pg in res.get("pages", [])
        )
    print(full_text[:6000])   # first 6,000 chars — enough to see the pattern
    if len(full_text) > 6000:
        print(f"\n... [{len(full_text) - 6000} more chars — see JSON cache for full text]")

# ── Step 4: Show cache location ───────────────────────────────────────────────
print("\n" + "=" * 70)
print("CACHED OCR FILES")
print("=" * 70)
for f in sorted(ocr_dir.glob("*_ocr.json")):
    size_kb = f.stat().st_size / 1024
    print(f"  {f.name}  ({size_kb:.0f} KB)")

print(f"\nShare the content of the JSON files above so the parser can be verified.")
print(f"Full pipeline (once parser is confirmed):")
print(f"  python billa_pdf_pipeline.py")
