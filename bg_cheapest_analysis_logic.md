# Bulgarian Grocery Prices — Cheapest by Category Analysis Logic

## Purpose
This document describes the complete end-to-end logic for taking a JSON file of scraped Bulgarian grocery promotional prices and producing an Excel spreadsheet that groups products into comparable categories and identifies the cheapest option in each category using normalized per-kg/per-liter pricing.

Feed this document to Claude Code along with a source JSON file to reproduce or update the analysis.

---

## TABLE OF CONTENTS

1. Input File Format
2. Three-Step Processing Pipeline (overview)
3. Step 1: Unit Parsing & Price Normalization
4. Step 2: Product Categorization
5. Step 3: Grouping, Ranking & Report Generation
6. XLSX Output Structure (4 sheets)
7. Manual Override Table for Unclassified Items
8. Edge Cases & Known Issues
9. Python Dependencies
10. Execution Checklist

---

## 1. INPUT FILE FORMAT

The input is a JSON array. Each element represents one scraped promotional item:

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
  "source_url": "https://www.kaufland.bg/...",
  "extraction_date": "2026-03-29"
}
```

### Key data characteristics

- **Language**: All product names are in Bulgarian (Cyrillic script)
- **Currency**: лв. (Bulgarian lev), decimal separator is period (2.99)
- **unit field**: Wildly inconsistent — 126+ unique formats including "кг", "1 кг", "500 г", "2 л", "750мл", "3x300 г", "10 бр.", null. This is the hardest problem.
- **product_category**: Null for ~90% of items. Cannot be relied upon.
- **regular_price**: Original/old price. Null for some items (especially Glovo).
- **promo_price**: Sale price. Almost always present.
- **source_store**: Retailer name — "Kaufland", "Billa", "Fantastico", "Coca-Cola Real Magic", "Gladen.bg / Hit Max"
- **source_channel**: "Direct" (retailer website) or "Glovo" (delivery platform, prices may differ)

---

## 2. THREE-STEP PROCESSING PIPELINE

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  STEP 1      │     │  STEP 2          │     │  STEP 3             │
│  Parse units │ ──► │  Classify into   │ ──► │  Group, normalize,  │
│  from messy  │     │  categories via  │     │  rank cheapest per  │
│  unit field  │     │  keyword rules   │     │  subcategory         │
└──────────────┘     └──────────────────┘     └─────────────────────┘
```

Each item gets enriched with:
- `parsed_qty` + `base_unit` (from Step 1)
- `category` + `subcategory` (from Step 2)
- `norm_price` + `norm_unit` (from Step 3)

---

## 3. STEP 1: UNIT PARSING & PRICE NORMALIZATION

### 3.1 The Problem

The `unit` field contains 126+ different formats. Examples from real data:

| Raw unit value | Meaning |
|---|---|
| `кг` | Price is per kilogram (standalone) |
| `1 кг` | Package is 1 kilogram |
| `500 г` | Package is 500 grams |
| `400г` | Package is 400 grams (no space) |
| `2 л` | Package is 2 liters |
| `750мл` | Package is 750 milliliters (no space) |
| `750 мл` | Package is 750 milliliters |
| `3x300 г` | Multipack: 3 × 300g = 900g total |
| `10 бр.` | 10 pieces |
| `10 бр` | 10 pieces (no period) |
| `бр.` | 1 piece (no number) |
| `1.5 л` | 1.5 liters |
| `null` | No unit specified |

### 3.2 The Parser Function

```python
import re

def parse_unit(unit_str, product_name=""):
    """
    Parse the unit field into (quantity_in_base_unit, base_unit).
    Falls back to extracting from product_name if unit_str is null/empty.
    
    Returns:
        (quantity, base_unit) where:
        - base_unit: 'g' (grams), 'ml' (milliliters), 'pcs' (pieces)
        - quantity: total amount in the base unit
        
    Returns (None, None) if unparseable.
    
    Special case: standalone "кг" (no number) means the listed price
    IS the per-kg price. We set qty=1000g so the math works out:
    price_per_kg = (price / 1000) * 1000 = price.
    """
    s = (unit_str or product_name or "").strip().lower()
    if not s:
        return None, None
    
    try:
        # ── Rule 1: Standalone "кг" = price is per kilogram ──
        if s == 'кг':
            return 1000, 'g'
        
        # ── Rule 2: Multipack "NxN г/мл" ──
        m = re.search(r'(\d+)\s*x\s*(\d+)\s*(г|мл)', s)
        if m:
            total = int(m.group(1)) * int(m.group(2))
            return (total, 'g') if m.group(3) == 'г' else (total, 'ml')
        
        # ── Rule 3: Kilograms "N кг" ──
        # Matches: "1 кг", "1.5 кг", "0,5 кг"
        m = re.search(r'([\d]+[.,]?[\d]*)\s*кг', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val * 1000, 'g'
        
        # ── Rule 4: Grams "N г" ──
        # Matches: "500 г", "400г"
        # Uses negative lookahead (?!р) to avoid matching "гр" 
        m = re.search(r'([\d]+[.,]?[\d]*)\s*г(?!р)', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val, 'g'
        
        # ── Rule 5: Liters "N л" ──
        # Matches: "1 л", "2 л", "1.5 л", "3 л"
        # Uses negative lookahead (?!в) to avoid matching "лв" (currency)
        m = re.search(r'([\d]+[.,]?[\d]*)\s*л(?!в)', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val * 1000, 'ml'
        
        # ── Rule 6: Milliliters "N мл" ──
        # Matches: "500 мл", "750мл"
        m = re.search(r'([\d]+[.,]?[\d]*)\s*мл', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val, 'ml'
        
        # ── Rule 7: Pieces with number "N бр" ──
        # Matches: "10 бр.", "6 бр", "10 бр"
        m = re.search(r'([\d]+[.,]?[\d]*)\s*бр', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val, 'pcs'
        
        # ── Rule 8: Standalone pieces "бр." ──
        if 'бр' in s:
            return 1, 'pcs'
    
    except (ValueError, AttributeError):
        pass
    
    return None, None
```

