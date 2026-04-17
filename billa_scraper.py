#!/usr/bin/env python3
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
"""
Billa Bulgaria — Weekly Brochure Scraper & Parser
==================================================
Source: ssbbilla.site/catalog/sedmichna-broshura
       (accessibility version of billa.bg weekly brochure — structured text, not flipbook images)

This script:
  1. Downloads the page from ssbbilla.site (or reads a saved file)
  2. Parses the HTML/markdown into structured product records
  3. Validates and deduplicates the data
  4. Merges with the existing dataset (bulgarian_promo_prices_*.json)
  5. Outputs updated JSON

Usage:
  # Auto-download and parse (easiest):
  python billa_scraper.py --existing bulgarian_promo_prices_2026-03-29.json

  # Or with explicit download flag:
  python billa_scraper.py --download --existing bulgarian_promo_prices_2026-03-29.json

  # If you already saved the page:
  python billa_scraper.py --input billa_raw.md --existing bulgarian_promo_prices_2026-03-29.json

Requirements:
  pip install requests   (for --download mode)
"""

import json
import re
import os
import sys
import argparse
from datetime import date
from pathlib import Path

# ─── CONFIGURATION ───────────────────────────────────────────────────────────

SCRAPE_URL = "https://ssbbilla.site/catalog/sedmichna-broshura"
SOURCE_STORE = "Billa"
SOURCE_CHANNEL = "Direct"
EXTRACTION_DATE = date.today().isoformat()

# Promo period for current week (update each run)
# Extracted from page text: "Валидност: от четвъртък 26.03. до 01.04.2026 г."
DEFAULT_PROMO_PERIOD = "26.03 - 01.04.2026"


def get_firecrawl_config():
    """
    FireCrawl MCP configuration to scrape the Billa accessibility brochure.

    Use this in Claude Cowork / MCP session:
        firecrawl_scrape(
            url="https://ssbbilla.site/catalog/sedmichna-broshura",
            formats=["markdown"],
            waitFor=10000,
            proxy="stealth",
            location={"country": "BG", "languages": ["bg"]},
            onlyMainContent=True
        )

    If ssbbilla.site/catalog/sedmichna-broshura returns a 403 or redirect,
    try the root URL instead:
        url="https://ssbbilla.site/"

    The page title is "Седмична брошура | BILLA Незрящи" (BILLA for visually impaired).
    This is an HTML page with full-text product listings (not a flipbook/PDF).
    """
    return {
        "url": SCRAPE_URL,
        "formats": ["markdown"],
        "waitFor": 10000,
        "proxy": "stealth",
        "location": {"country": "BG", "languages": ["bg"]},
        "onlyMainContent": True,
    }


# ─── PRICE EXTRACTION PATTERNS ──────────────────────────────────────────────

# Matches: "1,94 € / 3,79 лв." or "3.79 лв." or "3,79лв."
PRICE_EUR_BGN = re.compile(
    r'([\d]+[,.][\d]{2})\s*€\s*/\s*([\d]+[,.][\d]{2})\s*лв\.?'
)
PRICE_BGN_ONLY = re.compile(
    r'([\d]+[,.][\d]{2})\s*лв\.?'
)
PRICE_EUR_ONLY = re.compile(
    r'([\d]+[,.][\d]{2})\s*€'
)

# Matches promo labels that precede products (no ^ anchor for finditer)
PROMO_LABEL_FIND_RE = re.compile(
    r'(Супер цена|Сега в Billa|Само с Billa Card|Мултипак оферта|'
    r'Color Week оферт[а]?|Ново в Billa|Най-добра цена в BILLA|'
    r'BILLA Card оферт[а]?)\s*[-–—]?\s*',
    re.IGNORECASE
)
# Anchored version for matching at start of a block
PROMO_LABEL_RE = re.compile(
    r'^(Супер цена|Сега в Billa|Само с Billa Card|Мултипак оферта|'
    r'Color Week оферт[а]?|Ново в Billa|Най-добра цена в BILLA|'
    r'BILLA Card оферт[а]?)\s*[-–—]?\s*',
    re.IGNORECASE
)

