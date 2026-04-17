#!/usr/bin/env python3
"""
Write Kaufland Glovo and Billa Glovo product JSON from scraped data,
parse Kaufland Direct from FireCrawl file,
parse Fantastico Glovo from FireCrawl file,
then merge all into master.
"""
import sys, json, re
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MASTER_PATH = Path("bulgarian_promo_prices_merged.json")
EXTRACTION_DATE = date.today().isoformat()
PROMO_PERIOD = "02.04 - 08.04.2026"

# ── Kaufland Glovo — 16 Easter products scraped ──────────────────────────────
kaufland_glovo = [
    {"name": "Козунак с шоколад и портокалови корички 400г", "promo": 6.18, "reg": 8.70, "unit": "400 г"},
    {"name": "Козунак с орехов пълнеж 400г", "promo": 5.79, "reg": 7.78, "unit": "400 г"},
    {"name": "Брей! Козунак ръчно плетен локум, стафиди 500г", "promo": 3.68, "reg": 5.28, "unit": "500 г"},
    {"name": "MANIA Козунак Panettone стафиди и портокал 750 г", "promo": 8.98, "reg": 12.89, "unit": "750 г"},
    {"name": "MANIA Козунак Panettone с шоколад 750 г", "promo": 8.98, "reg": 12.89, "unit": "750 г"},
    {"name": "Елиаз Козунак капчица 450 г", "promo": 5.28, "reg": 6.94, "unit": "450 г"},
    {"name": "Cake Mania Брьош козунак класик 400г", "promo": 4.28, "reg": 5.26, "unit": "400 г"},
    {"name": "Домашни курабии, традиционни, 250 г", "promo": 2.44, "reg": 3.11, "unit": "250 г"},
    {"name": "CAKE MANIA Козунак Панетоне стафиди 500 г", "promo": 5.98, "reg": 11.52, "unit": "500 г"},
    {"name": "Домашен козунак със стафиди 400 г", "promo": 2.44, "reg": 3.38, "unit": "400 г"},
    {"name": "Dolce Forneria Panettone Кекс класик 1000 г", "promo": 15.98, "reg": 21.30, "unit": "1000 г"},
    {"name": "CAKE MANIA Козунак Панетоне шоколад 500 г", "promo": 5.98, "reg": 11.52, "unit": "500 г"},
    {"name": "Домашен козунак класически 400г", "promo": 1.08, "reg": 2.70, "unit": "400 г"},
    {"name": "Mania Козунак със стафиди /без консерванти/ 400 г", "promo": 3.48, "reg": 6.24, "unit": "400 г"},
    {"name": "Брьош плитка с ванилов крем и шоколад 300г", "promo": 4.48, "reg": 5.85, "unit": "300 г"},
    {"name": "Козунак плодов микс, орехи, белгийски шоколад 600 г", "promo": 8.39, "reg": 10.85, "unit": "600 г"},
]

kaufland_glovo_records = [
    {
        "source_store": "Kaufland", "source_channel": "Glovo",
        "product_name": p["name"], "product_category": None,
        "regular_price": p["reg"], "promo_price": p["promo"],
        "unit": p.get("unit"), "price_per_unit": None,
        "promo_period": PROMO_PERIOD,
        "source_url": "https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof",
        "extraction_date": EXTRACTION_DATE,
    }
    for p in kaufland_glovo
]
print(f"Kaufland Glovo: {len(kaufland_glovo_records)} products")

