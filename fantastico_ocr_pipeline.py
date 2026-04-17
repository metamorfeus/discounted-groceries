#!/usr/bin/env python3
"""
Fantastico Bulgaria — Brochure PDF → OCR → Structured Products Pipeline
========================================================================

Source: https://online.flippingbook.com/view/738517692/pdf/
        (FlippingBook viewer for fantastico.bg weekly brochure)

Pipeline:
  1. Download the PDF from FlippingBook
  2. Split into batches of N pages (Azure DI has size limits)
  3. OCR each batch via Azure Document Intelligence (prebuilt-read)
  4. Parse OCR text into structured product records
  5. Validate, deduplicate, and merge with existing dataset
  6. Output JSON

Requirements:
  pip install azure-ai-documentintelligence PyPDF2 requests

Usage:
  # Full pipeline (download + OCR + parse):
  python3 fantastico_ocr_pipeline.py --key YOUR_AZURE_KEY

  # If you already have the PDF:
  python3 fantastico_ocr_pipeline.py --key YOUR_AZURE_KEY --pdf fantastico_brochure.pdf

  # If you already have OCR text files:
  python3 fantastico_ocr_pipeline.py --ocr-dir ocr_output/

  # Merge with existing dataset:
  python3 fantastico_ocr_pipeline.py --ocr-dir ocr_output/ --existing bulgarian_promo_prices_2026-03-29.json
"""

import json
import re
import os
import sys
import time
import argparse
import logging
from pathlib import Path
from datetime import date

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─── CONFIGURATION ───────────────────────────────────────────────────────────

FLIPPINGBOOK_PDF_URL = "https://online.flippingbook.com/view/738517692/pdf/"
FLIPPINGBOOK_VIEW_URL = "https://online.flippingbook.com/view/738517692/"

# Azure Document Intelligence
AZURE_ENDPOINT = "https://invoice2024.cognitiveservices.azure.com/"
AZURE_MODEL_ID = "prebuilt-read"

# Pipeline settings
PAGES_PER_BATCH = 10         # Pages per OCR batch (Azure has ~50MB limit per request)
MAX_RETRIES = 3              # Retries per OCR batch on failure
RETRY_DELAY = 5              # Seconds between retries

# Output
SOURCE_STORE = "Fantastico"
SOURCE_CHANNEL = "Direct"
SOURCE_URL = "https://www.fantastico.bg/special-offers"
EXTRACTION_DATE = date.today().isoformat()
DEFAULT_PROMO_PERIOD = "26.03 - 01.04.2026"

# EUR → BGN fixed conversion rate (as of Bulgaria's eurozone entry preparation)
EUR_TO_BGN = 1.95583

# ─── STEP 1: DOWNLOAD PDF ───────────────────────────────────────────────────

def download_pdf_from_url(pdf_url, output_path):
    """Download a PDF from a direct URL. Returns path on success, None on failure."""
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    log.info(f"Downloading PDF from: {pdf_url}")
    resp = requests.get(pdf_url, headers=headers, allow_redirects=True, timeout=120, stream=True)
    resp.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    with open(output_path, "rb") as f:
        header = f.read(4)
    if header != b'%PDF':
        log.error(f"Downloaded file is NOT a valid PDF (header: {header!r}) — deleting")
        os.remove(output_path)
        return None

    log.info(f"PDF saved: {output_path} ({size_mb:.1f} MB)")
    return output_path


