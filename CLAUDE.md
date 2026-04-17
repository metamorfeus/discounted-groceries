# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Weekly pipeline that scrapes promotional grocery prices from Bulgarian retailers (Gladen.bg/Hit Max, Billa, Kaufland, Fantastico), merges them into a master JSON dataset, and generates an Excel price-comparison report.

---

## Weekly Execution (run in order each promo week — Wednesday or Thursday)

```bash
# Step 1: Gladen.bg / Hit Max (~991 records)
python gladen_html_scraper.py
# Update PROMO_PERIOD constant at top of the file each week before running
# Options: --pages N (limit pages), --dry-run (parse only, no write)

# Step 2a: Billa PDF brochure OCR — supplementary items only (~126 records)
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY
# Fallback: --pdf PATH if auto-download fails

# Step 2b: Billa ssbbilla.site — main Billa source (~319 records)
python billa_scraper.py
# Options: --input FILE (use saved page), --download (force re-fetch)

# Step 3: Kaufland Direct + all Glovo sources (~734+104 records)
python write_glovo_data.py
# IMPORTANT: Update hardcoded product lists and file paths in the script each week

# Step 4: Fantastico Direct — fully automated (~189 records)
python fantastico_pipeline.py
# Options: --dry-run, --pdf PATH, --force-ocr
# Requires: pip install playwright && playwright install chromium

# Step 5: Generate Excel report
python generate_cheapest_xlsx.py
```

### Do NOT run routinely
`merge_all.py`, `gladen_scraper.py`, `fantastico_pdf_parser.py`, `fantastico_ocr_pipeline.py`, `parse_all_new.py`, `generate_xlsx.py` — all superseded. `billa_ocr_test.py`, `billa_ocr_parse_test.py` — dev/debug only.

---

## Architecture

Each retailer has a dedicated script that scrapes, parses, and **merges directly into the master JSON** (`bulgarian_promo_prices_merged.json`). Scripts replace their own store/channel records on each run; they do not touch records from other sources.

```
gladen_html_scraper.py   → HTTP scrape of gladen.bg paginated HTML
billa_scraper.py         → HTTP scrape of ssbbilla.site (accessibility brochure)
billa_pdf_pipeline.py    → Publitas PDF → Azure Document Intelligence OCR → compare vs ssbbilla
fantastico_pipeline.py   → Playwright headless browser → FlippingBook PDF download
                           → pdfplumber (text PDF) or Azure DI OCR (scanned PDF)
write_glovo_data.py      → FireCrawl MCP result files + hardcoded manual Glovo lists
                           → Kaufland Direct, Kaufland/Billa/Fantastico Glovo
generate_cheapest_xlsx.py → Reads master JSON → 6-sheet Excel via openpyxl
                            → rule-based classification → GPT-4o for unclassified items
```

**FireCrawl** (MCP tool) is used for JS-heavy pages; result files are saved and passed to `write_glovo_data.py` — the script reads files, not live URLs. `analyze_categories.py` is a standalone GPT-4o auditor run ad-hoc.

---

## Configuration

| File | Purpose |
|---|---|
| `config.py` | Non-secret: Azure endpoint, batch sizes, feature flags, retry config |
| `secrets.py` | API keys: `AZURE_KEY` (Azure DI), Azure OpenAI key — **never commit** |
| `manual_overrides.json` | Manual category corrections keyed by `product_name` |
| `azure_config.json` / `azure_secrets.json` | Additional Azure configuration |

Key `config.py` flags:
- `BILLA_WEEKLY_COMPARISON` — enables PDF vs ssbbilla.site diff report
- `BILLA_COMPARISON_THRESHOLD` — similarity threshold (0.80) for product matching

---

## Master JSON Schema

File: `bulgarian_promo_prices_merged.json`

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

`source_channel` is either `Direct` (retailer website/brochure) or `Glovo` (Glovo app). All prices are in **EUR** (BGN ÷ 1.95583).

---

## Excel Report Sheets (`bg_cheapest_vN_YYYY-MM-DD.xlsx`)

| Sheet | Contents |
|---|---|
| Най-евтини по категория | Top 5 cheapest by normalized price per category |
| Обобщение | Cheapest per subcategory |
| Сравнение (авто) | Cross-store comparison via Union-Find keyword matching |
| Сравнение (ИИ) | Cross-store comparison via GPT-4o |
| Всички продукти | Full enriched product list |
| За преглед | Unclassified / no-unit products for manual review |

---

## Dependencies

No `requirements.txt` — install manually:

```bash
pip install requests pdfplumber openpyxl playwright PyPDF2 html2text markdownify azure-ai-documentintelligence
playwright install chromium
```

**External APIs:** Azure Document Intelligence (OCR), Azure OpenAI GPT-4o (classification), FireCrawl MCP (JS scraping).

---

## Documentation

For deeper detail on parsing logic, data structure, or project history:

| File | When to read it |
|---|---|
| `PIPELINE_GUIDE.md` | Full run commands, source coverage table, record counts |
| `PRICE_EXTRACTION.md` | Site-specific parsing logic, regex patterns, debugging |
| `project_overview.md` | Current dataset state, classification pipeline, RULES history |
| `PROJECT_HANDOFF.md` | Session-by-session history, architectural decisions |
