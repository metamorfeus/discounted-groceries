# Hermes Persistent Memory Integration — discounted-groceries Project
**How this project was set up with Hermes as Claude Code memory backend**
*April 2026 — Verified working*

---

## Overview

This document records how the Bulgarian grocery price pipeline project (`discounted-groceries`)
was integrated with Hermes Agent as a persistent memory backend for Claude Code.

The goal: every Claude Code session working on this project automatically has access to
accumulated knowledge — pipeline state, weekly run decisions, configuration, lessons learned —
without re-reading documentation files at the start of every session.

---

## Architecture

```
Claude Code (VS Code / Claude Code CLI)
    ↓ MCP via hermes-discounted-groceries-mcp.bat
Hermes Agent on VPS (discounted-groceries profile)
    ↓ persistent memory
MEMORY.md + USER.md (always in system prompt)
Hindsight plugin (semantic search across all sessions)
```

---

## Profile Details

| Item | Value |
|---|---|
| Profile name | `discounted-groceries` |
| Command alias | `discounted-groceries` (on VPS) |
| Profile path | `~/.hermes/profiles/discounted-groceries/` |
| Hindsight bank_id | `discounted-groceries` |
| GitHub repo | `github.com/metamorfeus/discounted-groceries` (private) |
| VPS repo path | `~/projects/discounted-groceries/` |
| MCP bat file | `hermes-discounted-groceries-mcp.bat` (project root) |
| MCP server name | `hermes-discounted-groceries` |
| Set up date | 2026-04-16 |

---

## What Was Done — Step by Step

### Step 1 — Created Hermes profile on VPS

```bash
hermes profile create discounted-groceries --clone
```

Output confirmed: profile created at `~/.hermes/profiles/discounted-groceries/`,
wrapper at `/home/hermes/.local/bin/discounted-groceries`.

`--clone` copies API keys and model config from `default` profile — no reconfiguration needed.

### Step 2 — Configured Hindsight memory bank

```bash
mkdir -p ~/.hermes/profiles/discounted-groceries/hindsight
cat > ~/.hermes/profiles/discounted-groceries/hindsight/config.json << 'EOF'
{
  "mode": "local",
  "bank_id": "discounted-groceries",
  "recall_budget": "mid",
  "memory_mode": "hybrid",
  "auto_retain": true,
  "auto_recall": true
}
EOF
```

### Step 3 — Initialized GitHub repo

The local project folder had no git repo. Initialized and connected to the
pre-existing empty GitHub repo `metamorfeus/discounted-groceries`:

```bash
git init
git remote add origin https://github.com/metamorfeus/discounted-groceries.git
git add [all appropriate files — see .gitignore for exclusions]
git commit -m "Initial commit — Bulgarian grocery price pipeline"
git push -u origin master
```

**Files excluded from git (see .gitignore):**
- `secrets.py`, `azure_secrets.json` — API keys
- `*.pdf`, `*.xlsx`, `*.png` — large binary/generated files
- `*-DESKTOP-CMDM9KH*` — machine-specific duplicates
- `billa_work/`, `fantastico_work/` — working directories
- Intermediate JSON data files (per-run outputs)
- `chat_history.md` — session notes

### Step 4 — Created MCP wrapper bat file

`hermes-discounted-groceries-mcp.bat` in project root:

```batch
@echo off
ssh -i C:\Users\PVELINOV\.ssh\hermes_contabo_openssh -p 2222 -o StrictHostKeyChecking=no -o BatchMode=yes hermes@62.146.169.66 "bash -l -c 'hermes -p discounted-groceries mcp serve'"
```

### Step 5 — Registered MCP server in Claude Code

```powershell
claude mcp add hermes-discounted-groceries --transport stdio "C:\AHA\OneDrive - AHA\BG\FOOD-PRICES\hermes-discounted-groceries-mcp.bat"
```

Config written to `C:\Users\PVELINOV\.claude.json` scoped to project folder
`C:\AHA\OneDrive - AHA\BG\FOOD-PRICES`.

### Step 6 — Cloned repo on VPS

VPS auto-sync cron already exists from previous project setup (`~/sync-projects.sh`
running every 5 minutes). Repo was also cloned immediately for first use:

```bash
cd ~/projects && git clone https://github.com/metamorfeus/discounted-groceries.git
```

---

## How to Use in Claude Code

**Start a session in the project folder:**
```powershell
cd "C:\AHA\OneDrive - AHA\BG\FOOD-PRICES"
claude
```

**Recall project context (do this at session start):**
```
Use hermes-discounted-groceries to recall what you know about this project
```

**Add new facts to memory during a session:**
```
Use hermes-discounted-groceries to save this fact: [fact in neutral language]
```

> ⚠️ **Azure content filter note:** If memory seeding is blocked, use short neutral
> factual statements. Avoid words like "critical", "bypass", "inject" even in innocent
> technical contexts — Azure's jailbreak filter triggers on these patterns.

**Update the repo after adding new docs:**
```powershell
git add .
git commit -m "Update docs / pipeline state"
git push
```

VPS syncs automatically within 5 minutes via `~/sync-projects.sh` cron job.

---

## Memory Seeding — Suggested Facts to Retain

After completing setup, SSH to VPS, start the profile, and seed these facts:

```bash
cd ~/projects/discounted-groceries
discounted-groceries
```

Then in Hermes:
```
Please save these facts to your memory:
This project scrapes weekly promotional grocery prices from Bulgarian retailers and generates an Excel price-comparison report.
The four retailers covered are Gladen.bg (Hit Max), Billa, Kaufland, and Fantastico.
All prices are stored in EUR by dividing BGN prices by 1.95583.
The master dataset file is bulgarian_promo_prices_merged.json — each retailer script merges its records into this file.
The weekly pipeline runs in order: gladen_html_scraper.py, billa_pdf_pipeline.py, billa_scraper.py, write_glovo_data.py, fantastico_pipeline.py, generate_cheapest_xlsx.py.
gladen_html_scraper.py requires PROMO_PERIOD to be updated at the top of the file before each weekly run.
write_glovo_data.py requires hardcoded product lists and file paths to be updated each week.
secrets.py contains the Azure API keys and is not committed to git.
The Excel report is generated by generate_cheapest_xlsx.py and uses Azure OpenAI GPT-4o for product classification.
The GitHub repo is metamorfeus/discounted-groceries and the VPS repo is at ~/projects/discounted-groceries/.
```

---

## VPS Auto-Sync

The existing cron job at `~/sync-projects.sh` (runs every 5 minutes) automatically
picks up `~/projects/discounted-groceries/` — no crontab changes were needed.

---

## Profile Commands (on VPS)

```bash
# Start the discounted-groceries profile
discounted-groceries

# Check memory status
discounted-groceries memory status

# List all profiles
hermes profile list
```