def download_pdf_with_browser(output_path):
    """
    Use Selenium to automate a real local Chrome browser:
      1. Open the FlippingBook /pdf/ page
      2. Wait for JS to render the download UI
      3. Find and click the download button
      4. Wait for the PDF file to appear in the download folder

    Requirements: pip install selenium
    Chrome browser must be installed. ChromeDriver is auto-managed by Selenium 4+.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        log.error(
            "Selenium is required for browser automation. Install with:\n"
            "  pip install selenium"
        )
        return None

    download_dir = os.path.abspath(os.path.dirname(output_path) or ".")
    os.makedirs(download_dir, exist_ok=True)

    # Configure Chrome to download PDFs instead of opening them
    chrome_options = Options()
    chrome_options.add_experimental_option("prefs", {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,  # Download PDF instead of viewer
    })
    # Run headed so the user can see what's happening (and solve CAPTCHAs if needed)
    # chrome_options.add_argument("--headless=new")  # Uncomment for headless mode

    log.info("Launching Chrome browser...")
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        log.error(f"Could not launch Chrome: {e}")
        log.info("Make sure Chrome is installed and up to date.")
        return None

    try:
        # Navigate to the /pdf/ download page
        log.info(f"Navigating to: {FLIPPINGBOOK_PDF_URL}")
        driver.get(FLIPPINGBOOK_PDF_URL)

        # Wait for the page to render (FlippingBook uses heavy JS)
        log.info("Waiting for page to render...")
        time.sleep(5)

        # Try multiple selectors for the download button
        download_selectors = [
            # Common FlippingBook download button selectors
            'a[href*=".pdf"]',
            'a[download]',
            'button[class*="download"]',
            'a[class*="download"]',
            '[data-action="download"]',
            '.pdf-download',
            '.download-btn',
            '.fb-download',
            # Generic buttons containing "download" or "PDF" text
            '//a[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"download")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"download")]',
            '//a[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"pdf")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"pdf")]',
            # FlippingBook specific: the "Изтегли" (Download in Bulgarian) button
            '//a[contains(text(),"Изтегли")]',
            '//button[contains(text(),"Изтегли")]',
            '//a[contains(text(),"Свали")]',
            '//span[contains(text(),"Изтегли")]/..',
        ]

        clicked = False
        for selector in download_selectors:
            try:
                if selector.startswith('//'):
                    # XPath selector
                    elements = driver.find_elements(By.XPATH, selector)
                else:
                    # CSS selector
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)

                for el in elements:
                    if el.is_displayed():
                        log.info(f"Found download element: <{el.tag_name}> text='{el.text[:50]}' selector='{selector}'")
                        el.click()
                        clicked = True
                        break
                if clicked:
                    break
            except Exception:
                continue

        if not clicked:
            # Last resort: log all clickable elements for debugging
            log.warning("Could not find download button automatically.")
            log.info("Visible links and buttons on the page:")
            for tag in ['a', 'button']:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for el in elements[:20]:
                    try:
                        if el.is_displayed():
                            href = el.get_attribute('href') or ''
                            log.info(f"  <{tag}> text='{el.text[:60]}' href='{href[:80]}'")
                    except:
                        pass

            log.info("\nWaiting 30 seconds — please click the download button manually in the browser...")
            time.sleep(30)

        # Wait for the PDF download to complete
        log.info("Waiting for PDF download to complete...")
        pdf_file = _wait_for_download(download_dir, timeout=60)

        if pdf_file:
            # Rename to our target filename
            final_path = os.path.join(download_dir, os.path.basename(output_path))
            if pdf_file != final_path:
                if os.path.exists(final_path):
                    os.remove(final_path)
                os.rename(pdf_file, final_path)
            size_mb = os.path.getsize(final_path) / (1024 * 1024)
            log.info(f"PDF downloaded via browser: {final_path} ({size_mb:.1f} MB)")
            return final_path
        else:
            log.error("Download did not complete within timeout")
            return None

    except Exception as e:
        log.error(f"Browser automation error: {e}")
        return None
    finally:
        driver.quit()
        log.info("Browser closed.")


def _wait_for_download(download_dir, timeout=60, poll_interval=2):
    """Wait for a new PDF file to appear in the download directory."""
    # Snapshot existing files before download
    existing = set(os.listdir(download_dir))
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(poll_interval)
        current = set(os.listdir(download_dir))
        new_files = current - existing

        for f in new_files:
            full_path = os.path.join(download_dir, f)
            # Skip temp/partial download files
            if f.endswith('.crdownload') or f.endswith('.tmp') or f.endswith('.part'):
                continue
            # Check if it's a PDF
            if f.lower().endswith('.pdf') and os.path.getsize(full_path) > 10000:
                # Verify it's a real PDF
                with open(full_path, 'rb') as fh:
                    if fh.read(4) == b'%PDF':
                        return full_path

    return None


def download_pdf(output_path="fantastico_brochure.pdf", **kwargs):
    """
    Download the Fantastico brochure as a PDF. Strategies:
      1. Selenium browser automation (opens Chrome, clicks download)
      2. Direct /pdf/ endpoint with requests (usually blocked, but try)
      3. Manual fallback instructions
    """
    import requests

    # ── Strategy 1: Browser automation ──
    log.info("Strategy 1: Browser automation (Selenium + Chrome)")
    result = download_pdf_with_browser(output_path)
    if result:
        return result

    # ── Strategy 2: Direct download attempts ──
    log.info("Strategy 2: Direct HTTP download attempts")
    for url in [FLIPPINGBOOK_PDF_URL, "https://online.flippingbook.com/view/738517692.pdf"]:
        log.info(f"  Trying: {url}")
        try:
            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0", "Referer": FLIPPINGBOOK_VIEW_URL,
            }, allow_redirects=True, timeout=60)
            if resp.content[:4] == b'%PDF':
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                log.info(f"PDF downloaded: {output_path}")
                return output_path
        except Exception as e:
            log.warning(f"  Failed: {e}")

    # ── Strategy 3: Manual fallback ──
    log.error(
        "\n" + "=" * 60 + "\n"
        "Could not download PDF automatically.\n\n"
        "Manual download:\n"
        f"  1. Open {FLIPPINGBOOK_VIEW_URL} in your browser\n"
        f"  2. Click the download/PDF button in the viewer menu\n"
        f"  3. Save as: {output_path}\n"
        f"  4. Run: python fantastico_ocr_pipeline.py --pdf {output_path} --key YOUR_AZURE_KEY\n"
        + "=" * 60
    )
    return None


# ─── STEP 2: SPLIT PDF INTO BATCHES ─────────────────────────────────────────

def split_pdf(pdf_path, output_dir="pdf_batches", pages_per_batch=PAGES_PER_BATCH):
    """
    Split a large PDF into smaller batch files of N pages each.
    Azure Document Intelligence has a ~50MB/500-page limit per request,
    so we split into manageable chunks.
    """
    from PyPDF2 import PdfReader, PdfWriter

    os.makedirs(output_dir, exist_ok=True)

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    log.info(f"PDF has {total_pages} pages — splitting into batches of {pages_per_batch}")

    batch_files = []
    for start in range(0, total_pages, pages_per_batch):
        end = min(start + pages_per_batch, total_pages)
        batch_num = (start // pages_per_batch) + 1
        batch_path = os.path.join(output_dir, f"batch_{batch_num:03d}_pages_{start+1}-{end}.pdf")

        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        
        with open(batch_path, "wb") as f:
            writer.write(f)
        
        size_kb = os.path.getsize(batch_path) / 1024
        log.info(f"  Batch {batch_num}: pages {start+1}-{end} → {batch_path} ({size_kb:.0f} KB)")
        batch_files.append(batch_path)

    return batch_files


# ─── STEP 3: OCR VIA AZURE DOCUMENT INTELLIGENCE ────────────────────────────

def ocr_batch(pdf_path, endpoint, key):
    """
    Send a single PDF batch to Azure Document Intelligence for OCR.
    Returns the full text content from all pages.
    """
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )

    # Read PDF as bytes
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    log.info(f"  Sending {pdf_path} ({len(pdf_bytes)/1024:.0f} KB) to Azure DI...")

    # Send for analysis using bytes (local file)
    # Handle different SDK versions: newer uses 'body', older uses 'analyze_request'
    try:
        poller = client.begin_analyze_document(
            AZURE_MODEL_ID,
            body=pdf_bytes,
            content_type="application/pdf"
        )
    except TypeError:
        # Fallback for older SDK versions
        poller = client.begin_analyze_document(
            AZURE_MODEL_ID,
            analyze_request=pdf_bytes,
            content_type="application/pdf"
        )
    result = poller.result()

    # Extract text by page
    pages_text = []
    for page in result.pages:
        page_lines = []
        for line in page.lines:
            page_lines.append(line.content)
        pages_text.append({
            "page_number": page.page_number,
            "width": page.width,
            "height": page.height,
            "text": "\n".join(page_lines),
            "lines": [line.content for line in page.lines],
            "words": [{"content": w.content, "confidence": w.confidence} for w in page.words]
        })

    full_text = result.content if result.content else ""
    
    return {
        "pages": pages_text,
        "full_text": full_text,
        "source_file": pdf_path
    }


def ocr_all_batches(batch_files, output_dir, endpoint, key):
    """
    OCR all PDF batches and save results as JSON + text files.
    """
    os.makedirs(output_dir, exist_ok=True)
    all_results = []

    for i, batch_path in enumerate(batch_files):
        batch_name = Path(batch_path).stem
        json_path = os.path.join(output_dir, f"{batch_name}_ocr.json")
        text_path = os.path.join(output_dir, f"{batch_name}_ocr.txt")

        # Skip if already processed
        if os.path.exists(json_path):
            log.info(f"  Batch {i+1}/{len(batch_files)}: {batch_name} — already processed, loading cache")
            with open(json_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            all_results.append(result)
            continue

        # OCR with retry
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = ocr_batch(batch_path, endpoint, key)
                
                # Save JSON result
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                
                # Save plain text
                with open(text_path, "w", encoding="utf-8") as f:
                    f.write(result["full_text"])
                
                page_count = len(result["pages"])
                log.info(f"  Batch {i+1}/{len(batch_files)}: {batch_name} — {page_count} pages OCR'd")
                all_results.append(result)
                break

            except Exception as e:
                log.warning(f"  Batch {i+1} attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    log.info(f"  Retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    log.error(f"  Batch {i+1} FAILED after {MAX_RETRIES} attempts — skipping")

        # Small delay between batches to avoid rate limiting
        if i < len(batch_files) - 1:
            time.sleep(2)

    return all_results


# ─── PATTERNS FOR ACTUAL OCR OUTPUT ──────────────────────────────────────────
# Real OCR format examples from Azure DI:
#   "Ягоди 500 г в оп. цена за оп.\n2.79 € -19% 2.25 €\n4.40 ЛВ."
#   "Прясно мляко МАДЖАРОВ масленост 3.6% 1 л\n2.04 € 1.49 €\n2.91 ЛВ."
#   "Салам Бургас; Шпек МАДЖАРОВ\n16.87 € -27% 12.29 €\nцена за кг\n24.04 ЛВ."
#   Split EUR pair: "7.66 €\n-51%\n3.69 €\n4.48 ЛВ."

# BGN price: "4.40 ЛВ." or "24.04 ЛВ."
BGN_PRICE_RE = re.compile(r'(\d{1,3}\.\d{2})\s*ЛВ\.', re.IGNORECASE)

# EUR price pair — handles same-line and multi-line (via \s* which matches \n):
# "2.79 € -19% 2.25 €"  or  "7.66 €\n-51%\n3.69 €"
EUR_PAIR_RE = re.compile(
    r'(\d{1,3}\.\d{2})\s*€\s*(?:-?\d+%?\s*(?:ОТСТЪПКА)?\s*)?(\d{1,3}\.\d{2})\s*€'
)

# Single EUR price: "2.25 €"
EUR_SINGLE_RE = re.compile(r'(\d{1,3}\.\d{2})\s*€')

# Discount: "-19%" or "-19% ОТСТЪПКА"
DISCOUNT_RE = re.compile(r'-(\d{1,2})%')

# Unit indicator: "цена за бр." / "цена за кг" / "цена за оп." / "цена за к-кт"
UNIT_INDICATOR_RE = re.compile(r'цена\s+за\s+(бр|кг|оп|л|к-кт)\.?', re.IGNORECASE)

# Weight/volume in product name
WEIGHT_RE = re.compile(r'(\d+(?:[,.]\d+)?)\s*(кг|г|мл|л)\b', re.IGNORECASE)

# Lines to skip when extracting product names (noise/headers/footnotes)
SKIP_RE = re.compile(
    r'^(?:'
    r'стр\.\s*\d|fantastico\.?stores?|www\.|ОФЕРТА ЗА|Продуктите се продават|'
    r'ТВ .Фантастико|Декорацията|'
    r'ПОСТНИ|вкусни идеи|f$|\d{1,3}$|℮|'
    r'ФАНТАСТИКО|събира ни|постНИ|находки|KRINA|Natural Choice|'
    r'Premium SELECTION|Compass$|Arriva$|GAEA$|LAURINI$|'
    r'ОТСТЪПКА$|'
    r'Всички\s+.*(?:с\s+марка|видове)|минимум\s+-?\d+|'  # bulk discount headers
    r'не носи отговорност|Поръчки се|Алергени:|catering@|тел\.\s*\+|'
    r'7 DAYS|СЕДМИЦА НА|NEW!|HOBO!|^DAYS$|^NEW$|'        # brand promo noise
    r'\*+|Период на кампанията|'                          # footnotes (any *)
    r'Совет от|Умението|MiAU MiAU ADULT|'
    r'предложението е валидно|акцията е валидна|'
    r'^•|^\[|^-{2,}'                                      # bullet/bracket/dash lines
    r')',
    re.IGNORECASE
)

# Cyrillic Unicode range: U+0400–U+04FF
_CYRILLIC_RE = re.compile(r'[\u0400-\u04FF]')


def _is_name_line(line):
    """Return True if the line could be a product name (not noise/price/header)."""
    line = line.strip()
    if not line or len(line) < 4:
        return False
    if SKIP_RE.match(line):
        return False
    if re.match(r'^[\d.]+\s*[€%]', line):
        return False
    if re.match(r'^-?\d+%', line):
        return False
    if BGN_PRICE_RE.match(line):
        return False
    if re.match(r'^цена\s+за', line, re.IGNORECASE):
        return False
    if re.match(r'^\d{1,3}$', line):   # bare page number
        return False
    # Skip weight/quantity-only lines: "680 г", "500 мл", "1.5 л"
    if re.match(r'^\d+(?:[,.]\d+)?\s*(?:г|кг|мл|л|бр)\.?$', line, re.IGNORECASE):
        return False
    # Skip very short all-caps Latin (logo fragments: "MAX", "DAYS", "ICO", "NEW!")
    if re.match(r'^[A-Z0-9\s\.\-\!\?]+$', line) and len(line) < 12:
        return False
    # Skip mathematical price calculations: "7,15 + 1,25 + 1,25 ="
    if re.match(r'^[\d,.\s\+\-\=\/]+$', line):
        return False
    return True


def _name_score(line):
    """Score a candidate name line: 2 = starts with Cyrillic, 1 = other."""
    first_alpha = next((c for c in line if c.isalpha()), None)
    if first_alpha and '\u0400' <= first_alpha <= '\u04FF':
        return 2
    return 1


def parse_ocr_to_products(ocr_results, promo_period=DEFAULT_PROMO_PERIOD):
    """
    Parse OCR text from all batches into structured product records.
    Uses BGN prices (X.XX ЛВ.) as anchors, then looks backwards
    in the text to find the product name, EUR prices, and unit.
    """
    products = []
    seen = set()

    for ocr_batch in ocr_results:
        full_text = ocr_batch.get("full_text", "")
        if not full_text:
            # Reconstruct from pages
            for page in ocr_batch.get("pages", []):
                full_text += page.get("text", "") + "\n"

        if not full_text.strip():
            continue

        batch_products = parse_text_stream(full_text, promo_period)
        for p in batch_products:
            key = (p["product_name"][:40].lower(), p["promo_price"])
            if key not in seen:
                seen.add(key)
                products.append(p)

    return products


def parse_text_stream(text, promo_period):
    """
    Parse a continuous OCR text stream into product records.

    Two-pass approach:
      Pass 1 — BGN-anchored: BGN price (X.XX ЛВ.) marks end of each product block.
               Look back in the window for EUR prices and product name.
      Pass 2 — EUR-pair-only: capture products whose BGN price was missed by OCR,
               using the EUR pair as the anchor and calculating BGN from EUR.

    Pre-processing fixes common Azure DI OCR errors:
      - Hyphen-as-decimal: "0-29 ЛВ." → "0.29 ЛВ.", "7-22 ЛВ." → "7.22 ЛВ."
    """
    products = []
    seen = set()   # (name[:40].lower(), price) dedup

    # ── Pre-process OCR text ──

    # Fix hyphen-as-decimal in BGN prices: "0-29 ЛВ." → "0.29 ЛВ."
    text = re.sub(
        r'\b(\d{1,3})-(\d{2})\s*ЛВ\.',
        lambda m: f"{m.group(1)}.{m.group(2)} ЛВ.",
        text, flags=re.IGNORECASE
    )
    # Fix bullet-as-decimal: "8•98 ЛВ." → "8.98 ЛВ."
    text = re.sub(
        r'\b(\d{1,3})[•·](\d{2})\s*ЛВ\.',
        lambda m: f"{m.group(1)}.{m.group(2)} ЛВ.",
        text, flags=re.IGNORECASE
    )
    # Strip catering menu section (Easter pre-orders, entirely different format).
    # Section starts with "m choice CATERING" or "ЗА ТВОЯ ВКУСЕН Великден"
    # and ends before "7 DAYS" brand promo or end-of-text.
    text = re.sub(
        r'(?:m choice CATERING|ЗА ТВОЯ ВКУСЕН Великден).*?(?=7 DAYS|$)',
        '\n', text, flags=re.DOTALL | re.IGNORECASE
    )

    # ── Helper: extract unit from a text window ──
    def _extract_unit(window):
        m = UNIT_INDICATOR_RE.search(window)
        if m:
            return {'кг': 'кг', 'бр': 'бр', 'оп': 'опаковка',
                    'л': 'л', 'к-кт': 'к-кт'}.get(m.group(1).lower())
        w = WEIGHT_RE.search(window)
        if w:
            return f"{w.group(1)} {w.group(2)}"
        return None

    # ── Helper: extract best product name from a text region ──
    def _extract_name(region):
        # Only look at the last 6 lines of the region to avoid noise from
        # previous product blocks captured in the wider window.
        lines = [l.strip() for l in region.split('\n')][-6:]
        # Collect valid lines in original order, with score
        scored = [(l, _name_score(l)) for l in lines if _is_name_line(l)]
        if not scored:
            return None
        # Prefer Cyrillic-starting lines
        cyrillic_lines = [l for l, s in scored if s == 2]
        pool = cyrillic_lines if cyrillic_lines else [l for l, s in scored]
        # Among candidates, pick the LONGEST (most descriptive) line.
        # This avoids short descriptors like "екстра качество" when a full
        # product name like "Маслен боб КРИНА 800 г" is also present.
        best = max(pool, key=len)
        # Cleanup suffixes
        best = re.sub(r'\s*цена за\s+\S+\.?\s*$', '', best, flags=re.IGNORECASE)
        best = re.sub(r'\s*произход\s+\S+.*$', '', best, flags=re.IGNORECASE)
        best = re.sub(r'\s*насипн[аи]\s+от щандова витрина\s*$', '', best, flags=re.IGNORECASE)
        best = re.sub(r'\s+', ' ', best).strip()
        return best if len(best) >= 8 else None

    # ── Helper: emit a product record ──
    def _emit(name, promo_eur, regular_eur, unit, pp):
        if not name or promo_eur < 0.05 or promo_eur > 260:
            return
        key = (name[:40].lower(), promo_eur)
        if key in seen:
            return
        seen.add(key)
        products.append({
            "source_store": SOURCE_STORE,
            "source_channel": SOURCE_CHANNEL,
            "product_name": name,
            "product_category": auto_categorize(name),
            "regular_price": regular_eur,
            "promo_price": promo_eur,
            "unit": unit,
            "price_per_unit": None,
            "promo_period": pp,
            "source_url": SOURCE_URL,
            "extraction_date": EXTRACTION_DATE,
        })

    # ════════════════════════════════════════════════════════════════
    # PASS 1 — BGN-anchored products
    # ════════════════════════════════════════════════════════════════
    bgn_matches = list(BGN_PRICE_RE.finditer(text))

    for idx, bgn_match in enumerate(bgn_matches):
        bgn_price = float(bgn_match.group(1))
        if bgn_price < 0.10 or bgn_price > 500:
            continue

        bgn_pos = bgn_match.start()
        window_start = bgn_matches[idx - 1].end() if idx > 0 else max(0, bgn_pos - 600)
        window = text[window_start:bgn_pos]

        # ── EUR prices ──
        eur_pair = EUR_PAIR_RE.search(window)
        regular_eur = None
        promo_eur = None

        if eur_pair:
            regular_eur = float(eur_pair.group(1))
            promo_eur = float(eur_pair.group(2))
            name_end = window_start + eur_pair.start()
        else:
            # Collect all single EUR prices; first = regular, last = promo
            all_eur = [float(x) for x in EUR_SINGLE_RE.findall(window)]
            if len(all_eur) >= 2:
                regular_eur = all_eur[0]
                promo_eur = all_eur[-1]
            elif len(all_eur) == 1:
                promo_eur = all_eur[0]
            # Name region ends at unit indicator or just before the EUR section
            unit_m = UNIT_INDICATOR_RE.search(window)
            if unit_m:
                name_end = window_start + unit_m.start()
            elif all_eur:
                # Find first EUR price position as name boundary
                first_eur_m = EUR_SINGLE_RE.search(window)
                name_end = window_start + first_eur_m.start() if first_eur_m else bgn_pos
            else:
                name_end = bgn_pos

        # Fall back: convert BGN anchor to EUR if no EUR price found
        if promo_eur is None:
            promo_eur = round(bgn_price / EUR_TO_BGN, 2)

        unit = _extract_unit(window)
        name = _extract_name(text[window_start:name_end])
        _emit(name, promo_eur, regular_eur, unit, promo_period)

    # ════════════════════════════════════════════════════════════════
    # PASS 2 — EUR-pair-only products (BGN price absent in OCR)
    # Emit products anchored on EUR pairs whose calculated BGN price
    # does NOT already appear in the seen set from Pass 1.
    # ════════════════════════════════════════════════════════════════
    eur_pair_matches = list(EUR_PAIR_RE.finditer(text))
    bgn_ends = {m.end() for m in bgn_matches}  # positions already consumed

    for idx, ep_match in enumerate(eur_pair_matches):
        old_eur = float(ep_match.group(1))
        new_eur = float(ep_match.group(2))

        # Check if a BGN price close to the calculated value follows this EUR pair
        # (within ~100 chars). If yes, Pass 1 already handled it — skip.
        after_window = text[ep_match.end(): ep_match.end() + 150]
        close_bgn = BGN_PRICE_RE.search(after_window)
        if close_bgn:
            continue  # Pass 1 captured this product

        # Window before this EUR pair (for name extraction)
        prev_ep_end = eur_pair_matches[idx - 1].end() if idx > 0 else 0
        # Also bound by previous BGN match end
        prev_bgn_end = 0
        for m in bgn_matches:
            if m.end() < ep_match.start():
                prev_bgn_end = m.end()
            else:
                break
        window_start = max(prev_ep_end, prev_bgn_end)
        name_region = text[window_start: ep_match.start()]

        unit = _extract_unit(name_region)
        name = _extract_name(name_region)
        _emit(name, new_eur, old_eur, unit, promo_period)

    return products


def auto_categorize(name):
    """Keyword-based category assignment for Bulgarian product names."""
    n = name.lower()
    # Check exclusions first (order matters)
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
                            'тост', 'питка', 'кроасан', 'франзела'],
        'Домакинство': ['тоалетна хартия', 'пране', 'почиств', 'препарат',
                         'кърпа', 'прах за', 'омекот'],
        'Консерви': ['пастет', 'лютеница', 'стерилизиран', 'компот', 'консерв'],
    }
    for cat, kws in cats.items():
        if any(kw in n for kw in kws):
            return cat
    return None


# ─── STEP 5: VALIDATE & MERGE ───────────────────────────────────────────────

def validate_products(products):
    """Apply data quality checks."""
    clean = []
    removed = []
    for p in products:
        if not p.get("product_name") or not p.get("promo_price"):
            removed.append(("missing_required", p))
            continue
        if len(p["product_name"]) < 4:
            removed.append(("name_too_short", p))
            continue
        if p.get("regular_price") and p["promo_price"] > p["regular_price"] * 1.05:
            removed.append(("price_anomaly", p))
            continue
        if p["promo_price"] < 0.05 or p["promo_price"] > 260:
            removed.append(("price_range", p))
            continue
        clean.append(p)
    return clean, removed


def merge_with_existing(new_products, existing_path):
    """Load existing dataset and merge new Fantastico products."""
    if not existing_path or not Path(existing_path).exists():
        return new_products

    with open(existing_path, "r", encoding="utf-8") as f:
        existing = json.load(f)

    # Remove old Fantastico Direct entries
    existing = [
        p for p in existing
        if not (p["source_store"] == "Fantastico" and p["source_channel"] == "Direct")
    ]

    merged = existing + new_products

    # Global dedup
    seen = set()
    deduped = []
    for p in merged:
        key = (p["source_store"][:15], p["source_channel"],
               p["product_name"][:40].lower(), p["promo_price"])
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


# ─── STEP 6: ALTERNATIVE — PARSE FROM PRE-EXISTING OCR TEXT FILES ───────────

def load_ocr_from_directory(ocr_dir):
    """Load OCR results from previously saved JSON files."""
    results = []
    json_files = sorted(Path(ocr_dir).glob("*_ocr.json"))
    
    if not json_files:
        # Try plain text files
        txt_files = sorted(Path(ocr_dir).glob("*.txt"))
        for txt_file in txt_files:
            text = txt_file.read_text(encoding="utf-8")
            # Convert plain text to our format
            lines = text.split("\n")
            results.append({
                "pages": [{
                    "page_number": 1,
                    "text": text,
                    "lines": lines,
                    "words": []
                }],
                "full_text": text,
                "source_file": str(txt_file)
            })
        log.info(f"Loaded {len(txt_files)} text files from {ocr_dir}")
    else:
        for jf in json_files:
            with open(jf, "r", encoding="utf-8") as f:
                results.append(json.load(f))
        log.info(f"Loaded {len(json_files)} OCR JSON files from {ocr_dir}")
    
    return results


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fantastico brochure OCR pipeline: PDF → Azure DI → Products JSON"
    )
    parser.add_argument("--key", "-k", default=os.environ.get("AZURE_DI_KEY"),
                        help="Azure Document Intelligence key (or set AZURE_DI_KEY env var)")
    parser.add_argument("--endpoint", default=AZURE_ENDPOINT,
                        help=f"Azure DI endpoint (default: {AZURE_ENDPOINT})")
    parser.add_argument("--pdf", default=None,
                        help="Path to already-downloaded PDF (skip download step)")
    parser.add_argument("--pdf-url", default=None,
                        help="Direct URL to download the PDF from (if you already know it)")
    parser.add_argument("--ocr-dir", default=None,
                        help="Path to directory with pre-existing OCR output (skip download + OCR)")
    parser.add_argument("--existing", "-e", default=None,
                        help="Path to existing JSON dataset to merge with")
    parser.add_argument("--output", "-o", default=None,
                        help="Output JSON path")
    parser.add_argument("--batch-size", type=int, default=PAGES_PER_BATCH,
                        help=f"Pages per OCR batch (default: {PAGES_PER_BATCH})")
    parser.add_argument("--work-dir", default="fantastico_work",
                        help="Working directory for intermediate files")
    args = parser.parse_args()

    work_dir = args.work_dir
    os.makedirs(work_dir, exist_ok=True)

    # ── Route based on what's provided ──

    if args.ocr_dir:
        # FAST PATH: OCR already done, just parse
        log.info(f"Loading pre-existing OCR from: {args.ocr_dir}")
        ocr_results = load_ocr_from_directory(args.ocr_dir)

    else:
        # Need Azure key for OCR
        if not args.key:
            parser.error(
                "Azure DI key required. Provide --key or set AZURE_DI_KEY env var.\n"
                "Or use --ocr-dir if you already have OCR output."
            )

        # Step 1: Get the PDF
        if args.pdf:
            pdf_path = args.pdf
            if not os.path.exists(pdf_path):
                log.error(f"PDF not found: {pdf_path}")
                sys.exit(1)
        elif args.pdf_url:
            pdf_path = os.path.join(work_dir, "fantastico_brochure.pdf")
            try:
                result = download_pdf_from_url(args.pdf_url, pdf_path)
                if not result:
                    sys.exit(1)
            except Exception as e:
                log.error(f"Failed to download from URL: {e}")
                sys.exit(1)
        else:
            pdf_path = os.path.join(work_dir, "fantastico_brochure.pdf")
            if os.path.exists(pdf_path):
                log.info(f"PDF already exists: {pdf_path} — skipping download")
            else:
                pdf_path = download_pdf(pdf_path)
                if not pdf_path:
                    sys.exit(1)

        # Step 2: Split PDF
        batch_dir = os.path.join(work_dir, "pdf_batches")
        batch_files = split_pdf(pdf_path, batch_dir, args.batch_size)
        log.info(f"Created {len(batch_files)} batches")

        # Step 3: OCR
        ocr_dir = os.path.join(work_dir, "ocr_output")
        ocr_results = ocr_all_batches(batch_files, ocr_dir, args.endpoint, args.key)
        log.info(f"OCR completed: {len(ocr_results)} batches processed")

    # Step 4: Parse OCR → products
    products = parse_ocr_to_products(ocr_results)
    log.info(f"Parsed {len(products)} raw products from OCR")

    # Step 5: Validate
    clean, removed = validate_products(products)
    log.info(f"After validation: {len(clean)} clean, {len(removed)} removed")
    for reason, p in removed[:5]:
        log.info(f"  Removed ({reason}): {p.get('product_name', '?')[:50]}")

    # Step 6: Merge
    if args.existing:
        merged = merge_with_existing(clean, args.existing)
        log.info(f"Merged with existing: {len(merged)} total records")
    else:
        merged = clean

    # Output
    output_path = args.output or os.path.join(work_dir, f"fantastico_products_{EXTRACTION_DATE}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    log.info(f"Output saved to: {output_path}")

    # Also save just the Fantastico products separately
    fant_only = os.path.join(work_dir, f"fantastico_only_{EXTRACTION_DATE}.json")
    with open(fant_only, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"\n{'═' * 60}")
    print(f"FANTASTICO OCR PIPELINE — RESULTS")
    print(f"{'═' * 60}")
    print(f"Products extracted:  {len(clean)}")
    print(f"Products removed:    {len(removed)}")
    if args.existing:
        stores = {}
        for p in merged:
            k = f"{p['source_store']} ({p['source_channel']})"
            stores[k] = stores.get(k, 0) + 1
        print(f"\nMerged dataset:")
        for k, v in sorted(stores.items()):
            print(f"  {k}: {v}")
        print(f"  TOTAL: {len(merged)}")
    
    # Category breakdown
    cats = {}
    for p in clean:
        c = p.get("product_category") or "Uncategorized"
        cats[c] = cats.get(c, 0) + 1
    if cats:
        print(f"\nBy category:")
        for c, n in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"  {c}: {n}")

    print(f"\nOutput: {output_path}")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
