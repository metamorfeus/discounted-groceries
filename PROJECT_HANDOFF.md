# Bulgarian Grocery Promotions Scraper — Project Handoff
**Last updated:** 2026-03-29
**Extraction date:** 2026-03-29 (Sunday morning, ~07:00–10:00 EET)
**Tool used:** FireCrawl MCP (`mcp__7b525947-7a06-4c60-a4a5-0ffb362202c4`)

---

## Project Mission

Extract ALL promotional/sale grocery items with prices from Bulgarian retail sites — both direct retailer websites and Glovo delivery platform storefronts — into a clean, unified JSON dataset ready for spreadsheet conversion.

The goal is a repeatable scraping pipeline covering:
- **Kaufland Bulgaria** (Direct + Glovo)
- **Billa Bulgaria** (Direct + Glovo)
- **Fantastico** (Direct + Glovo via "Coca-Cola Real Magic" slug)
- **Gladen.bg / Hit Max** (aggregator with live promo prices)

---

## Output Schema

Every record in the JSON dataset has these fields:

```json
{
  "source_store": "Kaufland",
  "source_channel": "Direct",
  "product_name": "Картофи Клас: I",
  "product_category": null,
  "regular_price": 1.58,
  "promo_price": 0.49,
  "unit": "кг",
  "price_per_unit": null,
  "promo_period": "29.03.2026",
  "source_url": "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html",
  "extraction_date": "2026-03-29"
}
```

**Field rules:**
- All prices in BGN (Bulgarian lev), normalized to `.` decimal (not `,`)
- `regular_price` and `price_per_unit` may be `null` if not shown on page
- `product_category` is `null` for Kaufland Direct (not tagged on their page); populated for Glovo and Gladen
- `promo_period` is a date-range string like `"26.03 - 01.04.2026"` or a single date

---

## Completed Work — Session 1 (2026-03-29)

### ✅ Successfully Scraped

| Site | Store | Channel | Products | Notes |
|------|-------|---------|----------|-------|
| kaufland.bg/aktualni-predlozheniya/oferti.html | Kaufland | Direct | **577** | Full promo catalogue |
| glovoapp.com/.../kaufland-sof | Kaufland | Glovo | **14** | Best-sellers only (store closed at scrape time) |
| glovoapp.com/.../coca-cola-real-magic-sof | Coca-Cola Real Magic* | Glovo | **20** | *Actually Fantastico's storefront |
| gladen.bg/promotions | Gladen.bg / Hit Max | Direct | **25** | Page 1 only; 2,976 total products available |

**Total clean records delivered:** 622 (after dedup + anomaly removal)

### ❌ Sites That Returned No Data

| Site | Reason | What To Do Next Time |
|------|--------|---------------------|
| billa.bg/promocii/sedmichna-broshura | **Publitas flipbook** — all content is scanned image JPEGs; zero extractable text | Needs OCR on the JPG pages; see "Next Steps" below |
| fantastico.bg/special-offers (brochure) | **FlippingBook** viewer — same problem, all images | Needs OCR; the PDF URL may be accessible directly |
| glovoapp.com/.../kaufland-sof?content=promotsii-pr | **Store closed** (Kaufland opens 10:00 on Sundays) | Re-scrape after 10:00 EET on any day |
| glovoapp.com/.../billa-sof1?content=promotsii-pr | **Store closed** (Billa opens 09:00 on Sundays) | Re-scrape after 09:00 EET on any day |

### ⚠️ Data Quality Actions Taken
- Removed 10 duplicate records (same store + name + price)
- Removed 8 records: 3 had malformed names (markdown parsing artifacts), 5 had `promo_price > regular_price` (parse errors)
- All prices normalized from Bulgarian comma format (`2,99`) to dot format (`2.99`)

---

## Saved Files

All files are in the **FOOD** workspace folder:

| File | Description |
|------|-------------|
| `bulgarian_promo_prices_2026-03-29.json` | **The final clean dataset — 622 records** |
| `PROJECT_HANDOFF.md` | This document |

---

## Site-by-Site Technical Notes

### 1. Kaufland Direct (`kaufland.bg`)

**Status:** ✅ Working well. 577 products.

**URL:** `https://www.kaufland.bg/aktualni-predlozheniya/oferti.html`