### 3.3 Rule Order Matters

The rules are checked in sequence — first match wins. This ordering prevents conflicts:
- "кг" is checked before the general gram regex (Rule 1 before Rule 4)
- Multipack "3x300 г" is checked before single gram (Rule 2 before Rule 4)
- "л" uses `(?!в)` to avoid matching "лв" (Bulgarian lev currency)
- "г" uses `(?!р)` to avoid matching "гр" (though this is rarely an issue)

### 3.4 The Fallback: Product Name Extraction

When `unit` is null (160+ items), the parser tries the `product_name` field. This catches cases like:
- Product: "Верея краве кисело мляко 3.6% (1 кг)" → unit=null but name contains "1 кг"
- Product: "Листото спанак листа (400 г)" → unit=null but name contains "400 г"

This is why the function takes both `unit_str` and `product_name` parameters.

### 3.5 Normalized Price Calculation

Once we have (quantity, base_unit), we compute the normalized price:

```python
price = item.get('promo_price') or item.get('regular_price')
qty, base = parse_unit(item.get('unit'), item.get('product_name', ''))

if price and qty and qty > 0:
    if base == 'g':
        norm_price = round((price / qty) * 1000, 2)  # лв. per kilogram
        norm_unit = 'лв./кг'
    elif base == 'ml':
        norm_price = round((price / qty) * 1000, 2)  # лв. per liter
        norm_unit = 'лв./л'
    elif base == 'pcs':
        norm_price = round(price / qty, 2)            # лв. per piece
        norm_unit = 'лв./бр'
```

### 3.6 Coverage

From the 2026-03-29 dataset (622 items):
- **293 items** → grams (47%) — dairy, meat, snacks, bread
- **120 items** → milliliters (19%) — beverages, cleaning products
- **49 items** → pieces (8%) — eggs, trash bags
- **160 items** → unparseable (26%) — mostly null units on non-food items

The 462 parseable items cover all core grocery categories.

---

## 4. STEP 2: PRODUCT CATEGORIZATION

### 4.1 Why Keyword-Based Classification

The `product_category` field is null for ~90% of items. Product names are all in Bulgarian and follow no standard format. Classification must be done by scanning product names for Bulgarian keywords.

### 4.2 Architecture: Priority-Layered Rules

Each rule is a tuple: `(category, subcategory, include_patterns, exclude_patterns)`

- **include_patterns**: List of regex patterns. If ANY matches the lowercased product name, the rule fires.
- **exclude_patterns**: List of regex patterns. If ANY matches, the rule is BLOCKED even if includes match.
- **First matching rule wins** — rule ORDER is critical.

```python
def classify(name):
    """Returns (category, subcategory) for a product name."""
    nl = name.lower()
    for cat, sub, incs, excs in RULES:
        # Check exclusions first — any exclusion blocks the rule
        if any(re.search(e, nl) for e in excs):
            continue
        # Check inclusions — any inclusion triggers the rule
        if any(re.search(i, nl) for i in incs):
            return cat, sub
    return "Некласифицирани", "Некласифицирани"
```

### 4.3 The Layer Architecture (Why Order Matters)

Bulgarian product names contain "misleading" food keywords inside non-food items. Without careful ordering, a cleaning product gets classified as food:

| Product | False Match | Why |
|---------|-------------|-----|
| "Frosch препарат малина с **оцет**" | Оцет/Подправки | "оцет" = vinegar |
| "Medix Обезмаслител **портокал**" | Плодове | "портокал" = orange |
| "**Тракия** Бутертесто" | Спиртни напитки | contains "ракия" substring |
| "Glade **аром.** гел за баня" | Спиртни напитки | "аром" contains "ром" (rum) |
| "Fino **Аром.** торби за смет" | Спиртни напитки | same "ром" false match |
| "K-Bio Паста **без яйца**" | Яйца | contains "яйца" |
| "Freshko Смути **ябълка, банан**" | Плодове | contains fruit words |
| "K-Classic Филтри за **вода**" | Вода (напитки) | contains "вода" |
| "Закуска с **гауда**" | Кашкавал | contains cheese word |

**Solution**: Rules are organized into priority layers:

```
LAYER 0: BRAND ANCHORS (override everything)
    If name contains "Frosch"/"Medix"/"Meglio" → Household/Cleaning
    If name contains "Glade" → Household/Air Fresheners
    If name contains "Garnier"/"SYOSS"/"Batiste" → Cosmetics/Hair
    If name contains "L'Oreal"/"L'Oréal"/"Revitalift" → Cosmetics/Face
    If name contains "Gillette" → Cosmetics/Shaving
    If name contains "K-Carinura"/"Dante" → Pet Food

LAYER 1: HOUSEHOLD (checked before any food rules)
    Trash bags, toilet paper, cleaning products, air fresheners
    These often contain food-adjacent words (оцет, портокал, лимон, аром)

LAYER 1.5: COSMETICS (checked before food)
    Shampoo, face cream, shaving — some contain "мляко" (milk)

LAYER 2: FOOD CATEGORIES
    Dairy, Eggs, Meat, Deli, Fish, Produce, Bread, Cooking Staples, Prepared Foods

LAYER 3: BEVERAGES
    Beer, Wine, Spirits (with careful exclusions for "аром" and "Тракия"),
    Soft drinks, Juices, Tea, Coffee, Water

LAYER 4: SWEETS & SNACKS
    Chocolate, Biscuits/Wafers, Chips, Cakes, Ice cream, Baking decorations

LAYER 5: HOME & GARDEN, OTHER
    Garden supplies, Kitchen equipment, Toys, Art supplies, Water filters, Tools

LAYER 6: CATCH-ALL
    "Некласифицирани" (Unclassified)
```

