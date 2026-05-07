#!/usr/bin/env python3
"""
Write Kaufland Glovo and Billa Glovo product JSON from scraped data,
parse Kaufland Direct from FireCrawl file,
parse Fantastico Glovo from FireCrawl file,
then merge all into master.
"""
import sys, json, re
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MASTER_PATH = Path("bulgarian_promo_prices_merged.json")
EXTRACTION_DATE = date.today().isoformat()
PROMO_PERIOD = "07.05 - 13.05.2026"

# ── Glovo store-name normalisation ───────────────────────────────────────────
# Maps non-standard Glovo store names → (source_store, source_channel).
# Glovo sometimes lists branded/virtual stores (e.g. "Coca-Cola Real Magic")
# that are not physical retailers. Add mappings here as they appear.
# "Coca-Cola Real Magic" — Coca-Cola branded virtual store on Glovo BG.
#   Not a physical retailer; skip or reclassify if/when encountered.
GLOVO_STORE_MAP: dict[str, tuple[str, str]] = {
    # "StoreName on Glovo": ("ActualStore", "Glovo"),
    # "Coca-Cola Real Magic": ("???", "Glovo"),  # unknown retailer — investigate
}

# ── Kaufland Glovo — CW16: not available (Glovo blocks non-BG IPs) ────────────
# Update manually from Glovo app when available
kaufland_glovo = []

kaufland_glovo_records = [
    {
        "source_store": "Kaufland", "source_channel": "Glovo",
        "product_name": p["name"], "product_category": None,
        "regular_price": p["reg"], "promo_price": p["promo"],
        "unit": p.get("unit"), "price_per_unit": None,
        "promo_period": PROMO_PERIOD,
        "source_url": "https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof",
        "extraction_date": EXTRACTION_DATE,
    }
    for p in kaufland_glovo
]
print(f"Kaufland Glovo: {len(kaufland_glovo_records)} products")

# ── Billa Glovo — CW16: not available (Glovo blocks non-BG IPs) ──────────────
# Update manually from Glovo app when available
billa_glovo_raw = []

billa_glovo_records = [
    {
        "source_store": "Billa", "source_channel": "Glovo",
        "product_name": name, "product_category": None,
        "regular_price": reg, "promo_price": promo,
        "unit": unit, "price_per_unit": None,
        "promo_period": PROMO_PERIOD,
        "source_url": "https://glovoapp.com/bg/bg/sofia/stores/billa-sof1",
        "extraction_date": EXTRACTION_DATE,
    }
    for name, promo, reg, unit in billa_glovo_raw
]
print(f"Billa Glovo: {len(billa_glovo_records)} products")

# ── Kaufland Direct — parse from FireCrawl file ──────────────────────────────
KAUFLAND_FILE = Path(
    r"C:\Users\PVELINOV\.claude\projects\c--AHA-OneDrive---AHA-BG-FOOD-PRICES"
    r"\2bc74b47-5ae6-4f01-99d9-46ef72da99a9\tool-results"
    r"\mcp-claude_ai_firecrawl-firecrawl_scrape-1778129195242.txt"
)

SEP     = '\\\\\n\\\\\n'
LV_RE   = re.compile(r'([\d,\.]+)\s*ЛВ\.', re.IGNORECASE)
EUR_RE  = re.compile(r'([\d]+[,.][\d]{2})\s*€')
UNIT_RE = re.compile(
    r'^(\d+[\.,]?\d*\s*(кг|бр|л|г|мл|пак|бут)\.?|кг|бр\.?|л|г|мл|пакет|бутилка)$',
    re.IGNORECASE
)
SKIP_PATS = [
    re.compile(r'^-?\d+%'),
    re.compile(r'^[\d,\.]+ ?€'),
    LV_RE,
    re.compile(r'^Специална|^при покупка|KAUFLAND CARD|^отстъпка', re.IGNORECASE),
]

