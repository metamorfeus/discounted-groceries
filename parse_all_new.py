#!/usr/bin/env python3
"""
Parse all newly scraped sources for CW14 (02.04-08.04.2026):
  1. Kaufland Direct  — from large FireCrawl result file
  2. Kaufland Glovo   — from markdown file
  3. Billa Glovo      — from markdown file
  4. Fantastico Glovo — from large FireCrawl result file

Usage:
  python parse_all_new.py [--dry-run]
"""
import sys, json, re
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MASTER_PATH   = Path("bulgarian_promo_prices_merged.json")
EXTRACTION_DATE = date.today().isoformat()
PROMO_PERIOD  = "02.04 - 08.04.2026"
EUR_TO_BGN    = 1.95583

# ── File paths ─────────────────────────────────────────────────────────────────
KAUFLAND_DIRECT_FILE = Path(
    r"C:\Users\PVELINOV\.claude\projects\C--Users-PVELINOV-ODP-OneDrive-BG-FOOD-PRICES"
    r"\609b30dc-ecb2-47a6-a596-86946a4455af\tool-results"
    r"\mcp-claude_ai_firecrawl-firecrawl_scrape-1775572521193.txt"
)
FANTASTICO_GLOVO_FILE = Path(
    r"C:\Users\PVELINOV\.claude\projects\C--Users-PVELINOV-ODP-OneDrive-BG-FOOD-PRICES"
    r"\609b30dc-ecb2-47a6-a596-86946a4455af\tool-results"
    r"\mcp-claude_ai_firecrawl-firecrawl_scrape-1775572571216.txt"
)

KAUFLAND_GLOVO_MD = Path("kaufland_glovo_cw14.md")
BILLA_GLOVO_MD    = Path("billa_glovo_cw14.md")


# ══════════════════════════════════════════════════════════════════════════════
# Kaufland Direct parser (same logic as session 1, updated for CW14)
# ══════════════════════════════════════════════════════════════════════════════

SEP      = '\\\\\n\\\\\n'
LV_RE    = re.compile(r'([\d,\.]+)\s*ЛВ\.', re.IGNORECASE)
UNIT_RE  = re.compile(
    r'^(\d+[\.,]?\d*\s*(кг|бр|л|г|мл|пак|бут)\.?|кг|бр\.?|л|г|мл|пакет|бутилка)$',
    re.IGNORECASE
)
SKIP_PATS = [
    re.compile(r'^-?\d+%'),
    re.compile(r'^[\d,\.]+ €'),
    LV_RE,
    re.compile(r'^Специална|^при покупка|KAUFLAND CARD|^отстъпка', re.IGNORECASE),
]


def parse_kaufland_direct(md: str) -> list[dict]:
    period_m = re.search(r'валидни\s+(?:от\s+)?(\d{2}\.\d{2}(?:\.\d{4})?)', md)
    period = period_m.group(1) if period_m else PROMO_PERIOD

    blocks = re.split(r'\[!\[Изображение на ', md)
    products, seen = [], set()

    for block in blocks[1:]:
        parts = block.split(SEP)
        data_parts = parts[1:]

        lv_prices = [LV_RE.search(p) for p in data_parts]
        lv_prices = [m.group(1).replace(',', '.') for m in lv_prices if m]
        if len(lv_prices) < 2:
            continue
        try:
            promo = float(lv_prices[0])
            regular = float(lv_prices[1])
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
                      if not UNIT_RE.match(p) and not any(pat.search(p) for pat in SKIP_PATS)
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


# ══════════════════════════════════════════════════════════════════════════════
# Glovo generic parser — works for Kaufland Glovo, Billa Glovo, Fantastico Glovo
# Product pattern:
#   -X,XX € (X,XX лв.)     ← discount line (optional)
#   ### Product Name        ← product heading
#   X,XX € (X,XX лв.)Y,YY € (Y,YY лв.)  ← promo + regular on same line
# ══════════════════════════════════════════════════════════════════════════════

_GLOVO_BGN_RE = re.compile(r'\((\d+[.,]\d+)\s*лв\.\)', re.IGNORECASE)
_GLOVO_PROD_RE = re.compile(
    r'### (.+?)\n\n'
    r'(\d+[.,]\d+)\s*€\s*\((\d+[.,]\d+)\s*лв\.\)'
    r'(\d+[.,]\d+)\s*€\s*\((\d+[.,]\d+)\s*лв\.\)',
    re.DOTALL
)


def parse_glovo_markdown(md: str, store: str, channel: str, url: str,
                         category: str = None) -> list[dict]:
    products, seen = [], set()

    for m in _GLOVO_PROD_RE.finditer(md):
        raw_name = m.group(1).strip()
        # Strip SKU suffix like "/ 20814181"
        product_name = re.sub(r'\s*/\s*\d+$', '', raw_name).strip()

        try:
            promo_eur  = float(m.group(2).replace(',', '.'))
            promo_bgn  = float(m.group(3).replace(',', '.'))
            regular_eur = float(m.group(4).replace(',', '.'))
            regular_bgn = float(m.group(5).replace(',', '.'))
        except ValueError:
            continue

        # Use BGN as primary; skip if no real discount
        if promo_bgn >= regular_bgn * 0.99:
            continue
        if promo_bgn < 0.20 or promo_bgn > 500:
            continue

        # Extract unit from product name (e.g. "400г", "0.75 Л", "160 ГР")
        unit_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(кг|г|гр|л|мл|бр|оп)\b', product_name, re.IGNORECASE)
        unit = None
        if unit_m:
            qty = unit_m.group(1)
            u   = unit_m.group(2).lower().replace('гр', 'г')
            unit = f"{qty} {u}"

        key = (product_name[:40].lower(), promo_bgn)
        if key in seen:
            continue
        seen.add(key)

        products.append({
            "source_store":     store,
            "source_channel":   channel,
            "product_name":     product_name,
            "product_category": category,
            "regular_price":    regular_bgn,
            "promo_price":      promo_bgn,
            "unit":             unit,
            "price_per_unit":   None,
            "promo_period":     PROMO_PERIOD,
            "source_url":       url,
            "extraction_date":  EXTRACTION_DATE,
        })

    return products


