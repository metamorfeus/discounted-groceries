# BG Food Prices — Extraction Guide

All prices are stored in **EUR**. The master dataset is `bulgarian_promo_prices_merged.json`.

---

## Sites and extraction methods

### Billa (`billa_scraper.py`)

**Source:** `https://ssbbilla.site/catalog/sedmichna-broshura`
An accessibility (screen-reader) version of the Billa weekly brochure with full structured text.

**How prices are extracted:**

The script auto-detects the input format:

- **HTML** (direct download): parses `<div class="product">` blocks. Each product has price spans tagged with currency — EUR prices are picked from `<span class="currency">€</span>`. Two prices with "ПРЕДИШНА ЦЕНА" / "НОВА ЦЕНА" labels indicate old/new price respectively.
- **Markdown** (FireCrawl output): scans for `EUR/BGN` price pairs matching `X,XX € / X,XX лв.`. The EUR part is used directly. BGN-only prices are converted to EUR by dividing by `1.95583`.

**How to run:**

```bash
# Auto-download and parse
python billa_scraper.py

# Download explicitly
python billa_scraper.py --download

# Use a saved HTML/markdown file
python billa_scraper.py --input billa_raw.md

# Merge into existing master dataset
python billa_scraper.py --download --existing bulgarian_promo_prices_merged.json
```

Output: `billa_products_YYYY-MM-DD.json`

Alternatively, if `ssbbilla.site` blocks automated requests, use Firecrawl MCP in a Claude session:

```
firecrawl_scrape(
    url="https://ssbbilla.site/catalog/sedmichna-broshura",
    formats=["markdown"],
    waitFor=10000,
    proxy="stealth",
    location={"country": "BG", "languages": ["bg"]},
    onlyMainContent=True
)
```
Then save the markdown result to `billa_raw.md` and run with `--input billa_raw.md`.

---

### Gladen.bg / Hit Max (`gladen_html_scraper.py`)

**Source:** `https://gladen.bg/promotions?page=N`
Paginated HTML promotions listing (up to ~42 pages, 24 products per page).

**How prices are extracted:**

Makes direct HTTP requests to each page. Per product card:
- Promo price: extracted from `<div class="product-card-price-current is-promo">` using regex `(\d+\.\d{2})\s*€`
- Regular price: extracted from `<div class="product-card-price-old">` the same way
- Only products where `promo_price < regular_price` are kept (genuine discounts only)

**How to run:**

```bash
# Full scrape and merge into master
python gladen_html_scraper.py

# Limit number of pages
python gladen_html_scraper.py --pages=10

# Dry run (print results, don't write to master)
python gladen_html_scraper.py --dry-run
```

The script writes directly into `bulgarian_promo_prices_merged.json`, replacing old Gladen records.

---

### Fantastico — PDF parser (`fantastico_pdf_parser.py`)

**Source:** Fantastico weekly brochure PDF (machine-readable text layer)
Obtained from: `https://www.fantastico.bg/special-offers` (FlippingBook viewer)

**How prices are extracted:**

Uses `pdfplumber` to extract words with bounding boxes (x/y coordinates) from the PDF.

1. Finds all BGN price words (`X.XX ЛВ.`) as spatial anchors for product locations
2. For each anchor, collects all words in the same x-column above it
3. Finds EUR prices (`X.XX €`) in that text region:
   - First EUR = regular/old price → stored directly as `regular_price`
   - Second EUR = promo price → stored as `promo_price`
   - If only one EUR and a discount % (`-19%`) is present, back-calculates the regular price
   - If no EUR found, converts BGN anchor ÷ 1.95583 as fallback
4. Product name is assembled from non-price Cyrillic lines in the same column region

**How to run:**

First, manually download the PDF from the FlippingBook viewer and place it at:
`fantastico_work/fantastico_brochure.pdf`

Then:

```bash
python fantastico_pdf_parser.py

# Dry run (show sample results without writing)
python fantastico_pdf_parser.py --dry-run
```

The script writes directly into `bulgarian_promo_prices_merged.json`, replacing old Fantastico Direct records.

