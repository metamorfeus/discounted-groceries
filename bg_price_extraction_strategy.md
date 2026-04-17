# Bulgarian Grocery Price Extraction — Strategy & Cowork Prompt

## Extraction Strategy

### Site Classification & Approach

| # | Site | Source Type | Expected Data Format | Difficulty |
|---|------|-----------|---------------------|------------|
| 1 | Glovo → Billa (promotions) | Delivery platform | JS-rendered product cards with prices | Medium-High (SPA) |
| 2 | Glovo → Coca-Cola Real Magic | Delivery platform (brand store) | JS-rendered product cards | Medium-High (SPA) |
| 3 | Glovo → Kaufland | Delivery platform | JS-rendered product cards | Medium-High (SPA) |
| 4 | Glovo → Kaufland (promotions) | Delivery platform | JS-rendered promo cards | Medium-High (SPA) |
| 5 | gladen.bg/promotions | Promo aggregator | Likely scanned flyer images OR structured HTML | High (may need OCR) |
| 6 | billa.bg weekly brochure | Retailer direct | May be embedded PDF/flipbook or HTML items | Medium |
| 7 | kaufland.bg offers | Retailer direct | Structured HTML product listings | Low-Medium |
| 8 | fantastico.bg special offers | Retailer direct | Structured HTML product listings | Low-Medium |

### Key Challenges

1. **Glovo is a Single Page App (SPA)** — pages load via JavaScript. FireCrawl needs to render JS before extracting. Use `scrape` with `waitFor` if available.
2. **Bulgarian language** — all content is in Bulgarian (Cyrillic). Product names, units (кг, бр, л), currency (лв.) must be preserved.
3. **Price formats** — Bulgarian sites use comma as decimal separator (e.g., "2,99 лв." or "2.99 лв."). Some show old price + new price for promotions.
4. **gladen.bg** — may show flyer images instead of structured data. If FireCrawl returns only images/no text prices, skip it.
5. **Pagination** — some sites may paginate promotional items. FireCrawl's `crawl` mode may be needed for multi-page listings.

### Data Schema (Target Output)

Each extracted item should have:
- **source_store** — Billa, Kaufland, Fantastico, Coca-Cola Real Magic
- **source_channel** — "Glovo" or "Direct" (physical store website)
- **product_name** — item description in Bulgarian
- **product_category** — if available (e.g., Месо, Млечни, Напитки)
- **regular_price** — original price if shown (лв.)
- **promo_price** — sale/promotional price (лв.)
- **unit** — кг, бр, л, пакет, etc.
- **price_per_unit** — if listed (e.g., 3.99 лв./кг)
- **promo_period** — valid from/to dates if shown
- **source_url** — the exact page URL where item was found
- **extraction_date** — timestamp of extraction

---

## Cowork Prompt (Copy this into Claude Cowork)

---

### PROMPT START