### 4.4 Complete Rules Table

The rules below are listed in EXACT execution order. First match wins.

#### LAYER 0 — Brand Anchors

```python
# Cleaning brands → always Household
("Домакински", "Перилни/Почистващи",
 [r'\bfrosch\b', r'\bmedix\b', r'\bmeglio\b'],
 [r'ароматизатор']),

# Air freshener brand → always Household
("Домакински", "Ароматизатори",
 [r'\bglade\b'],
 []),

# Hair care brands → always Cosmetics (when combined with product keywords)
("Козметика и хигиена", "Шампоан/Коса",
 [r'\bgarnier\b.*(?:шамп|балсам|маска|therapy)', r'\bsyoss\b', r'\bbatiste\b',
  r'\bhair vege\b', r'\bnivea\b.*шамп', r'\bwash.*go\b'],
 []),

# Face care brands → always Cosmetics
("Козметика и хигиена", "Крем за лице",
 [r"l'oreal", r"l'oréal", r'\brevitalift\b'],
 [r'шамп', r'коса']),

# Shaving brand → always Cosmetics
("Козметика и хигиена", "Бръснене",
 [r'\bgillette\b'],
 []),

# Pet food brands
("Домашни любимци", "Храна за животни",
 [r'k-carinura', r'\bdante\b.*куч', r'храна за куч', r'храна за кот',
  r'лакомство за куч', r'стикове за куч', r'пастет за куч', r'пастет за кот'],
 []),
```

#### LAYER 1 — Household

```python
("Домакински", "Торби за смет",
 [r'торби за смет', r'торбички.*смет', r'чували за смет',
  r'торби за отпадъци', r'торбички тип потник', r'торби за тежки отпадъци'],
 []),

("Домакински", "Тоалетна хартия",
 [r'тоалетна хартия'],
 []),

("Домакински", "Кухненска ролка",
 [r'кухненска ролка'],
 []),

("Домакински", "Салфетки",
 [r'\bсалфетки\b'],
 []),

("Домакински", "Перилни/Почистващи",
 [r'препарат', r'обезмаслител', r'гел за пране', r'прах за пране', r'омекотител',
  r'таблетки.*съдомиялн', r'гел.*съдомиялн', r'сол за съдомиялн',
  r'дезинфeк', r'wc блокче', r'wc гел', r'wc аромат', r'хигиенен спрей',
  r'против петна'],
 []),

("Домакински", "Ароматизатори",
 [r'ароматизатор'],
 []),

("Домакински", "Дамски превръзки",
 [r'дамски превръзки'],
 []),
```

#### LAYER 1.5 — Cosmetics (before food keywords like "мляко")

```python
("Козметика и хигиена", "Шампоан/Коса",
 [r'шампоан', r'балсам.*коса', r'маска за коса', r'серум за коса',
  r'спрей за корени', r'боя за коса', r'сух шампоан', r'\bolia\b', r'creme supreme'],
 []),

("Козметика и хигиена", "Крем за лице",
 [r'крем за лице', r'серум.*лице', r'флуид.*лице', r'age specialist',
  r'hyaluron', r'bright reveal'],
 []),

("Козметика и хигиена", "Бръснене",
 [r'бръсн', r'самобръсначка'],
 []),

("Козметика и хигиена", "Душ гел/Сапун",
 [r'душ гел', r'течен сапун', r'\bteo\b.*rich', r'\btreaclemoon\b', r'\bziaja\b'],
 []),
```

#### LAYER 2 — Food Categories

