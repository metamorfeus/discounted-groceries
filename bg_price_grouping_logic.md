# Bulgarian Grocery Prices — Product Grouping & Price Normalization Logic

## Purpose
This document describes how to categorize 600+ scraped Bulgarian grocery promotional items into comparable product groups, normalize prices to per-kg or per-liter, and generate a "cheapest by category" report. Designed to be used in Claude Code with an updated `bulgarian_promo_prices_*.json` file.

---

## OVERVIEW OF THE THREE PROBLEMS

### Problem 1: Unit Normalization
The `unit` field is wildly inconsistent — 126 unique formats including "кг", "1 кг", "500 г", "2 л", "750мл", "3x300 г", "10 бр.", null, etc. To compare prices we need a standardized price-per-gram or price-per-ml.

### Problem 2: Product Categorization
The `product_category` field is null for 90% of items. Product names are in Bulgarian and vary widely across stores. We need keyword-based classification into ~25 categories.

### Problem 3: Cross-product Comparison
Even within the same category, products differ in brand, size, and quality. The report should show the cheapest option within each category and subcategory, normalized to per-kg or per-liter pricing.

---

## PART 1: UNIT PARSING & PRICE NORMALIZATION

### 1.1 The Unit Parser

```python
import re

def parse_unit(unit_str, product_name=""):
    """
    Parse the unit field (or product name fallback) into (quantity, base_unit).
    
    Returns:
        (quantity_in_base, base_unit) where:
        - base_unit: 'g' (grams), 'ml' (milliliters), 'pcs' (pieces/бр)
        - quantity_in_base: total grams, ml, or piece count
        
    Returns (None, None) if unparseable.
    """
    # Try unit field first, fall back to product name
    s = (unit_str or product_name or "").strip().lower()
    if not s:
        return None, None
    
    try:
        # ── Standalone "кг" means price is already per-kg ──
        if s == 'кг':
            return 1000, 'g'
        
        # ── Composite: "3x300 г" ──
        m = re.search(r'(\d+)\s*x\s*(\d+)\s*(г|мл)', s)
        if m:
            total = int(m.group(1)) * int(m.group(2))
            return (total, 'g') if m.group(3) == 'г' else (total, 'ml')
        
        # ── Kilograms: "1 кг", "1.5 кг", "0,5 кг" ──
        m = re.search(r'([\d]+[.,]?[\d]*)\s*кг', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val * 1000, 'g'
        
        # ── Grams: "500 г", "400г" (but NOT "гр" which could be other things) ──
        m = re.search(r'([\d]+[.,]?[\d]*)\s*г(?!р)', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val, 'g'
        
        # ── Liters: "1 л", "1.5 л", "3 л" (but NOT "лв" = currency) ──
        m = re.search(r'([\d]+[.,]?[\d]*)\s*л(?!в)', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val * 1000, 'ml'
        
        # ── Milliliters: "500 мл", "750мл" ──
        m = re.search(r'([\d]+[.,]?[\d]*)\s*мл', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val, 'ml'
        
        # ── Pieces: "10 бр.", "6 бр" ──
        m = re.search(r'([\d]+[.,]?[\d]*)\s*бр', s)
        if m:
            val = float(m.group(1).replace(',', '.'))
            return val, 'pcs'
        
        # ── Standalone "бр." or "бр" ──
        if 'бр' in s:
            return 1, 'pcs'
    
    except (ValueError, AttributeError):
        pass
    
    return None, None
```

### 1.2 Computed Price Fields

For each item, compute:

```python
def compute_normalized_price(item):
    """
    Returns dict with:
      - quantity: parsed quantity in base units
      - base_unit: 'g', 'ml', or 'pcs'
      - price_per_kg: price in лв. per kilogram (if base_unit is 'g')
      - price_per_liter: price in лв. per liter (if base_unit is 'ml')
      - price_per_piece: price per piece (if base_unit is 'pcs')
    """
    price = item.get('promo_price') or item.get('regular_price')
    if not price:
        return {}
    
    qty, base = parse_unit(item.get('unit'), item.get('product_name', ''))
    
    result = {'quantity': qty, 'base_unit': base}
    
    if qty and qty > 0:
        if base == 'g':
            result['price_per_kg'] = round((price / qty) * 1000, 2)
        elif base == 'ml':
            result['price_per_liter'] = round((price / qty) * 1000, 2)
        elif base == 'pcs':
            result['price_per_piece'] = round(price / qty, 2)
    
    return result
```

