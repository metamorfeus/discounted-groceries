# Bulgarian Grocery Promo Prices — Pipeline Guide

## Overview

This project collects weekly promotional prices from Bulgarian grocery retailers,
merges them into a single master JSON file, and produces an Excel report.

**Master data file:** `bulgarian_promo_prices_merged.json`
**Final output:** `bg_cheapest_vN_YYYY-MM-DD.xlsx`

---

## Weekly Execution Sequence

Run these steps in order at the start of each promo week (Wednesday or Thursday).

### Step 1 — Gladen.bg / Hit Max (automated scraper)

```
python gladen_html_scraper.py
```

Fetches all promotion pages from `gladen.bg/promotions` directly via HTTP,
parses discounted products (promo price < regular price), and merges into master.

- **Source:** gladen.bg — live HTML, no browser needed
- **Updates:** `Gladen.bg / Hit Max / Direct` records in master
- **Config to update each week:** `PROMO_PERIOD` constant at top of file
- **Output:** ~991 records merged into master

Options: `--pages N` (limit pages), `--dry-run` (parse only, no write)

---

### Step 2 — Billa Direct (two sub-steps)

#### 2a. PDF brochure OCR (supplementary items only)

```
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY
```

Downloads the Billa weekly PDF brochure from `billa.bg` (Publitas flipbook),
OCRs it via Azure Document Intelligence, and compares against ssbbilla.site.
Items found **only** in the PDF (not on ssbbilla.site) are added to master as
supplementary records.

- **Source:** billa.bg → Publitas PDF viewer (image-only, requires OCR)
- **Fallback:** `--pdf PATH` to use a manually downloaded PDF
- **Updates:** Billa / Direct (PDF-only items, ~126 records)
- **Produces:** `billa_work/comparison_YYYY-MM-DD.xlsx` (comparison report)
- **Requires:** Azure Document Intelligence key (set in `secrets.py` or pass via `--key`)

#### 2b. Billa ssbbilla.site (main Billa data source)

```
python billa_scraper.py
```

Scrapes `ssbbilla.site/catalog/sedmichna-broshura` — the accessibility version
of the Billa weekly brochure — which has clean structured text (no OCR needed).
This is the primary Billa data source with ~319 products.

- **Source:** ssbbilla.site — live HTTP, no browser needed
- **Updates:** Billa / Direct records in master (replaces all previous Billa Direct)
- **Options:** `--input FILE` to parse a previously saved page, `--download` to force re-fetch

---

### Step 3 — Kaufland Direct + Glovo sources

```
python write_glovo_data.py
```

Processes sources that were collected via FireCrawl MCP or saved markdown files:

| Source | Method | File |
|--------|--------|------|
| Kaufland Direct | FireCrawl MCP result file | hardcoded path in script |
| Kaufland Glovo | Saved markdown file | `kaufland_glovo_cw14.md` |
| Billa Glovo | Saved markdown file | `billa_glovo_cw14.md` |
| Fantastico Glovo | FireCrawl MCP result file | hardcoded path in script |

**Note:** This script has hardcoded product lists for Kaufland Glovo (16 Easter
products) and Billa Glovo (66 products) that were manually scraped. The Kaufland
Direct and Fantastico Glovo data come from FireCrawl tool result files.
Update the hardcoded data and file paths each week before running.

- **Updates:** Kaufland/Direct, Kaufland/Glovo, Billa/Glovo, Fantastico/Glovo records

---

### Step 4 — Fantastico Direct (fully automated)

```
python fantastico_pipeline.py
```

**Fully automated** — no manual steps required:

1. Scrapes `fantastico.bg/special-offers` to find the active FlippingBook brochure
2. Launches headless Chromium (Playwright), opens the FlippingBook viewer
3. Clicks Download → "Full Flipbook" → downloads the PDF (~14 MB)
4. Detects PDF type: embedded text (pdfplumber) or scanned (Azure OCR)
5. Parses product name/promo price/regular price from column layout
6. Auto-detects promo period from downloaded filename
7. Replaces old Fantastico/Direct records in master

- **Source:** fantastico.bg → FlippingBook viewer → PDF download
- **Updates:** Fantastico / Direct records in master (~189 records)
- **Requires:** `pip install playwright && playwright install chromium`
- **OCR fallback:** Set Azure key in `secrets.py` if text extraction fails