```python
# ── Dairy ──
("Млечни продукти", "Прясно мляко",
 [r'прясно мляко', r'адаптирано мляко'],
 [r'кисело', r'цедено', r'кокосово']),

("Млечни продукти", "Кисело мляко",
 [r'кисело мляко', r'ацидофилно.*мляко', r'пробиотично.*мляко'],
 []),

("Млечни продукти", "Цедено мляко",
 [r'цедено.*мляко'],
 []),

("Млечни продукти", "Сирене",
 [r'\bсирене\b', r'\bмоцарела\b', r'\bbrimi\b', r'\bphiladelphia\b',
  r'крема сирене', r'котидж', r'\bбри\b', r'синьо сирене'],
 [r'панирани.*сиренца']),

("Млечни продукти", "Кашкавал",
 [r'\bкашкавал\b', r'\bементал\b', r'\bгауда\b.*(?:слайс|300)'],
 []),
# Note: "гауда" is restricted to "гауда слайс" or "гауда 300" to prevent
# matching "Закуска с гауда" which is a bakery item, not cheese

("Млечни продукти", "Масло (краве)",
 [r'масло краве', r'markenbutter'],
 [r'маслиново', r'олио']),

("Млечни продукти", "Сметана/Извара",
 [r'заквасена сметана', r'\bизвара\b', r'крем за разбиване'],
 []),

("Млечни продукти", "Млечни напитки/десерти",
 [r'млечна напитка', r'млечен десерт', r'протеинов йогурт'],
 []),

# ── Eggs ──
("Яйца", "Яйца",
 [r'\bяйца\b', r'\bбиояйца\b'],
 [r'без яйца']),
# CRITICAL: "без яйца" exclusion prevents "K-Bio Паста без яйца" from matching

# ── Meat ──
("Месо", "Пилешко",
 [r'пилеш', r'пиле\b', r'\bfragedo\b', r'la provincia.*пилеш',
  r'царевично пиле', r'frangosul.*пилеш'],
 [r'кренвирш']),
# Exclusion: chicken frankfurters go to Deli, not raw meat

("Месо", "Свинско",
 [r'свинск'],
 [r'салам', r'шунка', r'наденица', r'кренвирш', r'шпек', r'бекон']),
# Exclusion: processed pork products go to Deli

("Месо", "Телешко",
 [r'телеш'],
 [r'шкембе']),

("Месо", "Кайма",
 [r'\bкайма\b'],
 []),

("Месо", "Шкембе",
 [r'\bшкембе\b'],
 []),

# ── Deli (Колбаси) ──
("Колбаси и деликатеси", "Шунка",
 [r'\bшунка\b', r'\bпастърма\b'],
 []),

("Колбаси и деликатеси", "Салам/Колбас",
 [r'\bсалам\b', r'\bколбас\b', r'\bсуджук\b', r'\bлуканка\b', r'\bсушеник\b',
  r'\bнаденица\b', r'\bдебърцини\b', r'\bкренвирш\b', r'\bшпек\b', r'\bбекон\b',
  r'\bмезе\b', r'\bфуетек\b', r'кълцано карначе',
  r'\bпастет\b(?!.*куч)(?!.*кот)'],
 []),
# Note: "пастет" excludes pet food variants via negative lookahead

# ── Fish ──
("Риба и морски дарове", "Риба",
 [r'\bриб', r'\bсьомг', r'\bскумрия\b', r'\bпъстърв', r'\bсельод', r'\bхайвер\b',
  r'\bсуши\b', r'\bмиди\b', r'\bсурими\b', r'\bocean\b', r'\bmowi\b',
  r'филе панирано'],
 []),

# ── Produce ──
("Плодове", "Плодове",
 [r'\bбанан', r'\bябълк', r'\bягоди\b', r'\bгрозде\b', r'\bкруш',
  r'\bпортокал', r'\bлимон(?!ад)', r'\bлимет', r'\bкиви\b', r'\bборовинк',
  r'\bананас\b', r'\bкестен', r'\bсливи\b', r'\bфурми\b'],
 [r'сок', r'нектар', r'смути', r'препарат', r'обезмаслител',
  r'чипс', r'вино', r'сайдер']),
# Exclusions prevent juice, cleaning products, and chips from matching

("Зеленчуци", "Зеленчуци",
 [r'\bкартоф', r'\bдомат', r'\bкраставиц', r'\bчушк', r'\bлук\b',
  r'\bчесън\b', r'\bтиквичк', r'\bкопфсалат', r'салата.*фризе',
  r'салата.*бон тон', r'\bспанак\b', r'\bгъби\b', r'\bцелина\b',
  r'\bрепичк', r'\bпащърнак\b', r'\bмаслин'],
 [r'чипс', r'салата снежанка', r'руска салата', r'кьопо',
  r'лютеница', r'печена капия', r'препарат']),
# Exclusions: prepared salads go to "Готови храни", not vegetables

# ── Bread & Bakery ──
("Хляб и тестени", "Хляб",
 [r'\bхляб\b', r'\bбагет\b', r'\bземел\b', r'\bсомун\b', r'\bбиохляб\b'],
 []),

("Хляб и тестени", "Козунак",
 [r'\bкозунак\b', r'козуначен', r'\bcolomba\b'],
 []),

("Хляб и тестени", "Кроасан/Кифли",
 [r'\bкроасан\b', r'\bкифлич', r'\bпоничк', r'\bдонът\b', r'\bеклер\b'],
 []),

("Хляб и тестени", "Тесто/Кори",
 [r'\bтесто\b', r'\bкори\b', r'бутертесто', r'точени'],
 []),

# ── Cooking Staples ──
("Основни хранителни", "Захар",
 [r'\bзахар\b'],
 [r'декорация', r'захарна']),

("Основни хранителни", "Брашно",
 [r'\bбрашно\b', r'\bнишесте\b', r'овесени трици'],
 []),

("Основни хранителни", "Олио",
 [r'\bолио\b', r'слънчогледово'],
 [r'маслиново']),

("Основни хранителни", "Маслиново масло",
 [r'маслиново масло', r'\bbertolli\b', r"costa d.oro"],
 []),

("Основни хранителни", "Ориз/Булгур/Бобови",
 [r'\bориз\b', r'\bбулгур\b', r'\bбоб\b', r'зелен грах', r'сладка царевица'],
 [r'манастирски']),
# Exclusion: "боб по манастирски" is a prepared dish

("Основни хранителни", "Паста/Макарони",
 [r'\bпаста\b(?!.*зъби)', r'макаронени'],
 [r'без яйца']),

("Основни хранителни", "Оцет/Подправки",
 [r'\bкетчуп\b', r'доматено пюре', r'сода бикарбонат'],
 []),
# Note: generic "оцет" is NOT included here because it false-matches cleaning products.
# Only specific condiment products are listed.

# ── Prepared Foods ──
("Готови храни", "Готови храни",
 [r'\bкюфтет', r'\bбургер\b', r'\bпуканки\b', r'крем супа', r'\bкебап\b',
  r'супа топчета', r'\bпанирани\b', r'\bхумус\b', r'\bлютеница\b',
  r'\bкьопо', r'\bкатък\b', r'боб по манастирски', r'печена капия',
  r'руска салата', r'салата снежанка', r'салата северняшка',
  r'минибанички', r'\bмекици\b', r'\bпица\b', r'\bгюбек\b',
  r'продукт за мазане', r'\bзакуска с\b'],
 []),
```