# Matches unit patterns in product descriptions
UNIT_RE = re.compile(
    r'(\d+(?:[,\.]\d+)?(?:\s*[xх]\s*\d+(?:[,\.]\d+)?)?)\s*(кг|г|мл|л|бр|пак|бутилк[аи])\b\.?|'
    r'\b(За\s+1\s+кг)\b|'
    r'\b(\d+\s*пранета)\b',
    re.IGNORECASE
)

# Weight/volume patterns embedded in product name
WEIGHT_IN_NAME = re.compile(
    r'(\d+(?:[,.]?\d+)?)\s*(кг|г|мл|л)\b\.?'
)

# Origin pattern
ORIGIN_RE = re.compile(r'Произход\s*[-–—]\s*(.+?)(?:\s|$)')

# Old price pattern: "стара цена X,XX" or "предишна цена X,XX"
OLD_PRICE_RE = re.compile(
    r'(?:стара|предишна|без отстъпка)\s+(?:цена\s+)?([\d]+[,.][\d]{2})\s*(?:€|лв\.?)',
    re.IGNORECASE
)

# Validity period
VALIDITY_RE = re.compile(
    r'(?:Валидност|валидна).*?(\d{2}\.\d{2}\.?\d{0,4})\s*(?:г\.?\s*)?'
    r'(?:до|[-–—])\s*(\d{2}\.\d{2}\.?\d{0,4})',
    re.IGNORECASE
)

# EUR → BGN conversion rate
EUR_TO_BGN = 1.95583


# ─── PARSER ──────────────────────────────────────────────────────────────────

def normalize_price(price_str):
    """Convert '3,79' or '3.79' to float 3.79"""
    if not price_str:
        return None
    return float(price_str.replace(',', '.'))


def extract_promo_period(text):
    """Try to extract the brochure validity period from the page text."""
    m = VALIDITY_RE.search(text)
    if m:
        start, end = m.group(1), m.group(2)
        # Normalize: "26.03." → "26.03", add year if missing
        start = start.rstrip('.')
        end = end.rstrip('.')
        if len(end) <= 5:  # no year
            end += ".2026"
        return f"{start} - {end}"
    return DEFAULT_PROMO_PERIOD


def extract_unit(text):
    """Extract unit/weight from product description text."""
    m = UNIT_RE.search(text)
    if m:
        if m.group(3):  # "За 1 кг"
            return "кг"
        if m.group(4):  # "112 пранета"
            return m.group(4)
        qty = m.group(1)
        unit = m.group(2)
        return f"{qty} {unit}".strip()

    m = WEIGHT_IN_NAME.search(text)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return None


