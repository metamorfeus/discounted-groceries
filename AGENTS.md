# Discounted Groceries — Agent Context
**Last updated:** 2026-04-16
**Next session priority:** Weekly pipeline run for current promo week

---

## What This Project Does

Weekly pipeline that scrapes promotional grocery prices from Bulgarian retailers
(Gladen.bg/Hit Max, Billa, Kaufland, Fantastico), merges them into a master JSON
dataset (`bulgarian_promo_prices_merged.json`), and generates a 6-sheet Excel
price-comparison report. Prices are stored in EUR (BGN ÷ 1.95583).

---

## How to Start Every Session

1. Use `hermes-discounted-groceries` to recall what you know about this project
2. Check `CLAUDE.md` for the full weekly run sequence and architecture details
3. Confirm the current promo week (new week starts Wednesday or Thursday)
4. Update `PROMO_PERIOD` in `gladen_html_scraper.py` and hardcoded lists in `write_glovo_data.py` before running

---

## Weekly Execution Order

```bash
# Step 1: Gladen.bg / Hit Max (~991 records) — update PROMO_PERIOD first
python gladen_html_scraper.py

# Step 2a: Billa PDF OCR — supplementary items only (~126 records)
python billa_pdf_pipeline.py --key YOUR_AZURE_KEY

# Step 2b: Billa ssbbilla.site — main Billa source (~319 records)
python billa_scraper.py

# Step 3: Kaufland Direct + all Glovo sources (~734+104 records) — update hardcoded lists first
python write_glovo_data.py

# Step 4: Fantastico Direct — fully automated (~189 records)
python fantastico_pipeline.py

# Step 5: Generate Excel report
python generate_cheapest_xlsx.py
```

---

## Key File Paths

| File | Purpose |
|---|---|
| `bulgarian_promo_prices_merged.json` | Master dataset — all stores, all promo weeks |
| `config.py` | Non-secret config: Azure endpoint, batch sizes, feature flags |
| `secrets.py` | API keys — **NOT committed to git** |
| `azure_config.json` | Azure OpenAI deployment config (endpoint, model, api_version) |
| `manual_overrides.json` | Manual category corrections keyed by product_name |
| `generate_cheapest_xlsx.py` | Produces `bg_cheapest_vN_YYYY-MM-DD.xlsx` |
| `translator.py` / `translate_xlsx.py` | English translation feature (--english flag) |

---

## Master JSON Schema

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

`source_channel` is `Direct` (retailer site/brochure) or `Glovo` (Glovo app).

---

## Tech Stack

Python 3.x · pdfplumber · playwright · openpyxl · PyPDF2 · html2text ·
Azure Document Intelligence (OCR) · Azure OpenAI GPT-4o (category classification) ·
FireCrawl MCP (JS-heavy pages)

---

## Current Status

Pipeline fully operational. Last run: promo week 02.04–08.04.2026.
English translation feature (`--english` flag) added to `generate_cheapest_xlsx.py`.
Hermes persistent memory integration set up 2026-04-16.

---

## Scripts NOT to Run Routinely

`merge_all.py`, `gladen_scraper.py`, `fantastico_pdf_parser.py`,
`fantastico_ocr_pipeline.py`, `parse_all_new.py`, `generate_xlsx.py` — all superseded.
`billa_ocr_test.py`, `billa_ocr_parse_test.py` — dev/debug only.

---

## What NOT to Do

- Never commit `secrets.py` or `azure_secrets.json` (contain live API keys)
- Never run the superseded scripts listed above
- Never modify another store's records when running a single store's script
- Always update `PROMO_PERIOD` in `gladen_html_scraper.py` before each weekly run
- Always update hardcoded product lists in `write_glovo_data.py` each week

---

## How to Update This File

After each session: update **Current Status** and **Next session priority**, then:
```bash
git add AGENTS.md && git commit -m "Update AGENTS.md" && git push
```
VPS auto-syncs within 5 minutes — no manual `git pull` needed.
