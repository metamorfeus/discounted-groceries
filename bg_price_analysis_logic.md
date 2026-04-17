# Bulgarian Grocery Promo Prices — Analysis & XLSX Generation Logic

## Purpose
This document describes the complete logic for analyzing a JSON file of scraped Bulgarian grocery promotional prices and producing a formatted Excel spreadsheet. Use this as instructions for Claude Code to process any updated version of the data file.

---

## 1. INPUT FILE FORMAT

The input is a JSON array where each element is an object with these fields:

```json
{
  "source_store": "Kaufland",           // Retailer name: Kaufland, Billa, Fantastico, Coca-Cola Real Magic, Gladen.bg / Hit Max
  "source_channel": "Direct",           // "Direct" = retailer's own website, "Glovo" = via Glovo delivery platform
  "product_name": "Картофи Клас: I",    // Product description in Bulgarian (Cyrillic)
  "product_category": null,             // Category if available, often null
  "regular_price": 1.58,               // Original price in лв. (Bulgarian lev), null if not shown
  "promo_price": 0.49,                 // Promotional/sale price in лв., null if not shown
  "unit": "кг",                        // Unit of measure (кг, г, мл, л, бр, пакет, бутилка), can be null
  "price_per_unit": null,              // Price per standard unit if listed separately, often null
  "promo_period": "29.03.2026",        // Promotion validity dates as string, can be null
  "source_url": "https://...",         // URL of the page where the item was found
  "extraction_date": "2026-03-29"      // Date of extraction in YYYY-MM-DD
}
```

**Key data notes:**
- Prices are already normalized to period decimal format (2.99 not 2,99)
- Currency is always лв. (Bulgarian lev)
- Some items have only `promo_price` and no `regular_price` (especially Glovo items)
- `product_category` is populated for some sources (Glovo, Gladen) but null for others (Kaufland Direct)
- `unit` field is inconsistent — sometimes "кг", sometimes "1 кг", sometimes "700 г"

---

## 2. DATA QUALITY CHECKS (run first, print results)

Before building the spreadsheet, run these checks and print a summary:

### 2.1 Basic counts
```
- Total items in the JSON array
- Items per source_store (Counter)
- Items per source_channel (Counter)
- Items per (source_store, source_channel) combination (Counter)
```

### 2.2 Price validation
```
- Count items where BOTH promo_price AND regular_price are null → flag as "no price"
- Count items where product_name is empty or null → flag as "no name"
- Count items where both regular_price and promo_price exist → "has both prices"
- Count items where promo_price > regular_price → flag as "suspect" (promo should be lower)
```

### 2.3 Category coverage
```
- Count items per product_category value (including null)
- This shows which sources provide category data
```

### 2.4 Source URL breakdown
```
- Count items per source_url
- This confirms which pages were successfully scraped and which returned nothing
```

### 2.5 Price statistics per source
```
For each (source_store, source_channel) group, compute:
- Number of items
- Min promo_price
- Max promo_price
- Mean promo_price
- Median promo_price
```

### 2.6 Top discounts
```
For items where regular_price > 0 and promo_price is not null:
- discount_pct = 1 - (promo_price / regular_price)
- Sort descending, show top 10-15 with product name, store, regular → promo price
```

### 2.7 Identify missing/failed sites
Compare the source_urls found in the data against the expected list:
```
Expected URLs:
- https://www.kaufland.bg/aktualni-predlozheniya/oferti.html
- https://www.billa.bg/promocii/sedmichna-broshura
- https://www.fantastico.bg/special-offers
- https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof
- https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof?content=promotsii-pr
- https://glovoapp.com/bg/bg/sofia/stores/billa-sof1?content=promotsii-pr
- https://glovoapp.com/bg/bg/sofia/stores/coca-cola-real-magic-sof
- https://gladen.bg/promotions

Any expected URL not found in source_url values = failed site.
```

---

## 3. COMPUTED FIELDS (add to each item before spreadsheet generation)

For each item in the JSON array, compute:

### 3.1 Discount percentage
```python
if regular_price and promo_price and regular_price > 0:
    discount_pct = 1 - (promo_price / regular_price)  # as decimal, e.g., 0.69 = 69%
else:
    discount_pct = None
```

### 3.2 Savings amount
```python
if regular_price and promo_price:
    savings = regular_price - promo_price
else:
    savings = None
```

---

## 4. XLSX OUTPUT STRUCTURE

The output is a single .xlsx file with 3 sheets. Use openpyxl for creation.

### 4.1 Styling constants (used across all sheets)

