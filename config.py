"""
Project-wide configuration for BG Food Prices pipeline.
Edit this file to tune pipeline behaviour.
"""

# ─── Azure Document Intelligence ─────────────────────────────────────────────
AZURE_ENDPOINT = "https://invoice2024.cognitiveservices.azure.com/"
AZURE_MODEL_ID  = "prebuilt-read"

# ─── Master dataset ───────────────────────────────────────────────────────────
MASTER_JSON = "bulgarian_promo_prices_merged.json"

# ─── Fantastico OCR pipeline ──────────────────────────────────────────────────
FANTASTICO_PAGES_PER_BATCH = 10
FANTASTICO_OCR_MAX_RETRIES = 3
FANTASTICO_OCR_RETRY_DELAY = 5   # seconds between retries
FANTASTICO_WORK_DIR        = "fantastico_work"

# ─── Billa PDF pipeline ───────────────────────────────────────────────────────
BILLA_WORK_DIR         = "billa_work"
BILLA_PAGES_PER_BATCH  = 2       # 2-page batches — image PDFs are large per page
BILLA_OCR_MAX_RETRIES  = 3
BILLA_OCR_RETRY_DELAY  = 5       # seconds between retries

# Weekly comparison: PDF brochure vs ssbbilla.site
# Set to False once you've confirmed the two sources overlap and want to
# rely solely on ssbbilla.site going forward.
BILLA_WEEKLY_COMPARISON    = True
BILLA_COMPARISON_THRESHOLD = 0.80   # name similarity 0.0–1.0 to count as same product
