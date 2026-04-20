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

### Fantastico — unified pipeline (`fantastico_pipeline.py`)

**Source:** `https://www.fantastico.bg/special-offers` (FlippingBook brochure viewer)

**How prices are extracted:**

Fully automated — no manual steps:

1. Scrapes `fantastico.bg/special-offers` to find the active FlippingBook URL
2. Launches headless Chromium (Playwright), opens the viewer, clicks Download → "Full Flipbook"
3. Detects PDF type: embedded text layer → `pdfplumber`; scanned images → Azure Document Intelligence OCR
4. **Text-layer parsing (pdfplumber):** extracts words with bounding boxes; uses BGN price words (`X.XX ЛВ.`) as spatial anchors; collects words in the same column above each anchor; finds EUR price pairs (first = regular, second = promo); back-calculates regular price from discount % if only one EUR is present
5. **OCR parsing (Azure DI):** two-pass approach — Pass 1 anchors on `X.XX ЛВ.` and looks back for a EUR pair; Pass 2 catches EUR-pair-only products missed in Pass 1
6. Auto-detects promo period from the downloaded filename
7. Replaces all `Fantastico / Direct` records in master

**How to run:**

```bash
# Fully automated (download + parse + merge)
python fantastico_pipeline.py

# Use an already-downloaded PDF
python fantastico_pipeline.py --pdf fantastico_work/fantastico_brochure.pdf

# Force Azure OCR even if a text layer is detected
python fantastico_pipeline.py --force-ocr

# Dry run — parse and report without writing to master
python fantastico_pipeline.py --dry-run
```

Requires: `pip install playwright && playwright install chromium`
Azure key for OCR fallback: set `AZURE_KEY` in `secrets.py` or pass `--key YOUR_AZURE_KEY`.

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

Run in this order each promo week (Wednesday or Thursday). Each script merges its own records directly into the master JSON — no separate merge step needed.

```bash
# 1. Gladen.bg / Hit Max
#    Update PROMO_PERIOD constant at top of file first
python gladen_html_scraper.py

# 2a. Billa PDF brochure OCR (supplementary items only)
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY
#     Azure key can live in secrets.py — then just: python billa_pdf_pipeline.py

# 2b. Billa ssbbilla.site (main Billa source)
python billa_scraper.py

# 3. Kaufland Direct + all Glovo sources
#    Update hardcoded product lists and file paths in the script first
python write_glovo_data.py

# 4. Fantastico Direct (fully automated)
python fantastico_pipeline.py

# 5. Generate Excel report
python generate_cheapest_xlsx.py
```

> **Note on Billa sources:** `billa_scraper.py` (ssbbilla.site) is the primary Billa source. `billa_pdf_pipeline.py` supplements it by adding PDF-only items not found on ssbbilla.site. The weekly comparison report (`billa_work/comparison_YYYY-MM-DD.xlsx`) shows which items come from each source.

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
| `source_store` | string | `"Billa"`, `"Hit Max"`, `"Kaufland"`, `"Fantastico"` |
| `source_channel` | string | `"Direct"` (retailer site/brochure), `"Glovo"` (Glovo app), or `"Gladen.bg"` (Hit Max records only) |
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
pip install requests pdfplumber openpyxl openai

# For Billa PDF pipeline and Fantastico OCR fallback:
pip install azure-ai-documentintelligence PyPDF2

# Required for Fantastico pipeline (headless browser); also used as Billa PDF download fallback:
pip install playwright && playwright install chromium
```