**How it renders:** JavaScript SPA. FireCrawl with `waitFor: 8000` and `proxy: stealth` successfully renders the full product list. The page auto-filters to "Плодове и зеленчуци" on first load but the markdown contains ALL categories.

**Markdown structure:** Products appear as image-link blocks. The separator between fields within each block is `\\\\\n\\\\\n` (literal `\\` + newline in the markdown string). Fields per product in order:
1. Brand name
2. Product name (sometimes multi-line joined with a space after normalization)
3. Unit (кг / бр / г / мл / л / number+unit like `700 г`)
4. Discount percentage (e.g., `-69%`)
5. EUR promo price (e.g., `0,25 € `)
6. EUR regular price (e.g., `0,81 €`)
7. **BGN promo price** (e.g., `0,49 ЛВ.`) ← use this
8. **BGN regular price** (e.g., `1,58 ЛВ.`) ← use this

**Working parser logic:**
```python
import json, re

# Load the FireCrawl result
with open('kaufland_scrape.json','r', encoding='utf-8') as f:
    raw = f.read()
d = json.load(raw if isinstance(raw, str) else open(raw))
# The result file format is: [{type: str, text: str}]
# text is itself a JSON string containing {"markdown": "...", "metadata": {...}}
md = json.loads(d[0]['text'])['markdown']

SEP = '\\\\\n\\\\\n'  # The actual separator in the markdown string
LV_RE = re.compile(r'([\d,\.]+)\s*ЛВ\.')
UNIT_RE = re.compile(r'^(\d+\s*(кг|бр|л|г|мл|пак)\.?|кг|бр\.?|л|г|мл|пакет|бутилка)$', re.IGNORECASE)

blocks = re.split(r'\[!\[Изображение на ', md)
products = []
seen = set()

for block in blocks[1:]:
    parts = block.split(SEP)
    # parts[0] = "ALT_TEXT](img_url)\n" — skip it
    data_parts = parts[1:]

    # Get LV prices
    lv_prices = [LV_RE.search(p) for p in data_parts]
    lv_prices = [m.group(1).replace(',', '.') for m in lv_prices if m]
    if len(lv_prices) < 2:
        continue

    try:
        promo = float(lv_prices[0])
        regular = float(lv_prices[1])
    except:
        continue

    # Clean parts
    clean_parts = []
    for p in data_parts:
        p = p.strip()
        p = re.sub(r'\]\(https?://[^\)]*\)', '', p)  # remove closing link
        p = re.sub(r'!\[\]\(https?://[^\)]*\)', '', p)  # remove badge images
        p = p.strip().strip(']').strip('(').strip(')')
        if p:
            clean_parts.append(p)

    # Find unit
    unit = next((p for p in clean_parts if UNIT_RE.match(p)), None)

    # Build product name (skip discount %, prices, unit, KAUFLAND CARD mentions)
    skip_patterns = [
        re.compile(r'^-?\d+%'),
        re.compile(r'^[\d,\.]+ €'),
        LV_RE,
        re.compile(r'^Специална|^при покупка|KAUFLAND CARD|^отстъпка'),
    ]
    name_parts = [p for p in clean_parts
                  if not UNIT_RE.match(p) and not any(pat.search(p) for pat in skip_patterns) and len(p) >= 2]

    product_name = re.sub(r'\s+', ' ', ' '.join(name_parts[:2])).strip()

    if not product_name or len(product_name) < 3 or re.match(r'^-\d+%', product_name):
        continue

    key = (product_name[:40], promo)
    if key in seen:
        continue
    seen.add(key)

    products.append({
        "source_store": "Kaufland",
        "source_channel": "Direct",
        "product_name": product_name,
        "product_category": None,
        "regular_price": regular,
        "promo_price": promo,
        "unit": unit,
        "price_per_unit": None,
        "promo_period": "29.03.2026",  # Update per scrape date
        "source_url": "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html",
        "extraction_date": "2026-03-29"
    })
```

**Promo period:** Displayed on the page as "Предложенията са валидни на DD.MM." — extract with:
```python
period_match = re.search(r'валидни\s+(?:от\s+)?(\d{2}\.\d{2}(?:\.\d{4})?)', md)
```

---

### 2. Billa Direct (`billa.bg`)

**Status:** ❌ NO STRUCTURED DATA

**URL:** `https://www.billa.bg/promocii/sedmichna-broshura`