def parse_billa_html(html_text):
    """
    Parse the ssbbilla.site HTML page into product records.

    HTML structure per product:
        <div class="product">
            <div class="actualProduct">Product Name</div>
            <div class="priceText">ПРЕДИШНА<br>ЦЕНА</div>      ← old price label
            <div><span class="price">6.39</span><span class="currency">€</span>
                 <span class="price">12.50</span><span class="currency">лв.</span></div>
            <div class="priceText">НОВА<br>ЦЕНА</div>           ← new price label
            <div class="discount">-25%</div>
            <div><span class="price">2.70</span><span class="currency">€</span>
                 <span class="price">5.28</span><span class="currency">лв.</span></div>
        </div>

    Some products have no prices (they're footnotes, headers, or disclaimers).
    """
    products = []
    seen = set()

    # Extract promo period from page
    promo_period = DEFAULT_PROMO_PERIOD
    period_m = re.search(
        r'Валидност.*?(\d{2}\.\d{2})\.?\s*(?:до|[-–])\s*(\d{2}\.\d{2}\.\d{4})',
        html_text, re.IGNORECASE
    )
    if period_m:
        promo_period = f"{period_m.group(1)} - {period_m.group(2)}"

    # Split into product blocks
    product_blocks = re.split(r'<div\s+class="product">', html_text)

    for block in product_blocks[1:]:  # skip first chunk (before first product)
        # ── Extract product name from actualProduct div ──
        name_m = re.search(
            r'<div\s+class="actualProduct"[^>]*>\s*(.*?)\s*</div>',
            block, re.DOTALL
        )
        if not name_m:
            continue
        raw_name = name_m.group(1).strip()
        # Strip HTML tags from name
        raw_name = re.sub(r'<[^>]+>', ' ', raw_name)
        raw_name = re.sub(r'\s+', ' ', raw_name).strip()

        if len(raw_name) < 3:
            continue

        # Skip footnotes and disclaimers (start with *, **, ***)
        if re.match(r'^\*{1,3}\s', raw_name):
            continue

        # ── Extract all prices: <span class="price">X.XX</span><span class="currency">лв.</span> ──
        price_spans = re.findall(
            r'<span\s+class="price">([\d.]+)</span>\s*'
            r'<span\s+class="currency">(.*?)</span>',
            block, re.DOTALL
        )

        if not price_spans:
            continue  # No prices → not a product (header/disclaimer)

        # Separate EUR and BGN prices
        bgn_prices = []
        eur_prices = []
        for val, currency in price_spans:
            currency_clean = re.sub(r'<[^>]+>', '', currency).strip()
            if 'лв' in currency_clean:
                bgn_prices.append(float(val))
            elif '€' in currency_clean:
                eur_prices.append(float(val))

        if not eur_prices:
            continue

        # ── Determine old price vs new price ──
        # Check for "ПРЕДИШНА ЦЕНА" and "НОВА ЦЕНА" labels
        has_old_label = 'ПРЕДИШНА' in block or 'предишна' in block
        has_new_label = bool(re.search(r'НОВА\s*(?:<br\s*/?>)?\s*ЦЕНА', block, re.IGNORECASE))

        if has_old_label and has_new_label and len(eur_prices) >= 2:
            # First EUR price is old/regular, second is new/promo
            regular_price = eur_prices[0]
            promo_price = eur_prices[1]
        elif len(eur_prices) == 1:
            promo_price = eur_prices[0]
            regular_price = None
        else:
            # Multiple prices but no clear labels — last one is likely the promo
            promo_price = eur_prices[-1]
            regular_price = eur_prices[0] if eur_prices[0] != eur_prices[-1] else None

        # ── Extract discount percentage ──
        discount_m = re.search(r'<div\s+class="discount"[^>]*>\s*(-?\d+%)\s*</div>', block)
        discount = discount_m.group(1) if discount_m else None

        # ── Clean product name ──
        # Remove promo label prefixes
        clean_name = raw_name
        label_m = PROMO_LABEL_RE.match(clean_name)
        promo_label = None
        if label_m:
            promo_label = label_m.group(1).strip()
            clean_name = clean_name[label_m.end():].strip()

        # Remove trailing footnote markers and purchase limits
        clean_name = re.sub(r'\*{1,3}$', '', clean_name).strip()
        clean_name = re.sub(r'\s+До \d+ (?:бр|кг)\.?\s*на клиент.*$', '', clean_name, flags=re.IGNORECASE).strip()
        # Remove origin info
        clean_name = re.sub(r'\s*Произход\s*[-–—]\s*\S+.*$', '', clean_name).strip()
        # Remove "Цена за 1 бр." type suffixes
        clean_name = re.sub(r'\s*Цена за \d+ бр\.?.*$', '', clean_name, flags=re.IGNORECASE).strip()
        # Remove "Продукт, маркиран със синя звезда"
        clean_name = re.sub(r'\s*Продукт,?\s*маркиран със синя звезда', '', clean_name, flags=re.IGNORECASE).strip()

        # ── Extract unit from name ──
        unit = extract_unit(clean_name)

        # ── Dedup ──
        key = (clean_name[:40].lower(), promo_price)
        if key in seen:
            continue
        seen.add(key)

        # ── Auto-categorize ──
        category = auto_categorize(clean_name)

        products.append({
            "source_store": SOURCE_STORE,
            "source_channel": SOURCE_CHANNEL,
            "product_name": clean_name,
            "product_category": category,
            "regular_price": regular_price,
            "promo_price": promo_price,
            "unit": unit,
            "price_per_unit": None,
            "promo_period": promo_period,
            "promo_label": promo_label,
            "source_url": SCRAPE_URL,
            "extraction_date": EXTRACTION_DATE,
        })

    return products