---

### Fantastico — OCR pipeline (`fantastico_ocr_pipeline.py`)

**Source:** Same Fantastico brochure PDF, but processed via Azure Document Intelligence OCR.
Use this when the PDF has scanned/image pages without a text layer.

**How prices are extracted:**

OCR output follows the format: `OLD_EUR € DISCOUNT% NEW_EUR €\nBGN ЛВ.`
Example: `"2.79 € -19% 2.25 €\n4.40 ЛВ."`

Two-pass parsing of the OCR text stream:

- **Pass 1 (BGN-anchored):** `X.XX ЛВ.` marks the end of each product block. Looks back in the text window for a EUR pair (`OLD € NEW €`) and uses those EUR values directly. If only single EUR prices are found, first = regular, last = promo. If no EUR at all, converts BGN ÷ 1.95583.
- **Pass 2 (EUR-pair-only):** catches products where the BGN price was missed by OCR. Anchors on EUR pairs not already captured in Pass 1.

**How to run:**

```bash
# Full pipeline: download PDF, OCR via Azure, parse, merge
python fantastico_ocr_pipeline.py --key YOUR_AZURE_KEY

# If you already have the PDF
python fantastico_ocr_pipeline.py --key YOUR_AZURE_KEY --pdf fantastico_work/fantastico_brochure.pdf

# If OCR is already done (reuse cached JSON files)
python fantastico_ocr_pipeline.py --ocr-dir fantastico_work/ocr_output/

# Merge with existing dataset
python fantastico_ocr_pipeline.py --ocr-dir fantastico_work/ocr_output/ --existing bulgarian_promo_prices_merged.json
```

Azure credentials: endpoint is `https://invoice2024.cognitiveservices.azure.com/`. The API key must be passed via `--key`.

---

### Billa — PDF brochure pipeline (`billa_pdf_pipeline.py`)

**Source:** `https://www.billa.bg/promocii/sedmichna-broshura`
The official weekly brochure, hosted as an image-only PDF on Publitas. Requires Azure OCR.

**How prices are extracted:**

1. Scrapes `billa.bg` to find the current week's Publitas viewer URL (slug changes weekly)
2. Fetches the viewer page HTML and searches for the embedded direct PDF URL (`/pdfs/UUID.pdf`)
3. Downloads the PDF directly; if blocked, falls back to Playwright browser automation
4. Splits into 2-page batches (image PDFs are large per page)
5. OCRs each batch via Azure Document Intelligence `prebuilt-read`; results cached in `billa_work/ocr_output/`
6. Parses the OCR text stream using the same two-pass approach as Fantastico:
   - **Pass 1** (BGN-anchored): `X.XX ЛВ.` marks end of each product block; looks back for a EUR pair `OLD € → NEW €` and stores those EUR values directly
   - **Pass 2** (EUR-pair-only): catches products where the BGN price was missed by OCR
7. If `BILLA_WEEKLY_COMPARISON = True` in `config.py`:
   - Also scrapes `ssbbilla.site` for the current week's text-based data
   - Fuzzy-matches (≥80% similarity) each PDF product against ssbbilla products
   - Saves a colour-coded comparison report to `billa_work/comparison_YYYY-MM-DD.xlsx`
   - Only adds PDF items **not found on ssbbilla.site** to the master JSON
8. If `BILLA_WEEKLY_COMPARISON = False`: adds all PDF products to master directly

**Comparison report columns:** PDF product name | ssbbilla best match | similarity % | PDF promo € | ssbbilla promo € | price diff € | in ssbbilla? | PDF promo period | ssbbilla pull date

**How to run:**

```bash
# Full pipeline (auto-download + OCR + compare + merge)
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY

# Use a PDF you already downloaded
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY --pdf "billa_work/brochure.pdf"

# Reuse cached OCR output (skip download & OCR entirely)
python billa_pdf_pipeline.py --ocr-dir billa_work/ocr_output/

# Dry run — parse and show report, do not write to master JSON
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY --dry-run
```

