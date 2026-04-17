#!/usr/bin/env python3
"""
Fantastico brochure PDF parser — extracts structured product records
directly from the embedded PDF text using column-aware spatial grouping.

The brochure has 68 pages with 2-6 products per page in a grid layout.
pdfplumber extracts words with bounding boxes; we group them by x-column
so each product's name, prices, and unit stay together.

Usage:
    python fantastico_pdf_parser.py [--dry-run]
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber

# ── Config ────────────────────────────────────────────────────────────────────
SOURCE_STORE = "Fantastico"
SOURCE_CHANNEL = "Direct"
SOURCE_URL = "https://www.fantastico.bg/special-offers"
PROMO_PERIOD = "26.03 - 01.04.2026"
EXTRACTION_DATE = date.today().isoformat()

PDF_PATH = Path(__file__).parent / "fantastico_work" / "fantastico_brochure.pdf"
MASTER_PATH = Path(__file__).parent / "bulgarian_promo_prices_merged.json"

# ── Regex patterns ─────────────────────────────────────────────────────────────
# BGN price word: "4.40ЛВ." or "4.40 ЛВ." (as a single extracted word or two words)
_BGN_RE = re.compile(r'^(\d{1,3}[.,]\d{2})\s*ЛВ\.$', re.IGNORECASE)
# BGN price in text stream (from joined words)
_BGN_TEXT_RE = re.compile(r'(\d{1,3}[.,]\d{2})\s*ЛВ\.', re.IGNORECASE)
# EUR price: "2.25€" or "2.25 €"
_EUR_RE = re.compile(r'(\d{1,3}[.,]\d{2})\s*€')
# Discount: "-19%" or "-34%"
_DISC_RE = re.compile(r'-(\d{1,2})%')
# Unit indicator
_UNIT_RE = re.compile(r'цена\s+за\s+(бр|кг|оп|л|к-кт)\.?', re.IGNORECASE)
# Lines to skip as product names
_NOISE_RE = re.compile(
    r'^(?:'
    r'стр\.\s*\d|fantastico|www\.|ОФЕРТА ЗА|Продуктите се продават|'
    r'ТВ\s+[„"]?Фантастико|Декорацията|биоразградимите|'
    r'ПОСТНИ|вкусни идеи|KRINA|ORO$|Natural\s+Choice|'
    r'Premium\s+SELECTION|Compass$|Arriva$|GAEA$|LAURINI$|'
    r'ОТСТЪПКА$|Отстъпка$|отстъпка$|'
    r'находки|събира ни|постНИ|ФАНТАСТИКО|'    # cover page text
    r'Всички\s+.*(?:с\s+марка|видове)|[Мм]инимум\s+-?\d|'
    r'[Нн]е носи отговорност|[Пп]оръчки се|Алергени:|catering@|тел\.\s*\+|'
    r'7\s+DAYS|СЕДМИЦА НА|NEW[!]?|HOBO[!]?|'
    r'\*+|[Пп]ериод на кампанията|[Уу]икенд оферта|'
    r'[Пп]редложението е валидно|[Аа]кцията е валидна|'
    r'[Пп]родуктите се продават|[Дд]екорацията|'
    r'е валидно за магазините|валидно за магазините|'
    r'^\d{1,3}$|^[A-Z0-9\s\.\-\!\?]{1,10}$'  # page numbers, short all-caps Latin
    r')',
    re.IGNORECASE
)
_CYRILLIC_RE = re.compile(r'[\u0400-\u04FF]')

# Column window: [BGN.x0 - LEFT_MARGIN, BGN.x1 + RIGHT_MARGIN]
# Asymmetric: names are often to the LEFT of their price column
COL_LEFT_MARGIN = 140   # capture name words positioned left of price
COL_RIGHT_MARGIN = 60   # small right extension for price alignment


def _to_float(s: str) -> float:
    return float(s.replace(',', '.'))


def _is_noise(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 3:
        return True
    if _NOISE_RE.search(t):
        return True
    # Pure price/discount lines
    if re.match(r'^[\d.,€%\s\-\+\=\/]+$', t):
        return True
    # "цена за ..."
    if re.match(r'^цена\s+за', t, re.IGNORECASE):
        return True
    return False


def _has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text))


def _clean_name(lines: list[str]) -> str | None:
    """
    Given a list of text lines (bottom-up from BGN price), find the product name.
    Strategy:
    - Collect lines with Cyrillic until we hit a price/unit/noise line
    - Join them into a name
    - Prefer the longest meaningful name
    """
    name_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Stop at price/unit indicators
        if re.match(r'^\d{1,3}[.,]\d{2}\s*[€ЛВ]', line, re.IGNORECASE):
            break
        if re.match(r'^-\d{1,2}%', line):
            break
        if re.match(r'^цена\s+за', line, re.IGNORECASE):
            break
        # Skip pure noise lines (but keep weight/volume that's part of a name)
        if _is_noise(line) and not re.search(r'\d+\s*(?:г|кг|мл|л|бр)\b', line, re.IGNORECASE):
            continue
        name_lines.append(line)

    if not name_lines:
        return None

    # Join multi-line name
    name = ' '.join(name_lines)
    # Remove trailing unit/footnote fragments
    name = re.sub(r'\s*цена за\s+\S+\.?\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*произход\s+\S+.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*насипн[аи]\s+от щандова витрина\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip()

    if len(name) < 6 or not _has_cyrillic(name):
        return None
    return name


def extract_page_products(page, page_num: int) -> list[dict]:
    """Extract products from a single PDF page using spatial column grouping."""
    products = []

    words = page.extract_words(x_tolerance=5, y_tolerance=3)
    if not words:
        return products

    page_height = page.height

    # Find all BGN price words
    bgn_words = []
    for w in words:
        m = _BGN_RE.match(w['text'])
        if m:
            bgn_words.append({
                'price': _to_float(m.group(1)),
                'xc': (w['x0'] + w['x1']) / 2,
                'x0': w['x0'],
                'x1': w['x1'],
                'top': w['top'],
                'bottom': w['bottom'],
            })

    # Also try joining adjacent words for "4.40 ЛВ." split across two words
    # (pdfplumber sometimes splits "ЛВ." as a separate word)
    i = 0
    while i < len(words) - 1:
        w1, w2 = words[i], words[i + 1]
        combined = w1['text'] + w2['text']
        m = _BGN_RE.match(combined)
        if m and abs(w2['top'] - w1['top']) < 5:
            # Check not already captured
            xc = (w1['x0'] + w2['x1']) / 2
            already = any(abs(b['xc'] - xc) < 5 and abs(b['top'] - w1['top']) < 5 for b in bgn_words)
            if not already:
                bgn_words.append({
                    'price': _to_float(m.group(1)),
                    'xc': xc,
                    'x0': w1['x0'],
                    'x1': w2['x1'],
                    'top': w1['top'],
                    'bottom': w2['bottom'],
                })
        i += 1

    if not bgn_words:
        return products

    # Sort BGN prices by top position
    bgn_words.sort(key=lambda b: b['top'])

    for bgn in bgn_words:
        price = bgn['price']
        if price < 0.10 or price > 500:
            continue

        # Find words in same x region that appear ABOVE this BGN price.
        # Use asymmetric window: names are often to the LEFT of their price column.
        x_lo = bgn['x0'] - COL_LEFT_MARGIN
        x_hi = bgn['x1'] + COL_RIGHT_MARGIN
        col_words_above = [
            w for w in words
            if w['x0'] >= x_lo and w['x1'] <= x_hi + 40
            and w['top'] < bgn['top'] - 2
        ]

        # Bound from above: use the nearest previous BGN price (ANY x-column)
        # as the upper vertical limit. This prevents grabbing headers/noise
        # from sections above the current product block.
        lower_bound_top = 0
        for other_bgn in bgn_words:
            if (other_bgn is not bgn
                    and other_bgn['top'] < bgn['top']
                    and other_bgn['bottom'] > lower_bound_top):
                lower_bound_top = other_bgn['bottom']

        col_words_above = [w for w in col_words_above if w['top'] >= lower_bound_top]

        # Sort by top (reading order)
        col_words_above.sort(key=lambda w: (w['top'], w['x0']))

        # Reconstruct text lines from words (group by top position)
        line_groups: dict[int, list[str]] = {}
        for w in col_words_above:
            line_key = round(w['top'] / 2) * 2  # 2-pixel buckets
            line_groups.setdefault(line_key, []).append(w['text'])

        lines = [' '.join(g) for g in sorted(line_groups.values(), key=lambda g: 0)
                 for g in [g]]  # keep order
        # Rebuild properly sorted
        lines = []
        for key in sorted(line_groups.keys()):
            lines.append(' '.join(line_groups[key]))

        # Extract EUR prices (old/regular and new/promo) from these lines
        full_text = '\n'.join(lines)
        eur_prices = [_to_float(m.group(1)) for m in _EUR_RE.finditer(full_text)]

        regular_price = None
        promo_price_eur = None
        if len(eur_prices) >= 2:
            # First EUR price is old/regular, second is new/promo
            regular_price = eur_prices[0]
            promo_price_eur = eur_prices[1]
        elif len(eur_prices) == 1:
            # Only one EUR price — check if discount % present to derive regular
            disc_m = _DISC_RE.search(full_text)
            if disc_m:
                disc = int(disc_m.group(1))
                promo_price_eur = eur_prices[0]
                regular_price = round(promo_price_eur / (1 - disc / 100), 2)

        # Fall back: convert BGN anchor to EUR if promo EUR not found
        if promo_price_eur is None:
            promo_price_eur = round(price / 1.95583, 2)

        if regular_price is None:
            # Skip items with no identifiable regular price
            continue

        # Sanity: promo must be cheaper
        if promo_price_eur >= regular_price * 1.05:
            continue

        # Extract unit
        unit_m = _UNIT_RE.search(full_text)
        unit = None
        if unit_m:
            unit = {'кг': 'кг', 'бр': 'бр', 'оп': 'опаковка',
                    'л': 'л', 'к-кт': 'к-кт'}.get(unit_m.group(1).lower())

        # Extract name: collect ALL non-price, non-noise Cyrillic lines
        # (regardless of whether EUR prices appear before or after the name in
        # reading order — in some page layouts prices are in a right sub-column
        # that reads before the center/left name sub-column)
        name_lines = []
        for line in lines:
            # Skip pure price/discount lines
            if _EUR_RE.search(line) or _DISC_RE.search(line):
                continue
            if _BGN_TEXT_RE.search(line):
                continue
            if re.match(r'^цена\s+за', line, re.IGNORECASE):
                continue
            name_lines.append(line)

        name = _clean_name(name_lines)
        if not name:
            continue

        products.append({
            'name': name,
            'promo_price': promo_price_eur,
            'regular_price': regular_price,
            'unit': unit,
            'page': page_num,
        })

    return products


def auto_categorize(name: str) -> str | None:
    n = name.lower()
    if 'маслиново масло' in n or 'маслини' in n or 'олио' in n:
        return 'Масла и подправки'
    cats = {
        'Месо': ['месо', 'пиле', 'пилеш', 'свинск', 'телеш', 'агнеш', 'кебапч',
                 'кюфте', 'наденица', 'суджук', 'шунка', 'салам', 'бут', 'плешка',
                 'филе', 'бекон', 'крила', 'врат', 'кренвирш'],
        'Риба': ['риба', 'рибен', 'сьомга', 'хек', 'скумрия', 'скарид'],
        'Млечни продукти': ['сирене', 'масло', 'мляко', 'кисело', 'кашкавал',
                            'йогурт', 'извара', 'сметана'],
        'Плодове и зеленчуци': ['грозде', 'банан', 'ябълк', 'домат', 'краставиц',
                                 'картоф', 'лук', 'салата', 'авокадо', 'портокал',
                                 'лимон', 'диня', 'пъпеш', 'чушк', 'моркови',
                                 'ягоди', 'боб', 'леща'],
        'Напитки': ['бира', 'вино', 'сок', 'вода', 'напитка', 'кафе', 'чай',
                    'кола', 'пепси', 'ракия', 'уиски'],
        'Хляб и тестени': ['хляб', 'кифл', 'баница', 'козунак', 'бисквит', 'вафл',
                            'тост', 'питка', 'кроасан', 'франзела', 'паста'],
        'Домакинство': ['тоалетна хартия', 'пране', 'почиств', 'препарат',
                        'кърпа', 'прах за', 'омекот'],
        'Консерви': ['пастет', 'лютеница', 'стерилизиран', 'компот', 'консерв'],
    }
    for cat, kws in cats.items():
        if any(kw in n for kw in kws):
            return cat
    return None


def parse_pdf(pdf_path: Path) -> list[dict]:
    """Parse all pages of the Fantastico PDF."""
    all_raw = []
    seen = set()

    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        print(f'PDF: {total} pages', flush=True)
        for i, page in enumerate(pdf.pages):
            page_products = extract_page_products(page, i + 1)
            for p in page_products:
                key = (p['name'][:40].lower(), p['promo_price'])
                if key not in seen:
                    seen.add(key)
                    all_raw.append(p)
            if page_products:
                print(f'  Page {i+1:2d}: {len(page_products)} products', flush=True)

    return all_raw


_CYRILLIC_CHECK = re.compile(r'[\u0400-\u04FF]{3,}')  # at least 3 consecutive Cyrillic chars


def build_records(raw: list[dict]) -> list[dict]:
    """Convert raw extracted items to master JSON schema."""
    records = []
    seen = set()
    for p in raw:
        name = p['name']
        # Require at least 3 consecutive Cyrillic characters in name
        if not _CYRILLIC_CHECK.search(name):
            continue
        key = (name[:40].lower(), p['promo_price'])
        if key in seen:
            continue
        seen.add(key)
        records.append({
            'source_store': SOURCE_STORE,
            'source_channel': SOURCE_CHANNEL,
            'product_name': p['name'],
            'product_category': auto_categorize(p['name']),
            'regular_price': p['regular_price'],
            'promo_price': p['promo_price'],
            'unit': p['unit'],
            'price_per_unit': None,
            'promo_period': PROMO_PERIOD,
            'source_url': SOURCE_URL,
            'extraction_date': EXTRACTION_DATE,
        })
    return records


def merge_into_master(records: list[dict]) -> int:
    with open(MASTER_PATH, encoding='utf-8') as f:
        master = json.load(f)

    before = len(master)
    master = [r for r in master
              if not (r.get('source_store') == SOURCE_STORE
                      and r.get('source_channel') == SOURCE_CHANNEL)]
    removed = before - len(master)
    master.extend(records)

    seen = set()
    deduped = []
    for r in master:
        key = (r.get('source_store', '')[:15], r.get('source_channel', ''),
               r.get('product_name', '')[:40].lower(), r.get('promo_price'))
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    with open(MASTER_PATH, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f'\nMaster: removed {removed} old Fantastico Direct, '
          f'added {len(records)}, total {len(deduped)}')
    return len(records)


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    sys.stdout.reconfigure(encoding='utf-8')

    raw = parse_pdf(PDF_PATH)
    records = build_records(raw)
    print(f'\nTotal products: {len(records)}')

    if dry_run:
        print('\nSample records:')
        for r in records[:10]:
            print(f'  [{r["product_category"]}] {r["product_name"]} | '
                  f'promo={r["promo_price"]} reg={r["regular_price"]}')
    else:
        merge_into_master(records)
