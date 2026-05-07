# Pipeline Run Log

Weekly execution log for the Bulgarian grocery promo price pipeline.
Newest entries at the top.

---

## CW19 — 07.05 - 13.05.2026 | Run date: 2026-05-06

### Pre-run status

| Source | Channel | Previous period | Records | Notes |
|---|---|---|---|---|
| Hit Max | Gladen.bg | 16.04–22.04 (CW16) | 989 | Stale — 3 weeks |
| Kaufland | Direct | 16.04–22.04 (CW16) | 492 | Stale — 3 weeks |
| Billa | Direct | 16.04–22.04 (CW16) | 331+172 | Stale — 3 weeks |
| Fantastico | Direct | 16.04–22.04 (CW16) | 118 | Stale — 3 weeks |
| Kaufland | Glovo | 02.04–08.04 (CW14) | 16 | Very stale; VPN block CW16 |
| Billa | Glovo | 02.04–08.04 (CW14) | 66 | Very stale; VPN block CW16 |
| Fantastico | Glovo | 02.04–08.04 (CW14) | 22 | Very stale; VPN block CW16 |

CW17 (23.04–29.04) and CW18 (30.04–06.05) were not collected.

### Promo period confirmation

- **ssbbilla.site** confirmed `07.05 - 13.05.2026` (CW19) — brochure already live as of 2026-05-06
- **Gladen.bg** showing 2,551 active promos (~42 pages; up from 989/28 pages in CW16)
- Kaufland and Gladen.bg do not expose explicit promo dates in page HTML — period inferred from ssbbilla

### Data sources this run

| Step | Source | Method | Expected records | Status |
|---|---|---|---|---|
| 1 | Gladen.bg / Hit Max | HTTP scrape (`gladen_html_scraper.py`) | ~1,000–1,400 | — |
| 2b | Billa ssbbilla.site | HTTP scrape (`billa_scraper.py`) | ~319 | — |
| 2a | Billa PDF brochure | Azure DI OCR (`billa_pdf_pipeline.py`) | ~126 supplementary | — |
| 3a | Kaufland Direct | FireCrawl scrape → `write_glovo_data.py` | ~490 | — |
| 3b | Kaufland/Billa/Fantastico Glovo | Manual from Glovo app (VPN blocked) | 0 | Blocked |
| 4 | Fantastico Direct | Playwright + PDF (`fantastico_pipeline.py`) | ~189 | — |

### Step results

| Step | Records written | Period | Notes |
|---|---|---|---|
| 1 — Gladen.bg | 1,455 | 07.05–13.05 | Up from 989 in CW16; 42 pages scraped |
| 2b — Billa ssbbilla | 275 | 11.05–13.05 | Down from 331 in CW16 (Billa weekly subset) |
| 2a — Billa PDF | 63 | 01.05–31.05 | Monthly brochure; 94 before final dedup. Cache cleared and re-run required (stale OCR cache from old brochure caused wrong period on first run) |
| 3 — Kaufland Direct | 718 | 07.05–13.05 | FireCrawl scraped ot-ponedelnik.html; 1,801 blocks, 725 parsed, 718 after dedup. Glovo still blocked (non-BG IP) |
| 4 — Fantastico | 119 | 07.05–13.05 | PDF text mode; 38 pages; filename confirmed CW19 |
| 5 — Excel report | bg_cheapest_v4_2026-05-06.xlsx (954 KB) | — | 65% rule-classified; GPT-4o step failed (Azure OpenAI 401) |

### Issues encountered

- **Billa PDF OCR cache**: Stale `billa_work/ocr_output/*.json` from CW16 brochure caused wrong period detection on first run. Fix: clear `billa_work/ocr_output/` before each run (or implement PDF hash-based cache keys).
- **Billa scraper does not auto-merge to master**: Must run with `--existing bulgarian_promo_prices_merged.json --output bulgarian_promo_prices_merged.json`.
- **Azure OpenAI 401 error**: GPT-4o classification failed for all 24 batches (956 unclassified items). Check/rotate the Azure OpenAI key in `secrets.py`.
- **Glovo sources**: Still 0 records — blocked from non-BG IP. Requires VPN or manual app capture.

---

## CW16 — 16.04 - 22.04.2026 | Run date: 2026-04-16/17

| Source | Channel | Records | Notes |
|---|---|---|---|
| Hit Max | Gladen.bg | 989 | Scraped via gladen_html_scraper.py |
| Kaufland | Direct | 492 | FireCrawl + write_glovo_data.py |
| Billa | Direct | 331 | billa_scraper.py (ssbbilla.site) |
| Billa | Direct (PDF) | 172 | billa_pdf_pipeline.py (supplementary) |
| Fantastico | Direct | 118 | fantastico_pipeline.py |
| Kaufland | Glovo | 0 | Blocked (non-BG IP) |
| Billa | Glovo | 0 | Blocked (non-BG IP) |
| Fantastico | Glovo | 0 | Blocked (non-BG IP) |

Final Excel: `bg_cheapest_v4_2026-04-17.xlsx`
