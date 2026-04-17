# Fantastico Bulgaria — OCR Pipeline Solution

**Date:** 2026-03-31  
**Status:** ✅ Pipeline built & parser tested

---

## Problem

Fantastico (`fantastico.bg/special-offers`) uses a **FlippingBook** viewer at `https://online.flippingbook.com/view/738517692`. The brochure is rendered as page images — no structured text is extractable directly.

## Solution

**PDF → Split → Azure Document Intelligence OCR → Parse → Structured JSON**

### Pipeline Overview

```
FlippingBook PDF (50+ pages)
  ↓ download
fantastico_brochure.pdf
  ↓ split into batches of 10 pages
pdf_batches/batch_001.pdf, batch_002.pdf, ...
  ↓ Azure Document Intelligence (prebuilt-read)
ocr_output/batch_001_ocr.json, batch_001_ocr.txt, ...
  ↓ parse OCR text → structured products
fantastico_products_2026-03-31.json
  ↓ merge with existing dataset
bulgarian_promo_prices_updated.json
```

---

## Quick Start

### Prerequisites

```bash
pip install azure-ai-documentintelligence PyPDF2 requests
```

### Azure Document Intelligence Setup

- **Endpoint:** `https://invoice2024.cognitiveservices.azure.com/`
- **Region:** East US
- **Model:** `prebuilt-read`
- **Key:** Your Azure key (pass via `--key` flag or `AZURE_DI_KEY` env var)

### Step 1: Download the PDF

The FlippingBook `/pdf/` endpoint requires browser interaction. **Download manually:**

1. Open: `https://online.flippingbook.com/view/738517692/`
2. Click the download/PDF button in the viewer toolbar
3. Save as: `fantastico_brochure.pdf`

Or try the script's auto-download:
```bash
python3 fantastico_ocr_pipeline.py --key YOUR_KEY
```

### Step 2: Run the Full Pipeline

```bash
# Full pipeline (with pre-downloaded PDF):
python3 fantastico_ocr_pipeline.py \
  --key YOUR_AZURE_KEY \
  --pdf fantastico_brochure.pdf \
  --existing bulgarian_promo_prices_2026-03-29.json \
  --output bulgarian_promo_prices_updated.json

# Or set the key as env var:
export AZURE_DI_KEY=your_key_here
python3 fantastico_ocr_pipeline.py --pdf fantastico_brochure.pdf
```

### Step 3: If OCR Already Done (skip download + OCR)

```bash
# Parse from pre-existing OCR output:
python3 fantastico_ocr_pipeline.py \
  --ocr-dir fantastico_work/ocr_output/ \
  --existing bulgarian_promo_prices_2026-03-29.json
```

---

## How the OCR Parser Works

### Brochure Layout (typical per page)

Each page has 2–6 products in a grid. Azure DI reads top-to-bottom, left-to-right, producing lines like:

```
Масло краве                    ← name line 1
DEUTSCHE MARKENBUTTER           ← name line 2 (brand)
250 г                           ← unit/weight
стара цена 6,49                 ← old price
4,99                            ← promo price (standalone number)
лв.                             ← currency suffix
-23%                            ← discount %
```

### Parser Strategy

1. **Find "standalone price" lines** — lines that are just `\d{1,3}[,.]\d{2}` (e.g., "4,99")
2. **Look backwards** for `стара цена X,XX` → extract as regular_price
3. **Look backwards** for unit patterns (кг, г, л, мл, бр)
4. **Collect name lines** — non-price, non-unit text above the price
5. **Skip** headers, dates, category labels, discount percentages

### Test Results (simulated OCR)

```
Products extracted:  13/13 (100%)
Validation pass:     13/13 (100%)

Sample:
  DEUTSCHE MARKENBUTTER 250 г       promo: 4.99  regular: 6.49
  Банани 1 кг                       promo: 2.29
  Пилешко бутче охладено за 1 кг    promo: 5.99  regular: 8.99
  COCA-COLA 2 л                     promo: 2.49  regular: 3.79
  Краве сирене ДРЯНОВО за 1 кг      promo: 8.99  regular: 11.99
```

---

## File Structure

```
fantastico_work/
├── fantastico_brochure.pdf          # Downloaded PDF
├── pdf_batches/                     # Split PDFs
│   ├── batch_001_pages_1-10.pdf
│   ├── batch_002_pages_11-20.pdf
│   └── ...
├── ocr_output/                      # Azure DI results
│   ├── batch_001_ocr.json           # Full OCR data (pages, lines, words, confidence)
│   ├── batch_001_ocr.txt            # Plain text extraction
│   └── ...
├── fantastico_only_2026-03-31.json  # Fantastico products only
└── fantastico_products_2026-03-31.json  # Merged with existing dataset
```

---

## Command Reference

| Command | Description |
|---------|-------------|
| `--key KEY` | Azure Document Intelligence API key |
| `--endpoint URL` | Azure DI endpoint (default: invoice2024.cognitiveservices.azure.com) |
| `--pdf PATH` | Path to pre-downloaded PDF (skip download) |
| `--ocr-dir PATH` | Path to pre-existing OCR output (skip download + OCR) |
| `--existing PATH` | Existing JSON dataset to merge with |
| `--output PATH` | Output JSON file path |
| `--batch-size N` | Pages per OCR batch (default: 10) |
| `--work-dir PATH` | Working directory (default: fantastico_work/) |

---

## Expected Yield

A typical Fantastico weekly brochure has **50–60 pages** with **3–5 products per page**, yielding approximately **150–250 products**. The current dataset has 622 records; adding Fantastico would bring it to ~800+.

---

## Cost Estimate

Azure Document Intelligence pricing (prebuilt-read):
- ~$1.50 per 1,000 pages
- 60-page brochure split into 6 batches = ~$0.09 total
- Negligible cost per run
