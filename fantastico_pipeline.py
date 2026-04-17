#!/usr/bin/env python3
"""
Fantastico Bulgaria — Weekly Brochure Auto-Pipeline
====================================================

Automatically discovers the current week's Fantastico brochure from
fantastico.bg, downloads it from FlippingBook, and parses it into
structured product records.

Strategy:
  1. Scrape fantastico.bg/special-offers → find FlippingBook viewer URL
  2. Construct PDF download URL from book ID
  3. Download PDF (direct requests; Playwright fallback if blocked)
  4. Detect PDF type: embedded-text (pdfplumber) vs scanned-image (OCR)
  5. Parse accordingly — text mode is preferred (higher quality)
  6. Auto-detect promo period from PDF content
  7. Merge into master JSON, replacing old Fantastico Direct records

Usage:
  python fantastico_pipeline.py               # Full auto pipeline
  python fantastico_pipeline.py --dry-run     # Parse only, no write
  python fantastico_pipeline.py --pdf PATH    # Use an already-downloaded PDF

Requirements:
  pip install requests pdfplumber
  pip install azure-ai-documentintelligence PyPDF2   (OCR fallback only)
  pip install playwright && playwright install chromium  (browser fallback only)
"""

import sys
import json
import re
import os
import time
import argparse
import logging
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
FANTASTICO_URL   = "https://www.fantastico.bg/special-offers"
FLIPPINGBOOK_BASE = "https://online.flippingbook.com/view"

WORK_DIR    = Path("fantastico_work")
MASTER_PATH = Path("bulgarian_promo_prices_merged.json")

SOURCE_STORE   = "Fantastico"
SOURCE_CHANNEL = "Direct"
SOURCE_URL     = FANTASTICO_URL
EXTRACTION_DATE = date.today().isoformat()

# Minimum avg words/page to trust embedded text over OCR
MIN_TEXT_WORDS_PER_PAGE = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}

# ── Load Azure config (optional — only needed for OCR fallback) ───────────────
try:
    import config as _cfg
    AZURE_ENDPOINT  = _cfg.AZURE_ENDPOINT
    AZURE_MODEL_ID  = _cfg.AZURE_MODEL_ID
    PAGES_PER_BATCH = _cfg.FANTASTICO_PAGES_PER_BATCH
    MAX_RETRIES     = _cfg.FANTASTICO_OCR_MAX_RETRIES
    RETRY_DELAY     = _cfg.FANTASTICO_OCR_RETRY_DELAY
except ImportError:
    AZURE_ENDPOINT  = "https://invoice2024.cognitiveservices.azure.com/"
    AZURE_MODEL_ID  = "prebuilt-read"
    PAGES_PER_BATCH = 10
    MAX_RETRIES     = 3
    RETRY_DELAY     = 5


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Discover current brochure URL from fantastico.bg
# ══════════════════════════════════════════════════════════════════════════════