#### LAYER 3 — Beverages

```python
("Напитки", "Бира",
 [r'\bбира\b', r'\bсайдер\b', r'\bheineken\b', r'\bcorona\b', r'\bstaropramen\b',
  r'\bamstel\b', r'\bpaulaner\b', r'\btuborg\b', r'\bзагорка\b', r'\bкаменица\b',
  r'\bариана\b', r'\bпиринско\b', r'\bшуменско\b', r'\bбургаско\b',
  r'\bвитошко\b', r'\bболярка\b', r'\bradeberger\b', r'\bschofferhofer\b',
  r'\bsomersby\b', r'\bcorsendonk\b', r'\btemplier\b'],
 []),

("Напитки", "Вино",
 [r'\bвино\b', r'\bрозе\b(?!.*шоколад)', r'пино гриджо'],
 []),

("Напитки", "Спиртни напитки",
 [r'\bводка\b', r'\bуиски\b', r'\bузо\b', r'\bгроздова\b',
  r'zacapa.*ром', r'\bром\b(?!.*аром)'],
 [r'\bаром', r'\bтракия']),
# CRITICAL EXCLUSIONS:
# - \bаром excludes "Аром." (ароматизатор) which contains "ром"
# - \bтракия excludes "Тракия Бутертесто" which contains "ракия"

("Напитки", "Безалкохолни",
 [r'coca-cola', r'\bfanta\b', r'\bsprite\b', r'\bpepsi\b', r'\bschweppes\b',
  r'\bderby\b.*напитка', r'\bmonster\b', r'енергийна напитка',
  r'газирана напитка', r'\bлимонада\b'],
 []),

("Напитки", "Сокове",
 [r'\bсок\b', r'\bнектар\b', r'\bсмути\b', r'\bcappy\b', r'\bflorina\b',
  r'\bfreshko\b'],
 []),

("Напитки", "Студен чай",
 [r'студен чай', r'\bnestea\b'],
 []),

("Напитки", "Кафе",
 [r'\bкафе\b', r'\bjacobs\b', r'\bnescafe\b', r'\blavazza\b',
  r'\btchibo\b', r'\bespresso\b'],
 []),

("Напитки", "Вода",
 [r'\bdevin\b.*вод', r'горна баня', r'трапезна вода', r'минерална вода'],
 [r'филтър', r'кана']),
# Exclusions prevent water filters from being classified as water
```

#### LAYER 4 — Sweets & Snacks

```python
("Сладкарски", "Шоколад/Бонбони",
 [r'\bшоколад\b(?!.*фигур)', r'\bбонбон', r'\blindt\b', r'\bnutella\b',
  r'\bmoritz\b', r'\broshen\b', r'\bsnickers\b', r'\bmars\b', r'\btwix\b',
  r'\bkit kat\b', r'\blion\b.*десерт', r'\btoffifee\b'],
 [r'великденски заек']),

("Сладкарски", "Бисквити/Вафли",
 [r'\bбисквит', r'\bвафл[аи]', r'\bмаркизит', r'\b7 days\b',
  r'\bmilka\b.*бисквит', r'\bнасладки\b', r'\bтраяна\b',
  r'\bцаревец\b.*вафли', r'\bparadise\b', r'вафлен бар',
  r'\bкристал\b.*бисквит', r'бирени пръчици', r'\bbrusketi\b', r'\bmaretti\b'],
 []),

("Сладкарски", "Чипс/Снакс",
 [r'\bчипс\b', r'\bdoritos\b', r'\bpom bar\b', r'\bkubeti\b', r'ръжени кубчета'],
 []),

("Сладкарски", "Торти/Сладкиши",
 [r'\bторта\b', r'\bчийзкейк\b', r'\bсуфле\b', r'крем брюле',
  r'\bпрофитероли\b', r'\bтирамису\b', r'\bсладкиш', r'великденски заек',
  r'\bкейк\b', r'домашни сладки', r'\bbalocco\b'],
 [r'великденска чаша']),

("Сладкарски", "Сладолед",
 [r'\bсладолед\b'],
 []),

("Сладкарски", "Кремове/Декорации за печене",
 [r'крем без варене', r'смес за печене', r'микс за брауни',
  r'декорация', r'звездички', r'\bdolce\b.*крем', r'\bdolce\b.*декор'],
 []),

("Сладкарски", "Зърнени закуски",
 [r'зърнена закуска'],
 []),
```

#### LAYER 5 — Home, Garden, Other

```python
("Дом и градина", "Градина",
 [r'\bсубстрат\b', r'торфена смес', r'\bсаксия\b', r'\bгербер\b',
  r'\bсандъче\b', r'семена.*моята', r'подложка за саксия'],
 []),

("Дом и градина", "Кухненски",
 [r'\bтенджера\b', r'прибори за хранене', r'\bнож\b', r'чаши.*комплект',
  r'\bspice.*soul\b', r'\bудължител\b'],
 []),

("Други", "Играчки/Игри",
 [r'\blego\b', r'\bпъзел\b', r'дървена игра', r'топка за футбол',
  r'чадър детски', r'шоколадова фигур', r'плюшена играчка', r'великденска чаша'],
 []),

("Други", "Изкуство/Хартия",
 [r'платно за рисуване', r'блок за рисуване', r'хартия.*цвят', r'\btalentus\b'],
 []),

("Други", "Филтри за вода",
 [r'филтър за вода', r'филтри за вода', r'кана за вода'],
 []),

("Други", "Инструменти",
 [r'\bparkside\b.*станция', r'запояване'],
 []),
```