# ── Billa Glovo — 66 products scraped from ВЕЛИКДЕН + BILLA PREMIUM section ──
billa_glovo_raw = [
    ("VILLA MEDEN Вино Шардоне 0.75 Л", 15.63, 21.49, "0.75 л"),
    ("VILLA MEDEN Вино К.Сов&Мерло&Сира 0.75 Л", 15.63, 21.49, "0.75 л"),
    ("VILLA MEDEN Вино Розе 0.75 Л", 15.63, 21.49, "0.75 л"),
    ("BILLA PREMIUM Паста CASARECCE 500 ГР", 3.11, 4.28, "500 г"),
    ("VILLA MEDEN Вино Совиньон Блан 0.75 Л", 15.63, 21.49, "0.75 л"),
    ("Devin Изворна вода 8 X 0.5 Л", 4.87, 7.16, "8x0.5 л"),
    ("SOL VINEUS Розе 0.75 Л", 10.39, 12.99, "0.75 л"),
    ("BILLA Бри 200 ГР", 3.89, 5.98, "200 г"),
    ("BILLA Premium Фусили Pasta 500 ГР", 2.99, 4.19, "500 г"),
    ("BILLA Premium Спагети Spaghetti 500 ГР", 2.99, 4.19, "500 г"),
    ("BILLA Premium Суджук от телешко и говеждо месо 160 ГР", 8.98, 13.98, "160 г"),
    ("Billa Premium Талиатели с манатарки 250 ГР", 4.79, 6.75, "250 г"),
    ("Billa Premium Чипс с люти чушки 100 ГР", 3.50, 4.50, "100 г"),
    ("BILLA Premium Шпек 100 ГР", 4.69, 6.49, "100 г"),
    ("BILLA Premium Песто дженовезе 130 ГР", 4.87, 5.89, "130 г"),
    ("BILLA Premium Чили мелничка 35 ГР", 2.99, 4.09, "35 г"),
    ("BILLA Premium Хималайска сол мелничка 110 ГР", 3.29, 4.09, "110 г"),
    ("BILLA Premium Tон филе в собствен сос 200 ГР", 8.98, 10.99, "200 г"),
    ("Billa Premium Бисквити с черен касис и ябълка 80 ГР", 5.07, 5.98, "80 г"),
    ("BILLA Premium Пипер микс зърна мелничка 40 ГР", 4.99, 6.08, "40 г"),
    ("Billa Premium Глазура с балсамов оцет от Модена 250 МЛ", 3.99, 4.99, "250 мл"),
    ("Billa Premium Горчица лимон и джинджифил 120 ГР", 3.50, 5.98, "120 г"),
    ("Billa Premium Морска Сол С Черен Пипер С Вкус На Трюфел 100 ГР", 3.99, 4.99, "100 г"),
    ("BILLA PREMIUM Пушена сьомга в рапично масло 120 ГР", 7.80, 9.99, "120 г"),
    ("BILLA Premium Морска сол мелничка 110 ГР", 2.99, 3.99, "110 г"),
    ("BILLA PREMIUM Микс италиански маслини без костилка 290 ГР", 6.83, 8.98, "290 г"),
    ("Хамон Иберико Billa Premium 70 ГР", 9.37, 11.72, "70 г"),
    ("BILLA PREMIUM Сос за паста Alfredo четири сирена 270 ГР", 5.85, 8.00, "270 г"),
    ("Billa Premium Плосък хляб 200 ГР", 7.80, 9.99, "200 г"),
    ("BILLA PREMIUM Вафлени пури Шам фъстък 35 ГР", 2.13, 2.80, "35 г"),
    ("BILLA PREMIUM Маслиново масло ЕВ 750 МЛ", 17.99, 25.99, "750 мл"),
    ("BILLA PREMIUM Ориз за ризото Арборио 500 ГР", 4.38, 6.30, "500 г"),
    ("BILLA PREMIUM Зелени маслини 295 ГР", 6.83, 8.98, "295 г"),
    ("Billa Premium Бяла подправка 250 МЛ", 4.40, 8.96, "250 мл"),
    ("BILLA PREMIUM Мюсли с бадеми, шамфъстък и шоколадови парченца 300 ГР", 5.85, 7.49, "300 г"),
    ("Billa Premium Ризото с чери домати 300 ГР", 6.98, 8.78, "300 г"),
    ("Billa Premium Сос Къри 250 МЛ", 3.89, 5.59, "250 мл"),
    ("BILLA PREMIUM Ориз Червен 500 ГР", 4.38, 6.30, "500 г"),
    ("BILLA PREMIUM Ориз Черен 500 ГР", 4.38, 6.30, "500 г"),
    ("КФМ Виенска шунка 160 ГР", 5.48, 8.00, "160 г"),
    ("Тандем Габровска свинска пастърма 130 ГР", 5.98, 9.19, "130 г"),
    ("Schweppes Газирана напитка мандарина 1.25 Л", 2.33, 2.95, "1.25 л"),
    ("Schweppes Газирана напитка Розов Тоник 1.25 Л", 2.33, 2.95, "1.25 л"),
    ("Schweppes Газирана напитка тоник 1.25 Л", 2.33, 2.95, "1.25 л"),
    ("Тандем Луканка Майстор в занаята 170 ГР", 9.76, 14.30, "170 г"),
    ("KINDER Шоколадова фигурка 55 ГР", 3.66, 4.87, "55 г"),
    ("Майстор в занаята Телешка луканка 160 ГР", 9.76, 14.30, "160 г"),
    ("KINDER Шокобонс 300 ГР", 12.46, 16.60, "300 г"),
    ("Schweppes Газирана напитка битер лимон 1.25 Л", 2.33, 2.95, "1.25 л"),
    ("HEINEKEN Бира мултипак 5+1х0.5 Л", 9.37, 13.24, "5+1x0.5 л"),
    ("КФМ Старобългарска луканка слайс 150 ГР", 4.99, 7.20, "150 г"),
    ("Бира Stella Artois мултипакет 4x0.5 Л", 6.79, 8.08, "4x0.5 л"),
    ("HAPPY DAY сок Портокал 100% 1.5 Л", 7.22, 9.19, "1.5 л"),
    ("Пиринско кен мултипак 6X0.5 Л", 6.49, 9.25, "6x0.5 л"),
    ("RAFFAELO Великденско яйце 100 ГР", 7.61, 8.98, "100 г"),
    ("CASTELLO Крема сирене ананас 125 ГР", 3.70, 5.50, "125 г"),
    ("Камембер Castello 125 ГР", 4.48, 5.50, "125 г"),
    ("CASTELLO Бри със синя плесен 150 ГР", 4.48, 5.50, "150 г"),
    ("CASTELLO Крема сирене кокос и лайм 125 ГР", 3.70, 5.50, "125 г"),
    ("Синьо сирене Castello 100 ГР", 3.89, 6.40, "100 г"),
    ("CASTELLO Крема сирене домат и босилек 125 ГР", 3.70, 5.50, "125 г"),
    ("Fort Burgozone Вино Мерло& Сира 0.75 Л", 11.52, 14.79, "0.75 л"),
    ("Mezzek Вино Совиньон блан& Пино Гри 0.75 Л", 10.99, 14.79, "0.75 л"),
    ("Mezzek Вино Каберне Совиньон 0.75 Л", 10.99, 14.79, "0.75 л"),
    ("Mezzek Вино розе 0.75 Л", 10.99, 14.79, "0.75 л"),
    ("Mezzek Вино Мерло 0.75 Л", 10.99, 14.79, "0.75 л"),
]