### 1.3 Coverage Analysis (from current data)

Out of 622 items:
- **293 items** → parseable to grams (47%)
- **120 items** → parseable to milliliters (19%)
- **49 items** → parseable to pieces (8%)
- **160 items** → unparseable (26%) — mostly null units on non-food items like cleaning products, home goods, cosmetics

For food comparison purposes, the 413 items with weight/volume units cover the core grocery categories well.

### 1.4 Special Cases

| Scenario | How to handle |
|----------|---------------|
| `unit` is "кг" (standalone) | Price is already per-kg. Set qty=1000g. |
| `unit` is null but product name has "500 г" | Parser falls back to product_name extraction |
| `unit` is "2 л" | Convert: 2 л = 2000 ml |
| `unit` is "3x300 г" | Multiply: 3×300 = 900g total |
| `unit` is "10 бр." | Pieces — compute price_per_piece only |
| Eggs "10 бр" | Compare price_per_piece (price per egg) |
| Toilet paper "различни видове" | Unparseable — exclude from per-unit comparison |

---

## PART 2: PRODUCT CATEGORIZATION

### 2.1 Architecture: Priority-Ordered Keyword Rules

The classifier uses an ordered list of rules. Each rule has:
- **category**: top-level group (e.g., "Млечни продукти")
- **subcategory**: specific type (e.g., "Кисело мляко")
- **brand_anchors**: brand names that force classification regardless of other keywords (e.g., "Frosch" → always cleaning)
- **include_patterns**: regex patterns — ANY match triggers the rule
- **exclude_patterns**: regex patterns — ANY match blocks the rule

**First matching rule wins.** This means rule ORDER matters critically.

### 2.2 The Ordering Problem (and Solution)

Bulgarian product names often contain "misleading" food keywords inside non-food items:
- "Frosch почиств. препарат малина с **оцет**" → contains "оцет" (vinegar) but is a cleaning product
- "Medix Обезмаслител **портокал**" → contains "портокал" (orange) but is a degreaser  
- "**Тракия** Бутертесто" → contains "ракия" substring but is puff pastry
- "`ром\b`" matches "А**ром**." (ароматизатор prefix) — not rum

**Solution: Rule priority layers.**

```
Layer 0: BRAND ANCHORS (override everything)
  - If product name contains "Frosch", "Medix", "Glade", "viGO!" → Household
  - If product name contains "Gillette", "L'Oreal", "Garnier", "SYOSS" → Cosmetics
  
Layer 1: HOUSEHOLD & NON-FOOD (checked before any food rules)
  - Trash bags, cleaning products, detergents, air fresheners
  - These often contain food-adjacent words (оцет, портокал, лимон, аром)

Layer 2: FOOD CATEGORIES (checked after household is excluded)
  - Dairy, Meat, Produce, Bread, etc.

Layer 3: BEVERAGES (after food)

Layer 4: CATCH-ALL ("Некласифицирани")
```

### 2.3 Complete Category Rules