### 4.5 Classification Results (2026-03-29 data)

- **600 of 622 items** classified by rules (96.5%)
- **22 items** fell through to "Некласифицирани" — handled via manual overrides (Section 7)
- After manual overrides: **621 of 622** classified (99.8%), 1 truly unclassifiable ("0,75 л")

---

## 5. STEP 3: GROUPING, RANKING & REPORT GENERATION

### 5.1 Grouping Logic

Items are grouped by `(category, subcategory)`. Within each group, only items that have a successfully parsed `norm_price` are included in rankings.

```python
from collections import defaultdict

groups = defaultdict(list)
for item in enriched_data:
    if item['norm_price'] is not None and item['category'] != 'Некласифицирани':
        groups[(item['category'], item['subcategory'])].append(item)
```

### 5.2 Ranking Logic

Within each (category, subcategory) group, items are sorted by `norm_price` ascending (cheapest first):

```python
for key in groups:
    groups[key].sort(key=lambda x: x['norm_price'])
```

This means:
- A 400g yogurt at 0.84 лв. (norm: 2.10 лв./кг) ranks ABOVE a 1kg yogurt at 2.40 лв. (norm: 2.40 лв./кг)
- Items priced per-kg automatically compare against items priced per-gram
- Liquids compare лв./л across different bottle sizes (330ml, 500ml, 1L, 2L)
- Piece-counted items (eggs, trash bags) compare лв./бр

### 5.3 Comparison Unit Compatibility

Items within the same subcategory can ONLY be compared if they share the same `base_unit`:
- Grams items compare via лв./кг
- Milliliter items compare via лв./л
- Piece items compare via лв./бр

In practice, most subcategories contain only one unit type (dairy = grams, beverages = ml, eggs = pieces). In rare cases where a subcategory mixes unit types, they sort together by norm_price but the `norm_unit` column makes the difference visible.

### 5.4 Category Display Order

Categories are displayed in a fixed order for readability:

```python
CAT_ORDER = [
    "Млечни продукти", "Яйца", "Месо", "Колбаси и деликатеси",
    "Риба и морски дарове", "Плодове", "Зеленчуци",
    "Хляб и тестени", "Основни хранителни", "Готови храни",
    "Напитки", "Сладкарски", "Домакински",
    "Козметика и хигиена", "Домашни любимци", "Дом и градина", "Други"
]
```

### 5.5 Top N Per Subcategory

The "Cheapest by Category" sheet shows the **top 5 cheapest** items per subcategory. This provides enough alternatives without overwhelming the report. The "Best Deals Summary" sheet shows only the **top 1** (single cheapest).

---

## 6. XLSX OUTPUT STRUCTURE

The workbook contains 4 sheets. Use openpyxl for creation.

### 6.1 Styling Constants

```python
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

HEADER_FILL = PatternFill('solid', fgColor='1F4E79')       # Dark blue
HEADER_FONT = Font(name='Arial', bold=True, color='FFFFFF', size=11)
DATA_FONT = Font(name='Arial', size=10)
BOLD_FONT = Font(name='Arial', bold=True, size=10)
TITLE_FONT = Font(name='Arial', bold=True, size=14, color='1F4E79')
SUBTITLE_FONT = Font(name='Arial', bold=True, size=12, color='1F4E79')
CATROW_FONT = Font(name='Arial', bold=True, size=11, color='1F4E79')
NOTE_FONT = Font(name='Arial', italic=True, size=10, color='808080')
GREEN_FONT = Font(name='Arial', bold=True, size=10, color='006100')
MONEY_FMT = '#,##0.00" лв."'
NORM_FMT = '#,##0.00'
PCT_FMT = '0%'
GREEN = PatternFill('solid', fgColor='C6EFCE')
BLUE_LIGHT = PatternFill('solid', fgColor='D6E4F0')
YELLOW = PatternFill('solid', fgColor='FFF2CC')
GRAY = PatternFill('solid', fgColor='F2F2F2')
CAT_FILL = PatternFill('solid', fgColor='D9E2F3')          # Category header row
SUBCAT_FILL = PatternFill('solid', fgColor='E9EDF4')        # Subcategory header row
BORDER = Border(bottom=Side(style='thin', color='D9D9D9'))
THICK_BORDER = Border(bottom=Side(style='medium', color='1F4E79'))
```

### 6.2 Sheet 1: "Cheapest by Category"

**Tab color**: '00B050' (green) — this is the main report

**Layout**:
- Row 1: Title "Най-евтини продукти по категория" (merged A1:K1, TITLE_FONT)
- Row 2: Subtitle in gray italic explaining the normalization (merged)
- Row 3: blank
- Row 4: Column headers (frozen, styled)
- Row 5+: Data grouped by category → subcategory

**Columns**:
| Col | Header | Content | Format |
|-----|--------|---------|--------|
| A | Категория | Category name (shown only on category header rows) | Text |
| B | Подкатегория | Subcategory name (shown only on subcategory header rows) | Text |
| C | # | Rank within subcategory (1=cheapest) | Number |
| D | Продукт | product_name | Text |
| E | Магазин | source_store | Text |
| F | Канал | source_channel (Direct/Glovo) | Text |
| G | Промо цена | promo_price (or regular_price) | Money лв. |
| H | Опаковка | Raw unit/package label (e.g., "400 г", "2 л") | Text |
| I | Цена за кг/л/бр | Normalized price | Number #,##0.00 |
| J | Единица | norm_unit label ("лв./кг", "лв./л", "лв./бр") | Text |
| K | Отстъпка % | Discount: 1 - (promo/regular) | Percentage |