**Problem:** The weekly brochure is embedded via **Publitas** flipbook viewer. The page renders as a series of JPG images (one per brochure page). No text content is extractable by FireCrawl. The current week is:
- Brochure: `BG_weekly_Digital_Leaflet_26.03.-01.04.2026__CW13__WEB`
- The flipbook is hosted at: `https://view.publitas.com/billa-bulgaria/bg_weekly_digital_leaflet_26-03-01-04-2026__cw13__web/`

**Options to get Billa data:**
1. **OCR the flipbook images** — fetch each page JPG (e.g., `page/1`, `page/2-3`...) and run OCR (e.g., Tesseract or a vision model). The JPG URLs are structured like:
   `https://view.publitas.com/62093/2928708/pages/{page_id}-at800.jpg`
2. **Billa online shop** — try `https://www.billa.bg/products` or the Billa app API (may require auth)
3. **Glovo** — Billa Glovo has a "ОФЕРТИ ДО -50%" category (26-01.04.2026). Re-scrape after 09:00 EET when the store opens; the promotions tab should load product listings

**Glovo category structure for Billa (when open):**
```
ВЕЛИКДЕН! → Великденски оферти до -50%
ОФЕРТИ ДО -50% 26-01.04.2026 → Храни До -50% / Напитки До -50% / Нехрани До -50%
Billa Card Оферти → Оферти -25% с BILLA Card / Оферти -20% с BILLA Card
```

---

### 3. Fantastico Direct (`fantastico.bg`)

**Status:** ❌ NO STRUCTURED DATA

**URL:** `https://www.fantastico.bg/special-offers`

**Problem:** Brochure is a **FlippingBook** viewer at `https://online.flippingbook.com/view/738517692`. Same issue as Billa — all images.
- Brochure period: `26.03.2026 - 01.04.2026`

**Options:**
1. **OCR the FlippingBook images** (CloudFront CDN URLs visible in the page source)
2. **Fantastico via Glovo** — see item #5 below; they do have a working Glovo store
3. The FlippingBook PDF download URL may be accessible; try:
   `https://online.flippingbook.com/view/738517692/pdf/`

---

### 4. Kaufland via Glovo — Promotions Tab

**Status:** ❌ EMPTY (store closed at scrape time)

**URL:** `https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof?content=promotsii-pr`

**Problem:** Kaufland opens at **10:00 on Sundays**; all other days likely 07:00–08:00. The Glovo SPA renders navigation/categories but shows "Няма списък с продукти за този обект. Моля, опитайте отново по-късно." when the store is closed.

**When it works:** The promotions tab (`?content=promotsii-pr`) loads the "Седмични предложения" section with promo items. FireCrawl settings that should work:
```python
firecrawl_scrape(
    url="https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof?content=promotsii-pr",
    formats=["markdown"],
    waitFor=12000,
    proxy="stealth",
    location={"country": "BG", "languages": ["bg"]}
)
```

**Product format on Glovo (when open):** Products appear as `### Product Name\n\nX.XX€ (Y.YY лв.)` — extractable with:
```python
products = re.findall(r'###\s+([^\n]+)\n+[\d,\.]+\s*€\s*\(([^\)]+лв\.)\)', md)
```
Note: Glovo shows **current store price** only — no regular/promo distinction unless you're in the promotions tab, where promo items appear with a badge and sometimes two prices.

---

### 5. Kaufland via Glovo — General Store

**Status:** ⚠️ PARTIAL (14 best-sellers captured, store was closed)

**URL:** `https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof`

Same timing constraint as #4. Re-scrape after 10:00. The general store page shows all categories when open.

---

### 6. Billa via Glovo — Promotions Tab

**Status:** ❌ EMPTY (store closed at scrape time)

**URL:** `https://glovoapp.com/bg/bg/sofia/stores/billa-sof1?content=promotsii-pr`

**Problem:** Billa opens at **09:00**. Same pattern as Kaufland Glovo.

**Key observation:** The Billa Glovo category nav loaded successfully and shows the full promo structure:
- `ОФЕРТИ ДО -50% 26-01.04.2026` → sub-categories: Храни До -50%, Напитки До -50%, Нехрани До -50%
- `Billa Card Оферти` → -25% and -20% discount tiers

This confirms rich promo data IS available — just needs to be scraped when open.

---

### 7. Coca-Cola Real Magic via Glovo

**Status:** ✅ 20 products extracted

**URL:** `https://glovoapp.com/bg/bg/sofia/stores/coca-cola-real-magic-sof`