```python
CATEGORY_RULES = [
    # ═══════════════════════════════════════════════════════════
    # LAYER 0: BRAND ANCHORS — checked first, override everything
    # ═══════════════════════════════════════════════════════════
    
    # Cleaning brands
    ("Домакински", "Перилни/Почистващи",
     [r'\bfrosch\b', r'\bmedix\b', r'\bmeglio\b'],
     [r'ароматизатор']),
    
    # Air freshener brand
    ("Домакински", "Ароматизатори",
     [r'\bglade\b'],
     []),
    
    # Personal care brands  
    ("Козметика и хигиена", "Шампоан/Коса",
     [r'\bgarnier\b', r'\bsyoss\b', r'\bbatiste\b', r'\bhair vege\b', r'\bnivea шамп'],
     []),
    
    ("Козметика и хигиена", "Крем за лице",
     [r"l'oreal", r"l'oréal", r'\brevitalift\b'],
     []),
    
    ("Козметика и хигиена", "Бръснене",
     [r'\bgillette\b'],
     []),

    # Pet food brands
    ("Домашни любимци", "Храна за животни",
     [r'k-carinura', r'\bdante\b.*куч'],
     []),
    
    # ═══════════════════════════════════════════════════════════
    # LAYER 1: HOUSEHOLD (before food — these contain food keywords)
    # ═══════════════════════════════════════════════════════════
    
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
     [r'ароматизатор', r'микроспрей.*аром'],
     []),
    
    ("Домакински", "Дамски превръзки",
     [r'дамски превръзки', r'every day.*превръзки'],
     []),
    
    # ═══════════════════════════════════════════════════════════
    # LAYER 1.5: COSMETICS (before food keywords like "мляко" in body care)
    # ═══════════════════════════════════════════════════════════
    
    ("Козметика и хигиена", "Шампоан/Коса",
     [r'шампоан', r'балсам.*коса', r'маска за коса', r'серум за коса',
      r'спрей за корени', r'боя за коса', r'сух шампоан'],
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

    ("Козметика и хигиена", "Боя за коса",
     [r'боя за коса', r'\bolia\b.*боя', r'creme supreme.*боя'],
     []),
    
    # ═══════════════════════════════════════════════════════════
    # LAYER 2: FOOD CATEGORIES
    # ═══════════════════════════════════════════════════════════
    
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
      r'крема сирене', r'котидж', r'\bбри\b(?!.*пръч)', r'синьо сирене'],
     [r'панирани.*сиренца']),
    
    ("Млечни продукти", "Кашкавал",
     [r'\bкашкавал\b', r'\bементал\b'],
     []),
    
    ("Млечни продукти", "Масло (краве)",
     [r'масло краве', r'markenbutter'],
     [r'маслиново', r'олио', r'слънчогледово']),
    
    ("Млечни продукти", "Сметана/Извара",
     [r'заквасена сметана', r'\bизвара\b', r'крем за разбиване'],
     []),
    
    ("Млечни продукти", "Млечни напитки/десерти",
     [r'млечна напитка', r'млечен десерт', r'протеинов йогурт'],
     []),
    
    # ── Eggs ──
    ("Яйца", "Яйца",
     [r'\bяйца\b', r'\bбиояйца\b'],
     [r'без яйца', r'паста']),  # CRITICAL: "паста без яйца" is NOT eggs
    
    # ── Meat ──
    ("Месо", "Пилешко",
     [r'пилеш', r'пиле\b', r'\bfragedo\b', r'la provincia.*пилеш',
      r'царевично пиле', r'frangosul.*пилеш'],
     [r'кренвирш']),
    
    ("Месо", "Свинско",
     [r'свинск'],
     [r'салам', r'шунка', r'наденица', r'кренвирш', r'шпек', r'бекон']),
    
    ("Месо", "Телешко",
     [r'телеш'],
     [r'шкембе']),
    
    ("Месо", "Кайма",
     [r'\bкайма\b'],
     []),
    
    ("Месо", "Шкембе",
     [r'\bшкембе\b'],
     []),
    
    # ── Deli ──
    ("Колбаси и деликатеси", "Шунка",
     [r'\bшунка\b', r'\bпастърма\b'],
     []),
    
    ("Колбаси и деликатеси", "Салам/Колбас",
     [r'\bсалам\b', r'\bколбас\b', r'\bсуджук\b', r'\bлуканка\b', r'\bсушеник\b',
      r'\bнаденица\b', r'\bдебърцини\b', r'\bкренвирш\b', r'\bшпек\b', r'\bбекон\b',
      r'\bмезе\b', r'\bфуетек\b', r'кълцано карначе',
      r'\bпастет\b(?!.*куч)(?!.*кот)'],
     []),
    
    # ── Fish ──
    ("Риба и морски дарове", "Риба",
     [r'\bриб', r'\bсьомг', r'\bскумрия\b', r'\bпъстърв', r'\bсельод', r'\bхайвер\b',
      r'\bсуши\b', r'\bмиди\b', r'\bсурими\b', r'\bocean\b', r'\bmowi\b',
      r'филе панирано'],
     []),
    
    # ── Produce ──
    ("Плодове", "Плодове",
     [r'\bбанан', r'\bябълк', r'\bягоди\b', r'\bгрозде\b', r'\bкруш',
      r'\bпортокал(?!.*препарат)(?!.*обезмасл)', r'\bлимон(?!ад)',
      r'\bлимет', r'\bкиви\b', r'\bборовинк', r'\bананас\b', r'\bкестен',
      r'\bсливи\b', r'\bфурми\b', r'\bманго\b'],
     [r'сок', r'нектар', r'смути', r'компот', r'препарат', r'обезмаслител',
      r'frosch', r'medix', r'чипс', r'вино', r'сайдер']),
    
    ("Зеленчуци", "Зеленчуци",
     [r'\bкартоф', r'\bдомат', r'\bкраставиц', r'\bчушк', r'\bлук\b',
      r'\bчесън\b', r'\bтиквичк', r'\bкопфсалат', r'салата.*фризе',
      r'салата.*бон тон', r'\bспанак\b', r'\bгъби\b', r'\bцелина\b',
      r'\bрепичк', r'\bпащърнак\b', r'\bмаслин'],
     [r'чипс', r'салата снежанка', r'руска салата', r'кьопоолу',
      r'лютеница', r'печена капия', r'препарат']),
    
    # ── Bread & Bakery ──
    ("Хляб и тестени", "Хляб",
     [r'\bхляб\b', r'\bбагет\b', r'\bземел\b', r'\bсомун\b', r'\bбиохляб\b'],
     []),
    
    ("Хляб и тестени", "Козунак",
     [r'\bкозунак\b', r'козуначен', r'colomba'],
     []),
    
    ("Хляб и тестени", "Кроасан/Кифли",
     [r'\bкроасан\b', r'\bкифлич', r'\bпоничк', r'\bдонът\b', r'\bеклер\b'],
     []),
    
    ("Хляб и тестени", "Тесто/Кори",
     [r'\bтесто\b', r'\bкори\b(?!.*д)', r'бутертесто', r'точени'],
     []),
    
    # ── Cooking Staples ──
    ("Основни хранителни", "Захар",
     [r'\bзахар\b(?!на)(?!.*декорация)'],
     []),
    
    ("Основни хранителни", "Брашно",
     [r'\bбрашно\b', r'\bнишесте\b', r'\bовесени трици\b'],
     []),
    
    ("Основни хранителни", "Олио",
     [r'\bолио\b', r'слънчогледово'],
     [r'маслиново']),
    
    ("Основни хранителни", "Маслиново масло",
     [r'маслиново масло', r'\bbertolli\b', r"costa d'oro"],
     []),
    
    ("Основни хранителни", "Ориз/Булгур/Бобови",
     [r'\bориз\b', r'\bбулгур\b', r'\bбоб\b(?!.*манастирски)', r'\bзелен грах\b',
      r'сладка царевица'],
     []),
    
    ("Основни хранителни", "Паста/Макарони",
     [r'\bпаста\b', r'макаронени'],
     [r'за зъби']),
    
    ("Основни хранителни", "Оцет/Подправки",
     [r'\bоцет\b(?!.*препарат)(?!.*frosch)(?!.*medix)',
      r'сода бикарбонат', r'\bкетчуп\b', r'\bдоматено пюре\b'],
     [r'препарат', r'почист', r'frosch']),
    
    # ── Prepared Foods ──
    ("Готови храни", "Готови храни",
     [r'\bкюфтет', r'\bбургер\b(?!.*салам)', r'\bпуканки\b', r'крем супа',
      r'\bкебап\b', r'супа топчета', r'\bпанирани\b', r'\bхумус\b',
      r'\bлютеница\b', r'\bкьопо[оу]лу\b', r'\bкатък\b', r'боб по манастирски',
      r'печена капия', r'руска салата', r'салата снежанка', r'салата северняшка',
      r'минибанички', r'\bмекици\b', r'\bпица\b', r'\bгюбек\b',
      r'продукт за мазане'],
     []),
    
    # ── Beverages ──
    ("Напитки", "Бира",
     [r'\bбира\b', r'\bсайдер\b', r'\bheineken\b', r'\bcorona\b(?!.*вирус)',
      r'\bstaropramen\b', r'\bamstel\b', r'\bpaulaner\b', r'\btuborg\b',
      r'\bзагорка\b', r'\bкаменица\b', r'\bариана\b', r'\bпиринско\b',
      r'\bшуменско\b', r'\bбургаско\b', r'\bвитошко\b', r'\bболярка\b',
      r'\bradeberger\b', r'\bschofferhofer\b', r'\bsomersby\b',
      r'\bcorsendonk\b', r'\btemplier\b'],
     []),
    
    ("Напитки", "Вино",
     [r'\bвино\b', r'\bрозе\b(?!.*шоколад)', r'пино гриджо'],
     []),
    
    ("Напитки", "Спиртни напитки",
     [r'\bводка\b', r'\bуиски\b', r'\bузо\b', r'\bгроздова\b',
      r'\bZacapa\b.*[Рр]ом', r'\bром\b(?!.*аром)'],
     [r'\bаром', r'\bтракия\b']),  # CRITICAL: exclude "Аром." and "Тракия"
    
    ("Напитки", "Безалкохолни",
     [r'coca-cola', r'\bfanta\b', r'\bsprite\b', r'\bpepsi\b', r'\bschweppes\b',
      r'\bderby\b.*напитка', r'\bmonster\b.*напитка', r'енергийна напитка',
      r'газирана напитка', r'\bлимонада\b'],
     []),
    
    ("Напитки", "Сокове",
     [r'\bсок\b', r'\bнектар\b', r'\bсмути\b', r'\bcappy\b', r'\bflorina\b',
      r'\bfreshko\b.*сок', r'\bfreshko\b.*смути'],
     []),
    
    ("Напитки", "Чай/Студен чай",
     [r'студен чай', r'\bnestea\b'],
     [r'бисквит']),
    
    ("Напитки", "Кафе",
     [r'\bкафе\b', r'\bjacobs\b', r'\bnescafe\b', r'\blavazza\b',
      r'\btchibo\b', r'\bespresso\b'],
     []),
    
    ("Напитки", "Вода",
     [r'\bdevin\b.*вод', r'горна баня.*вод', r'трапезна вода',
      r'минерална вода'],
     [r'филтър', r'кана за вода']),
    
    ("Напитки", "Други напитки",
     [r'\bбионапитка\b', r'\bшот\b.*видове'],
     []),
    
    # ── Sweets & Snacks ──
    ("Сладкарски", "Шоколад/Бонбони",
     [r'\bшоколад\b(?!.*фигур)', r'\bбонбон', r'\blindt\b', r'\bnutella\b',
      r'\bmoritz\b', r'\broshen\b', r'\bsnickers\b', r'\bmars\b(?!.*ка)',
      r'\btwix\b', r'\bkit kat\b', r'\blion\b.*десерт', r'\btoffifee\b'],
     []),
    
    ("Сладкарски", "Бисквити/Вафли",
     [r'\bбисквит', r'\bвафл[аи]', r'\bмаркизит', r'\b7 days\b',
      r'\bmilka\b.*бисквит', r'\bнасладки\b', r'\bтраяна\b',
      r'\bцаревец\b.*вафли', r'\bparadise\b.*бисквит',
      r'\bкристал\b.*бисквит', r'\bвафлен бар\b'],
     []),
    
    ("Сладкарски", "Чипс/Снакс",
     [r'\bчипс\b', r'\bdoritos\b', r'\bpom bar\b', r'\bбрускети\b',
      r'\bкубчета\b', r'\bмарети\b', r'бирени пръчици'],
     []),
    
    ("Сладкарски", "Торти/Сладкиши",
     [r'\bторта\b', r'\bчийзкейк\b', r'\bсуфле\b', r'крем брюле',
      r'\bпрофитероли\b', r'\bтирамису\b', r'\bсладкиш\b',
      r'великденски заек(?!.*чаша)', r'\bкейк\b', r'домашни сладки'],
     []),
    
    ("Сладкарски", "Сладолед",
     [r'\bсладолед\b'],
     []),
    
    ("Сладкарски", "Кремове за печене",
     [r'крем без варене', r'смес за печене', r'микс за брауни',
      r'декорация.*торт', r'захарна декорация', r'звездички',
      r'\bdolce\b.*крем', r'\bdolce\b.*декорация'],
     []),
    
    ("Сладкарски", "Зърнени закуски",
     [r'зърнена закуска'],
     []),

    # ── Home & Garden ──
    ("Дом и градина", "Градина",
     [r'\bсубстрат\b', r'торфена смес', r'\bсаксия\b', r'\bгербер\b',
      r'\bсандъче\b', r'семена.*моята', r'подложка за саксия'],
     []),
    
    ("Дом и градина", "Кухненски",
     [r'\bтенджера\b', r'прибори за хранене', r'\bнож\b(?!.*ици)',
      r'чаши.*комплект', r'\bspice.*soul\b', r'\bудължител\b'],
     []),
    
    # ── Other ──
    ("Други", "Играчки/Игри",
     [r'\blego\b', r'\bпъзел\b', r'дървена игра', r'топка за футбол',
      r'чадър детски', r'шоколадова фигур', r'плюшена играчка',
      r'великденска чаша'],
     []),
    
    ("Други", "Изкуство/Хартия",
     [r'платно за рисуване', r'блок за рисуване', r'хартия.*цвят',
      r'\btalentus\b'],
     []),
    
    ("Други", "Филтри за вода",
     [r'филтър за вода', r'филтри за вода', r'кана за вода'],
     []),
    
    ("Други", "Инструменти",
     [r'\bparkside\b.*станция', r'запояване'],
     []),
    
    ("Домашни любимци", "Храна за животни",
     [r'храна за куч', r'храна за кот', r'лакомство за куч',
      r'стикове за куч', r'пастет за куч', r'пастет за кот'],
     []),
]
```

