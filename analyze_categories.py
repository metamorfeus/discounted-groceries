#!/usr/bin/env python3
"""
Изпраща всички 2,222 продукта до Azure OpenAI GPT-4o за анализ на категориите.

Резултат:
  - Предложения за нови подкатегории (само ако >5 продукта отговарят)
  - Грешно класифицирани продукти с предложена корекция
  - Запазва report в category_analysis_report.json
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Import from main script — safe because main() is under __name__ == '__main__' guard
sys.path.insert(0, str(Path(__file__).parent))
from generate_cheapest_xlsx import (
    RULES, enrich, load_azure,
    BASE, MASTER_PATH, OVERRIDES_PATH,
)

try:
    import openai
except ImportError:
    print("Грешка: pip install openai")
    sys.exit(1)

BATCH_SIZE       = 50
MIN_ITEMS        = 5   # minimum unique products for a new subcategory to be surfaced
OUTPUT_REPORT    = BASE / "category_analysis_report.json"

# ── Build current category list string ────────────────────────────────────────
_CAT_PAIRS = sorted(set(f"{cat} → {sub}" for cat, sub, _, _ in RULES))
_CAT_LIST_STR = "\n".join(f"  - {c}" for c in _CAT_PAIRS)


# ── Azure client ──────────────────────────────────────────────────────────────
def make_client(cfg, key):
    return openai.AzureOpenAI(
        api_key=key,
        azure_endpoint=cfg['endpoint'],
        api_version=cfg.get('api_version', '2024-02-01'),
    )


# ── Single batch analysis call ────────────────────────────────────────────────
def analyze_batch(client, cfg, batch, extra_context=""):
    items_str = "\n".join(
        f"{i+1}. [{it['category']} → {it['subcategory']}] "
        f"{it['product_name']} | {it.get('store', '')} | "
        f"{it.get('price', '')} лв. | {it.get('unit', '') or 'няма'}"
        for i, it in enumerate(batch)
    )

    prompt = (
        "Ти анализираш продукти от български супермаркети за оптимизация на категориите.\n\n"
        f"ТЕКУЩИ КАТЕГОРИИ (категория → подкатегория):\n{_CAT_LIST_STR}\n\n"
        f"{extra_context}"
        f"ПРОДУКТИ:\n{items_str}\n\n"
        "ЗАДАЧИ:\n"
        "1. НОВИ ПОДКАТЕГОРИИ: Идентифицирай групи продукти (поне 3 в тази партида) "
        "които не се вписват добре в нито една от текущите подкатегории. "
        "Предложи нова категория и подкатегория на БЪЛГАРСКИ.\n"
        "2. ГРЕШНО КЛАСИФИЦИРАНИ: Маркирай продукти, чиято ТЕКУЩА категория изглежда очевидно неправилна, "
        "и предложи правилната категория.\n\n"
        "СТРОГО ПРАВИЛО: Предлагай САМО когато си абсолютно сигурен. НЕ ИЗМИСЛЯЙ!\n"
        "Ако нямаш предложения — върни празни списъци.\n\n"
        'Върни САМО JSON:\n'
        '{"new_subcategories": [{"category": "...", "subcategory": "...", '
        '"reason": "...", "example_products": ["..."]}], '
        '"misclassified": [{"product_name": "...", "current_category": "...", '
        '"current_subcategory": "...", "suggested_category": "...", '
        '"suggested_subcategory": "...", "reason": "..."}]}'
    )

    try:
        resp = client.chat.completions.create(
            model=cfg['deployment_name'],
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
            timeout=cfg.get('timeout_seconds', 60),
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"  [грешка: {e}]", flush=True)
        return {"new_subcategories": [], "misclassified": []}


# ── Run batched analysis ───────────────────────────────────────────────────────
def run_analysis(client, cfg, items, label, extra_context=""):
    batches = [items[i:i+BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    print(f"\n{label} ({len(items)} продукта, {len(batches)} партиди)...", flush=True)

    all_new_subcats  = []
    all_misclassified = []

    for idx, batch in enumerate(batches, 1):
        print(f"  Партида {idx}/{len(batches)}...", end=" ", flush=True)
        result = analyze_batch(client, cfg, batch, extra_context)
        ns = result.get("new_subcategories", []) or []
        mc = result.get("misclassified", []) or []
        print(f"нови: {len(ns)}, грешни: {len(mc)}", flush=True)
        all_new_subcats.extend(ns)
        all_misclassified.extend(mc)
        time.sleep(0.5)

    return all_new_subcats, all_misclassified


# ── Aggregate & filter suggestions ────────────────────────────────────────────
def aggregate_new_subcats(raw_suggestions):
    """Merge duplicate suggestions, count unique example products, filter by MIN_ITEMS."""
    grouped = defaultdict(lambda: {"reasons": [], "products": set(), "batches": 0})

    for ns in raw_suggestions:
        cat = (ns.get("category") or "").strip()
        sub = (ns.get("subcategory") or "").strip()
        if not cat or not sub:
            continue
        key = (cat, sub)
        grouped[key]["batches"] += 1
        if ns.get("reason"):
            grouped[key]["reasons"].append(ns["reason"])
        for p in ns.get("example_products") or []:
            grouped[key]["products"].add(str(p).strip())

    result = []
    for (cat, sub), data in sorted(grouped.items()):
        unique_products = sorted(data["products"])
        if len(unique_products) > MIN_ITEMS:
            result.append({
                "category": cat,
                "subcategory": sub,
                "mentioned_in_batches": data["batches"],
                "unique_product_count": len(unique_products),
                "example_products": unique_products[:20],
                "reason": data["reasons"][0] if data["reasons"] else "",
            })

    # Sort by product count descending
    result.sort(key=lambda x: x["unique_product_count"], reverse=True)
    return result


def aggregate_misclassified(raw_mc):
    """Deduplicate by product_name, keep first suggestion per product."""
    seen = {}
    for mc in raw_mc:
        name = (mc.get("product_name") or "").strip()
        if name and name not in seen:
            seen[name] = mc
    return list(seen.values())


# ── Pretty-print report ───────────────────────────────────────────────────────
def print_report(new_subcats, misclassified):
    print("\n" + "=" * 70)
    print(f"ПРЕДЛОЖЕНИЯ ЗА НОВИ ПОДКАТЕГОРИИ (>{MIN_ITEMS} продукта)")
    print("=" * 70)
    if new_subcats:
        for s in new_subcats:
            print(f"\n  [{s['category']}] → \"{s['subcategory']}\"")
            print(f"  Уникални продукти: {s['unique_product_count']}  |  "
                  f"Партиди: {s['mentioned_in_batches']}")
            print(f"  Причина: {s['reason']}")
            print("  Примери:")
            for p in s["example_products"][:8]:
                print(f"    - {p}")
    else:
        print("  Няма предложения над прага.")

    print("\n" + "=" * 70)
    print(f"ГРЕШНО КЛАСИФИЦИРАНИ ({len(misclassified)} продукта)")
    print("=" * 70)
    if misclassified:
        for mc in misclassified[:40]:
            cur  = f"{mc.get('current_category','')} → {mc.get('current_subcategory','')}"
            sugg = f"{mc.get('suggested_category','')} → {mc.get('suggested_subcategory','')}"
            print(f"\n  \"{mc.get('product_name','')}\"")
            print(f"  Текущо:    {cur}")
            print(f"  Предложено: {sugg}")
            print(f"  Причина:   {mc.get('reason','')}")
        if len(misclassified) > 40:
            print(f"\n  ... и още {len(misclassified)-40} — вж. {OUTPUT_REPORT.name}")
    else:
        print("  Не са открити очевидно грешно класифицирани продукти.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Зареждам данни...", flush=True)
    raw = json.loads(MASTER_PATH.read_text(encoding='utf-8'))
    print(f"  {len(raw)} записа", flush=True)

    overrides = {}
    if OVERRIDES_PATH.exists():
        try:
            data      = json.loads(OVERRIDES_PATH.read_text(encoding='utf-8'))
            overrides = data.get('overrides', {})
        except Exception:
            pass

    print("Класифициране (само правила)...", flush=True)
    enriched     = enrich(raw, overrides)
    classified   = [it for it in enriched if it['category'] != 'Некласифицирани']
    unclassified = [it for it in enriched if it['category'] == 'Некласифицирани']
    print(f"  Класифицирани: {len(classified)}/{len(enriched)}", flush=True)
    print(f"  Некласифицирани (без правило): {len(unclassified)}", flush=True)

    print("Зареждам Azure конфигурация...", flush=True)
    cfg, key = load_azure()
    if not key:
        print("Грешка: липсва API ключ в azure_secrets.json")
        sys.exit(1)
    client = make_client(cfg, key)

    # ── Pass 1: All 2,222 items ────────────────────────────────────────────────
    ns1, mc1 = run_analysis(
        client, cfg, enriched,
        label="Анализ 1 — всички продукти",
    )

    # ── Pass 2: Unclassified items only ────────────────────────────────────────
    ns2, mc2 = [], []
    if unclassified:
        ns2, mc2 = run_analysis(
            client, cfg, unclassified,
            label="Анализ 2 — некласифицирани продукти",
            extra_context=(
                "ВНИМАНИЕ: Тези продукти НЕ са разпознати от правилата. "
                "Фокусирай се върху нови категории ИЛИ посочи в коя СЪЩЕСТВУВАЩА принадлежат.\n\n"
            ),
        )

    # ── Aggregate ──────────────────────────────────────────────────────────────
    print("\nОбобщавам...", flush=True)
    new_subcats   = aggregate_new_subcats(ns1 + ns2)
    misclassified = aggregate_misclassified(mc1 + mc2)
    print(f"  Нови подкатегории (>{MIN_ITEMS} продукта): {len(new_subcats)}", flush=True)
    print(f"  Грешно класифицирани: {len(misclassified)}", flush=True)

    # ── Save report ────────────────────────────────────────────────────────────
    report = {
        "new_subcategory_suggestions": new_subcats,
        "misclassified_items": misclassified,
        "stats": {
            "total_items": len(enriched),
            "classified_by_rules": len(classified),
            "unclassified_by_rules": len(unclassified),
            "raw_new_subcat_suggestions": len(ns1) + len(ns2),
            "filtered_new_subcats_above_threshold": len(new_subcats),
            "misclassified_flagged": len(misclassified),
        },
    }
    OUTPUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    # ── Print report ───────────────────────────────────────────────────────────
    print_report(new_subcats, misclassified)
    print(f"\nПълен доклад: {OUTPUT_REPORT.name}")


if __name__ == '__main__':
    main()