def parse_billa_markdown(md_text):
    """
    Parse the ssbbilla.site accessibility brochure markdown into product records.

    The page uses multiple possible separators:
      - Double newlines between products
      - "·" (middle dot) separators
      - Promo label prefixes ("Супер цена -", "Сега в Billa -", etc.)

    Strategy:
      1. Split text into candidate blocks (by newlines, then by promo labels)
      2. For each block, check if it contains a price
      3. Extract product name, prices, unit from the block
    """
    products = []
    seen = set()

    # Extract promo period from full text
    promo_period = extract_promo_period(md_text)

    # ── Build candidate blocks ──
    # First, split by double newlines
    raw_blocks = re.split(r'\n\s*\n', md_text)

    # Then, for blocks that still contain multiple products (separated by promo labels),
    # split further at promo label boundaries
    blocks = []
    for raw_block in raw_blocks:
        # Find promo label positions within this block
        label_positions = [(m.start(), m.group(1)) for m in PROMO_LABEL_FIND_RE.finditer(raw_block)]

        if len(label_positions) > 1:
            # Multiple products in one block — split at label boundaries
            for i, (pos, _label) in enumerate(label_positions):
                end = label_positions[i + 1][0] if i + 1 < len(label_positions) else len(raw_block)
                blocks.append(raw_block[pos:end].strip())
        elif len(label_positions) == 1 and label_positions[0][0] > 20:
            # There's a non-labeled product before the labeled one
            blocks.append(raw_block[:label_positions[0][0]].strip())
            blocks.append(raw_block[label_positions[0][0]:].strip())
        else:
            blocks.append(raw_block.strip())

    # Also try splitting by "·" if blocks are large
    expanded = []
    for block in blocks:
        if '·' in block and len(block) > 200:
            parts = block.split('·')
            expanded.extend(p.strip() for p in parts if p.strip())
        else:
            expanded.append(block)
    blocks = expanded

    for block in blocks:
        block = block.strip()
        if len(block) < 10:
            continue

        # Skip non-product blocks
        skip_keywords = [
            'Посочените цени са обозначени',
            'Виж рецептата',
            'Празнично работно време',
            'Спечели от наши марки',
            'www.billalottery',
            'Избери за великден',
            'Billa е единствената',
            'Валидност:',
            'Color Week.Открий',
            'Седмична брошура',
            'Предстояща брошура',
        ]
        if any(kw in block for kw in skip_keywords):
            # But check if this block ALSO has a product with a price
            # (some disclaimer blocks contain a product at the end)
            has_price = PRICE_EUR_BGN.search(block) or PRICE_BGN_ONLY.search(block)
            if not has_price:
                continue

        # ── Must contain a price to be a product ──
        if not (PRICE_EUR_BGN.search(block) or PRICE_BGN_ONLY.search(block) or PRICE_EUR_ONLY.search(block)):
            continue

        # ── Extract promo label ──
        promo_label = None
        m = PROMO_LABEL_RE.match(block)
        if m:
            promo_label = m.group(1).strip()
            block_for_name = block[m.end():].strip()
        else:
            block_for_name = block

        # ── Extract prices ──
        promo_price_eur = None
        regular_price_eur = None

        # Strip per-unit/per-wash pricing before main price extraction
        # Pattern: "1 изпиране = 0,14 €/0,27 лв./112 пранета, 0,21 €/0,41 лв./ 72 пранета"
        price_block = re.sub(
            r'\d+\s*изпиране\s*=\s*[\d,\.]+\s*€\s*/\s*[\d,\.]+\s*лв\.?[^€]*?(?=\d+[,\.]\d{2}\s*€\s*/\s*\d+[,\.]\d{2}\s*лв)',
            '', block, flags=re.IGNORECASE
        )
        # Also strip "Цена за 1 бр." prefix prices for multipack (keep the block for multipack logic)
        is_multipack = 'без отстъпка' in block and 'с отстъпка' in block

        # Try EUR/BGN pair first
        eur_bgn_matches = PRICE_EUR_BGN.findall(price_block)
        if eur_bgn_matches:
            if is_multipack and len(eur_bgn_matches) >= 3:
                # Multi-pack: use "без отстъпка" as regular, "с отстъпка" as promo
                regular_price_eur = normalize_price(eur_bgn_matches[1][0])
                promo_price_eur = normalize_price(eur_bgn_matches[2][0])
            elif is_multipack and len(eur_bgn_matches) >= 2:
                regular_price_eur = normalize_price(eur_bgn_matches[0][0])
                promo_price_eur = normalize_price(eur_bgn_matches[-1][0])
            else:
                # Use the LAST price pair as the product price (per-unit prices come first)
                promo_price_eur = normalize_price(eur_bgn_matches[-1][0])

                # Check for old/regular price
                old_m = OLD_PRICE_RE.search(block)
                if old_m:
                    old_price_str = old_m.group(1)
                    old_price = normalize_price(old_price_str)
                    context = block[max(0, old_m.start()-5):old_m.end()+10]
                    if '€' in context and 'лв' not in context:
                        regular_price_eur = old_price
                    else:
                        regular_price_eur = round(old_price / EUR_TO_BGN, 2)
        else:
            # Try BGN-only and convert to EUR
            bgn_matches = PRICE_BGN_ONLY.findall(price_block)
            if bgn_matches:
                promo_price_eur = round(normalize_price(bgn_matches[-1]) / EUR_TO_BGN, 2)
                old_m = OLD_PRICE_RE.search(block)
                if old_m:
                    regular_price_eur = round(normalize_price(old_m.group(1)) / EUR_TO_BGN, 2)
            else:
                # Try EUR-only
                eur_matches = PRICE_EUR_ONLY.findall(price_block)
                if eur_matches:
                    promo_price_eur = normalize_price(eur_matches[-1])

        if promo_price_eur is None:
            continue

        # ── Build product name ──
        name_text = block_for_name
        # Remove price patterns
        name_text = PRICE_EUR_BGN.sub('', name_text)
        name_text = PRICE_BGN_ONLY.sub('', name_text)
        name_text = PRICE_EUR_ONLY.sub('', name_text)
        name_text = OLD_PRICE_RE.sub('', name_text)
        # Remove origin
        name_text = ORIGIN_RE.sub('', name_text)
        # Remove common noise
        noise_patterns = [
            r'Продукт,?\s*маркиран със синя звезда',
            r'Billa Ready',
            r'От топлата витрина',
            r'От деликатесната витрина',
            r'От Billa пекарна',
            r'Цена за \d+ бр\.?\s*(?:без отстъпка|с отстъпка)?',
            r'\d+\s*опаковк[аи]',
            r'\d+\s*изпиране\s*=.*?(?:пранета|бр\.?)',
            r'Само с Billa Card',
            r'До \d+ (?:бр|кг)\.?(?:\s*на клиент(?:\s+на ден)?)?',
            r'\*+\s*.*?(?:наличните количества|регулярната|$)',
            r'Градините в с\.[^·\n]*',
            r'в опаковка',
        ]
        for pat in noise_patterns:
            name_text = re.sub(pat, '', name_text, flags=re.IGNORECASE)

        # Remove stray symbols
        name_text = re.sub(r'[€/]', '', name_text)
        name_text = re.sub(r'\s+', ' ', name_text).strip()
        name_text = name_text.strip('·,- \t\n')

        if len(name_text) < 3:
            continue

        # ── Extract unit ──
        unit = extract_unit(block)

        # ── Dedup ──
        key = (name_text[:40].lower(), promo_price_eur)
        if key in seen:
            continue
        seen.add(key)

        # ── Auto-categorize from product name ──
        category = auto_categorize(name_text)

        products.append({
            "source_store": SOURCE_STORE,
            "source_channel": SOURCE_CHANNEL,
            "product_name": name_text,
            "product_category": category,
            "regular_price": regular_price_eur,
            "promo_price": promo_price_eur,
            "unit": unit,
            "price_per_unit": None,
            "promo_period": promo_period,
            "promo_label": promo_label,
            "source_url": SCRAPE_URL,
            "extraction_date": EXTRACTION_DATE,
        })

    return products