### 2.4 The Classifier Function

```python
def classify_product(name):
    """Returns (category, subcategory) for a product name."""
    name_lower = name.lower()
    
    for category, subcategory, include_patterns, exclude_patterns in CATEGORY_RULES:
        # Check exclusions first
        excluded = any(re.search(exc, name_lower) for exc in exclude_patterns)
        if excluded:
            continue
        
        # Check inclusions — any match triggers
        if any(re.search(inc, name_lower) for inc in include_patterns):
            return category, subcategory
    
    return "Некласифицирани", "Некласифицирани"
```

### 2.5 Known Misclassification Fixes (applied in Layer ordering)

| Product | False match | Root cause | Fix |
|---------|------------|------------|-----|
| "Frosch препарат малина с оцет" | Оцет/Подправки | "оцет" matched food rule | Brand anchor: Frosch → Household (Layer 0) |
| "Medix Обезмаслител портокал" | Плодове | "портокал" matched fruit | Brand anchor: Medix → Household (Layer 0) |
| "Glade аром. гел за баня" | Спиртни ("ром\b") | "Аром" contains "ром" | Exclude `\bаром` from spirits; Brand anchor: Glade (Layer 0) |
| "Тракия Бутертесто" | Спиртни ("ракия") | "Тракия" contains "ракия" | Exclude `\bтракия\b` from spirits |
| "Fino Аром. торби за смет" | Спиртни ("ром\b") | "Аром" prefix | Layer 1: trash bags checked before beverages |
| "K-Bio Паста без яйца" | Яйца | "яйца" keyword | Exclude pattern: "без яйца" on eggs rule |
| "Freshko Смути ябълка, банан" | Плодове | "банан"/"ябълка" | Exclude "смути" from fruits; Juice rule catches first |
| "K-Classic Филтри за вода" | Вода | "вода" keyword | Exclude "филтър" from water rule |

