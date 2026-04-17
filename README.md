# BG Food Prices — Project Index

Quick reference for what each document covers. Open the linked file when you have questions in that area.

---

## I want to...

| Question | Go to |
|---|---|
| Run the weekly data collection from scratch | `PIPELINE_GUIDE.md` → Weekly Execution Sequence |
| Know which scripts to run and in what order | `PIPELINE_GUIDE.md` → Weekly Execution Sequence |
| Understand what a specific script does | `PIPELINE_GUIDE.md` → Source Coverage Summary |
| Know which scripts are obsolete / legacy | `PIPELINE_GUIDE.md` → Legacy / Utility Scripts |
| Understand how prices are parsed from a specific site | `PRICE_EXTRACTION.md` → site-specific section |
| Debug why a price looks wrong | `PRICE_EXTRACTION.md` → site-specific section |
| See the JSON output schema (field names, types) | `PRICE_EXTRACTION.md` → Output schema |
| Check config flags (comparison threshold, batch size) | `PRICE_EXTRACTION.md` → Configuration |
| Install dependencies | `PRICE_EXTRACTION.md` → Dependencies |
| Know the current state of the dataset (record counts) | `project_overview.md` → Current Dataset State |
| Understand the Excel report sheets | `PIPELINE_GUIDE.md` → Step 5 / `project_overview.md` → Classification Pipeline |
| Know how GPT-4o classification works | `project_overview.md` → Classification Pipeline |
| See the history of RULES changes / category additions | `project_overview.md` → RULES Overhaul History |
| Know which config files exist and what they do | `project_overview.md` → Config Files |
| Know what Azure resources are used (endpoints, keys) | `project_overview.md` → Azure OpenAI Config |
| Understand the Billa PDF OCR strategy | `PRICE_EXTRACTION.md` → Billa PDF pipeline section |
| Understand the Billa PDF vs ssbbilla.site comparison | `PIPELINE_GUIDE.md` → Step 2 / `PRICE_EXTRACTION.md` → Billa PDF |

---

## Document Summaries

### `PIPELINE_GUIDE.md` — How to run the pipeline
**Use this when:** You are about to collect data for a new promo week.

- Weekly execution sequence: Step 1 (Gladen) → Step 2 (Billa PDF + ssbbilla) → Step 3 (Kaufland + Glovo) → Step 4 (Fantastico) → Step 5 (Excel report)
- Run commands for each script with common options
- What each step writes to the master JSON
- Source coverage table: which script feeds which store/channel
- Typical record counts per source (~2,337 total)
- Legacy scripts to avoid

### `PRICE_EXTRACTION.md` — How prices are extracted
**Use this when:** You want to understand or debug the parsing logic for a specific source.

| Source | What it explains |
|---|---|
| `billa_scraper.py` | HTML vs markdown auto-detection; EUR/BGN pair parsing; FireCrawl fallback |
| `gladen_html_scraper.py` | CSS selector patterns; genuine-discount filter |
| `fantastico_pdf_parser.py` | pdfplumber bounding-box column layout; EUR pair extraction |
| `fantastico_ocr_pipeline.py` | Two-pass OCR parsing; BGN anchor strategy |
| `billa_pdf_pipeline.py` | Publitas PDF download; Azure OCR batching; BGN-anchored EUR derivation; ssbbilla comparison; noise filtering |

Also covers: output JSON schema, config.py flags, pip dependencies.

### `project_overview.md` (memory file) — Project state and history
**Use this when:** You want context on the project's current state, history of decisions, or classification pipeline.

- Retailer table with current status per source
- Dataset record counts as of last update (2,301 records, 2026-04-07)
- Key scripts table
- Config files table
- Classification pipeline: rule-based (79%) → GPT-4o (93%) → За преглед (147 items)
- RULES overhaul history (v3, v4) — what categories exist and why
- Azure OpenAI config details
- Pending work

---

## Key Files

| File | Role |
|---|---|
| `bulgarian_promo_prices_merged.json` | Master dataset — all stores, all weeks |
| `bg_cheapest_v4_YYYY-MM-DD.xlsx` | Main deliverable — 6-sheet Excel report |
| `billa_work/comparison_YYYY-MM-DD.xlsx` | Weekly Billa PDF vs ssbbilla.site comparison |
| `secrets.py` | API keys (Azure DI + OpenAI) — never commit |
| `config.py` | Non-secret settings (batch sizes, feature flags) |
| `manual_overrides.json` | Manual category corrections keyed by product_name |

---

## Scripts at a Glance

| Script | Runs | Writes to master |
|---|---|---|
| `gladen_html_scraper.py` | Weekly | Yes — replaces Gladen records |
| `billa_pdf_pipeline.py` | Weekly | Yes — adds PDF-only Billa records |
| `billa_scraper.py` | Weekly | Yes — replaces Billa Direct records |
| `fantastico_pipeline.py` | Weekly | Yes — replaces Fantastico Direct records |
| `write_glovo_data.py` | Weekly | Yes — Kaufland + Billa + Fantastico Glovo |
| `generate_cheapest_xlsx.py` | After all scrapers | No — generates Excel from master |
| `analyze_categories.py` | Ad-hoc | No — outputs category_analysis_report.json |
| `billa_ocr_test.py` | Dev/debug only | No |
| `billa_ocr_parse_test.py` | Dev/debug only | No |