**Important discovery:** This Glovo slug actually resolves to **Фантастико (Fantastico)**'s store — it is NOT a Coca-Cola branded store. The store title on the page is "Фантастико" and it sells standard grocery items. The 20 products extracted are the **"Най-продавани" (best-sellers)** visible on the landing page.

**No regular prices are shown** on these items (promo_price is the only price, regular_price = null) because Glovo shows a single "store price" unless an item is explicitly on promotion with a crossed-out price.

To get actual promotional items: the store may have subcategories with discounts — check the category navigation when the store page loads more fully.

---

### 8. Gladen.bg — Promotions Aggregator

**Status:** ✅ 25 products from page 1 — **2,976 total available**

**URL:** `https://gladen.bg/promotions`

**This is NOT a scanned flyer site** — it is a fully structured online grocery store (associated with **Hit Max**) with real product listings, promo prices, and regular prices. FireCrawl renders it correctly with `waitFor: 5000`.

**Product format in markdown:**
```
[Brand\\\n**Product Name**\\\nPROMO_EUR €\\\n/\\\nPROMO_BGN лв.\\\n\\\nREG_EUR €\\\n/\\\nREG_BGN лв.\\\n\\\nPROMO_EUR €\\\n/\\\nPROMO_BGN лв.\\\nза UNIT.](url)
```

**Working parser:**
```python
# Regex: extracts bold name + two price pairs (promo and regular, both in BGN)
pattern = re.compile(
    r'\*\*(.+?)\*\*'                          # bold product name
    r'[\s\S]*?'
    r'([\d\.]+)\s*€[\s\S]*?([\d\.]+)\s*лв\.' # promo EUR + BGN
    r'[\s\S]*?'
    r'([\d\.]+)\s*€[\s\S]*?([\d\.]+)\s*лв\.' # regular EUR + BGN
)
```

**Pagination:** The page shows 24 items per page. To get all 2,976:
- Food category (994 items): iterate `?has_promo=1&sort=sort_order&category_id=541&page=1` through page 42
- Drinks (456): `category_id=31`
- Home (641): `category_id=664`
- Cosmetics/Drugstore (691): `category_id=47`
- Baby/Child (95): `category_id=16`
- Pets (61): `category_id=751`
- Organic (38): `category_id=18`

Or scrape the paginated general promotions URL:
```
https://gladen.bg/promotions?has_promo=1&sort=sort_order&page=2
https://gladen.bg/promotions?has_promo=1&sort=sort_order&page=3
... (up to ~124 pages)
```

---

## Next Steps (Priority Order)

### Immediate — High Value

1. **Re-scrape Glovo stores after opening time**
   - Kaufland Glovo Promotions: after 10:00 EET any day
   - Billa Glovo Promotions: after 09:00 EET any day
   - URLs to hit: same as above with `proxy: stealth` and `waitFor: 12000`
   - Expected yield: 50–200 additional promo items each

2. **Paginate Gladen.bg** to get all 2,976 promo items instead of just 25
   - Loop pages 1–124 on `https://gladen.bg/promotions?has_promo=1&sort=sort_order&page={n}`
   - Or scrape each category URL listed above
   - Be polite: add `time.sleep(1)` between requests

3. **Assign product categories to Kaufland Direct items**
   - Currently all 577 have `product_category: null`
   - The kaufland.bg offers page has a category filter in the URL: `?kloffer-category=XX_CategoryName`
   - Scrape each category URL separately to get categorized items

### Medium Priority

4. **Billa via Glovo — get the real promo items**
   - After opening (09:00+), navigate to: `?content=promotsii-pr` and within that to sub-category Храни До -50%
   - May need FireCrawl interact tool to click into the category

5. **Billa Direct — OCR the flipbook**
   - Fetch JPG pages from the Publitas viewer
   - Run through a vision model to extract product names and prices
   - Brochure JPG URLs follow the pattern seen in the HTML source

6. **Fantastico Direct — try FlippingBook PDF**
   - Attempt: `https://online.flippingbook.com/view/738517692/pdf/`
   - If accessible, use FireCrawl PDF parser

### Low Priority / Enhancement

7. **Add `price_per_unit`** where the per-kg/per-liter price is shown
   - Kaufland's page shows this for some items
   - Gladen shows it as "за кг" / "за бр." suffix