```python
HEADER_FILL = PatternFill('solid', fgColor='1F4E79')       # Dark blue background
HEADER_FONT = Font(name='Arial', bold=True, color='FFFFFF', size=11)  # White text
DATA_FONT = Font(name='Arial', size=10)
TITLE_FONT = Font(name='Arial', bold=True, size=14, color='1F4E79')
SUBTITLE_FONT = Font(name='Arial', bold=True, size=11, color='1F4E79')
NOTE_FONT = Font(name='Arial', italic=True, size=10, color='808080')
GREEN_FONT = Font(name='Arial', bold=True, size=10, color='006100')
MONEY_FORMAT = '#,##0.00" лв."'
PCT_FORMAT = '0%'
GREEN_FILL = PatternFill('solid', fgColor='E2EFDA')         # Light green — best deals / cheapest price
YELLOW_FILL = PatternFill('solid', fgColor='FFF2CC')        # Light yellow — moderate deals / warnings
RED_FILL = PatternFill('solid', fgColor='FCE4EC')           # Light red — problems
GRAY_FILL = PatternFill('solid', fgColor='F2F2F2')          # Alternating row background
BORDER = Border(bottom=Side(style='thin', color='D9D9D9'))  # Light bottom border
```

### 4.2 Helper functions

```python
def style_header(ws, row, num_columns):
    """Apply header styling to an entire row."""
    for col in range(1, num_columns + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

def style_data_row(ws, row, num_columns, alternating=False):
    """Apply data row styling. Use alternating=True for even rows for zebra striping."""
    for col in range(1, num_columns + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = DATA_FONT
        cell.border = BORDER
        if alternating:
            cell.fill = GRAY_FILL
```

---

## 5. SHEET 1: "All Items" — Complete listing

### Structure
- Tab color: '1F4E79' (dark blue)
- Row 1: Headers (frozen, with auto-filter enabled)
- Row 2+: One row per item from the JSON

### Columns (in order)
| Col | Header | Source | Format |
|-----|--------|--------|--------|
| A | # | Row counter (1, 2, 3...) | Number |
| B | Store | source_store | Text |
| C | Channel | source_channel | Text |
| D | Product Name | product_name | Text |
| E | Category | product_category (empty string if null) | Text |
| F | Regular Price | regular_price | Money (лв.) |
| G | Promo Price | promo_price | Money (лв.) |
| H | Discount % | computed: 1 - (promo/regular) | Percentage |
| I | Savings | computed: regular - promo | Money (лв.) |
| J | Unit | unit (empty string if null) | Text |
| K | Price/Unit | price_per_unit (empty string if null) | Text |
| L | Promo Period | promo_period (empty string if null) | Text |
| M | Source URL | source_url | Text |

### Column widths
```python
[5, 18, 10, 50, 22, 14, 14, 12, 12, 12, 14, 20, 55]
```

### Conditional formatting on Discount % column (H)
```
- If discount >= 50%: GREEN_FILL background + GREEN_FONT (bold dark green)
- If discount >= 30% (but < 50%): YELLOW_FILL background
- Otherwise: no special formatting (just normal data row styling)
```
**Important**: Apply the discount formatting AFTER the alternating row styling, so the color highlights override the gray zebra stripe.

### Features
- Freeze panes at A2 (header row always visible when scrolling)
- Auto-filter on entire data range A1:M{last_row}

---

## 6. SHEET 2: "Cross-Store Comparison" — Matching products across sources

### The problem
Product names are NOT standardized across sources. The same product appears with completely different names:
- Kaufland Direct: "Верея Кисело мляко"
- Gladen.bg: "Верея краве кисело мляко 3.6% (1 кг)"
- Coca-Cola Glovo: "Мляко Прясно Верея 3% 2 л"

Exact string matching returns zero results. Fuzzy keyword matching is required.

### Fuzzy matching algorithm

#### Step 1: Normalize product names for comparison
```python
def normalize_name(name):
    """Simple normalization — strip to lowercase, remove trailing numbers+units."""
    n = name.lower().strip()
    n = re.sub(r'\s+', ' ', n)  # collapse whitespace
    n = re.sub(r'\d+\s*(г|мл|кг|л|бр)\s*$', '', n).strip()  # remove trailing "500 г" etc.
    return n
```
This is used for exact match grouping. It will find matches only when names are nearly identical.