def auto_categorize(name):
    """Simple keyword-based category assignment for Bulgarian product names."""
    name_lower = name.lower()
    categories = {
        'Месо': ['месо', 'пиле', 'пилеш', 'свинск', 'телеш', 'агнеш', 'кебапч',
                  'кюфте', 'наденица', 'суджук', 'шунка', 'салам', 'бут', 'плешка',
                  'вешалица', 'джолан', 'крила', 'бекон'],
        'Риба': ['риба', 'рибен', 'сьомга', 'хек', 'скумрия', 'суши', 'филе от'],
        'Млечни продукти': ['сирене', 'масло', 'мляко', 'кисело', 'кашкавал',
                            'йогурт', 'извара', 'крема'],
        'Плодове и зеленчуци': ['грозде', 'банан', 'ябълк', 'домат', 'краставиц',
                                 'картоф', 'лук', 'салата', 'авокадо', 'портокал',
                                 'лимон', 'череш', 'ягод', 'диня', 'пъпеш'],
        'Напитки': ['бира', 'вино', 'сок', 'вода', 'напитка', 'кафе', 'чай',
                     'кола', 'пепси', 'ракия', 'уиски', 'водка'],
        'Хляб и тестени': ['хляб', 'сомун', 'кифл', 'баница', 'козунак', 'тест',
                            'питка', 'бисквит', 'вафл'],
        'Домакинство': ['тоалетна хартия', 'кухненска ролка', 'пране', 'почиств',
                         'препарат', 'гел за', 'прах за', 'омекотител'],
    }
    for cat, keywords in categories.items():
        if any(kw in name_lower for kw in keywords):
            return cat
    return None

    return products