8. **Category mapping for Kaufland Direct**
   - Map product names to categories using a keyword lookup (месо → Месо, сирене → Млечни, etc.)
   - A simple keyword dict would handle ~80% of cases

9. **Set up scheduled scraping**
   - Use the `schedule` skill to run the extraction daily or weekly
   - Kaufland updates offers every Thursday

---

## FireCrawl Configuration Reference

```python
# Standard stealth scrape (works for most sites)
firecrawl_scrape(
    url="...",
    formats=["markdown"],
    waitFor=8000,           # milliseconds to wait for JS rendering
    proxy="stealth",        # use "basic" as fallback if stealth fails
    location={"country": "BG", "languages": ["bg"]},
    onlyMainContent=True    # strips nav/footer boilerplate
)

# For Glovo SPAs (needs longer wait, full page)
firecrawl_scrape(
    url="...",
    formats=["markdown"],
    waitFor=12000,
    proxy="stealth",
    location={"country": "BG", "languages": ["bg"]},
    onlyMainContent=False   # keep full page for SPA product lists
)

# For structured data extraction (when page structure is known)
firecrawl_scrape(
    url="...",
    formats=["json"],
    jsonOptions={"prompt": "Extract all promotional products with names and prices in лв..."},
    proxy="stealth"
)
```

**Note on large results:** FireCrawl sometimes returns results exceeding the context window. When this happens, the result is saved to a temp file path provided in the error message. Access it with:
```python
# The file format is: [{type: str, text: str}]
# text is itself a JSON string: {"markdown": "...", "metadata": {...}}
with open('/path/to/tool-result.txt', 'r') as f:
    raw = f.read()
d = json.loads(raw)
md = json.loads(d[0]['text'])['markdown']
```

---

## Data Validation Rules

When building the final dataset, apply these checks:

```python
def validate_and_clean(products):
    clean = []
    removed = []

    for p in products:
        # Must have both name and promo_price
        if not p.get('product_name') or not p.get('promo_price'):
            removed.append(('missing_required', p))
            continue

        # Product name must be real (not markdown artifacts)
        if p['product_name'].startswith('![') or len(p['product_name']) < 4:
            removed.append(('bad_name', p))
            continue

        # Price sanity: promo should not be more than 5% above regular
        if p.get('regular_price') and p['promo_price'] > p['regular_price'] * 1.05:
            removed.append(('price_error', p))
            continue

        # Normalize prices
        for field in ('promo_price', 'regular_price', 'price_per_unit'):
            if isinstance(p.get(field), str):
                p[field] = float(p[field].replace(',', '.'))

        clean.append(p)

    # Deduplication
    seen = set()
    deduped = []
    for p in clean:
        key = (p['source_store'][:15], p['source_channel'],
               p['product_name'][:40].lower(), p['promo_price'])
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    return deduped, removed
```

---

## Dataset Statistics (Session 1)

```
Total records:          622
By store:
  Kaufland:             577  (Direct: 577, Glovo: 14 = 591 but 14 are Glovo)
  Coca-Cola Real Magic:  20  (Glovo — actually Fantastico)
  Gladen.bg / Hit Max:   25  (Direct)

By channel:
  Direct:               602
  Glovo:                 34 (14 Kaufland + 20 CC/Fantastico)

Price ranges (BGN):
  Kaufland Direct:      0.12 – 74.99 лв.
  Coca-Cola/Fantastico: 5.46 – 18.99 лв.
  Gladen.bg:            1.35 –  8.19 лв.

Records with regular_price: 602 (97%)
Records with unit:           ~480 (77%)
Records with category:        45 (7%) — only Glovo + Gladen items

Sites with NO data:
  Billa Direct          — flipbook (image-only)
  Fantastico Direct     — flipbook (image-only)
  Kaufland Glovo Promo  — store closed at scrape time
  Billa Glovo Promo     — store closed at scrape time
```

---

## Key Bulgarian Vocabulary

