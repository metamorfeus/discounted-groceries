#!/usr/bin/env python3
"""
Gladen.bg HTML scraper — fetches all promotion pages directly from HTML
and merges results into the master JSON.

Usage:
    python gladen_html_scraper.py [--pages N] [--dry-run]
"""

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
SOURCE_STORE = "Gladen.bg / Hit Max"
SOURCE_CHANNEL = "Direct"
SOURCE_URL_BASE = "https://gladen.bg/promotions"
PROMO_PERIOD = "02.04 - 08.04.2026"
EXTRACTION_DATE = date.today().isoformat()
MAX_PAGES = 42  # 1,000 products / 24 per page

MASTER_PATH = Path(__file__).parent / "bulgarian_promo_prices_merged.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}

# ── Regex patterns ─────────────────────────────────────────────────────────────
_EUR_RE = re.compile(r'(\d+\.\d{2})\s*€')
_UNIT_RE = re.compile(r'за\s+(бр|кг|л|оп|пак)\b\.?', re.IGNORECASE)

# Product card: <a href="https://gladen.bg/product/..." class="product-card-info-link" ...>
_CARD_RE = re.compile(
    r'<a\s+href="(https://gladen\.bg/product/[^"]+)"\s+class="product-card-info-link"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(r'<h2[^>]*class="product-card-title"[^>]*>\s*(.+?)\s*</h2>', re.DOTALL)

# Price blocks
_PROMO_BLOCK_RE = re.compile(
    r'<div[^>]*class="product-card-price-current is-promo"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_OLD_BLOCK_RE = re.compile(
    r'<div[^>]*class="product-card-price-old"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_UNIT_BLOCK_RE = re.compile(
    r'<div[^>]*class="product-card-cart-unit-price"[^>]*>(.*?)</div>',
    re.DOTALL,
)

# Category keywords (same as before)
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
    'Консерви': ['lutenicha', 'kechap', 'pastet', 'kompot', 'tuna',
                 'steriliziran', 'konserv'],
    'Домакинство': ['toaletna', 'prane', 'preparat', 'krp', 'prah'],
}


def _auto_category(product_name: str, url_slug: str = "") -> str | None:
    combined = (product_name + " " + url_slug).lower()
    for cat, kws in _CAT_KEYWORDS.items():
        if any(kw in combined for kw in kws):
            return cat
    return None


def _strip_tags(html: str) -> str:
    return re.sub(r'<[^>]+>', ' ', html).strip()


def parse_page_html(html: str, page_url: str) -> list[dict]:
    """Parse one Gladen.bg promotions page HTML → list of product records."""
    products = []
    seen = set()

    for card_m in _CARD_RE.finditer(html):
        product_url = card_m.group(1)
        card_html = card_m.group(2)

        # Product name
        title_m = _TITLE_RE.search(card_html)
        if not title_m:
            continue
        product_name = _strip_tags(title_m.group(1)).strip()
        if len(product_name) < 4:
            continue

        # URL slug for category
        url_slug = product_url.split('/product/')[-1] if '/product/' in product_url else ''

        # Promo price (current)
        promo_m = _PROMO_BLOCK_RE.search(card_html)
        if not promo_m:
            continue
        promo_eur = _EUR_RE.search(promo_m.group(1))
        if not promo_eur:
            continue
        promo_price = float(promo_eur.group(1))

        # Regular price (old) — only present when discounted
        old_m = _OLD_BLOCK_RE.search(card_html)
        regular_price = None
        if old_m:
            old_content = old_m.group(1).strip()
            # Skip empty old-price divs
            if old_content and not re.match(r'^\s*$', re.sub(r'<[^>]+>', '', old_content)):
                old_eur = _EUR_RE.search(old_m.group(1))
                if old_eur:
                    regular_price = float(old_eur.group(1))

        # Skip if no actual discount
        if regular_price is None:
            continue
        if promo_price >= regular_price:
            continue

        # Sanity check price range
        if promo_price < 0.10 or promo_price > 500:
            continue

        # Unit
        unit_m_block = _UNIT_BLOCK_RE.search(card_html)
        unit = None
        if unit_m_block:
            unit_text = _strip_tags(unit_m_block.group(1))
            um = _UNIT_RE.search(unit_text)
            if um:
                unit = um.group(1).lower()

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
            "promo_period": PROMO_PERIOD,
            "source_url": product_url,
            "extraction_date": EXTRACTION_DATE,
        })

    return products


def scrape_all_pages(max_pages: int = MAX_PAGES, delay: float = 0.5) -> list[dict]:
    """Fetch and parse all promotion pages."""
    session = requests.Session()
    session.headers.update(HEADERS)

    all_products = []
    seen_global = set()

    for page in range(1, max_pages + 1):
        url = f"{SOURCE_URL_BASE}?page={page}"
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"  Page {page}: ERROR — {e}", flush=True)
            continue

        page_products = parse_page_html(resp.text, url)

        # Global dedup across pages
        for p in page_products:
            key = (p['product_name'][:50].lower(), p['promo_price'])
            if key not in seen_global:
                seen_global.add(key)
                all_products.append(p)

        print(f"  Page {page:2d}: {len(page_products):2d} discounted items "
              f"(running total: {len(all_products)})", flush=True)

        # Stop early if page returned zero products (past last page)
        if len(page_products) == 0 and page > 5:
            print(f"  → No products on page {page}, stopping.")
            break

        if delay and page < max_pages:
            time.sleep(delay)

    return all_products


def merge_into_master(new_items: list[dict]) -> int:
    with open(MASTER_PATH, encoding='utf-8') as f:
        master = json.load(f)

    before = len(master)
    master = [r for r in master if r.get('source_store') != SOURCE_STORE]
    removed = before - len(master)

    master.extend(new_items)

    # Global dedup
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

    print(f"\nMaster updated: removed {removed} old Gladen records, "
          f"added {len(new_items)} new, total {len(deduped)} records.")
    return len(new_items)


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    max_pages = MAX_PAGES
    for arg in sys.argv[1:]:
        if arg.startswith('--pages='):
            max_pages = int(arg.split('=')[1])

    print(f"Scraping Gladen.bg promotions — up to {max_pages} pages...")
    products = scrape_all_pages(max_pages=max_pages, delay=0.3)
    print(f"\nTotal discounted products found: {len(products)}")

    if dry_run:
        print("DRY RUN — not writing to master.")
        for p in products[:5]:
            print(" ", p)
    else:
        merge_into_master(products)