billa_glovo_records = [
    {
        "source_store": "Billa", "source_channel": "Glovo",
        "product_name": name, "product_category": None,
        "regular_price": reg, "promo_price": promo,
        "unit": unit, "price_per_unit": None,
        "promo_period": PROMO_PERIOD,
        "source_url": "https://glovoapp.com/bg/bg/sofia/stores/billa-sof1",
        "extraction_date": EXTRACTION_DATE,
    }
    for name, promo, reg, unit in billa_glovo_raw
]
print(f"Billa Glovo: {len(billa_glovo_records)} products")

# ── Kaufland Direct — parse from FireCrawl file ──────────────────────────────
KAUFLAND_FILE = Path(
    r"C:\Users\PVELINOV\.claude\projects\C--Users-PVELINOV-ODP-OneDrive-BG-FOOD-PRICES"
    r"\609b30dc-ecb2-47a6-a596-86946a4455af\tool-results"
    r"\mcp-claude_ai_firecrawl-firecrawl_scrape-1775572521193.txt"
)

SEP     = '\\\\\n\\\\\n'
LV_RE   = re.compile(r'([\d,\.]+)\s*ЛВ\.', re.IGNORECASE)
EUR_RE  = re.compile(r'([\d]+[,.][\d]{2})\s*€')
UNIT_RE = re.compile(
    r'^(\d+[\.,]?\d*\s*(кг|бр|л|г|мл|пак|бут)\.?|кг|бр\.?|л|г|мл|пакет|бутилка)$',
    re.IGNORECASE
)
SKIP_PATS = [
    re.compile(r'^-?\d+%'),
    re.compile(r'^[\d,\.]+ ?€'),
    LV_RE,
    re.compile(r'^Специална|^при покупка|KAUFLAND CARD|^отстъпка', re.IGNORECASE),
]

def parse_kaufland_direct(md):
    period_m = re.search(r'валидни\s+(?:от\s+)?(\d{2}\.\d{2}(?:\.\d{4})?)', md)
    period = period_m.group(1) if period_m else PROMO_PERIOD

    blocks = re.split(r'\[!\[Изображение на ', md)
    products, seen = [], set()

    for block in blocks[1:]:
        parts = block.split(SEP)
        data_parts = parts[1:]

        eur_prices = [EUR_RE.search(p) for p in data_parts]
        eur_prices = [m.group(1).replace(',', '.') for m in eur_prices if m]
        if len(eur_prices) >= 2:
            try:
                promo   = float(eur_prices[0])
                regular = float(eur_prices[1])
            except ValueError:
                continue
        else:
            # Fallback: convert BGN to EUR
            lv_prices = [LV_RE.search(p) for p in data_parts]
            lv_prices = [m.group(1).replace(',', '.') for m in lv_prices if m]
            if len(lv_prices) < 2:
                continue
            try:
                promo   = round(float(lv_prices[0]) / 1.95583, 2)
                regular = round(float(lv_prices[1]) / 1.95583, 2)
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
                      if not UNIT_RE.match(p)
                      and not any(pat.search(p) for pat in SKIP_PATS)
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