#### Step 2: Keyword extraction for fuzzy matching
```python
def extract_keywords(name):
    """Extract meaningful keywords from a product name."""
    n = name.lower().strip()
    n = re.sub(r'[/\-–—()]', ' ', n)          # replace punctuation with spaces
    n = re.sub(r'\d+', '', n)                   # remove all numbers
    # Remove common filler words and units
    n = re.sub(r'\b(г|мл|кг|л|бр|бут|пакет|различни|видове|клас|произход|пр-д)\b', '', n)
    words = set(w for w in n.split() if len(w) > 2)  # keep only words with 3+ chars
    return words
```

#### Step 3: Find cross-store matches
```python
# Group items by (source_store, source_channel)
by_source = defaultdict(list)
for item in data:
    by_source[(item['source_store'], item['source_channel'])].append(item)

# Compare every item in one source against every item in other sources
matches = []
sources = list(by_source.keys())
for i in range(len(sources)):
    for j in range(i+1, len(sources)):
        for item_a in by_source[sources[i]]:
            kw_a = extract_keywords(item_a['product_name'])
            if len(kw_a) < 2:
                continue  # skip items with too few keywords
            for item_b in by_source[sources[j]]:
                kw_b = extract_keywords(item_b['product_name'])
                overlap = kw_a & kw_b  # set intersection
                if len(overlap) >= 2:  # at least 2 keywords in common
                    matches.append({
                        'overlap_count': len(overlap),
                        'overlap_words': overlap,
                        'item_a': item_a,
                        'item_b': item_b
                    })

# Sort by overlap count descending (more shared keywords = higher confidence match)
matches.sort(key=lambda x: -x['overlap_count'])
```

#### Step 4: Curate matches (manual review recommended)
The keyword matching produces many false positives. For example, "кашкавал от краве мляко" (kashkaval from cow milk) matches against "кисело мляко" (yogurt) because they share "краве" and "мляко". 

**Recommended approach**: Print the top 20-30 matches, manually review them, and include only genuine product matches in the spreadsheet. Look for:
- Same brand name (e.g., "Верея" appears in both)
- Same product type (e.g., both are "кисело мляко" not one yogurt and one cheese)
- Comparable sizes/units

### Sheet layout
- Tab color: '2E75B6' (medium blue)
- Row 1: Title — "Cross-Store Price Comparison" (merged across columns, TITLE_FONT)
- Row 2: Subtitle/note (merged, NOTE_FONT italic gray) explaining the matching methodology
- Row 3: blank spacer
- Row 4: Column headers (styled with style_header)
- Row 5+: Data rows (frozen panes at A5)

### Columns
| Col | Header | Content | Format |
|-----|--------|---------|--------|
| A | Product Name | "Product A ↔ Product B" (both names joined with ↔) | Text |
| B | Store 1 | source_store of cheaper item | Text |
| C | Channel 1 | source_channel of cheaper item | Text |
| D | Price 1 | promo_price (or regular_price) of item 1 | Money |
| E | Store 2 | source_store of other item | Text |
| F | Channel 2 | source_channel of other item | Text |
| G | Price 2 | promo_price (or regular_price) of item 2 | Money |
| H | Price Diff | abs(price2 - price1) | Money |
| I | Cheaper At | "StoreName (Channel)" of the cheaper item | Text |

### Column widths
```python
[45, 18, 10, 14, 18, 10, 14, 14, 30]
```

### Conditional formatting
- The cell with the LOWER price (D or G) gets GREEN_FILL background
- Price diff column (H) formatted as money

### Footer note
After the last data row, add a merged note row (span A:I) in NOTE_FONT:
"⚠ Cross-store comparison is limited because [list missing stores] returned no data, and product naming differs between platforms."

---

## 7. SHEET 3: "Summary" — Dashboard overview

### Tab color: '00B050' (green)

### Layout (top to bottom)

#### Section A: Title block (rows 1-2)
- Row 1: "Bulgarian Grocery Promo Prices — Summary" (merged A1:F1, TITLE_FONT)
- Row 2: "Extraction: {extraction_date} | Total Items: {count}" (merged A2:F2, SUBTITLE_FONT)

#### Section B: Coverage table (rows 4+)
- Row 4: Section title "Coverage by Store & Channel" (SUBTITLE_FONT)
- Row 5: Headers
- Row 6+: One row per (source_store, source_channel) group, sorted by item count descending

| Col | Header | Value | Format |
|-----|--------|-------|--------|
| A | Store | source_store | Text |
| B | Channel | source_channel | Text |
| C | Items | count of items in this group | Number |
| D | Avg Promo Price | mean of promo_price values | Money |
| E | Min Price | minimum promo_price | Money |
| F | Max Price | maximum promo_price | Money |

