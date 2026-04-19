#!/usr/bin/env python3
"""
seed_hermes_memory.py — Seed Hermes memory for the discounted-groceries project.

Connects to the VPS via SSH, starts the discounted-groceries Hermes profile,
sends seed facts, then exits. No manual VPS access required.

Usage:
    python seed_hermes_memory.py
    python seed_hermes_memory.py --dry-run       # print facts, no connection
    python seed_hermes_memory.py --verbose        # show clean Hermes output
    python seed_hermes_memory.py --timeout 180    # max seconds to wait (default 180)

Requirements:
    pip install paramiko
"""

import argparse
import re
import sys
import time

# Ensure stdout handles Unicode on Windows (cp1252 console)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import paramiko
except ImportError:
    print("paramiko not installed. Run: pip install paramiko")
    sys.exit(1)

ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# ── VPS connection ──────────────────────────────────────────────────────────────
VPS_HOST = "62.146.169.66"
VPS_PORT = 2222
VPS_USER = "hermes"
SSH_KEY  = r"C:\Users\PVELINOV\.ssh\hermes_contabo_openssh"
PROFILE  = "discounted-groceries"

# ── Hermes input prompt markers ─────────────────────────────────────────────────
HERMES_PROMPTS = ["You:", "you:", "User:", "user:", "❯", ">>> ", "> "]
SHELL_PROMPTS  = ["$ ", "# "]

# ── Seed facts (single long message — avoids multi-line submission ambiguity) ───
SEED_FACTS = (
    "Please save these facts to your memory: "
    "This project scrapes weekly promotional grocery prices from Bulgarian retailers "
    "and generates an Excel price-comparison report. "
    "The four retailers covered are Gladen.bg (Hit Max), Billa, Kaufland, and Fantastico. "
    "All prices are stored in EUR by dividing BGN prices by 1.95583. "
    "The master dataset file is bulgarian_promo_prices_merged.json and each retailer script "
    "merges its own records into this file without touching other sources. "
    "The weekly pipeline runs in order: gladen_html_scraper.py, billa_pdf_pipeline.py, "
    "billa_scraper.py, write_glovo_data.py, fantastico_pipeline.py, generate_cheapest_xlsx.py. "
    "gladen_html_scraper.py requires the PROMO_PERIOD constant to be updated before each weekly run. "
    "write_glovo_data.py requires hardcoded product lists and file paths to be updated each week. "
    "secrets.py contains the Azure API keys and is excluded from git. "
    "The Excel report uses Azure OpenAI GPT-4o for product classification. "
    "The GitHub repo is metamorfeus/discounted-groceries and the VPS repo is at ~/projects/discounted-groceries/."
)


def clean(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def read_until_ready(channel, markers, timeout=180, silence_sec=6):
    """
    Read until a known prompt marker appears OR output goes silent for silence_sec seconds.
    Returns (raw_buf, matched_marker_or_None, reason) where reason is 'marker'|'silence'|'timeout'.
    """
    buf = ""
    deadline = time.time() + timeout
    last_recv = time.time()

    while time.time() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode(errors="replace")
            buf += chunk
            last_recv = time.time()
            stripped = clean(buf)
            for m in markers:
                if m in stripped:
                    return buf, m, "marker"
        else:
            if time.time() - last_recv >= silence_sec:
                return buf, None, "silence"
            time.sleep(0.25)

    return buf, None, "timeout"


def seed_memory(timeout: int, verbose: bool) -> int:
    print(f"Connecting to {VPS_USER}@{VPS_HOST}:{VPS_PORT} ...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            VPS_HOST, port=VPS_PORT, username=VPS_USER,
            key_filename=SSH_KEY, timeout=15,
        )
    except Exception as exc:
        print(f"SSH connection failed: {exc}")
        return 1

    channel = client.invoke_shell(width=220, height=50)

    # ── Wait for shell ready ──────────────────────────────────────────────────
    buf, found, reason = read_until_ready(channel, SHELL_PROMPTS, timeout=15, silence_sec=3)
    if verbose:
        print(f"[shell]\n{clean(buf).strip()}\n")
    if reason == "timeout":
        print("Timed out waiting for shell prompt.")
        channel.close(); client.close(); return 1

    # ── Start Hermes profile ──────────────────────────────────────────────────
    print(f"Starting '{PROFILE}' profile (loading may take 1-2 min) ...")
    channel.send(f"{PROFILE}\n")

    buf, found, reason = read_until_ready(channel, HERMES_PROMPTS, timeout=timeout, silence_sec=6)
    c = clean(buf)
    if verbose:
        print(f"[hermes-start — reason={reason}]\n{c[-800:]}\n")

    if reason == "timeout":
        print("Timed out waiting for Hermes to start. Last output:")
        print(c[-600:])
        channel.close(); client.close(); return 1

    if reason == "silence":
        print(f"Hermes output went silent (no known prompt detected). Proceeding anyway ...")
    else:
        print(f"Hermes prompt detected ('{found}'). Ready.")

    # ── Send seed facts ───────────────────────────────────────────────────────
    print("Sending seed facts ...")
    channel.send(SEED_FACTS + "\n")

    buf, found, reason = read_until_ready(channel, HERMES_PROMPTS, timeout=timeout, silence_sec=6)
    c = clean(buf)
    if verbose:
        print(f"[hermes-response — reason={reason}]\n{c[-1200:]}\n")

    if reason == "timeout":
        print("Warning: timed out waiting for Hermes response. Attempting exit anyway.")
    elif reason == "silence":
        print("Hermes responded (output settled). Exiting ...")
    else:
        print("Facts received by Hermes. Exiting ...")

    # ── Exit Hermes ───────────────────────────────────────────────────────────
    channel.send("/exit\n")
    time.sleep(3)

    if verbose and channel.recv_ready():
        print(f"[exit]\n{clean(channel.recv(4096).decode(errors='replace'))}")

    channel.close()
    client.close()
    print("Done — memory seeded successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Seed Hermes memory for the discounted-groceries project"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the facts that would be sent, without connecting",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show clean Hermes terminal output at each stage",
    )
    parser.add_argument(
        "--timeout", type=int, default=180,
        help="Max seconds to wait for Hermes at each stage (default: 180)",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== Facts to be seeded ===")
        print(SEED_FACTS)
        print("==========================")
        return

    sys.exit(seed_memory(timeout=args.timeout, verbose=args.verbose))


if __name__ == "__main__":
    main()