# ─── STRATEGY B: Line-by-line parser (fallback) ─────────────────────────────

def parse_billa_line_by_line(md_text):
    """
    Fallback parser: split by "·" separator (common in accessibility pages)
    and extract product + price from each segment.
    """
    products = []
    seen = set()
    promo_period = extract_promo_period(md_text)

    segments = re.split(r'\s*·\s*', md_text)

    for seg in segments:
        seg = seg.strip()
        if len(seg) < 10:
            continue

        # Must contain a price
        bgn_match = PRICE_EUR_BGN.search(seg) or PRICE_BGN_ONLY.search(seg)
        if not bgn_match:
            continue

        # Skip disclaimers
        if 'Посочените цени' in seg or 'Валидност' in seg:
            continue

        # Extract promo label
        promo_label = None
        m = PROMO_LABEL_RE.match(seg)
        if m:
            promo_label = m.group(1).strip()
            seg_clean = seg[m.end():].strip()
        else:
            seg_clean = seg

        # Extract prices
        eur_bgn = PRICE_EUR_BGN.findall(seg)
        if eur_bgn:
            promo_price = normalize_price(eur_bgn[0][0])
            regular_price = None
            old_m = OLD_PRICE_RE.search(seg)
            if old_m:
                regular_price = normalize_price(old_m.group(1))
        else:
            bgn_only = PRICE_BGN_ONLY.findall(seg)
            if bgn_only:
                promo_price = round(normalize_price(bgn_only[0]) / EUR_TO_BGN, 2)
                regular_price = round(normalize_price(bgn_only[1]) / EUR_TO_BGN, 2) if len(bgn_only) > 1 else None
            else:
                continue

        # Build name
        name = seg_clean
        name = PRICE_EUR_BGN.sub('', name)
        name = PRICE_BGN_ONLY.sub('', name)
        name = PRICE_EUR_ONLY.sub('', name)
        name = OLD_PRICE_RE.sub('', name)
        name = ORIGIN_RE.sub('', name)
        name = re.sub(r'Продукт,?\s*маркиран със синя звезда', '', name)
        name = re.sub(r'\s+', ' ', name).strip().strip('·- ')

        if len(name) < 3:
            continue

        unit = extract_unit(seg)

        key = (name[:40].lower(), promo_price)
        if key in seen:
            continue
        seen.add(key)

        products.append({
            "source_store": SOURCE_STORE,
            "source_channel": SOURCE_CHANNEL,
            "product_name": name,
            "product_category": None,
            "regular_price": regular_price,
            "promo_price": promo_price,
            "unit": unit,
            "price_per_unit": None,
            "promo_period": promo_period,
            "promo_label": promo_label,
            "source_url": SCRAPE_URL,
            "extraction_date": EXTRACTION_DATE,
        })

    return products