The Azure key can also be set in `secrets.py` (AZURE_KEY) or the `AZURE_DI_KEY` environment variable — the `--key` argument is then optional.

Working files are stored in `billa_work/`:
```
billa_work/
  billa_brochure_YYYY-MM-DD.pdf     ← downloaded PDF
  ssbbilla_raw.html                 ← ssbbilla.site snapshot for comparison
  pdf_batches/                      ← 2-page batch PDFs
  ocr_output/                       ← cached Azure DI JSON results
  comparison_YYYY-MM-DD.xlsx        ← weekly comparison report
```

---

## Running all sources and rebuilding the master dataset

Run each scraper individually (in any order), then rebuild the master:

```bash
# 1. Billa — PDF pipeline (auto-downloads, OCRs, compares with ssbbilla.site, merges)
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY
#    Azure key can live in secrets.py instead: then just run:
#    python billa_pdf_pipeline.py

# 2. Gladen
python gladen_html_scraper.py

# 3. Fantastico (PDF parser — preferred if PDF has a text layer)
#    First place the PDF at: fantastico_work/fantastico_brochure.pdf
python fantastico_pdf_parser.py
#    OR via OCR if the PDF is scanned images:
python fantastico_ocr_pipeline.py --key YOUR_AZURE_KEY --existing bulgarian_promo_prices_merged.json

# 4. Rebuild master from all sources
python merge_all.py
```

> **Note on Billa sources:** `billa_scraper.py` (ssbbilla.site text scraper) and `billa_pdf_pipeline.py` (PDF OCR) are complementary. The PDF pipeline is the authoritative source; it uses ssbbilla.site to fill gaps. Once you've confirmed via the weekly comparison report that ssbbilla.site covers all products, set `BILLA_WEEKLY_COMPARISON = False` in `config.py` to skip the PDF OCR step and rely on ssbbilla.site alone.

After merging, regenerate the Excel output:

```bash
python generate_xlsx.py
python generate_cheapest_xlsx.py
```

---

## Output schema

Each record in `bulgarian_promo_prices_merged.json`:

| Field | Type | Description |
|---|---|---|
| `product_name` | string | Product name in Bulgarian |
| `product_category` | string\|null | Auto-assigned category |
| `promo_price` | float | Promotional price in **EUR** |
| `regular_price` | float\|null | Regular price in **EUR** (null if not shown) |
| `unit` | string\|null | Unit (бр, кг, л, etc.) |
| `price_per_unit` | null | Reserved, not yet populated |
| `promo_period` | string | Validity period, e.g. `"26.03 - 01.04.2026"` |
| `source_store` | string | `"Billa"`, `"Gladen.bg / Hit Max"`, or `"Fantastico"` |
| `source_channel` | string | `"Direct"` for all current sources |
| `source_url` | string | URL of the source page or product |
| `extraction_date` | string | ISO date of extraction, e.g. `"2026-04-06"` |

---

## Configuration

Non-secret settings live in `config.py`. Key flags:

| Setting | Default | Description |
|---|---|---|
| `BILLA_WEEKLY_COMPARISON` | `True` | Generate weekly PDF vs ssbbilla.site comparison report |
| `BILLA_COMPARISON_THRESHOLD` | `0.80` | Fuzzy-match similarity threshold (0.0–1.0) |
| `BILLA_PAGES_PER_BATCH` | `2` | Pages per Azure DI batch for Billa PDF |
| `FANTASTICO_PAGES_PER_BATCH` | `10` | Pages per Azure DI batch for Fantastico |
| `AZURE_ENDPOINT` | `invoice2024...` | Azure Document Intelligence endpoint |

Azure API key goes in `secrets.py` (never commit this file):
```python
# secrets.py
AZURE_KEY = "your-key-here"
```

## Dependencies

```bash
pip install requests pdfplumber openpyxl

# For Billa PDF pipeline and Fantastico OCR:
pip install azure-ai-documentintelligence PyPDF2

# For Playwright fallback (Billa PDF download if direct URL fails):
pip install playwright && playwright install chromium
```