**Column widths**: `[18, 22, 4, 50, 20, 10, 14, 14, 16, 10, 12]`

**Row structure within each category**:
```
[Category header row — merged, CAT_FILL, THICK_BORDER]
  [Subcategory header row — SUBCAT_FILL, shows count "(N продукта)"]
    [Rank 1 — GREEN fill, GREEN_FONT on price column, bold product name]
    [Rank 2 — BLUE_LIGHT fill]
    [Rank 3 — normal or GRAY alternating]
    [Rank 4 — normal or GRAY alternating]
    [Rank 5 — normal or GRAY alternating]
  [blank row]
  [Next subcategory header...]
```

**Max items per subcategory**: 5

### 6.3 Sheet 2: "Best Deals Summary"

**Tab color**: '2E75B6' (blue)

**Purpose**: One row per subcategory showing only the single cheapest item. Quick reference.

**Layout**:
- Row 1: Title "Най-евтиният продукт във всяка категория" (merged)
- Row 2: Subtitle
- Row 3: blank
- Row 4: Headers (frozen)
- Row 5+: One row per subcategory, grouped under category headers

**Columns**:
| Col | Header | Content | Format |
|-----|--------|---------|--------|
| A | Категория | (blank — shown in category header rows) | Text |
| B | Подкатегория | Subcategory | Text |
| C | Най-евтин продукт | Product name of cheapest item | Text, bold |
| D | Магазин | source_store | Text |
| E | Канал | source_channel | Text |
| F | Промо цена | Raw promo price | Money лв. |
| G | Опаковка | Package label | Text |
| H | Нормализирана цена | norm_price (cheapest) | Number, GREEN fill + GREEN_FONT |
| I | Единица | norm_unit | Text |
| J | # алтернативи | Count of other items in same subcategory minus 1 | Number |

**Column widths**: `[18, 22, 50, 20, 10, 14, 14, 18, 10, 14]`

**Formatting**:
- Category separator rows: merged A:J, CAT_FILL, THICK_BORDER
- Normalized price column: always GREEN fill + GREEN_FONT
- Alternating row gray fill on even rows

### 6.4 Sheet 3: "All Items"

**Tab color**: '1F4E79' (dark blue)

**Purpose**: Full dataset with all enriched fields. Filterable.

**Columns**:
| Col | Header | Format |
|-----|--------|--------|
| A | # | Counter |
| B | Категория | Text |
| C | Подкатегория | Text |
| D | Продукт | Text |
| E | Магазин | Text |
| F | Канал | Text |
| G | Редовна цена | Money |
| H | Промо цена | Money |
| I | Отстъпка % | Percentage |
| J | Спестяване | Money |
| K | Опаковка | Text |
| L | Цена за кг/л/бр | Number |
| M | Единица | Text |
| N | Промо период | Text |
| O | URL | Text |

**Column widths**: `[5, 18, 22, 50, 18, 10, 14, 14, 10, 12, 14, 16, 10, 18, 55]`

**Features**: Frozen panes at A2, auto-filter on full range, alternating row gray.

### 6.5 Sheet 4: "Uncomparable Items"

**Tab color**: 'FFC000' (orange/warning)

**Purpose**: Items where no unit could be parsed — cannot participate in normalized price comparison.

**Columns**:
| Col | Header | Format |
|-----|--------|--------|
| A | Категория | Text |
| B | Подкатегория | Text |
| C | Продукт | Text |
| D | Магазин | Text |
| E | Канал | Text |
| F | Промо цена | Money |
| G | Unit (raw) | Text — the raw unit value, or "(няма)" if null |
| H | Причина | Text — "Няма посочена единица" or "Единицата не е разпозната" |

**Column widths**: `[18, 22, 50, 18, 10, 14, 14, 30]`

Reason column cells get YELLOW fill.

---

## 7. MANUAL OVERRIDE TABLE

After the classifier runs, ~20-25 items typically fall through as unclassified. Apply these manual overrides AFTER classification but BEFORE building the spreadsheet.

These are items where:
- The product name uses an unusual spelling (Cyrillic "T" vs Latin "T" in "Tоалетна")
- The name has a "Био" prefix that the regex doesn't catch ("Биобанани", "Биочушки")
- The product doesn't contain any matching keywords ("Великденски микс шоколадови фигури")

