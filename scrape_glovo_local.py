#!/usr/bin/env python3
"""
scrape_glovo_local.py — Scrape Glovo promo products locally via Playwright.

Rate-limiting strategy (avoids bot detection):
  - Human-like random delays throughout (jitter on every sleep)
  - 45-75 second pause between stores
  - Slow mouse scrolling with variable timing
  - One browser context per store (fresh session each time)
  - slow_mo=500 on browser launch to pace all Playwright actions
  - Retries with exponential backoff on "Oh, no" blocks

Scraping strategy:
  1. Accept cookies + dismiss "store closed" modal before any interaction
  2. Intercept Glovo API XHR responses (api.glovoapp.com) for product data
  3. Click into promo sections and scroll to trigger lazy-loading
  4. DOM fallback if API gave nothing

Usage:
    python scrape_glovo_local.py                  # headed, all stores
    python scrape_glovo_local.py --headless        # headless
    python scrape_glovo_local.py --stores kaufland billa
    python scrape_glovo_local.py --debug           # verbose API + modal output
    python scrape_glovo_local.py --dump-api        # save raw API JSON per store

Output:
    Prints Python list snippets ready to paste into write_glovo_data.py.
    Saves glovo_raw_YYYY-MM-DD.json for inspection.

Requirements:
    pip install playwright playwright-stealth && playwright install chromium
"""

import argparse
import json
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    from playwright_stealth import stealth_sync
    STEALTH = True
except ImportError:
    STEALTH = False

# ── Config ─────────────────────────────────────────────────────────────────────
PROMO_PERIOD    = "16.04 - 22.04.2026"
EXTRACTION_DATE = date.today().isoformat()
SOFIA_LAT, SOFIA_LON = 42.6977, 23.3219
CHROME_PATH     = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_AGENT      = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Rate-limiting — tune these if still getting blocked
STORE_GAP_MIN   = 45   # seconds to wait between stores (min)
STORE_GAP_MAX   = 75   # seconds to wait between stores (max)
PAGE_LOAD_WAIT  = 5    # seconds after page load before any interaction
SCROLL_DELAY    = 0.5  # seconds between scroll steps (will be jittered ±0.2s)
POST_CLICK_WAIT = 7    # seconds after clicking a section before scrolling
MAX_RETRIES     = 2    # retries on "Oh, no" block (with 60s backoff each)