def parse_kaufland_direct(md):
    period_m = re.search(r'валидни\s+(?:от\s+)?(\d{2}\.\d{2}(?:\.\d{4})?)', md)
    period = period_m.group(1) if period_m else PROMO_PERIOD

    blocks = re.split(r'\[!\[Изображение на ', md)
    products, seen = [], set()

    for block in blocks[1:]:
        parts = block.split(SEP)
        data_parts = parts[1:]

        eur_prices = [EUR_RE.search(p) for p in data_parts]
        eur_prices = [m.group(1).replace(',', '.') for m in eur_prices if m]
        if len(eur_prices) >= 2:
            try:
                promo   = float(eur_prices[0])
                regular = float(eur_prices[1])
            except ValueError:
                continue
        else:
            # Fallback: convert BGN to EUR
            lv_prices = [LV_RE.search(p) for p in data_parts]
            lv_prices = [m.group(1).replace(',', '.') for m in lv_prices if m]
            if len(lv_prices) < 2:
                continue
            try:
                promo   = round(float(lv_prices[0]) / 1.95583, 2)
                regular = round(float(lv_prices[1]) / 1.95583, 2)
            except ValueError:
                continue

        clean_parts = []
        for p in data_parts:
            p = p.strip()
            p = re.sub(r'\]\(https?://[^\)]*\)', '', p)
            p = re.sub(r'!\[\]\(https?://[^\)]*\)', '', p)
            p = p.strip().strip(']').strip('(').strip(')')
            if p:
                clean_parts.append(p)

        unit = next((p for p in clean_parts if UNIT_RE.match(p)), None)
        name_parts = [p for p in clean_parts
                      if not UNIT_RE.match(p)
                      and not any(pat.search(p) for pat in SKIP_PATS)
                      and len(p) >= 2]
        product_name = re.sub(r'\s+', ' ', ' '.join(name_parts[:2])).strip()

        if not product_name or len(product_name) < 3 or re.match(r'^-\d+%', product_name):
            continue

        key = (product_name[:40], promo)
        if key in seen:
            continue
        seen.add(key)

        products.append({
            "source_store":     "Kaufland",
            "source_channel":   "Direct",
            "product_name":     product_name,
            "product_category": None,
            "regular_price":    regular,
            "promo_price":      promo,
            "unit":             unit,
            "price_per_unit":   None,
            "promo_period":     period,
            "source_url":       "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html",
            "extraction_date":  EXTRACTION_DATE,
        })

    return products

print("\nParsing Kaufland Direct...")
with open(KAUFLAND_FILE, encoding='utf-8') as f:
    raw = f.read()
d = json.loads(raw)
md = json.loads(d[0]['text'])['markdown']
kaufland_direct = parse_kaufland_direct(md)
print(f"Kaufland Direct: {len(kaufland_direct)} products")

# ── Fantastico Glovo — parse from FireCrawl file ─────────────────────────────
# CW16: Fantastico Glovo not available — Glovo blocks non-BG IPs
FANTASTICO_FILE = None

_GLOVO_PROD_RE = re.compile(
    r'### (.+?)\n\n'
    r'(\d+[.,]\d+)\s*€\s*\((\d+[.,]\d+)\s*лв\.\)'
    r'(\d+[.,]\d+)\s*€\s*\((\d+[.,]\d+)\s*лв\.\)',
    re.DOTALL
)

def parse_glovo_file(path, store, channel, url):
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    d = json.loads(raw)
    md = json.loads(d[0]['text'])['markdown']

    products, seen = [], set()
    for m in _GLOVO_PROD_RE.finditer(md):
        raw_name = m.group(1).strip()
        product_name = re.sub(r'\s*/\s*\d+$', '', raw_name).strip()
        try:
            promo_eur   = float(m.group(2).replace(',', '.'))
            regular_eur = float(m.group(4).replace(',', '.'))
        except ValueError:
            continue
        if promo_eur >= regular_eur * 0.99 or promo_eur < 0.10 or promo_eur > 300:
            continue
        unit_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(кг|г|гр|л|мл|бр|оп)\b', product_name, re.IGNORECASE)
        unit = f"{unit_m.group(1)} {unit_m.group(2).lower().replace('гр','г')}" if unit_m else None
        key = (product_name[:40].lower(), promo_eur)
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "source_store": store, "source_channel": channel,
            "product_name": product_name, "product_category": None,
            "regular_price": regular_eur, "promo_price": promo_eur,
            "unit": unit, "price_per_unit": None,
            "promo_period": PROMO_PERIOD,
            "source_url": url,
            "extraction_date": EXTRACTION_DATE,
        })
    return products

print("\nParsing Fantastico Glovo...")
if FANTASTICO_FILE and Path(FANTASTICO_FILE).exists():
    fantastico_glovo = parse_glovo_file(
        FANTASTICO_FILE,
        store="Fantastico", channel="Glovo",
        url="https://glovoapp.com/bg/bg/sofia/stores/fantastico-sof",
    )
else:
    print("  Skipped — no FireCrawl file available for this week")
    fantastico_glovo = []
print(f"Fantastico Glovo: {len(fantastico_glovo)} products")

# ── Merge all into master ─────────────────────────────────────────────────────
all_new = kaufland_direct + kaufland_glovo_records + billa_glovo_records + fantastico_glovo
print(f"\nTotal new records: {len(all_new)}")

# Load master
with open(MASTER_PATH, encoding='utf-8') as f:
    master = json.load(f)

before = len(master)

# Remove old records for the stores/channels being replaced
replace_keys = set((r['source_store'], r['source_channel']) for r in all_new)
master = [r for r in master if (r.get('source_store'), r.get('source_channel')) not in replace_keys]
removed = before - len(master)
master.extend(all_new)

# Global dedup
seen = set()
deduped = []
for r in master:
    key = (
        r.get('source_store','')[:15],
        r.get('source_channel',''),
        r.get('product_name','')[:40].lower(),
        r.get('promo_price'),
    )
    if key not in seen:
        seen.add(key)
        deduped.append(r)

with open(MASTER_PATH, 'w', encoding='utf-8') as f:
    json.dump(deduped, f, ensure_ascii=False, indent=2)

print(f"\nMaster: removed {removed} old records, added {len(all_new)}, total {len(deduped)}")
print("Done!")