# ─── VALIDATION & MERGE ─────────────────────────────────────────────────────

def validate_products(products):
    """Apply data quality checks matching the project's validation rules."""
    clean = []
    removed = []

    for p in products:
        if not p.get('product_name') or not p.get('promo_price'):
            removed.append(('missing_required', p))
            continue

        if p['product_name'].startswith('![') or len(p['product_name']) < 4:
            removed.append(('bad_name', p))
            continue

        # Price sanity: promo should not exceed regular by more than 5%
        if p.get('regular_price') and p['promo_price'] > p['regular_price'] * 1.05:
            removed.append(('price_anomaly', p))
            continue

        # Price range sanity (BGN)
        if p['promo_price'] < 0.01 or p['promo_price'] > 500:
            removed.append(('price_range', p))
            continue

        clean.append(p)

    return clean, removed


def merge_with_existing(new_products, existing_path):
    """Load existing JSON dataset and merge new Billa products."""
    if not existing_path or not Path(existing_path).exists():
        return new_products

    with open(existing_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)

    # Remove any old Billa Direct entries (replacing them)
    existing = [
        p for p in existing
        if not (p['source_store'] == 'Billa' and p['source_channel'] == 'Direct')
    ]

    merged = existing + new_products

    # Global dedup
    seen = set()
    deduped = []
    for p in merged:
        key = (
            p['source_store'][:15],
            p['source_channel'],
            p['product_name'][:40].lower(),
            p['promo_price']
        )
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    return deduped


# ─── DOWNLOADER ──────────────────────────────────────────────────────────────