---

## PART 3: CHEAPEST-BY-CATEGORY REPORT

### 3.1 Report Structure

For each (category, subcategory), show:

```
Category: Млечни продукти
Subcategory: Кисело мляко
══════════════════════════════════════════════════════════
Cheapest per kg:
  1. На хорото Кисело мляко    — 2.10 лв./кг (0.84 лв. / 400 г) @ Kaufland Direct
  2. Булгарче Кисело мляко     — 2.40 лв./кг (0.96 лв. / 400 г) @ Kaufland Direct
  3. Саяна КМ 3.6%             — 3.38 лв./кг (1.35 лв. / 400 г) @ Gladen.bg
  ...
```

### 3.2 Generation Logic

```python
def generate_cheapest_report(data):
    """
    For each subcategory:
    1. Classify all items
    2. Parse units, compute price_per_kg or price_per_liter
    3. Sort by normalized price ascending
    4. Return top N cheapest per subcategory
    """
    from collections import defaultdict
    
    groups = defaultdict(list)
    
    for item in data:
        cat, subcat = classify_product(item['product_name'])
        qty, base = parse_unit(item.get('unit'), item.get('product_name', ''))
        price = item.get('promo_price') or item.get('regular_price')
        
        if not price or not qty or qty <= 0:
            continue
        
        # Compute normalized price
        if base == 'g':
            norm_price = (price / qty) * 1000  # лв. per kg
            norm_unit = 'лв./кг'
        elif base == 'ml':
            norm_price = (price / qty) * 1000  # лв. per liter
            norm_unit = 'лв./л'
        elif base == 'pcs':
            norm_price = price / qty  # лв. per piece
            norm_unit = 'лв./бр'
        else:
            continue  # skip unparseable
        
        groups[(cat, subcat)].append({
            'product_name': item['product_name'],
            'source_store': item['source_store'],
            'source_channel': item['source_channel'],
            'promo_price': item.get('promo_price'),
            'regular_price': item.get('regular_price'),
            'unit': item.get('unit'),
            'quantity': qty,
            'base_unit': base,
            'normalized_price': round(norm_price, 2),
            'norm_unit': norm_unit,
        })
    
    # Sort each group by normalized price
    for key in groups:
        groups[key].sort(key=lambda x: x['normalized_price'])
    
    return groups
```