```
You are extracting grocery promotional prices from Bulgarian websites using the FireCrawl MCP browser tool. Stay logged into FireCrawl throughout this entire session — do not disconnect between tasks.

## YOUR MISSION

Extract ALL promotional/sale items with their prices and descriptions from the sites listed below. For each item you extract, capture these fields:

- source_store: The retailer name (Billa, Kaufland, Fantastico, or Coca-Cola Real Magic)
- source_channel: "Glovo" if from glovoapp.com, "Direct" if from the retailer's own website
- product_name: The item description in Bulgarian exactly as shown on the page
- product_category: Category if visible on the page (e.g., Месо, Млечни продукти, Напитки, Плодове и зеленчуци)
- regular_price: The original/old price in лв. (if shown). Use the number only, e.g., 5.99
- promo_price: The promotional/sale price in лв. Use the number only, e.g., 3.49
- unit: The unit of measure (кг, бр, л, мл, г, пакет, бутилка, etc.)
- price_per_unit: Price per kg/liter if shown separately
- promo_period: The promotion validity dates if shown (e.g., "24.03 - 30.03.2026")
- source_url: The exact URL of the page where this item was found
- extraction_date: Today's date in YYYY-MM-DD format

## IMPORTANT RULES

1. STAY CONNECTED to FireCrawl MCP for the entire session. Do not disconnect between sites.
2. After extracting data from each site, VERIFY the results by checking that:
   - Each item has BOTH a product description AND a price (at minimum promo_price)
   - Prices are numeric values in лв. (Bulgarian lev), not placeholder text
   - Product names are actual products, not navigation labels or category headers
   - If a site returns no valid price+description pairs, report it as "NO STRUCTURED DATA FOUND" and move on
3. Bulgarian price format: prices may use comma (2,99) or period (2.99) as decimal separator. Normalize all to period format (2.99) in your output.
4. For Glovo sites: these are Single Page Applications. Use FireCrawl's JavaScript rendering / wait capabilities to ensure the page content loads fully before extracting.
5. For each site, report how many valid items you extracted before moving to the next site.

## SITES TO SCRAPE (in this order)

### GROUP 1 — Direct Retailer Sites (physical stores, likely easiest)

**Site 1: Kaufland Bulgaria — Current Offers**
URL: https://www.kaufland.bg/aktualni-predlozheniya/oferti.html
Store: Kaufland
Channel: Direct
Notes: Look for structured product listings with prices. May have sub-pages or tabs for different weeks.

**Site 2: Billa Bulgaria — Weekly Brochure**
URL: https://www.billa.bg/promocii/sedmichna-broshura
Store: Billa
Channel: Direct
Notes: May be an embedded flipbook/PDF viewer or HTML product cards. If it's an embedded PDF/iframe with no extractable text, note that and try to find alternative product listing pages on billa.bg.

**Site 3: Fantastico — Special Offers**
URL: https://www.fantastico.bg/special-offers
Store: Fantastico
Channel: Direct
Notes: Should have structured HTML listings.

### GROUP 2 — Glovo Delivery Platform

**Site 4: Kaufland via Glovo (Promotions)**
URL: https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof?content=promotsii-pr
Store: Kaufland
Channel: Glovo
Notes: SPA — ensure JavaScript renders fully. This is the PROMOTIONS filtered view. Prices here may differ from direct store prices.

**Site 5: Kaufland via Glovo (General)**
URL: https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof
Store: Kaufland
Channel: Glovo
Notes: General store page. Extract any visible promotional items.

**Site 6: Billa via Glovo (Promotions)**
URL: https://glovoapp.com/bg/bg/sofia/stores/billa-sof1?content=promotsii-pr
Store: Billa
Channel: Glovo
Notes: Promotions filtered view on Glovo.

**Site 7: Coca-Cola Real Magic via Glovo**
URL: https://glovoapp.com/bg/bg/sofia/stores/coca-cola-real-magic-sof
Store: Coca-Cola Real Magic
Channel: Glovo
Notes: Branded promotional storefront. May have limited items.

### GROUP 3 — Aggregator (attempt, may fail)

**Site 8: Gladen.bg — Promotions**
URL: https://gladen.bg/promotions
Store: Multiple (aggregator)
Channel: Direct
Notes: This site aggregates flyers from multiple stores. Content MAY be scanned images rather than structured text. Attempt extraction — if the page only returns image URLs with no text prices, report "NO STRUCTURED DATA — site uses scanned flyer images" and skip.

## OUTPUT FORMAT

After processing ALL sites, compile the results into a single structured dataset. Present it as a JSON array where each item is an object with the fields listed above.

Example item:
{
  "source_store": "Kaufland",
  "source_channel": "Direct",
  "product_name": "Пилешко филе",
  "product_category": "Месо",
  "regular_price": 12.99,
  "promo_price": 8.99,
  "unit": "кг",
  "price_per_unit": "8.99 лв./кг",
  "promo_period": "24.03 - 30.03.2026",
  "source_url": "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html",
  "extraction_date": "2026-03-29"
}

If a field is not available on the page, use null.

## FINAL VERIFICATION STEP

After all extractions are complete, review the full dataset and:
1. Remove any duplicate items (same product, same store, same channel, same price)
2. Flag any items where promo_price is HIGHER than regular_price (likely a data error)
3. Report a summary: total items per store, total items per channel (Glovo vs Direct), and any sites that failed or returned no data
4. Present the final clean JSON dataset ready for spreadsheet conversion
```

### PROMPT END

---

## Post-Extraction: Converting to XLSX

Once Cowork returns the JSON data, bring it back to this Claude chat and I will:
1. Parse the JSON into a structured spreadsheet
2. Create sheets: "All Items", "Price Comparison" (matching items across stores), and "Summary"
3. Add conditional formatting to highlight lowest prices
4. Output as a downloadable .xlsx file