def download_billa_page(output_path="billa_raw.md"):
    """
    Download the Billa accessibility brochure page directly.
    Works when running locally (not in restricted container environments).
    Tries multiple URLs in order.
    """
    try:
        import requests
    except ImportError:
        print("ERROR: 'requests' package required for download. Install with:")
        print("  pip install requests")
        return None

    urls = [
        "https://ssbbilla.site/catalog/sedmichna-broshura",
        "https://ssbbilla.site/",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "bg,en;q=0.9",
    }

    for url in urls:
        print(f"Downloading from: {url}")
        try:
            resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            resp.encoding = 'utf-8'
            if resp.status_code == 200 and len(resp.text) > 1000:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(resp.text)
                print(f"  Saved {len(resp.text)} chars to {output_path}")
                return output_path
            else:
                print(f"  HTTP {resp.status_code}, content length {len(resp.text)} — trying next URL")
        except requests.RequestException as e:
            print(f"  Failed: {e} — trying next URL")

    print("\nERROR: Could not download from any URL.")
    print("You can manually save the page:")
    print("  1. Open https://ssbbilla.site/catalog/sedmichna-broshura in your browser")
    print("  2. Press Ctrl+S → save as 'billa_raw.md' (or .html)")
    print("  3. Re-run with: python billa_scraper.py --input billa_raw.md")
    return None


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Billa accessibility brochure scraper (ssbbilla.site)',
        epilog='Example: python billa_scraper.py --download --existing bulgarian_promo_prices_2026-03-29.json'
    )
    parser.add_argument('--input', '-i', default=None,
                        help='Path to markdown/HTML file (from browser save or FireCrawl)')
    parser.add_argument('--download', '-d', action='store_true',
                        help='Download page from ssbbilla.site automatically (requires requests)')
    parser.add_argument('--existing', '-e', default=None,
                        help='Path to existing JSON dataset to merge with')
    parser.add_argument('--output', '-o', default=None,
                        help='Output JSON path (default: billa_products_{date}.json)')
    args = parser.parse_args()

    # Determine input source
    if args.input and os.path.exists(args.input):
        input_path = args.input
    elif args.download or not args.input:
        # Auto-download if --download flag or no --input given
        if args.input and not os.path.exists(args.input):
            print(f"File not found: {args.input}")
            print(f"Attempting to download from ssbbilla.site...\n")
        elif not args.input:
            print("No --input file specified. Downloading from ssbbilla.site...\n")

        input_path = download_billa_page("billa_raw.md")
        if not input_path:
            sys.exit(1)
    else:
        print(f"ERROR: File not found: {args.input}")
        print(f"Use --download to fetch from ssbbilla.site, or save the page manually.")
        sys.exit(1)

    # Read raw content
    with open(input_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    # If the input is a FireCrawl tool-result JSON, extract markdown
    if raw.strip().startswith('[') or raw.strip().startswith('{'):
        try:
            d = json.loads(raw)
            if isinstance(d, list):
                md_text = json.loads(d[0]['text'])['markdown']
            elif isinstance(d, dict) and 'markdown' in d:
                md_text = d['markdown']
            else:
                md_text = raw
        except (json.JSONDecodeError, KeyError):
            md_text = raw
    else:
        md_text = raw

    print(f"Input size: {len(md_text)} chars")

    # Detect if input is HTML (from direct download) or markdown (from FireCrawl)
    is_html = '<div class="product">' in md_text or '<span class="price">' in md_text

    if is_html:
        print("Detected HTML format (ssbbilla.site direct download)")
        products = parse_billa_html(md_text)
        print(f"HTML parser: {len(products)} products")
    else:
        print("Detected markdown/text format (FireCrawl or browser text)")
        # Parse with primary strategy
        products = parse_billa_markdown(md_text)
        print(f"Strategy A (promo-label split): {len(products)} products")

        # If primary strategy yields few results, try fallback
        if len(products) < 10:
            products_b = parse_billa_line_by_line(md_text)
            print(f"Strategy B (line-by-line): {len(products_b)} products")
            if len(products_b) > len(products):
                products = products_b
                print("  → Using Strategy B results")

    # Validate
    clean, removed = validate_products(products)
    print(f"After validation: {len(clean)} clean, {len(removed)} removed")
    if removed:
        for reason, p in removed[:5]:
            print(f"  Removed ({reason}): {p.get('product_name', '?')[:50]}")

    # Remove the promo_label field (not in the project schema)
    for p in clean:
        p.pop('promo_label', None)

    # Merge with existing dataset
    if args.existing:
        merged = merge_with_existing(clean, args.existing)
        print(f"Merged with existing: {len(merged)} total records")
    else:
        merged = clean

    # Output
    output_path = args.output or f"billa_products_{EXTRACTION_DATE}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"Written to: {output_path}")

    # Summary
    stores = {}
    for p in merged:
        key = f"{p['source_store']} ({p['source_channel']})"
        stores[key] = stores.get(key, 0) + 1
    print("\n── Summary ──")
    for k, v in sorted(stores.items()):
        print(f"  {k}: {v}")


if __name__ == '__main__':
    main()