STORES = {
    "kaufland": {
        "url": "https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof",
        "promo_section": ["Седмични предложения", "Промоции", "Акции", "Великденски"],
        "source_store": "Kaufland", "source_channel": "Glovo",
        "source_url": "https://glovoapp.com/bg/bg/sofia/stores/kaufland-sof",
    },
    "billa": {
        "url": "https://glovoapp.com/bg/bg/sofia/stores/billa-sof1",
        "promo_section": ["Промоции", "ОФЕРТИ", "Акции", "Специални оферти"],
        "source_store": "Billa", "source_channel": "Glovo",
        "source_url": "https://glovoapp.com/bg/bg/sofia/stores/billa-sof1",
    },
    "fantastico": {
        "url_candidates": [
            "https://glovoapp.com/bg/bg/sofia/stores/fantastico-sof",
            "https://glovoapp.com/bg/bg/sofia/stores/fantastico-sofia",
            "https://glovoapp.com/bg/bg/sofia/stores/fantastico",
            "https://glovoapp.com/bg/bg/sofia/stores/fantastico-bg",
        ],
        "promo_section": ["Промоции", "Акции", "Седмични предложения"],
        "source_store": "Fantastico", "source_channel": "Glovo",
        "source_url": "https://glovoapp.com/bg/bg/sofia/stores/fantastico-sof",
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def jitter(base: float, spread: float = 0.2) -> float:
    """Return base ± spread seconds."""
    return base + random.uniform(-spread, spread)


def pause(seconds: float, spread: float = 0.0):
    time.sleep(max(0.1, jitter(seconds, spread)))


def parse_unit(name: str) -> str | None:
    m = re.search(
        r"\b(\d+(?:[.,]\d+)?\s*(?:кг|г|гр|л|мл|бр|бут(?:илки?)?|пак(?:ет)?|оп(?:аковки?)?)\.?)\b",
        name, re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def eur(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if val > 500:
            return round(val / 100, 2)
        return round(float(val), 2)
    return None


def products_from_api_data(data: dict, debug=False) -> list[dict]:
    """Recursively walk Glovo API JSON and extract discounted products."""
    products = []
    seen = set()

    def process_item(item):
        name = item.get("name") or item.get("title") or ""
        name = name.strip()
        if not name or len(name) < 3:
            return

        pricing    = item.get("pricing") or {}
        price_info = item.get("price") or item.get("priceInfo") or {}

        promo_raw   = (pricing.get("crossedOutPrice") or pricing.get("originalPrice") or
                       price_info.get("crossedOutPrice") or price_info.get("originalPrice"))
        regular_raw = (pricing.get("price") or price_info.get("price") or item.get("price"))

        if item.get("discountPercentage") or item.get("discount"):
            regular_raw = pricing.get("price") or price_info.get("price") or item.get("price")
            promo_raw   = (pricing.get("discountedPrice") or price_info.get("discountedPrice")
                           or regular_raw)

        p_promo   = eur(promo_raw)
        p_regular = eur(regular_raw)

        if p_promo is None or p_regular is None:
            return
        if p_promo >= p_regular * 0.99 or p_promo < 0.05 or p_promo > 500:
            return

        unit = parse_unit(name)
        key  = (name[:40].lower(), p_promo)
        if key in seen:
            return
        seen.add(key)
        products.append({"name": name, "promo": p_promo, "reg": p_regular, "unit": unit})

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("name") and ("price" in obj or "pricing" in obj or "priceInfo" in obj):
                process_item(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    if debug and products:
        print(f"    API products parsed: {len(products)}")
    return products


def dismiss_modals(page, debug=False):
    """
    Dismiss cookie consent and 'store closed' modals before interaction.
    Returns list of what was dismissed.
    """
    dismissed = []

    # 1. Accept cookies
    for text in ["Приемане на всички", "Accept all", "Приемам"]:
        try:
            btn = page.get_by_text(text, exact=False).first
            if btn.is_visible(timeout=2000):
                btn.click()
                dismissed.append(f"cookies ({text})")
                pause(1.5, 0.3)
                break
        except Exception:
            continue

    # 2. Dismiss 'store is closed' modal — click "Schedule order" to proceed
    for text in ["Насрочване на поръчка", "Schedule an order"]:
        try:
            btn = page.get_by_text(text, exact=False).first
            if btn.is_visible(timeout=2000):
                btn.click()
                dismissed.append(f"closed-modal ({text})")
                pause(2, 0.5)
                break
        except Exception:
            continue

    # 3. Close any remaining modal via × / close button
    for sel in ['button[aria-label="Close"]', 'button[aria-label="close"]',
                '[data-testid="modal-close"]']:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                dismissed.append(f"close-btn")
                pause(1, 0.2)
                break
        except Exception:
            continue

    if dismissed and debug:
        print(f"    Dismissed: {', '.join(dismissed)}")
    return dismissed


def human_scroll(page, steps=20):
    """Scroll down the page in human-like steps with random pauses."""
    for _ in range(steps):
        page.keyboard.press("End")
        pause(SCROLL_DELAY, 0.2)
    page.keyboard.press("Home")
    pause(1, 0.3)


def load_store_page(page, url: str, debug: bool) -> bool:
    """Navigate to a store URL, retry on block. Returns True if loaded OK."""
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            backoff = 60 * attempt
            print(f"  Retry {attempt}/{MAX_RETRIES} — waiting {backoff}s backoff...")
            time.sleep(backoff)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  Navigation error: {e}")
            continue

        pause(PAGE_LOAD_WAIT, 1)
        text = page.inner_text("body")

        if "Oh, no" in text:
            print(f"  Blocked (Oh, no) — attempt {attempt + 1}")
            continue
        if "извън зоната" in text:
            print("  Outside delivery zone.")
            return False
        if "не съществува" in text:
            return False

        return True

    return False


def scrape_store(browser, store_key: str, cfg: dict, headless: bool, debug: bool,
                 dump_api: bool) -> list[dict]:
    print(f"\n── {cfg['source_store']} Glovo ──")

    captured_api = []
    api_bodies   = []

    ctx = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 768},
        geolocation={"latitude": SOFIA_LAT, "longitude": SOFIA_LON},
        permissions=["geolocation"],
        locale="bg-BG",
        timezone_id="Europe/Sofia",
        extra_http_headers={"Accept-Language": "bg-BG,bg;q=0.9,en-US;q=0.8"},
    )
    page = ctx.new_page()
    if STEALTH:
        stealth_sync(page)

    # Intercept all Glovo API responses
    def handle_response(response):
        if "api.glovoapp.com" in response.url and response.status == 200:
            try:
                body = response.json()
                short = response.url.split("?")[0]
                short = short[short.find("glovoapp.com") + 12:]
                if debug:
                    print(f"    API: {short}")
                captured_api.append(body)
                if dump_api:
                    api_bodies.append({"url": response.url.split("?")[0], "body": body})
            except Exception:
                pass

    page.on("response", handle_response)

    # ── Navigate ──────────────────────────────────────────────────────────────
    url = cfg.get("url")
    if not url:
        # Probe candidates (Fantastico — slug unknown)
        for candidate in cfg.get("url_candidates", []):
            if load_store_page(page, candidate, debug):
                url = candidate
                cfg["source_url"] = candidate
                print(f"  Found: {candidate}")
                break
        if not url:
            print("  No working URL found.")
            ctx.close()
            return []
    else:
        if not load_store_page(page, url, debug):
            print("  Could not load store page.")
            ctx.close()
            return []

    print(f"  Title: {page.title()[:70]}")

    # ── Dismiss modals before any interaction ─────────────────────────────────
    dismissed = dismiss_modals(page, debug=debug)
    if dismissed:
        print(f"  Dismissed: {', '.join(dismissed)}")

    # ── Initial scroll to render all section links ────────────────────────────
    human_scroll(page, steps=12)

    # ── Click into promo section ──────────────────────────────────────────────
    clicked = False
    for section_name in cfg.get("promo_section", []):
        for exact in (True, False):
            try:
                link = page.get_by_text(section_name, exact=exact).first
                if not link.is_visible(timeout=2000):
                    continue
                href = link.get_attribute("href")
                print(f"  Clicking section: '{section_name}'" +
                      (f" → {href}" if href else ""))
                link.click()
                pause(POST_CLICK_WAIT, 1.5)
                # Deep scroll to load all products in the section
                human_scroll(page, steps=30)
                pause(4, 1)
                clicked = True
                break
            except Exception:
                continue
        if clicked:
            break

    if not clicked:
        print("  No promo section clicked — scrolling main page only")
        human_scroll(page, steps=20)
        pause(3, 1)

    if debug:
        print(f"  Current URL: {page.url}")

    page.screenshot(path=f"glovo_{store_key}_screenshot.png")

    # ── Parse API data ────────────────────────────────────────────────────────
    all_products = []
    for body in captured_api:
        all_products.extend(products_from_api_data(body, debug=debug))

    seen = set()
    deduped = []
    for p in all_products:
        key = (p["name"][:40].lower(), p["promo"])
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    print(f"  API calls: {len(captured_api)} | Products: {len(deduped)}")

    if dump_api and api_bodies:
        dump_path = Path(f"glovo_{store_key}_api_dump.json")
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(api_bodies, f, ensure_ascii=False, indent=2)
        print(f"  API dump saved: {dump_path}")

    # ── DOM fallback ──────────────────────────────────────────────────────────
    if not deduped:
        print("  Trying DOM fallback...")
        raw = page.evaluate(r"""() => {
            const results = [];
            document.querySelectorAll(
                '[data-testid="product-card"], [data-testid="store-product-card"], ' +
                '[class*="product-card"], [class*="ProductCard"], [class*="product-item"]'
            ).forEach(el => {
                const prices = [...el.querySelectorAll('[class*="price"], [class*="Price"]')]
                    .map(p => p.innerText.trim()).join(' | ');
                const name = el.querySelector(
                    'p, h3, h4, [class*="name"], [class*="title"]'
                )?.innerText?.trim() || '';
                if (name && prices) results.push({name, prices, html: el.innerText.trim()});
            });
            return results;
        }""")
        if debug:
            print(f"    DOM elements found: {len(raw)}")

        seen2 = set()
        for item in raw:
            html = item.get("html", "").replace("\xa0", " ")
            name = item.get("name", "").strip()
            if not name or len(name) < 3:
                continue
            prices = [float(f"{a}.{b}") for a, b in re.findall(r"(\d+)[,.](\d{2})\s*€", html)]
            if len(prices) < 2:
                continue
            promo, regular = min(prices[:2]), max(prices[:2])
            if promo >= regular * 0.99:
                continue
            key = (name[:40].lower(), promo)
            if key not in seen2:
                seen2.add(key)
                deduped.append({"name": name, "promo": promo, "reg": regular,
                                "unit": parse_unit(name)})

        print(f"  DOM fallback products: {len(deduped)}")

    ctx.close()
    return deduped


def format_python(store_key: str, cfg: dict, products: list[dict]) -> str:
    store = cfg["source_store"].lower()
    lines = [
        f"# ── {cfg['source_store']} Glovo — CW16 {EXTRACTION_DATE} ({len(products)} products) ──",
        f"{store}_glovo = [",
    ]
    for p in products:
        unit_s = f'"{p["unit"]}"' if p["unit"] else "None"
        lines.append(
            f"    {{\"name\": {json.dumps(p['name'], ensure_ascii=False)}, "
            f"\"promo\": {p['promo']}, \"reg\": {p['reg']}, \"unit\": {unit_s}}},"
        )
    lines.append("]")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Glovo promo products from a BG IP with rate-limiting"
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--stores", nargs="+", choices=list(STORES.keys()),
                        default=list(STORES.keys()))
    parser.add_argument("--debug",    action="store_true")
    parser.add_argument("--dump-api", action="store_true",
                        help="Save raw API JSON per store for inspection")
    args = parser.parse_args()

    all_results = {}

    with sync_playwright() as pw:
        # slow_mo=500 paces every Playwright action to look more human
        launch_kwargs = dict(
            headless=args.headless,
            slow_mo=500,
            args=["--disable-blink-features=AutomationControlled"],
        )
        if Path(CHROME_PATH).exists():
            browser = pw.chromium.launch(executable_path=CHROME_PATH, **launch_kwargs)
            print("Using real Chrome.")
        else:
            browser = pw.chromium.launch(channel="chrome", **launch_kwargs)
            print("Using Chrome channel.")

        for i, store_key in enumerate(args.stores):
            # Rate-limiting pause between stores
            if i > 0:
                gap = random.randint(STORE_GAP_MIN, STORE_GAP_MAX)
                print(f"\n  Pausing {gap}s before next store (rate limiting)...")
                time.sleep(gap)

            cfg      = dict(STORES[store_key])
            products = scrape_store(browser, store_key, cfg, args.headless,
                                    args.debug, args.dump_api)
            all_results[store_key] = {"cfg": cfg, "products": products}

        browser.close()

    print("\n\n" + "=" * 70)
    print("RESULTS — paste into write_glovo_data.py")
    print("=" * 70)

    all_records = {}
    for store_key, result in all_results.items():
        print(f"\n{format_python(store_key, result['cfg'], result['products'])}\n")
        all_records[store_key] = result["products"]

    out = Path(f"glovo_raw_{EXTRACTION_DATE}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
    print(f"Raw data saved: {out}")

    print("\n── Summary ──")
    for sk, r in all_results.items():
        n = len(r["products"])
        print(f"  {r['cfg']['source_store']:12s}: {n:3d}  {'✓' if n else '✗'}")


if __name__ == "__main__":
    main()