| Bulgarian | English | Notes |
|-----------|---------|-------|
| Промоция / Оферта | Promotion / Offer | |
| Намаление | Discount | |
| Валидно | Valid | |
| Предложенията са валидни на | Offers valid on | Date shown on page |
| Актуални предложения | Current offers | |
| лв. / ЛВ. | BGN (Bulgarian Lev) | Fixed to EUR at 1.95583 |
| кг / г / мл / л / бр | kg / g / ml / l / piece | Units |
| Плодове и зеленчуци | Fruits & vegetables | Category |
| Месо | Meat | Category |
| Млечни продукти | Dairy products | Category |
| Напитки | Drinks | Category |
| Колбаси | Cold cuts / deli meats | Category |
| Замразени | Frozen | Category |
| Закуска | Breakfast | Category |
| Хляб | Bread | Category |
| Брашно | Flour | Category |
| Захар | Sugar | Category |

---

*End of Session 1 handoff.*

---

---

## Session 2 — 2026-03-31 (Part 1): Billa Merge + Fantastico OCR Fix Attempt + Gladen Pagination Start

### Context at Start of Session
- Master JSON had 654 records (Kaufland 577, Gladen 25 page-1-only, Coca-Cola/Fantastico Glovo 20, Billa 32 old)
- `billa_products_2026-03-31.json` existed with 971 items (full Billa scrape done separately), not yet merged
- `fantastico_ocr_pipeline.py` existed; Azure DI OCR had run on 7 PDF batches but returned only ~30 items
- Gladen had 2,976 promo items across ~124 pages; only page 1 was scraped

### Work Done

**Billa merge:**
- Ran `merge_all.py` (already written) which strips old Billa Direct records and loads fresh from `billa_products_2026-03-31.json`
- Fixed a bug: the billa file contains records from multiple stores; filter to `source_store == "Billa" AND source_channel == "Direct"` → 349 records merged (not 971; the rest were other stores mixed in)
- Fixed `UnicodeEncodeError` in merge_all.py (replaced `→` with ASCII comma in a print statement)
- Fixed `NameError: EUR_TO_BGN` in fantastico_ocr_pipeline.py (added the constant)

**Fantastico OCR investigation:**
- Diagnosed: `fantastico_ocr_pipeline.py` `parse_ocr_to_products()` was called on JSON files that only had 2 pages of content each (Azure DI returned partial results — 2 pages per 10-page batch). Result: only 33 items total.
- Root cause identified but NOT fixed in this session (deferred to Session 3)

**Gladen.bg full pagination (FireCrawl MCP approach):**
- Discovered Gladen now has 1,000 promo products (not 2,976) across 42 pages (24/page, last page has 16)
- Scraped pages 1–24 using FireCrawl MCP in batches of 8 — all HTTP 200
- Scraped pages 25–32, 33–40, 41–42 — all HTTP 200
- Page 42 confirmed as last page (16 products, no "Още продукти" button)
- **Pages 1–24 content was lost** when this session's context was compacted — not persisted to files

### Files Created/Modified
- `gladen_scraper.py` — Gladen markdown parser (written but ultimately superseded in Session 3)
- `merge_all.py` — bug fixes applied

### State at End of Session 2 Part 1
- Master JSON: ~1,001 records (Kaufland 577, Billa 349, Coca-Cola 20, Gladen 25, Fantastico 30)
- Gladen pages 1–42 scraped but markdown content not persisted; re-scrape needed

---

## Session 3 — 2026-03-31 (Part 2): Gladen HTML Scraper + Fantastico PDF Parser

### Context at Start of Session
- Session 2 context was compacted; Gladen pages 1–24 markdown lost
- Master JSON: ~1,001 records
- Fantastico still at 30 items

### Work Done

#### Gladen.bg — Direct HTML Scraper (`gladen_html_scraper.py`)

**Discovery:** gladen.bg renders server-side (SSR). pdfplumber/requests can fetch the HTML directly — no FireCrawl needed.

**HTML product card structure:**
```html
<a href="https://gladen.bg/product/SLUG" class="product-card-info-link">
  <h2 class="product-card-title">Product Name</h2>
  <div class="product-card-price-current is-promo">0.89 € / 1.74 лв.</div>
  <div class="product-card-price-old">1.09 € / 2.13 лв.</div>
  <div class="product-card-cart-unit-price">0.89 € / 1.74 лв. за бр.</div>
</a>
```

**Parser logic:**
- Regex `_PROMO_BLOCK_RE` extracts BGN from `product-card-price-current is-promo`
- Regex `_OLD_BLOCK_RE` extracts BGN from `product-card-price-old`
- Skip items where `old_price_div` is empty (no discount)
- Skip items where `promo >= regular`
- Dedup on `(name[:50].lower(), promo_price)`