def discover_flippingbook_url(session) -> tuple[str | None, str | None]:
    """
    Scrape fantastico.bg/special-offers and extract the FlippingBook viewer URL.
    Returns (viewer_url, pdf_download_url) or (None, None).

    The page uses data-url attributes on brochure-switch divs; the active one
    has class="brochure-switch hold-options active".
    """
    log.info(f"Scraping {FANTASTICO_URL} for FlippingBook embed...")
    try:
        resp = session.get(FANTASTICO_URL, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        log.error(f"Failed to fetch {FANTASTICO_URL}: {e}")
        return None, None

    # Helper: extract book_id from any FlippingBook URL string
    def _book_id_from_url(url: str) -> str | None:
        m = re.search(r'/view/(\d+)', url)
        return m.group(1) if m else None

    # Strategy 1: active brochure via data-url on the active brochure-switch div
    m = re.search(
        r'brochure-switch[^>]*active[^>]*data-url=["\']([^"\']+)["\']'
        r'|data-url=["\']([^"\']+)["\'][^>]*brochure-switch[^>]*active',
        html, re.IGNORECASE
    )
    if m:
        raw_url = m.group(1) or m.group(2)
        book_id = _book_id_from_url(raw_url)
        if book_id:
            viewer_url = f"{FLIPPINGBOOK_BASE}/{book_id}/"
            pdf_url    = f"{FLIPPINGBOOK_BASE}/{book_id}/pdf/"
            log.info(f"Found active FlippingBook (data-url): ID={book_id}  viewer={viewer_url}")
            return viewer_url, pdf_url

    # Strategy 2: first data-url pointing to FlippingBook (fallback)
    m = re.search(r'data-url=["\']([^"\']*flippingbook[^"\']+)["\']', html, re.IGNORECASE)
    if m:
        raw_url = m.group(1)
        book_id = _book_id_from_url(raw_url)
        if book_id:
            viewer_url = f"{FLIPPINGBOOK_BASE}/{book_id}/"
            pdf_url    = f"{FLIPPINGBOOK_BASE}/{book_id}/pdf/"
            log.info(f"Found FlippingBook (first data-url): ID={book_id}  viewer={viewer_url}")
            return viewer_url, pdf_url

    # Strategy 3: iframe/embed src
    m = re.search(r'(?:src|href)=["\']([^"\']*flippingbook\.com/view/\d+[^"\']*)["\']', html, re.IGNORECASE)
    if m:
        raw_url = m.group(1)
        book_id = _book_id_from_url(raw_url)
        if book_id:
            viewer_url = f"{FLIPPINGBOOK_BASE}/{book_id}/"
            pdf_url    = f"{FLIPPINGBOOK_BASE}/{book_id}/pdf/"
            log.info(f"Found FlippingBook (iframe src): ID={book_id}")
            return viewer_url, pdf_url

    # Strategy 4: any FlippingBook URL anywhere in the page
    m = re.search(r'https://online\.flippingbook\.com/view/(\d+)', html, re.IGNORECASE)
    if m:
        book_id    = m.group(1)
        viewer_url = f"{FLIPPINGBOOK_BASE}/{book_id}/"
        pdf_url    = f"{FLIPPINGBOOK_BASE}/{book_id}/pdf/"
        log.info(f"Found FlippingBook (raw URL scan): ID={book_id}")
        return viewer_url, pdf_url

    # Strategy 5: direct PDF link
    pdf_pat = re.search(r'(https://[^\s"\'<>]*fantastico[^\s"\'<>]*\.pdf)', html, re.IGNORECASE)
    if pdf_pat:
        pdf_url = pdf_pat.group(1)
        log.info(f"Found direct PDF URL: {pdf_url}")
        return pdf_url, pdf_url

    log.warning("No FlippingBook URL found in page.")
    log.debug(f"Page HTML snippet: {html[:3000]}")
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Download PDF
# ══════════════════════════════════════════════════════════════════════════════

def _is_valid_pdf(path: Path) -> bool:
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'%PDF'
    except Exception:
        return False


def download_pdf_direct(session, pdf_url: str, output_path: Path) -> bool:
    """Try downloading the PDF directly with requests. Returns True on success."""
    log.info(f"Trying direct PDF download: {pdf_url}")
    try:
        resp = session.get(pdf_url, timeout=120, stream=True, allow_redirects=True)
        resp.raise_for_status()
        with open(output_path, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        if _is_valid_pdf(output_path):
            size_kb = output_path.stat().st_size // 1024
            log.info(f"PDF downloaded successfully ({size_kb} KB): {output_path}")
            return True
        else:
            log.warning(f"Downloaded file is not a valid PDF — content type may be HTML/JS")
            output_path.unlink(missing_ok=True)
            return False
    except Exception as e:
        log.warning(f"Direct download failed: {e}")
        output_path.unlink(missing_ok=True)
        return False


def _find_cdn_pdf_url(session, book_id: str) -> str | None:
    """
    FlippingBook serves the PDF from a CDN URL embedded in the viewer JS.
    Try to extract it without a full browser.
    Patterns tried:
      - https://online.flippingbook.com/view/{id}/files/mobile/*.pdf
      - Fetch viewer HTML and grep for pdf URLs in JS config
    """
    viewer_url = f"https://online.flippingbook.com/view/{book_id}/"
    try:
        resp = session.get(viewer_url, timeout=30)
        html = resp.text
    except Exception:
        return None

    # Look for CDN PDF URL in the page source / embedded JS
    for pat in [
        r'["\'](https://[^"\']+\.pdf)["\']',
        r'pdfUrl["\s]*:["\s]*["\']([^"\']+)["\']',
        r'["\'](https://[^"\']*flippingbook[^"\']*pdf[^"\']*)["\']',
        r'["\'](https://[^"\']*\.pdf\?[^"\']*)["\']',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            url = m.group(1)
            if 'flippingbook' in url.lower() or url.endswith('.pdf'):
                log.info(f"Found CDN PDF URL in viewer source: {url}")
                return url

    return None


def download_pdf_playwright(viewer_url: str, output_path: Path, book_id: str = None) -> bool:
    """
    Use Playwright (headless Chromium) to navigate the FlippingBook viewer and
    download the PDF via the toolbar:
      1. Click the "Download" toolbar button → modal opens
      2. Click "Download the flipbook as a PDF file" in the modal → browser download
    """
    log.info("Trying Playwright browser download...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(accept_downloads=True)
            page = ctx.new_page()

            log.info(f"Navigating to: {viewer_url}")
            page.goto(viewer_url, wait_until='load', timeout=60000)
            page.wait_for_timeout(5000)
            log.info(f"Viewer title: {page.title()}")

            # Step 1: Click toolbar Download button (opens modal)
            dl_btn = page.locator('[aria-label="Download"]')
            if dl_btn.count() == 0:
                dl_btn = page.locator('[title="Download"]')
            if dl_btn.count() == 0:
                log.error("Playwright: Download toolbar button not found")
                browser.close()
                return False

            dl_btn.first.click()
            page.wait_for_timeout(2000)

            # Step 2: Click "Full Flipbook" PDF option in the modal
            full_pdf_btn = page.locator('[aria-label="Download the flipbook as a PDF file"]')
            if full_pdf_btn.count() == 0:
                full_pdf_btn = page.locator('[href="linkFull"]')
            if full_pdf_btn.count() == 0:
                full_pdf_btn = page.locator('[title="Download the flipbook as a PDF file"]')

            if full_pdf_btn.count() == 0:
                log.error("Playwright: Full PDF download option not found in modal")
                browser.close()
                return False

            log.info("Clicking 'Full Flipbook' PDF download...")
            with page.expect_download(timeout=120000) as dl_info:
                full_pdf_btn.first.click()

            dl = dl_info.value
            suggested = dl.suggested_filename
            log.info(f"Download filename: {suggested}")
            dl.save_as(str(output_path))
            # Save suggested filename as sidecar for promo period extraction
            sidecar = output_path.with_suffix('.name.txt')
            sidecar.write_text(suggested, encoding='utf-8')
            browser.close()

            if _is_valid_pdf(output_path):
                size_kb = output_path.stat().st_size // 1024
                log.info(f"PDF saved: {output_path} ({size_kb} KB)")
                return True
            else:
                log.error("Downloaded file is not a valid PDF")
                output_path.unlink(missing_ok=True)
                return False

    except Exception as e:
        log.error(f"Playwright error: {e}")
        return False


def download_pdf(session, pdf_url: str, viewer_url: str, output_path: Path,
                 book_id: str = None) -> bool:
    """Try multiple download strategies in order."""
    # 1. Direct PDF URL
    if download_pdf_direct(session, pdf_url, output_path):
        return True
    # 2. CDN URL extracted from viewer page source
    if book_id:
        cdn_url = _find_cdn_pdf_url(session, book_id)
        if cdn_url and download_pdf_direct(session, cdn_url, output_path):
            return True
    # 3. Playwright browser
    if viewer_url:
        return download_pdf_playwright(viewer_url, output_path, book_id=book_id)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Detect PDF type (embedded text vs scanned image)
# ══════════════════════════════════════════════════════════════════════════════

def detect_pdf_type(pdf_path: Path) -> str:
    """
    Returns 'text' if the PDF has sufficient embedded text, 'ocr' otherwise.
    """
    try:
        import pdfplumber
    except ImportError:
        log.warning("pdfplumber not installed — assuming OCR mode")
        return 'ocr'

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            total_pages = len(pdf.pages)
            sample_pages = min(5, total_pages)
            total_words = 0
            for page in pdf.pages[:sample_pages]:
                words = page.extract_words()
                total_words += len(words)
            avg_words = total_words / sample_pages if sample_pages else 0
            log.info(f"PDF text quality: {avg_words:.0f} avg words/page over {sample_pages} pages")
            return 'text' if avg_words >= MIN_TEXT_WORDS_PER_PAGE else 'ocr'
    except Exception as e:
        log.warning(f"Could not inspect PDF text: {e} — assuming OCR")
        return 'ocr'


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4a — Parse embedded-text PDF (pdfplumber, high quality)
# ══════════════════════════════════════════════════════════════════════════════

import re as _re

_BGN_RE       = _re.compile(r'^(\d{1,3}[.,]\d{2})\s*ЛВ\.$', _re.IGNORECASE)
_BGN_TEXT_RE  = _re.compile(r'(\d{1,3}[.,]\d{2})\s*ЛВ\.', _re.IGNORECASE)
_EUR_RE       = _re.compile(r'(\d{1,3}[.,]\d{2})\s*€')
_DISC_RE      = _re.compile(r'-(\d{1,2})%')
_UNIT_RE      = _re.compile(r'цена\s+за\s+(бр|кг|оп|л|к-кт)\.?', _re.IGNORECASE)
_CYRILLIC_RE  = _re.compile(r'[\u0400-\u04FF]')
_CYRILLIC_3RE = _re.compile(r'[\u0400-\u04FF]{3,}')

COL_LEFT_MARGIN  = 140
COL_RIGHT_MARGIN = 60

_NOISE_RE = _re.compile(
    r'^(?:'
    r'стр\.\s*\d|fantastico|www\.|ОФЕРТА ЗА|Продуктите се продават|'
    r'ТВ\s+[„"]?Фантастико|Декорацията|биоразградимите|'
    r'ПОСТНИ|вкусни идеи|KRINA|ORO$|Natural\s+Choice|'
    r'Premium\s+SELECTION|Compass$|Arriva$|GAEA$|LAURINI$|'
    r'ОТСТЪПКА$|Отстъпка$|отстъпка$|'
    r'находки|събира ни|постНИ|ФАНТАСТИКО|'
    r'Всички\s+.*(?:с\s+марка|видове)|[Мм]инимум\s+-?\d|'
    r'[Нн]е носи отговорност|[Пп]оръчки се|Алергени:|catering@|тел\.\s*\+|'
    r'7\s+DAYS|СЕДМИЦА НА|NEW[!]?|HOBO[!]?|'
    r'\*+|[Пп]ериод на кампанията|[Уу]икенд оферта|'
    r'[Пп]редложението е валидно|[Аа]кцията е валидна|'
    r'[Пп]родуктите се продават|[Дд]екорацията|'
    r'е валидно за магазините|валидно за магазините|'
    r'^\d{1,3}$|^[A-Z0-9\s\.\-\!\?]{1,10}$'
    r')',
    _re.IGNORECASE,
)


def _to_float(s: str) -> float:
    return float(s.replace(',', '.'))


def _is_noise(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 3:
        return True
    if _NOISE_RE.search(t):
        return True
    if _re.match(r'^[\d.,€%\s\-\+\=\/]+$', t):
        return True
    if _re.match(r'^цена\s+за', t, _re.IGNORECASE):
        return True
    return False


def _clean_name(lines: list) -> str | None:
    name_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if _re.match(r'^\d{1,3}[.,]\d{2}\s*[€ЛВ]', line, _re.IGNORECASE):
            break
        if _re.match(r'^-\d{1,2}%', line):
            break
        if _re.match(r'^цена\s+за', line, _re.IGNORECASE):
            break
        if _is_noise(line) and not _re.search(r'\d+\s*(?:г|кг|мл|л|бр)\b', line, _re.IGNORECASE):
            continue
        name_lines.append(line)
    if not name_lines:
        return None
    name = ' '.join(name_lines)
    name = _re.sub(r'\s*цена за\s+\S+\.?\s*$', '', name, flags=_re.IGNORECASE)
    name = _re.sub(r'\s*произход\s+\S+.*$', '', name, flags=_re.IGNORECASE)
    name = _re.sub(r'\s*насипн[аи]\s+от щандова витрина\s*$', '', name, flags=_re.IGNORECASE)
    name = _re.sub(r'\s+', ' ', name).strip()
    if len(name) < 6 or not _CYRILLIC_RE.search(name):
        return None
    return name


def _extract_page_products(page, page_num: int) -> list:
    products = []
    words = page.extract_words(x_tolerance=5, y_tolerance=3)
    if not words:
        return products

    # Find BGN price words
    bgn_words = []
    for w in words:
        m = _BGN_RE.match(w['text'])
        if m:
            bgn_words.append({
                'price': _to_float(m.group(1)),
                'xc': (w['x0'] + w['x1']) / 2,
                'x0': w['x0'], 'x1': w['x1'],
                'top': w['top'], 'bottom': w['bottom'],
            })

    # Handle split "4.40 ЛВ." across two words
    i = 0
    while i < len(words) - 1:
        w1, w2 = words[i], words[i + 1]
        combined = w1['text'] + w2['text']
        m = _BGN_RE.match(combined)
        if m and abs(w2['top'] - w1['top']) < 5:
            xc = (w1['x0'] + w2['x1']) / 2
            already = any(abs(b['xc'] - xc) < 5 and abs(b['top'] - w1['top']) < 5
                          for b in bgn_words)
            if not already:
                bgn_words.append({
                    'price': _to_float(m.group(1)),
                    'xc': xc,
                    'x0': w1['x0'], 'x1': w2['x1'],
                    'top': w1['top'], 'bottom': w2['bottom'],
                })
        i += 1

    if not bgn_words:
        return products

    bgn_words.sort(key=lambda b: b['top'])

    for bgn in bgn_words:
        price = bgn['price']
        if price < 0.10 or price > 500:
            continue

        x_lo = bgn['x0'] - COL_LEFT_MARGIN
        x_hi = bgn['x1'] + COL_RIGHT_MARGIN
        col_words_above = [
            w for w in words
            if w['x0'] >= x_lo and w['x1'] <= x_hi + 40 and w['top'] < bgn['top'] - 2
        ]

        lower_bound_top = 0
        for other_bgn in bgn_words:
            if (other_bgn is not bgn
                    and other_bgn['top'] < bgn['top']
                    and other_bgn['bottom'] > lower_bound_top):
                lower_bound_top = other_bgn['bottom']
        col_words_above = [w for w in col_words_above if w['top'] >= lower_bound_top]
        col_words_above.sort(key=lambda w: (w['top'], w['x0']))

        line_groups: dict = {}
        for w in col_words_above:
            line_key = round(w['top'] / 2) * 2
            line_groups.setdefault(line_key, []).append(w['text'])
        lines = [' '.join(line_groups[k]) for k in sorted(line_groups.keys())]

        full_text = '\n'.join(lines)
        eur_prices = [_to_float(m.group(1)) for m in _EUR_RE.finditer(full_text)]

        regular_price = None
        promo_price_eur = None
        if len(eur_prices) >= 2:
            regular_price = eur_prices[0]
            promo_price_eur = eur_prices[1]
        elif len(eur_prices) == 1:
            disc_m = _DISC_RE.search(full_text)
            if disc_m:
                disc = int(disc_m.group(1))
                promo_price_eur = eur_prices[0]
                regular_price = round(promo_price_eur / (1 - disc / 100), 2)

        if promo_price_eur is None:
            promo_price_eur = round(price / 1.95583, 2)
        if regular_price is None:
            continue
        if promo_price_eur >= regular_price * 1.05:
            continue

        unit_m = _UNIT_RE.search(full_text)
        unit = None
        if unit_m:
            unit = {'кг': 'кг', 'бр': 'бр', 'оп': 'опаковка',
                    'л': 'л', 'к-кт': 'к-кт'}.get(unit_m.group(1).lower())

        name_lines = []
        for line in lines:
            if _EUR_RE.search(line) or _DISC_RE.search(line):
                continue
            if _BGN_TEXT_RE.search(line):
                continue
            if _re.match(r'^цена\s+за', line, _re.IGNORECASE):
                continue
            if _is_noise(line):
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


def parse_text_pdf(pdf_path: Path) -> tuple[list, str]:
    """
    Parse an embedded-text PDF with pdfplumber.
    Returns (raw_products, detected_promo_period).
    """
    import pdfplumber
    all_raw = []
    seen = set()
    promo_period = EXTRACTION_DATE
    full_text_sample = ""

    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        log.info(f"PDF: {total} pages (text mode)")
        for i, page in enumerate(pdf.pages):
            # Collect text from first few pages to detect promo period
            if i < 3:
                full_text_sample += (page.extract_text() or "") + "\n"

            page_products = _extract_page_products(page, i + 1)
            for p in page_products:
                key = (p['name'][:40].lower(), p['promo_price'])
                if key not in seen:
                    seen.add(key)
                    all_raw.append(p)
            if page_products:
                log.info(f"  Page {i+1:2d}: {len(page_products)} products")

    # Detect promo period from page text
    period = _detect_promo_period(full_text_sample)
    if period:
        promo_period = period

    return all_raw, promo_period


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4b — Parse image PDF via Azure DI OCR (fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _get_azure_key():
    """Resolve Azure key from secrets.py or environment."""
    try:
        import secrets as _s
        if hasattr(_s, 'AZURE_KEY') and _s.AZURE_KEY and 'your-azure' not in _s.AZURE_KEY:
            return _s.AZURE_KEY
    except ImportError:
        pass
    return os.environ.get('AZURE_DI_KEY')


def _ocr_one_batch(pdf_path: Path, endpoint: str, key: str) -> dict:
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.documentintelligence import DocumentIntelligenceClient

    client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))
    data = pdf_path.read_bytes()
    log.info(f"  OCR: {pdf_path.name} ({len(data)//1024} KB)")

    try:
        poller = client.begin_analyze_document(
            AZURE_MODEL_ID, body=data, content_type="application/pdf"
        )
    except TypeError:
        poller = client.begin_analyze_document(
            AZURE_MODEL_ID, analyze_request=data, content_type="application/pdf"
        )

    result = poller.result()
    pages_data = []
    for pg in result.pages:
        pages_data.append({
            "page_number": pg.page_number,
            "text": "\n".join(ln.content for ln in pg.lines),
            "lines": [ln.content for ln in pg.lines],
        })
    return {"pages": pages_data, "full_text": result.content or "", "source_file": str(pdf_path)}


def _split_pdf(pdf_path: Path, batch_dir: Path) -> list:
    """Split into PAGES_PER_BATCH-page chunks."""
    from PyPDF2 import PdfReader, PdfWriter
    batch_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    batches = []
    for start in range(0, total, PAGES_PER_BATCH):
        end = min(start + PAGES_PER_BATCH, total)
        num = start // PAGES_PER_BATCH + 1
        out = batch_dir / f"batch_{num:03d}_pages_{start+1}-{end}.pdf"
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        with open(out, 'wb') as f:
            writer.write(f)
        batches.append(out)
    return batches


# BGN / EUR patterns for OCR text
_OCR_BGN_RE = re.compile(r"(\d{1,3}[.,]\d{1,2})\s*(?:ЛВ|лв|JB|MB)\.?(?!\d)", re.IGNORECASE)
_OCR_EUR_RE = re.compile(r"(\d{1,3}[.,]\d{2})\s*[€ЄЕ]|(\d{1,3}[.,]\d{2})\s+6(?!\d)", re.IGNORECASE)
_OCR_DISC_RE = re.compile(r"-\s*(\d{1,2})\s*%")


def _parse_bgn(s: str) -> float:
    return float(s.replace(',', '.'))


def _is_name_line_ocr(line: str) -> bool:
    line = line.strip()
    if not line or len(line) < 4:
        return False
    if re.match(r'^[\d.]+\s*[€%]', line):
        return False
    if re.match(r'^-?\d+%', line):
        return False
    if _OCR_BGN_RE.match(line):
        return False
    if re.match(r'^цена\s+за', line, re.IGNORECASE):
        return False
    if re.match(r'^\d{1,3}$', line):
        return False
    return True


def _parse_ocr_page_text(text: str) -> list:
    """Extract products from a single page's OCR text."""
    products = []

    # Fix OCR artifacts
    text = re.sub(r"\b(\d{1,3})-(\d{1,2})\s*(?:ЛВ|лв)", lambda m: f"{m.group(1)}.{m.group(2)} ЛВ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)[•·](\d{1,2})\s*(?:ЛВ|лв)", lambda m: f"{m.group(1)}.{m.group(2)} ЛВ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d)\s+(\d{2})\s+(?:ЛВ|лв)", lambda m: f"{m.group(1)}.{m.group(2)} ЛВ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(JB|MB)\.?", "ЛВ", text)

    bgn_matches = list(_OCR_BGN_RE.finditer(text))
    seen = set()

    for idx, bgn_m in enumerate(bgn_matches):
        try:
            bgn_price = _parse_bgn(bgn_m.group(1))
        except ValueError:
            continue
        if bgn_price < 0.20 or bgn_price > 980:
            continue

        bgn_pos = bgn_m.start()
        window_start = bgn_matches[idx - 1].end() if idx > 0 else max(0, bgn_pos - 600)
        window = text[window_start:bgn_pos]

        promo_eur = round(bgn_price / 1.95583, 2)

        # Try to find regular price from discount %
        disc_m = _OCR_DISC_RE.search(window)
        regular_eur = None
        if disc_m:
            disc = int(disc_m.group(1))
            if 5 <= disc <= 70:
                regular_eur = round(promo_eur / (1 - disc / 100), 2)
        if regular_eur is None:
            for em in _OCR_EUR_RE.finditer(window):
                raw = em.group(1) or em.group(2)
                if not raw:
                    continue
                try:
                    val = float(raw.replace(',', '.'))
                    if val > promo_eur * 1.05:
                        regular_eur = val
                        break
                except ValueError:
                    pass
        if regular_eur is None:
            continue

        # Extract name lines
        lines = [l.strip() for l in window.split('\n') if l.strip()]
        name_lines = [l for l in lines if _is_name_line_ocr(l) and _CYRILLIC_RE.search(l)]
        if not name_lines:
            continue
        name = ' '.join(name_lines[-3:])
        name = re.sub(r'\s+', ' ', name).strip()
        if len(name) < 5 or not _CYRILLIC_3RE.search(name):
            continue

        key = (name[:40].lower(), promo_eur)
        if key in seen:
            continue
        seen.add(key)

        products.append({
            'name': name,
            'promo_price': promo_eur,
            'regular_price': regular_eur,
            'unit': None,
            'page': 0,
        })

    return products


def parse_ocr_pdf(pdf_path: Path, azure_key: str) -> tuple[list, str]:
    """
    Split PDF into batches, OCR via Azure DI, parse products.
    Returns (raw_products, detected_promo_period).
    """
    batch_dir = WORK_DIR / "pdf_batches"
    ocr_dir   = WORK_DIR / "ocr_output"
    ocr_dir.mkdir(parents=True, exist_ok=True)

    batches = _split_pdf(pdf_path, batch_dir)
    log.info(f"Split into {len(batches)} batches")

    all_raw = []
    seen = set()
    promo_period = EXTRACTION_DATE
    full_text_sample = ""

    for i, batch_path in enumerate(batches):
        cache = ocr_dir / f"{batch_path.stem}_ocr.json"

        if cache.exists():
            log.info(f"  Batch {i+1}/{len(batches)}: {batch_path.name} — using cache")
            with open(cache, encoding='utf-8') as f:
                result = json.load(f)
        else:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = _ocr_one_batch(batch_path, AZURE_ENDPOINT, azure_key)
                    with open(cache, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    log.info(f"  Batch {i+1}/{len(batches)}: {batch_path.name} — {len(result['pages'])} pages OCR'd")
                    break
                except Exception as e:
                    log.warning(f"  Batch {i+1} attempt {attempt} failed: {e}")
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY)
            else:
                log.error(f"  Batch {i+1} failed permanently — skipping")
                continue

        for pg in result.get('pages', []):
            text = pg.get('text', '')
            if i == 0 and pg.get('page_number', 1) <= 3:
                full_text_sample += text + '\n'
            for p in _parse_ocr_page_text(text):
                key = (p['name'][:40].lower(), p['promo_price'])
                if key not in seen:
                    seen.add(key)
                    all_raw.append(p)

        if i < len(batches) - 1:
            time.sleep(1)

    period = _detect_promo_period(full_text_sample)
    if period:
        promo_period = period

    return all_raw, promo_period


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Auto-detect promo period from PDF text
# ══════════════════════════════════════════════════════════════════════════════

def _detect_promo_period(text: str) -> str | None:
    """
    Find date range in text like "02.04 - 08.04.2026" or "02.04.2026-08.04.2026".
    Returns formatted string or None.
    """
    # Pattern: DD.MM.YYYY - DD.MM.YYYY or DD.MM - DD.MM.YYYY
    patterns = [
        r'(\d{2}\.\d{2}(?:\.\d{4})?)\s*[-–]\s*(\d{2}\.\d{2}\.\d{4})',
        r'(\d{2}\.\d{2})\s*[-–]\s*(\d{2}\.\d{2}(?:\.\d{4})?)',
        r'валидно[то]?\s+(?:от\s+)?(\d{2}\.\d{2}(?:\.\d{4})?)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            if m.lastindex >= 2:
                return f"{m.group(1)} - {m.group(2)}"
            else:
                return m.group(1)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Build master JSON records
# ══════════════════════════════════════════════════════════════════════════════

def _auto_categorize(name: str) -> str | None:
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


def build_records(raw: list, promo_period: str) -> list:
    records, seen = [], set()
    for p in raw:
        name = p['name']
        if not _CYRILLIC_3RE.search(name):
            continue
        key = (name[:40].lower(), p['promo_price'])
        if key in seen:
            continue
        seen.add(key)
        records.append({
            'source_store':     SOURCE_STORE,
            'source_channel':   SOURCE_CHANNEL,
            'product_name':     name,
            'product_category': _auto_categorize(name),
            'regular_price':    p['regular_price'],
            'promo_price':      p['promo_price'],
            'unit':             p.get('unit'),
            'price_per_unit':   None,
            'promo_period':     promo_period,
            'source_url':       SOURCE_URL,
            'extraction_date':  EXTRACTION_DATE,
        })
    return records


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Merge into master JSON
# ══════════════════════════════════════════════════════════════════════════════

def merge_into_master(records: list) -> int:
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

    log.info(f"Master updated: removed {removed} old Fantastico Direct records, "
             f"added {len(records)}, total {len(deduped)}")
    return len(records)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Fantastico weekly brochure auto-pipeline",
        epilog=(
            "Examples:\n"
            "  python fantastico_pipeline.py                  # Full auto\n"
            "  python fantastico_pipeline.py --pdf PATH       # Skip download\n"
            "  python fantastico_pipeline.py --dry-run        # Parse only\n"
            "  python fantastico_pipeline.py --force-ocr      # Force OCR even if text detected\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument('--pdf',       help='Path to already-downloaded PDF (skips discovery & download)')
    parser.add_argument('--dry-run',   action='store_true', help='Parse and report only — no master update')
    parser.add_argument('--force-ocr', action='store_true', help='Force OCR even if embedded text detected')
    args = parser.parse_args()

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    import requests
    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Determine PDF path ────────────────────────────────────────────────────
    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            log.error(f"PDF not found: {pdf_path}")
            sys.exit(1)
        log.info(f"Using provided PDF: {pdf_path}")
        viewer_url = None
    else:
        # Discover current brochure URL
        viewer_url, pdf_url = discover_flippingbook_url(session)
        book_id = re.search(r'/view/(\d+)', viewer_url or '')
        book_id = book_id.group(1) if book_id else None

        if not pdf_url:
            log.error(
                "Could not find Fantastico brochure URL.\n"
                "Possible causes:\n"
                "  - fantastico.bg changed their page structure\n"
                "  - No brochure published this week yet\n"
                "Workaround: download the PDF manually and pass with --pdf PATH"
            )
            sys.exit(1)

        # Check for a cached PDF from today
        pdf_path = WORK_DIR / f"fantastico_brochure_{EXTRACTION_DATE}.pdf"
        if pdf_path.exists() and _is_valid_pdf(pdf_path):
            log.info(f"Using today's cached PDF: {pdf_path}")
        else:
            # Also check the generic name (backward compat)
            generic = WORK_DIR / "fantastico_brochure.pdf"
            if generic.exists() and _is_valid_pdf(generic):
                # Check if it was modified today
                import datetime
                mtime = datetime.date.fromtimestamp(generic.stat().st_mtime)
                if mtime == date.today():
                    pdf_path = generic
                    log.info(f"Using cached PDF (modified today): {pdf_path}")
                else:
                    log.info("Cached PDF is from a previous run — re-downloading")
                    success = download_pdf(session, pdf_url, viewer_url, pdf_path, book_id=book_id)
                    if not success:
                        log.error(
                            "PDF download failed.\n"
                            "Manual fallback:\n"
                            f"  1. Open {viewer_url or pdf_url}\n"
                            f"  2. Download the PDF\n"
                            f"  3. Re-run: python fantastico_pipeline.py --pdf <saved_path>"
                        )
                        sys.exit(1)
            else:
                success = download_pdf(session, pdf_url, viewer_url, pdf_path, book_id=book_id)
                if not success:
                    log.error(
                        "PDF download failed.\n"
                        "Manual fallback:\n"
                        f"  1. Open {viewer_url or pdf_url}\n"
                        f"  2. Download the PDF\n"
                        f"  3. Re-run: python fantastico_pipeline.py --pdf <saved_path>"
                    )
                    sys.exit(1)

    # ── Detect PDF type and parse ─────────────────────────────────────────────
    pdf_type = 'ocr' if args.force_ocr else detect_pdf_type(pdf_path)
    log.info(f"PDF mode: {pdf_type.upper()}")

    if pdf_type == 'text':
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            log.error("pdfplumber not installed. Install: pip install pdfplumber")
            sys.exit(1)
        raw, promo_period = parse_text_pdf(pdf_path)
    else:
        azure_key = _get_azure_key()
        if not azure_key:
            log.error(
                "Azure DI key required for OCR mode.\n"
                "Set AZURE_KEY in secrets.py or env var AZURE_DI_KEY."
            )
            sys.exit(1)
        raw, promo_period = parse_ocr_pdf(pdf_path, azure_key)

    # If period detection fell back to today's date, try extracting from the original filename
    if promo_period == EXTRACTION_DATE:
        # Check sidecar file (saved by Playwright downloader with original filename)
        sidecar = pdf_path.with_suffix('.name.txt')
        if sidecar.exists():
            original_name = sidecar.read_text(encoding='utf-8')
        else:
            original_name = pdf_path.name
        name_period = _detect_promo_period(original_name)
        if name_period:
            promo_period = name_period
            log.info(f"Promo period extracted from filename: {promo_period}")

    log.info(f"Promo period: {promo_period}")
    log.info(f"Raw products extracted: {len(raw)}")

    records = build_records(raw, promo_period)
    log.info(f"Final records after dedup/validation: {len(records)}")

    if not records:
        log.error("No products extracted — check the PDF and parser logs above")
        sys.exit(1)

    # ── Report ────────────────────────────────────────────────────────────────
    by_cat: dict = {}
    for r in records:
        cat = r['product_category'] or 'Некласифицирани'
        by_cat[cat] = by_cat.get(cat, 0) + 1
    log.info("Products by category:")
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        log.info(f"  {cat}: {n}")

    if args.dry_run:
        log.info("DRY RUN — master JSON not updated")
        log.info("Sample records:")
        for r in records[:10]:
            print(f"  [{r['product_category']}] {r['product_name']} "
                  f"| promo={r['promo_price']} reg={r['regular_price']}")
    else:
        merge_into_master(records)

    log.info("Done.")


if __name__ == '__main__':
    main()