```python
MANUAL_OVERRIDES = {
    # Typo/encoding: Cyrillic vs Latin characters
    "Maliva Tоалетна хартия различни видове": ("Домакински", "Тоалетна хартия"),
    "NEVOS Tорби за смет с дръжки": ("Домакински", "Торби за смет"),
    
    # "Био" prefix products
    "K-CLASSIC Био хартиена торбичка за боклук": ("Домакински", "Торби за смет"),
    "K-Bio Биочушки Калифорния": ("Зеленчуци", "Зеленчуци"),
    "K-Bio Биобанани": ("Плодове", "Плодове"),
    "София мел Биобрашно от лимец": ("Основни хранителни", "Брашно"),
    "Dragon Superfoods Биобрашно от бадеми": ("Основни хранителни", "Брашно"),
    "K-Bio Паста без яйца различни видове": ("Основни хранителни", "Паста/Макарони"),
    "K-take it veggie Бионапитка избрани видове": ("Напитки", "Други напитки"),
    
    # Deli products with unusual names
    "Майстор Цветко Пуешки гърди от свежата витрина": ("Колбаси и деликатеси", "Шунка"),
    "Лотос Роле Трапезица от свежата витрина": ("Колбаси и деликатеси", "Салам/Колбас"),
    "Мегдана Кренвирши": ("Колбаси и деликатеси", "Салам/Колбас"),
    "Чоки Кренвирши от пилешко месо": ("Колбаси и деликатеси", "Салам/Колбас"),
    
    # Products with no matching keywords
    "Maggi Фикс или Супа различни видове": ("Готови храни", "Готови храни"),
    "Eisberg Салата Колсло": ("Готови храни", "Готови храни"),
    "Великденски микс шоколадови фигури": ("Сладкарски", "Шоколад/Бонбони"),
    "K-Ostern Шоколадова близалка": ("Сладкарски", "Шоколад/Бонбони"),
    "Vibo Хималайски солни кристали различни видове": ("Основни хранителни", "Оцет/Подправки"),
    "Мляко Прясно Верея 3% 2 л": ("Млечни продукти", "Прясно мляко"),
    "Бяла багета от нашата пекарна": ("Хляб и тестени", "Хляб"),
    "Земела годжи бери (150 г)": ("Хляб и тестени", "Хляб"),
}

# Apply overrides
for item in enriched_data:
    if item['product_name'] in MANUAL_OVERRIDES:
        item['category'], item['subcategory'] = MANUAL_OVERRIDES[item['product_name']]
```

**When processing a new JSON file**: Run the classifier first, print unclassified items, then add new manual overrides as needed. Aim for <1% unclassified.

---

## 8. EDGE CASES & KNOWN ISSUES

### 8.1 Standalone "кг" Unit

When `unit` is just "кг" with no number, the listed price IS the per-kg price. The parser handles this by setting qty=1000g, so:
`norm_price = (price / 1000) * 1000 = price`

Products affected: fresh meat, bulk vegetables, deli counter items.

### 8.2 "Различни видове" (Various types)

Many products say "различни видове" (various types) in the name. These are valid products — the retailer offers multiple flavors/variants at the same price. They should NOT be filtered out.

### 8.3 "От свежата витрина" (From the fresh counter)

Products with this suffix are sold by weight at the deli counter. Their unit is typically "кг" (per kilogram pricing). The suffix itself is not a category indicator.

### 8.4 Duplicate Products

Some products appear with slight name variations:
- "VITAE D'ORO Олио слънчогледово" vs "Vitae d'Oro Олио цена до 4 бр. на покупка"
- "Classic Max Хумус различни видове" vs "CLASSIC MAX Хумус различни вкусове"

The current logic does NOT deduplicate — both appear in rankings. For a future improvement, normalize names (lowercase, strip suffixes) and keep only the cheapest instance.

### 8.5 Glovo Price Markup

Items from source_channel "Glovo" often have higher prices than "Direct" (in-store). The `source_channel` column makes this visible, but the ranking treats them equally. A future enhancement could flag Glovo items or separate them.

### 8.6 Mixed Unit Types in One Subcategory

Rare, but possible. Example: Eggs might have both "10 бр" (pieces) and "кг" items if someone sells eggs by weight. The norm_unit column ("лв./бр" vs "лв./кг") distinguishes them, but they sort together by raw norm_price value.

### 8.7 Cyrillic vs Latin Character Confusion

Some product names contain Latin characters that look like Cyrillic (e.g., Latin "T" in "Tоалетна" instead of Cyrillic "Т"). This causes regex word-boundary `\b` matches to fail. The manual override table catches these, but new data may introduce new cases. Always check unclassified items for this issue.

### 8.8 Missing Stores

If major stores (Billa, Fantastico) return no data from the scrape, the "cheapest" report is biased toward whichever stores did return data. The Summary sheet should note which stores are missing. With the 2026-03-29 data, Kaufland dominates (563 of 622 items).

---

## 9. PYTHON DEPENDENCIES

```
openpyxl      — XLSX creation and formatting (pip install openpyxl)
json          — reading input file (standard library)
re            — regex for unit parsing and classification (standard library)
collections   — Counter, defaultdict for grouping (standard library)
```

All standard library except openpyxl. Pre-installed in Claude Code environments.

---

## 10. EXECUTION CHECKLIST

When given a new JSON file, execute these steps in order:

```
1. LOAD the JSON file into a list of dicts

2. CLASSIFY every item:
   a. Run classify(product_name) for each item → (category, subcategory)
   b. Print classification summary (items per category/subcategory)
   c. Print unclassified items
   d. Apply manual overrides from Section 7
   e. Add new overrides for any remaining unclassified items

3. PARSE UNITS for every item:
   a. Run parse_unit(unit, product_name) → (quantity, base_unit)
   b. Print parsing summary (how many g/ml/pcs/unparseable)

4. COMPUTE NORMALIZED PRICES:
   a. For each item with parsed units: compute norm_price and norm_unit
   b. Use promo_price preferentially, fall back to regular_price

5. GROUP items by (category, subcategory)
   a. Only include items with norm_price != None
   b. Exclude "Некласифицирани"

6. SORT each group by norm_price ascending

7. BUILD XLSX with 4 sheets:
   a. "Cheapest by Category" — top 5 per subcategory, grouped (Section 6.2)
   b. "Best Deals Summary" — top 1 per subcategory (Section 6.3)
   c. "All Items" — full enriched dataset (Section 6.4)
   d. "Uncomparable Items" — items without normalized price (Section 6.5)

8. SAVE to /home/claude/ and COPY to /mnt/user-data/outputs/

9. PRESENT the file using present_files tool
```

**Expected runtime**: Under 10 seconds for 600-1000 items.
**Expected output**: ~45 subcategories, ~360 rows in Cheapest sheet, ~80 rows in Summary.