Options:
- `--dry-run` — parse and report without writing to master
- `--pdf PATH` — use an already-downloaded PDF instead of auto-downloading
- `--force-ocr` — force Azure OCR even if text is detected

---

### Step 5 — Generate Excel Report

```
python generate_cheapest_xlsx.py
```

Reads the master JSON and produces `bg_cheapest_vN_YYYY-MM-DD.xlsx` with sheets:

| Sheet | Contents |
|-------|----------|
| Най-евтини по категория | Top 5 cheapest by normalized price per category |
| Обобщение | Cheapest product per subcategory |
| Сравнение (авто) | Cross-store price comparison (Union-Find keyword matching) |
| Сравнение (ИИ) | Cross-store comparison via Azure OpenAI GPT-4o |
| Всички продукти | Full product list with enriched fields |
| За преглед | Unclassified products and items without unit |

- **Requires:** `pip install openpyxl`
- **Azure OpenAI** optional (for the AI comparison sheet) — key in `secrets.py`

---

## Configuration Files

| File | Purpose |
|------|---------|
| `secrets.py` | API keys — Azure DI key, Azure OpenAI key. Never commit to git. |
| `config.py` | Non-secret settings — batch sizes, retry counts, feature flags |

---

## Master JSON Schema

Each record in `bulgarian_promo_prices_merged.json`:

```json
{
  "source_store":     "Kaufland",
  "source_channel":   "Direct",
  "product_name":     "Прясно пиле, охладено, цяло",
  "product_category": "Месо",
  "regular_price":    4.99,
  "promo_price":      2.99,
  "unit":             "кг",
  "price_per_unit":   null,
  "promo_period":     "02.04 - 08.04.2026",
  "source_url":       "https://www.kaufland.bg/...",
  "extraction_date":  "2026-04-07"
}
```

**Channels:** `Direct` = retailer's own website/brochure; `Glovo` = Glovo app listing

---

## Legacy / Utility Scripts (do not run routinely)

| Script | What it was for |
|--------|----------------|
| `merge_all.py` | One-off merge script from early CW13 session; superseded by per-source merges |
| `gladen_scraper.py` | Old Gladen parser expecting FireCrawl markdown; replaced by `gladen_html_scraper.py` |
| `fantastico_pdf_parser.py` | Standalone pdfplumber parser; logic absorbed into `fantastico_pipeline.py` |
| `fantastico_ocr_pipeline.py` | Old manual OCR pipeline for Fantastico; superseded by `fantastico_pipeline.py` |
| `parse_all_new.py` | Intermediate CW14 helper; superseded by `write_glovo_data.py` |
| `generate_xlsx.py` | Earlier version of the Excel generator; superseded by `generate_cheapest_xlsx.py` |
| `analyze_categories.py` | One-off GPT-4o category review tool; run ad-hoc when categories need audit |
| `billa_ocr_test.py` | Development/testing script for Billa OCR |
| `billa_ocr_parse_test.py` | Development/testing script for Billa OCR parsing |

---

## Source Coverage Summary

| Store | Channel | Script | Method |
|-------|---------|--------|--------|
| Gladen.bg / Hit Max | Direct | `gladen_html_scraper.py` | HTTP scrape |
| Billa | Direct | `billa_scraper.py` | HTTP scrape (ssbbilla.site) |
| Billa | Direct | `billa_pdf_pipeline.py` | PDF OCR (supplementary) |
| Billa | Glovo | `write_glovo_data.py` | FireCrawl / manual |
| Kaufland | Direct | `write_glovo_data.py` | FireCrawl result file |
| Kaufland | Glovo | `write_glovo_data.py` | FireCrawl / manual |
| Fantastico | Direct | `fantastico_pipeline.py` | Playwright + pdfplumber |
| Fantastico | Glovo | `write_glovo_data.py` | FireCrawl result file |

---

## Typical Record Counts per Source (CW14, April 2026)

| Source | Records |
|--------|---------|
| Gladen.bg / Hit Max / Direct | ~991 |
| Kaufland / Direct | ~734 |
| Billa / Direct (ssbbilla.site) | ~319 |
| Fantastico / Direct | ~189 |
| Billa / Glovo | ~66 |
| Fantastico / Glovo | ~22 |
| Kaufland / Glovo | ~16 |
| **Total** | **~2,337** |