### 3.3 XLSX Output for Cheapest Report

Create a sheet called "Cheapest by Category" with:

| Col | Header | Content |
|-----|--------|---------|
| A | Category | Top-level category |
| B | Subcategory | Subcategory |
| C | Rank | 1, 2, 3... within subcategory |
| D | Product Name | Item name |
| E | Store | source_store |
| F | Channel | Direct / Glovo |
| G | Promo Price | Raw promo price in лв. |
| H | Package Size | Parsed quantity + unit (e.g., "400 г", "1 кг", "2 л") |
| I | Price per kg/L/pc | Normalized price with unit label |
| J | Comparison Unit | "лв./кг", "лв./л", or "лв./бр" |

**Formatting:**
- Group rows by category/subcategory
- Highlight rank=1 (cheapest) with GREEN_FILL
- Highlight rank=2 with light blue
- Add thick border between subcategory groups

### 3.4 Items That Cannot Be Compared

Some items cannot be normalized:
- No unit AND no weight/volume in product name (e.g., "Шуменско Бира", "K-Classic Филтри за вода")
- Piece-counted items mixed with weight-based items in the same subcategory (e.g., eggs by piece vs by pack)

**Strategy**: Include these in a separate "Uncomparable Items" section at the bottom, showing raw promo_price only.

