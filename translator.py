#!/usr/bin/env python3
"""
Bulgarian → English translation module using Azure OpenAI GPT-4o.
Caches all translations in translation_cache.json to minimise API costs.

Public API:
    load_azure_cfg()               -> (cfg_dict, api_key | None)
    translate_strings(strings, cfg, key) -> {original: english}
    translate_workbook(wb, cfg, key)     -> wb  (in-place, returns same object)
"""

import json
import re
import time
from pathlib import Path

BASE        = Path(__file__).parent
CACHE_PATH  = BASE / "translation_cache.json"
CONFIG_PATH = BASE / "azure_config.json"
SECRETS_PATH = BASE / "azure_secrets.json"

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

# Bulgarian DD.MM[.YYYY] – DD.MM.YYYY  (handles both – and -)
_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})(?:\.(\d{4}))?\s*[-–]\s*(\d{2})\.(\d{2})\.(\d{4})"
)
_MONTHS = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def has_cyrillic(s: str) -> bool:
    return bool(_CYRILLIC_RE.search(str(s or "")))


def translate_date(s: str) -> str:
    """
    Reformat any Bulgarian date range inside a string.
    '02.04 - 08.04.2026'  →  'Apr 2, 2026 – Apr 8, 2026'
    Also works when embedded in longer translated text.
    """
    def _replace(m):
        d1, mo1, yr1, d2, mo2, yr2 = m.groups()
        yr1 = yr1 or yr2
        start = f"{_MONTHS.get(mo1, mo1)} {int(d1)}, {yr1}"
        end   = f"{_MONTHS.get(mo2, mo2)} {int(d2)}, {yr2}"
        return f"{start} – {end}"
    return _DATE_RE.sub(_replace, str(s))


# ── Cache ─────────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Azure config ──────────────────────────────────────────────────────────────

def load_azure_cfg():
    """Return (cfg_dict, api_key) from azure_config.json + azure_secrets.json."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        sec = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        key = sec.get("api_key", "")
        return cfg, (key if key else None)
    except Exception as e:
        print(f"  Azure config error: {e}", flush=True)
        return {}, None


# ── GPT-4o call ───────────────────────────────────────────────────────────────

def _gpt_translate_batch(client, deployment: str, strings: list[str]) -> list[str]:
    """Send one batch to GPT-4o, return list of English translations."""
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(strings))
    prompt = (
        "Translate the following Bulgarian grocery/retail strings to English.\n"
        "Rules:\n"
        "- Keep brand names, numbers, URLs, and already-English words unchanged\n"
        "- Natural English for food names ('Прясно пиле' → 'Fresh Chicken')\n"
        "- Standard English grocery category names ('Млечни продукти' → 'Dairy')\n"
        "- Professional English for column/sheet headers\n"
        "- Translate 'лв./кг' → '€/kg', 'лв./л' → '€/l', 'лв./бр' → '€/pcs'\n"
        "- Keep numeric values, percentages, and store names unchanged\n"
        "- Match original brevity — no explanatory additions\n\n"
        "Return ONLY JSON: {\"translations\": [\"...\", ...]}\n\n"
        f"Strings:\n{numbered}"
    )
    resp = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=4096,
        temperature=0.0,
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("translations", [])


# ── Public: translate a list of strings ───────────────────────────────────────

def translate_strings(
    strings: list[str],
    cfg: dict,
    api_key: str,
    batch_size: int = 50,
    delay: float = 0.5,
    verbose: bool = True,
) -> dict:
    """
    Translate a list of unique strings from Bulgarian to English.
    - Non-Cyrillic strings are returned unchanged.
    - Cached translations are served without an API call.
    - New translations are written back to translation_cache.json.

    Returns dict: {original: english}
    """
    try:
        from openai import AzureOpenAI
    except ImportError:
        print("  openai package not installed — run: pip install openai", flush=True)
        return {s: s for s in strings}

    cache = load_cache()
    result: dict = {}
    to_translate: list[str] = []

    for s in strings:
        if not has_cyrillic(s):
            result[s] = s
        elif s in cache:
            result[s] = cache[s]
        else:
            to_translate.append(s)

    cached_count = len(strings) - len(to_translate)
    if not to_translate:
        if verbose:
            print(f"  Translation: all {len(strings)} strings from cache.", flush=True)
        return result

    if verbose:
        print(
            f"  Translating {len(to_translate)} new strings "
            f"({cached_count} from cache)...",
            flush=True,
        )

    client = AzureOpenAI(
        azure_endpoint=cfg["endpoint"],
        api_key=api_key,
        api_version=cfg["api_version"],
        timeout=cfg.get("timeout_seconds", 60),
    )

    batches = [
        to_translate[i : i + batch_size]
        for i in range(0, len(to_translate), batch_size)
    ]

    for b_idx, batch in enumerate(batches, 1):
        if verbose:
            print(
                f"    Batch {b_idx}/{len(batches)} ({len(batch)} strings)...",
                flush=True,
            )
        try:
            translations = _gpt_translate_batch(client, cfg["deployment_name"], batch)
            for i, orig in enumerate(batch):
                tr = translations[i].strip() if i < len(translations) else ""
                if tr:
                    cache[orig] = tr
                    result[orig] = tr
                else:
                    result[orig] = orig  # fallback: keep original
        except Exception as e:
            print(f"    Batch {b_idx} error: {e}", flush=True)
            for orig in batch:
                result[orig] = orig

        if b_idx < len(batches):
            time.sleep(delay)

    save_cache(cache)
    return result


# ── Public: translate an openpyxl Workbook in-place ───────────────────────────

def translate_workbook(wb, cfg: dict, api_key: str, batch_size: int = 50, verbose: bool = True):
    """
    Translate all Bulgarian text in an openpyxl Workbook in-place.

    What is translated:
      - Sheet titles (except hidden sheets, to preserve data-validation formula refs)
      - All cell string values containing Cyrillic characters

    What is also fixed automatically:
      - Number formats:  '#,##0.00" лв."'  →  '#,##0.00" €"'
      - Date ranges in cell values:  '02.04 - 08.04.2026'  →  'Apr 2, 2026 – Apr 8, 2026'

    Returns the same workbook object.
    """
    # 1. Collect unique strings to translate
    strings: set[str] = set()
    for ws in wb.worksheets:
        if ws.sheet_state != "hidden" and has_cyrillic(ws.title):
            strings.add(ws.title)
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and has_cyrillic(cell.value):
                    strings.add(cell.value)

    if not strings:
        if verbose:
            print("  No Bulgarian strings found in workbook.", flush=True)
        return wb

    if verbose:
        print(f"  Found {len(strings)} unique Bulgarian strings.", flush=True)

    # 2. Translate (uses cache + GPT-4o for new strings)
    t_map = translate_strings(
        list(strings), cfg, api_key,
        batch_size=batch_size, verbose=verbose,
    )

    # 3. Apply: sheet names, cell values, number formats, date reformatting
    for ws in wb.worksheets:
        if ws.sheet_state != "hidden" and has_cyrillic(ws.title):
            ws.title = t_map.get(ws.title, ws.title)

        for row in ws.iter_rows():
            for cell in row:
                v = cell.value

                if isinstance(v, str):
                    if has_cyrillic(v):
                        translated = t_map.get(v, v)
                        # Post-process: reformat any date ranges that appear in the text
                        cell.value = translate_date(translated)
                    else:
                        # Non-Cyrillic strings may still contain a date pattern
                        cell.value = translate_date(v)

                # Fix currency number format
                if cell.number_format and "лв" in cell.number_format:
                    cell.number_format = cell.number_format.replace('" лв."', '" €"')

    return wb
