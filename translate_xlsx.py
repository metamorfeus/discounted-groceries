#!/usr/bin/env python3
"""
One-time (and reusable) translator for the Bulgarian price-comparison Excel report.

Usage:
    python translate_xlsx.py                          # auto-detects latest bg_cheapest_*.xlsx
    python translate_xlsx.py --input bg_cheapest_v4_2026-04-07.xlsx

Output:
    <input_stem>_en.xlsx  (saved next to the input file)

Translation is powered by Azure OpenAI GPT-4o.
All translations are cached in translation_cache.json — re-runs are fast and free.
"""

import sys
import argparse
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from openpyxl import load_workbook
except ImportError:
    print("ERROR: pip install openpyxl")
    sys.exit(1)

import translator as tr

BASE = Path(__file__).parent


def find_latest_report() -> Path | None:
    """Return the most recently modified bg_cheapest_v*.xlsx (excluding _en files)."""
    candidates = sorted(
        (f for f in BASE.glob("bg_cheapest_v*.xlsx") if "_en" not in f.stem),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(
        description="Translate a Bulgarian price-report xlsx to English."
    )
    parser.add_argument(
        "--input", "-i",
        default=None,
        help="Path to the .xlsx to translate (default: latest bg_cheapest_v*.xlsx)",
    )
    args = parser.parse_args()

    # Resolve input file
    if args.input:
        input_path = Path(args.input)
        if not input_path.is_absolute():
            input_path = BASE / input_path
        if not input_path.exists():
            print(f"ERROR: file not found: {input_path}")
            sys.exit(1)
    else:
        input_path = find_latest_report()
        if not input_path:
            print("ERROR: no bg_cheapest_v*.xlsx found. Use --input to specify a file.")
            sys.exit(1)
        print(f"Auto-detected: {input_path.name}")

    output_path = input_path.with_stem(input_path.stem + "_en")

    # Load Azure credentials
    cfg, api_key = tr.load_azure_cfg()
    if not api_key:
        print("ERROR: Azure OpenAI key not found in azure_secrets.json.")
        sys.exit(1)

    # Load workbook
    print(f"Loading {input_path.name}...", flush=True)
    wb = load_workbook(str(input_path))
    sheets = [ws.title for ws in wb.worksheets]
    print(f"  {len(sheets)} sheets: {', '.join(sheets)}", flush=True)

    # Translate
    print("Translating...", flush=True)
    tr.translate_workbook(wb, cfg, api_key, batch_size=50, verbose=True)

    # Save
    try:
        wb.save(str(output_path))
    except PermissionError:
        output_path = output_path.with_stem(output_path.stem + "_new")
        wb.save(str(output_path))
        print(f"Note: original was open — saved as {output_path.name}")

    size_kb = output_path.stat().st_size // 1024
    print(f"\nDone!  {output_path.name}  ({size_kb} KB)", flush=True)


if __name__ == "__main__":
    main()