---

## PART 4: EDGE CASES & KNOWN ISSUES

### 4.1 "кг" as unit = price is per kilogram
When unit is standalone "кг" (no number prefix), the listed price IS the per-kg price. So `price_per_kg = promo_price` directly. The parser handles this by setting qty=1000g.

### 4.2 Products spanning multiple subcategories
"Кайма от свинско месо" matches both "Кайма" and "Свинско". Rule order resolves this — whichever rule appears first wins. Currently "Свинско" is checked before "Кайма", so the exclusion `[r'салам', r'шунка'...]` on Свинско must NOT exclude кайма. Check ordering carefully.

### 4.3 Duplicate products (same item, different wording)
Products like "VITAE D'ORO Олио слънчогледово" and "Vitae d'Oro Олио цена до 4 бр. на покупка" are the same product. The report should ideally deduplicate, but this is complex. For now, both appear — the user can filter.

### 4.4 Brand-specific items with no generic match
"Coca-Cola Real Magic" Glovo items often have unique product names not found elsewhere, making cross-store comparison impossible for those items.

### 4.5 Gladen.bg store naming
Items from Gladen.bg come tagged as "Gladen.bg / Hit Max" — the store name may vary in future extractions. Treat any source containing "Gladen" or "Hit Max" or "Хит Макс" as the aggregator channel.

---

## PART 5: EXECUTION CHECKLIST

1. **Load JSON** file
2. **Run classifier** on all items → assign (category, subcategory) to each
3. **Print classification summary** — items per category, list unclassified
4. **Review unclassified** — add rules if >5% unclassified
5. **Parse units** for all items → compute (quantity, base_unit)
6. **Print unit parsing summary** — how many parseable vs not
7. **Compute normalized prices** (per kg, per liter, per piece)
8. **Generate cheapest-by-category report** sorted by normalized price
9. **Build XLSX** with sheets:
   - "All Items" (from original logic doc, now with category/subcategory columns)
   - "Cheapest by Category" (new sheet from this doc)
   - "Cross-Store Comparison" (from original logic doc)
   - "Summary" (from original logic doc, updated with category stats)
10. **Save and present** .xlsx file