# ══════════════════════════════════════════════════════════════════════════════
# Load FireCrawl result file → markdown
# ══════════════════════════════════════════════════════════════════════════════

def load_firecrawl_file(path: Path) -> str:
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    try:
        d = json.loads(raw)
        return json.loads(d[0]['text'])['markdown']
    except Exception as e:
        print(f"  ERROR loading {path.name}: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# Load Glovo markdown saved to a .md file
# ══════════════════════════════════════════════════════════════════════════════

def load_md_file(path: Path) -> str:
    if not path.exists():
        print(f"  MISSING: {path}")
        return ""
    with open(path, encoding='utf-8') as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════════
# Merge into master JSON
# ══════════════════════════════════════════════════════════════════════════════

def merge_into_master(new_records: list[dict], stores_to_replace: list[str]) -> int:
    with open(MASTER_PATH, encoding='utf-8') as f:
        master = json.load(f)

    before = len(master)
    master = [r for r in master
              if not (r.get('source_store') in stores_to_replace
                      and r.get('source_channel') == 'Direct'
                      and r.get('source_store') == 'Kaufland')
              or r.get('source_channel') != 'Direct']

    # More precise removal: remove only the stores+channels being replaced
    master = json.load(open(MASTER_PATH, encoding='utf-8'))
    replace_keys = set()
    for r in new_records:
        replace_keys.add((r['source_store'], r['source_channel']))

    master = [r for r in master
              if (r.get('source_store'), r.get('source_channel')) not in replace_keys]
    removed = before - len(master)
    master.extend(new_records)

    # Dedup
    seen = set()
    deduped = []
    for r in master:
        key = (
            r.get('source_store', '')[:15],
            r.get('source_channel', ''),
            r.get('product_name', '')[:40].lower(),
            r.get('promo_price'),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    with open(MASTER_PATH, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f"  Removed {removed} old records for replaced store/channels")
    print(f"  Added {len(new_records)} new records")
    print(f"  Total master: {len(deduped)}")
    return len(new_records)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    dry_run = '--dry-run' in sys.argv
    all_new = []

    # 1. Kaufland Direct
    print("\n[1] Kaufland Direct...")
    if KAUFLAND_DIRECT_FILE.exists():
        md = load_firecrawl_file(KAUFLAND_DIRECT_FILE)
        if md:
            kd = parse_kaufland_direct(md)
            print(f"    Parsed {len(kd)} products")
            all_new.extend(kd)
        else:
            print("    Empty markdown — skipping")
    else:
        print(f"    File not found: {KAUFLAND_DIRECT_FILE}")

    # 2. Kaufland Glovo
    print("\n[2] Kaufland Glovo (Easter/Promo)...")
    md = load_md_file(KAUFLAND_GLOVO_MD)
    if md:
        kg = parse_glovo_markdown(
            md,
            store="Kaufland", channel="Glovo",
            url="https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof"
        )
        print(f"    Parsed {len(kg)} products")
        all_new.extend(kg)
    else:
        print("    No markdown file — skipping")

    # 3. Billa Glovo
    print("\n[3] Billa Glovo...")
    md = load_md_file(BILLA_GLOVO_MD)
    if md:
        bg = parse_glovo_markdown(
            md,
            store="Billa", channel="Glovo",
            url="https://glovoapp.com/bg/bg/sofia/stores/billa-sof1"
        )
        print(f"    Parsed {len(bg)} products")
        all_new.extend(bg)
    else:
        print("    No markdown file — skipping")

    # 4. Fantastico Glovo (Coca-Cola Real Magic slug)
    print("\n[4] Fantastico Glovo...")
    if FANTASTICO_GLOVO_FILE.exists():
        md = load_firecrawl_file(FANTASTICO_GLOVO_FILE)
        if md:
            fg = parse_glovo_markdown(
                md,
                store="Fantastico", channel="Glovo",
                url="https://glovoapp.com/bg/bg/sofia/stores/coca-cola-real-magic-sof"
            )
            print(f"    Parsed {len(fg)} products")
            all_new.extend(fg)
        else:
            print("    Empty markdown — skipping")
    else:
        print(f"    File not found: {FANTASTICO_GLOVO_FILE}")

    print(f"\nTotal new records across all sources: {len(all_new)}")

    if dry_run:
        print("DRY RUN — not writing to master.")
        by_store = {}
        for r in all_new:
            k = f"{r['source_store']} ({r['source_channel']})"
            by_store[k] = by_store.get(k, 0) + 1
        for k, n in sorted(by_store.items()):
            print(f"  {k}: {n}")
        for r in all_new[:5]:
            print(f"  SAMPLE: [{r['source_store']}] {r['product_name']} | {r['promo_price']} лв. (was {r['regular_price']})")
    else:
        print("\nMerging into master...")
        merge_into_master(all_new, [])

    print("\nDone.")


if __name__ == '__main__':
    main()
