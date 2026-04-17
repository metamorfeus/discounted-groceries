#!/usr/bin/env python3
"""
Gladen.bg promotions scraper and parser.

Usage (called from Claude session — not standalone):
    from gladen_scraper import parse_gladen_markdown, merge_gladen_into_master

The page structure per product block:
    [Brand\\\\n\\\\n**ProductName**\\\\n\\\\n
     PROMO_EUR €\\\\n/\\\\nPROMO_LV лв.\\\\n\\\\n\\\\n
     REGULAR_EUR €\\\\n/\\\\nREGULAR_LV лв.\\\\n\\\\n\\\\n  (only when discounted)
     PROMO_EUR €\\\\n/\\\\nPROMO_LV лв.\\\\nunit](url)

BGN prices in лв. are the canonical prices we capture.
Pattern when DISCOUNTED: 3 LV prices — promo, regular, promo again
Pattern when NOT discounted: 2 LV prices — both the same (no old price)
"""

import json
import re
from datetime import date
from pathlib import Path

SOURCE_STORE = "Gladen.bg / Hit Max"
SOURCE_CHANNEL = "Direct"
SOURCE_URL_BASE = "https://gladen.bg/promotions"
EXTRACTION_DATE = date.today().isoformat()
DEFAULT_PROMO_PERIOD = "26.03 - 01.04.2026"

# EUR price: "5.07 €" or "11.13 €"
_EUR_RE = re.compile(r'(\d+\.\d{2})\s*€')
# Product bold name: **Name**
_NAME_RE = re.compile(r'\*\*(.+?)\*\*')
# Unit after price block: "за бр." / "за кг" / "за л"
_UNIT_RE = re.compile(r'за\s+(бр|кг|л|оп|пак)\b\.?', re.IGNORECASE)
# Category from product URL slug hints
_CAT_KEYWORDS = {
    'Млечни продукти': ['kiselo-mlyako', 'mlyako', 'sirene', 'kashkaval',
                        'maslo', 'smetana', 'ayran', 'kefir'],
    'Месо': ['meso', 'pile', 'kokosha', 'svinsko', 'govezhdo', 'agreshko',
             'nadenitsa', 'salam', 'shunga', 'krenvirshi', 'bek'],
    'Риба': ['riba', 'syomga', 'hek', 'skumriya'],
    'Плодове и зеленчуци': ['domati', 'krastavitsi', 'kartofi', 'luk', 'chushki',
                             'yabylki', 'portokali', 'banani', 'jagodi', 'grinde'],
    'Напитки': ['bira', 'vino', 'sok', 'voda', 'kafe', 'chay', 'gazirana',
                'mineralna', 'energiyna', 'coca-cola', 'pepsi'],
    'Хляб и тестени': ['hlyab', 'kifli', 'banitsa', 'kozunak', 'biskviti',
                       'vafli', 'keks', 'kroasan'],
    'Консерви': ['lutenicha', 'kechap', 'pastет', 'kompot', 'tuна',
                 'steriliziran', 'konserv'],
    'Домакинство': ['tоaletna', 'pране', 'prilagatelnо', 'препарат',
                    'krp', 'prах'],
}


def _auto_category(product_name: str, url_slug: str = "") -> str | None:
    combined = (product_name + " " + url_slug).lower()
    for cat, kws in _CAT_KEYWORDS.items():
        if any(kw in combined for kw in kws):
            return cat
    return None


def parse_gladen_markdown(markdown: str, source_url: str = SOURCE_URL_BASE,
                          promo_period: str = DEFAULT_PROMO_PERIOD) -> list[dict]:
    """
    Parse Gladen.bg promotions page markdown into product records.
    Only returns items where a discount exists (promo_price < regular_price)
    OR where there's at least a promo_price (no regular shown = new/everyday price).
    """
    products = []
    seen = set()

    # Split by "Добави" (Add to cart button) — marks end of each product card
    blocks = markdown.split('\nДобави\n')

    for block in blocks:
        # Find bold product name
        name_m = _NAME_RE.search(block)
        if not name_m:
            continue
        product_name = name_m.group(1).strip()
        if len(product_name) < 4:
            continue

        # Extract product URL (for category hint)
        url_m = re.search(r'\]\((https://gladen\.bg/product/[^)]+)\)', block)
        product_url = url_m.group(1) if url_m else source_url
        url_slug = product_url.split('/product/')[-1] if '/product/' in product_url else ''

        # Collect EUR prices
        eur_prices = [float(m.group(1)) for m in _EUR_RE.finditer(block)]

        if not eur_prices:
            continue

        # Determine promo vs regular
        if len(eur_prices) >= 3:
            # Discounted: promo, regular, promo (3 values)
            promo_price = eur_prices[0]
            regular_price = eur_prices[1]
            # sanity check: promo should be lower
            if promo_price >= regular_price:
                promo_price, regular_price = min(eur_prices[:2]), max(eur_prices[:2])
        elif len(eur_prices) == 2:
            if abs(eur_prices[0] - eur_prices[1]) < 0.01:
                # Same price — no actual discount; skip (no promo)
                continue
            promo_price = min(eur_prices)
            regular_price = max(eur_prices)
        elif len(eur_prices) == 1:
            promo_price = eur_prices[0]
            regular_price = None
            # No discount — skip items without a real promo
            continue
        else:
            continue

        # Validate price range
        if promo_price < 0.10 or promo_price > 500:
            continue
        if regular_price and promo_price >= regular_price * 1.05:
            continue  # anomaly: promo not cheaper than regular

        # Extract unit
        unit_m = _UNIT_RE.search(block)
        unit = unit_m.group(1).lower() if unit_m else None

        # Dedup
        key = (product_name[:50].lower(), promo_price)
        if key in seen:
            continue
        seen.add(key)

        products.append({
            "source_store": SOURCE_STORE,
            "source_channel": SOURCE_CHANNEL,
            "product_name": product_name,
            "product_category": _auto_category(product_name, url_slug),
            "regular_price": regular_price,
            "promo_price": promo_price,
            "unit": unit,
            "price_per_unit": None,
            "promo_period": promo_period,
            "source_url": source_url,
            "extraction_date": EXTRACTION_DATE,
        })

    return products


def merge_gladen_into_master(new_items: list[dict], master_path: str | Path) -> int:
    """
    Merge new Gladen items into the master JSON, replacing old Gladen records.
    Returns count of new records added.
    """
    master_path = Path(master_path)
    with open(master_path, encoding='utf-8') as f:
        master = json.load(f)

    # Remove existing Gladen records
    master = [r for r in master if r.get('source_store') != SOURCE_STORE]

    # Append new items
    master.extend(new_items)

    # Global dedup
    seen = set()
    deduped = []
    for r in master:
        key = (r.get('source_store', '')[:15],
               r.get('source_channel', ''),
               r.get('product_name', '')[:40].lower(),
               r.get('promo_price'))
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    with open(master_path, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    return len(new_items)