#### Section C: Missing/failed sites (after coverage table + 1 blank row)
- Section title: "Sites With No Data Returned" (SUBTITLE_FONT, RED_FILL background on the title cell)
- Headers: Store, Channel, URL, Likely Reason
- One row per missing site
- "Likely Reason" column cells get YELLOW_FILL background

Determine missing sites by comparing expected URLs against actual source_urls in the data:
```python
expected_urls = [
    ("Kaufland", "Direct", "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html"),
    ("Billa", "Direct", "https://www.billa.bg/promocii/sedmichna-broshura"),
    ("Fantastico", "Direct", "https://www.fantastico.bg/special-offers"),
    ("Kaufland", "Glovo", "https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof"),
    ("Kaufland", "Glovo (Promos)", "https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof?content=promotsii-pr"),
    ("Billa", "Glovo", "https://glovoapp.com/bg/bg/sofia/stores/billa-sof1?content=promotsii-pr"),
    ("Coca-Cola Real Magic", "Glovo", "https://glovoapp.com/bg/bg/sofia/stores/coca-cola-real-magic-sof"),
    ("Gladen.bg", "Direct", "https://gladen.bg/promotions"),
]
# Check which expected URLs have zero items in the data
actual_urls = set(item['source_url'] for item in data)
missing = [(s, c, u) for s, c, u in expected_urls if u not in actual_urls]
```

For each missing site, provide a likely reason:
- billa.bg → "Embedded PDF flipbook — no structured HTML"
- Glovo SPA pages → "SPA content did not render for FireCrawl"
- fantastico.bg → "No structured data extracted"
- Glovo promo filter pages → "Promo filter parameter may not have rendered"

#### Section D: Top 15 biggest discounts (after missing sites + 1 blank row)
- Section title: "Top 15 Biggest Discounts" (SUBTITLE_FONT)
- Headers: Product, Store, Regular Price, Promo Price, Discount %, You Save

```python
# Compute and sort
discounts = []
for item in data:
    reg = item.get('regular_price')
    promo = item.get('promo_price')
    if reg and promo and reg > 0:
        discounts.append((1 - promo/reg, item))
discounts.sort(reverse=True, key=lambda x: x[0])
# Take top 15
```

| Col | Header | Value | Format |
|-----|--------|-------|--------|
| A | Product | product_name | Text |
| B | Store | source_store | Text |
| C | Regular Price | regular_price | Money |
| D | Promo Price | promo_price | Money |
| E | Discount % | computed discount as decimal | Percentage, GREEN_FILL + GREEN_FONT |
| F | You Save | regular_price - promo_price | Money |

### Column widths for Summary sheet
```python
[45, 20, 14, 14, 12, 14]
```

---

## 8. FINAL STEPS

### 8.1 Save the workbook
```python
wb.save('/home/claude/bg_promo_prices_YYYY-MM-DD.xlsx')
```
Use the extraction_date from the JSON data for the filename.

### 8.2 Copy to outputs
```bash
cp /home/claude/bg_promo_prices_YYYY-MM-DD.xlsx /mnt/user-data/outputs/
```

### 8.3 No formula recalculation needed
This spreadsheet uses only hardcoded values (no Excel formulas), so the recalc.py step is not required. All calculations (discount %, savings) are computed in Python and written as values.

---

## 9. PYTHON DEPENDENCIES

```
openpyxl    — spreadsheet creation and formatting
json        — reading the input file
re          — regex for product name normalization
statistics  — mean, median calculations
collections — Counter, defaultdict for grouping
```

All are standard library except openpyxl (pre-installed in Claude Code environments).

---

## 10. QUICK REFERENCE — RUNNING THE ANALYSIS

When given an updated JSON file, the full workflow is:

1. **Load** the JSON file
2. **Run data quality checks** (Section 2) — print summary to console
3. **Compute derived fields** (Section 3) — discount %, savings
4. **Build Sheet 1** "All Items" (Section 5) — all items with formatting and conditional highlighting
5. **Run fuzzy matching** (Section 6) — find cross-store product matches
6. **Review matches** — manually check top 20-30, keep only genuine matches
7. **Build Sheet 2** "Cross-Store Comparison" (Section 6) — curated matches with price comparison
8. **Build Sheet 3** "Summary" (Section 7) — coverage, missing sites, top deals
9. **Save and present** the .xlsx file (Section 8)

Total expected runtime: under 10 seconds for 600-1000 items.