print("\nParsing Kaufland Direct...")
with open(KAUFLAND_FILE, encoding='utf-8') as f:
    raw = f.read()
d = json.loads(raw)
md = json.loads(d[0]['text'])['markdown']
kaufland_direct = parse_kaufland_direct(md)
print(f"Kaufland Direct: {len(kaufland_direct)} products")

# ── Fantastico Glovo — parse from FireCrawl file ─────────────────────────────
FANTASTICO_FILE = Path(
    r"C:\Users\PVELINOV\.claude\projects\C--Users-PVELINOV-ODP-OneDrive-BG-FOOD-PRICES"
    r"\609b30dc-ecb2-47a6-a596-86946a4455af\tool-results"
    r"\mcp-claude_ai_firecrawl-firecrawl_scrape-1775572571216.txt"
)

_GLOVO_PROD_RE = re.compile(
    r'### (.+?)\n\n'
    r'(\d+[.,]\d+)\s*€\s*\((\d+[.,]\d+)\s*лв\.\)'
    r'(\d+[.,]\d+)\s*€\s*\((\d+[.,]\d+)\s*лв\.\)',
    re.DOTALL
)

def parse_glovo_file(path, store, channel, url):
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    d = json.loads(raw)
    md = json.loads(d[0]['text'])['markdown']

    products, seen = [], set()
    for m in _GLOVO_PROD_RE.finditer(md):
        raw_name = m.group(1).strip()
        product_name = re.sub(r'\s*/\s*\d+$', '', raw_name).strip()
        try:
            promo_eur   = float(m.group(2).replace(',', '.'))
            regular_eur = float(m.group(4).replace(',', '.'))
        except ValueError:
            continue
        if promo_eur >= regular_eur * 0.99 or promo_eur < 0.10 or promo_eur > 300:
            continue
        unit_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(кг|г|гр|л|мл|бр|оп)\b', product_name, re.IGNORECASE)
        unit = f"{unit_m.group(1)} {unit_m.group(2).lower().replace('гр','г')}" if unit_m else None
        key = (product_name[:40].lower(), promo_eur)
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "source_store": store, "source_channel": channel,
            "product_name": product_name, "product_category": None,
            "regular_price": regular_eur, "promo_price": promo_eur,
            "unit": unit, "price_per_unit": None,
            "promo_period": PROMO_PERIOD,
            "source_url": url,
            "extraction_date": EXTRACTION_DATE,
        })
    return products

print("\nParsing Fantastico Glovo...")
fantastico_glovo = parse_glovo_file(
    FANTASTICO_FILE,
    store="Fantastico", channel="Glovo",
    url="https://glovoapp.com/bg/bg/sofia/stores/coca-cola-real-magic-sof"
)
print(f"Fantastico Glovo: {len(fantastico_glovo)} products")

# ── Merge all into master ─────────────────────────────────────────────────────
all_new = kaufland_direct + kaufland_glovo_records + billa_glovo_records + fantastico_glovo
print(f"\nTotal new records: {len(all_new)}")

# Load master
with open(MASTER_PATH, encoding='utf-8') as f:
    master = json.load(f)

before = len(master)

# Remove old records for the stores/channels being replaced
replace_keys = set((r['source_store'], r['source_channel']) for r in all_new)
master = [r for r in master if (r.get('source_store'), r.get('source_channel')) not in replace_keys]
removed = before - len(master)
master.extend(all_new)

# Global dedup
seen = set()
deduped = []
for r in master:
    key = (
        r.get('source_store','')[:15],
        r.get('source_channel',''),
        r.get('product_name','')[:40].lower(),
        r.get('promo_price'),
    )
    if key not in seen:
        seen.add(key)
        deduped.append(r)

with open(MASTER_PATH, 'w', encoding='utf-8') as f:
    json.dump(deduped, f, ensure_ascii=False, indent=2)

print(f"\nMaster: removed {removed} old records, added {len(all_new)}, total {len(deduped)}")
print("Done!")