**Results:** 998 discounted items from all 42 pages (3 cross-page dupes removed → 995 in master)
**Speed:** ~15 seconds for all 42 pages with 0.3s delay between pages.

**Key implementation notes:**
- `COL_LEFT_MARGIN = 140` for column detection (names are LEFT of their price column in some layouts)
- `merge_gladen_into_master()` replaces old Gladen records by `source_store == "Gladen.bg / Hit Max"`

---

#### Fantastico — PDF Text Parser (`fantastico_pdf_parser.py`)

**Discovery:** `fantastico_brochure.pdf` (68 pages) contains **embedded text** — no OCR needed. The Azure DI OCR only returned 2/10 pages per batch, which was the root cause of the 30-item output.

**Why previous OCR approach failed:**
- Azure DI batches had 10 pages each
- Azure DI only returned 2 pages of extracted text per batch
- The OCR `.txt` files matched the JSON `full_text` exactly — both incomplete

**Why pdfplumber + column-aware extraction:**
- PyPDF2 extracts text in garbled order (prices before names due to PDF column layout)
- pdfplumber extracts words with bounding boxes (x0, x1, top, bottom)
- The brochure has 2–6 products per page in a grid; sequential text extraction interleaves them
- Solution: for each BGN price anchor, collect words within x-column window, bounded vertically by the nearest previous BGN price on the page

**Critical layout insight — two product layout types:**
1. **Name-above-price** (most pages): name words appear above EUR/BGN prices in reading order
2. **Price-left/Name-right** (e.g., pages 6–7): EUR prices appear at top-right, name in center-left, BGN price at right — EUR prices appear BEFORE name in sequential reading order

**Fix for layout type 2:**
- Use asymmetric x-window: `[BGN.x0 - 140, BGN.x1 + 60]` (wider to the left) to capture name words positioned left of their price column
- Use nearest previous BGN (any x) as upper vertical bound — prevents grabbing headers/promo-labels from earlier in the page
- Name extraction: collect ALL non-price Cyrillic lines regardless of order (don't break on first EUR price)

**Results:** 207 discounted items from 68 pages (up from 30)

**Pages with no products:** Pages 10 (bakery location directory), 30 (blank/footnote), 31–32 (blank), 33 (footnote only) — expected.

**Key regexes:**
```python
_BGN_RE = re.compile(r'^(\d{1,3}[.,]\d{2})\s*ЛВ\.$', re.IGNORECASE)  # word-level
_PROMO_BLOCK_RE = re.compile(r'<div[^>]*class="product-card-price-current is-promo"[^>]*>(.*?)</div>', re.DOTALL)
_EUR_RE = re.compile(r'(\d{1,3}[.,]\d{2})\s*€')
```

---

### Final Master JSON State (End of Session 3)

**File:** `bulgarian_promo_prices_merged.json`

```
Total records:  2,148
  Gladen.bg / Hit Max:  995  (all 42 pages, discounted items only)
  Kaufland:             577  (Direct, full promo catalogue)
  Billa:                349  (Direct)
  Fantastico:           207  (Direct, from PDF embedded text)
  Coca-Cola Real Magic:  20  (Glovo — actually Fantastico storefront)
```

### Files Created in Sessions 2–3

| File | Purpose |
|------|---------|
| `gladen_html_scraper.py` | Gladen.bg SSR HTML scraper — all 42 pages, run in ~15s |
| `fantastico_pdf_parser.py` | Fantastico PDF text parser — pdfplumber, column-aware |
| `gladen_scraper.py` | Old Gladen markdown parser (superseded, kept for reference) |

### Pending Work (Carry Forward)

1. **Glovo re-scrape** — Kaufland and Billa Glovo stores (after 10:00 / 09:00 EET)
   - URLs: `glovoapp.com/.../kaufland-sof?content=promotsii-pr` and `billa-sof1?content=promotsii-pr`
   - FireCrawl: `proxy="stealth"`, `waitFor=12000`
   - Expected yield: 50–200 additional promo items each

2. **Billa record count** — Verify: 349 records are from `source_channel == "Direct"` filter on `billa_products_2026-03-31.json`. The file has 971 total records — confirm whether non-Billa records in that file are valid or artifacts.

3. **XLSX analysis generation** — All sources now scraped. Build the price comparison spreadsheet per `bg_price_analysis_logic.md`.

---

*End of Session 3. Resume from "Pending Work" above.*
