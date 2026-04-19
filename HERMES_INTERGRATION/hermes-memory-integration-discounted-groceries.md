# Hermes Persistent Memory Integration — discounted-groceries Project
**How this project was set up with Hermes as Claude Code memory backend**
*April 2026 — Verified working (updated 2026-04-17)*

---

## Overview

This document records how the Bulgarian grocery price pipeline project (`discounted-groceries`)
was integrated with Hermes Agent as a persistent memory backend for Claude Code.

The goal: every Claude Code session working on this project automatically has access to
accumulated knowledge — pipeline state, weekly run decisions, configuration, lessons learned —
without re-reading documentation files at the start of every session.

---

## Why a Separate Profile

Other projects were already running under the default Hermes profile. To prevent memory
contamination between projects, a dedicated profile was created for this project. Each
profile is a completely isolated environment with its own:

- `MEMORY.md` — only facts about this project
- `USER.md` — blank (fresh)
- Hindsight memory bank — separate `bank_id: "discounted-groceries"`
- Session history — completely separate database

The default profile and all other projects are completely unaffected.

---

## Architecture

```
Claude Code (Windows laptop)
    ↓ MCP via hermes-discounted-groceries-mcp.bat
Hermes Agent on VPS (discounted-groceries profile)
    ├── MEMORY.md + USER.md (always in system prompt)
    └── Hindsight plugin (semantic recall across sessions)
            ↓ mode: local_external
        hindsight-api server (localhost:8888)
            ├── PostgreSQL backend
            └── LLM calls → LiteLLM proxy (localhost:4000)
                                ↓
                        Azure OpenAI gpt-4o
```

**Key insight:** Hermes has two memory layers — `MEMORY.md` (always injected) and
Hindsight (semantic search). Claude Code gets both automatically via MCP. The Hindsight
layer requires two running services on the VPS: a **LiteLLM proxy** (port 4000, routes
to Azure) and a **hindsight-api server** (port 8888, PostgreSQL-backed). Both run as
systemd user services and start automatically on VPS reboot.

---

## Profile Details

| Item | Value |
|---|---|
| Profile name | `discounted-groceries` |
| Command alias | `discounted-groceries` (on VPS) |
| Profile path | `~/.hermes/profiles/discounted-groceries/` |
| Hindsight bank_id | `discounted-groceries` |
| Hindsight mode | `local_external` (connects to port 8888 server) |
| GitHub repo | `github.com/metamorfeus/discounted-groceries` (private) |
| VPS repo path | `~/projects/discounted-groceries/` |
| MCP bat file | `hermes-discounted-groceries-mcp.bat` (project root) |
| MCP server name | `hermes-discounted-groceries` |
| Set up date | 2026-04-16 |
| Memory seeded | 2026-04-17 (54 items via Hindsight API) |

---

## What Was Done — Step by Step

### Step 1 — Created Hermes profile on VPS

```bash
hermes profile create discounted-groceries --clone
```

Output confirmed: profile created at `~/.hermes/profiles/discounted-groceries/`,
wrapper at `/home/hermes/.local/bin/discounted-groceries`.

`--clone` copies API keys and model config from `default` profile — no reconfiguration needed.

**Profile name constraint:** Hermes requires `[a-z0-9][a-z0-9_-]{0,63}` — lowercase
only, no uppercase, no special characters.

### Step 2 — Configured LiteLLM proxy

The Hindsight API server needs an LLM for memory processing. A LiteLLM proxy routes
requests from hindsight-api to Azure OpenAI.

```yaml
# ~/.hermes/litellm_config.yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_base: https://openai-ops-meeting.openai.azure.com/
      api_key: os.environ/AZURE_OPENAI_API_KEY
      api_version: "2024-02-01"
```

Started and made persistent via systemd:
```bash
# ~/.config/systemd/user/litellm-proxy.service
[Unit]
Description=LiteLLM Proxy for Azure OpenAI
After=network.target

[Service]
Type=simple
EnvironmentFile=%h/.hermes/.env
ExecStart=%h/.local/bin/litellm --config %h/.hermes/litellm_config.yaml --port 4000 --host 127.0.0.1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now litellm-proxy.service
```

### Step 3 — Started hindsight-api server

The hindsight-api server stores and retrieves memories using PostgreSQL. It needs LLM
env vars pointing to the LiteLLM proxy.

A wrapper script handles env var sourcing:

```bash
# ~/.hermes/start-hindsight-api.sh
#!/bin/bash
source ~/.hermes/.env
export HINDSIGHT_API_LLM_PROVIDER=openai
export HINDSIGHT_API_LLM_MODEL=gpt-4o
export HINDSIGHT_API_LLM_BASE_URL=http://localhost:4000/v1
export HINDSIGHT_API_LLM_API_KEY=$HINDSIGHT_LLM_API_KEY
exec ~/.hermes/hermes-agent/venv/bin/hindsight-api --host 127.0.0.1 --port 8888
```

Systemd service:
```bash
# ~/.config/systemd/user/hindsight-api.service
[Unit]
Description=Hindsight API Server (discounted-groceries memory)
After=network.target litellm-proxy.service

[Service]
Type=simple
ExecStart=%h/.hermes/start-hindsight-api.sh
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now hindsight-api.service
# Takes ~15s to start (PostgreSQL initialization)
curl http://localhost:8888/health  # → {"status":"healthy","database":"connected"}
```

### Step 4 — Configured Hindsight memory bank

**Critical:** mode must be `"local_external"` — NOT `"local"`. The value `"local"` is a
legacy alias for `"local_embedded"` which tries to start a new embedded server, ignoring
our standalone port-8888 instance. This will silently fail.

```bash
mkdir -p ~/.hermes/profiles/discounted-groceries/hindsight
cat > ~/.hermes/profiles/discounted-groceries/hindsight/config.json << 'EOF'
{
  "mode": "local_external",
  "api_url": "http://localhost:8888",
  "bank_id": "discounted-groceries",
  "recall_budget": "mid",
  "memory_mode": "hybrid",
  "auto_retain": true,
  "auto_recall": true
}
EOF
```

### Step 5 — Initialized GitHub repo

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

### Step 6 — Created MCP wrapper bat file

`hermes-discounted-groceries-mcp.bat` in project root:

```batch
@echo off
ssh -i C:\Users\PVELINOV\.ssh\hermes_contabo_openssh -p 2222 -o StrictHostKeyChecking=no -o BatchMode=yes hermes@62.146.169.66 "bash -l -c 'hermes -p discounted-groceries mcp serve'"
```

The `bash -l -c` wrapper is required — plain SSH doesn't load PATH where hermes is installed.

### Step 7 — Registered MCP server in Claude Code

```powershell
claude mcp add hermes-discounted-groceries --transport stdio "C:\AHA\OneDrive - AHA\BG\FOOD-PRICES\hermes-discounted-groceries-mcp.bat"
```

Config written to `C:\Users\PVELINOV\.claude.json` scoped to project folder
`C:\AHA\OneDrive - AHA\BG\FOOD-PRICES`. This is correct — MCP is intentionally
project-scoped, not global.

### Step 8 — Cloned repo on VPS

VPS auto-sync cron already exists from previous project setup (`~/sync-projects.sh`
running every 5 minutes). Repo was also cloned immediately for first use:

```bash
cd ~/projects && git clone https://github.com/metamorfeus/discounted-groceries.git
```

### Step 9 — Seeded Hindsight memory bank (2026-04-17)

Memory was seeded directly via the Hindsight REST API (not via `hermes chat`) because
the chat `hindsight_retain` step was hanging while the bank didn't yet exist. The
direct API approach is more reliable for initial seeding.

```bash
curl -X POST http://localhost:8888/v1/default/banks/discounted-groceries/memories \
  -H "Content-Type: application/json" \
  -d '{"items": [{"content": "Your fact here"}]}'
```

A batch seeding script (`seed_hermes_memory.py`) was used to store 7 fact groups
(54 memory items total) covering:
1. Project overview — directory, master JSON, CW16 stats, output file
2. Pipeline order — 6 scripts, run Wednesday/Thursday each week
3. Excel report sheets — 7 sheets and their purpose
4. Data sources — per-store scraping method and URL type
5. CW16 issues — Glovo blocked by bot detection, needs Bulgarian VPN IP
6. `generate_cheapest_xlsx.py` features
7. Azure/LiteLLM configuration

---

## How Memory Recall Works

- Recall activates starting from **the second turn** of each chat session
- Turn 1: Hermes responds without memory context (no prior prefetch cached)
- After turn 1: Hindsight runs a background recall and caches results
- Turn 2+: recalled memories are automatically injected into system context

In single-turn (`-Q -q`) mode, recall never fires. Use two `-q` flags as a workaround:
`hermes -p discounted-groceries chat -Q -q "hello" -q "your real question"`

---

## How to Use

**Start an interactive session on VPS:**
```bash
ssh -i /c/Users/PVELINOV/.ssh/hermes_contabo_openssh -p 2222 hermes@62.146.169.66
hermes -p discounted-groceries chat
```

**Recall project context (do this at session start):**
```
Use hermes-discounted-groceries to recall what you know about this project
```

**Add new facts to memory during a session:**
```
Use hermes-discounted-groceries to save this fact: [fact in neutral language]
```

> ⚠️ **Azure content filter:** If memory seeding fails, use short neutral factual
> statements. Avoid words like "critical", "bypass", "inject", "override" even in
> innocent technical contexts — Azure's jailbreak filter triggers on these patterns.

**Update the repo after adding new docs:**
```powershell
git add .
git commit -m "Update docs / pipeline state"
git push
```

VPS syncs automatically within 5 minutes via `~/sync-projects.sh` cron job.

---

## Profile Commands (on VPS)

```bash
# Start the discounted-groceries profile interactively
hermes -p discounted-groceries chat

# One-shot query (recall fires from turn 2 — use two -q flags)
hermes -p discounted-groceries chat -Q -q "hello" -q "your question"

# Check service health
curl http://localhost:8888/health
curl http://localhost:4000/health

# Systemd service management
systemctl --user status litellm-proxy.service hindsight-api.service
systemctl --user restart hindsight-api.service

# List Hermes profiles
hermes profile list
```

---

## VPS Auto-Sync

The existing cron job at `~/sync-projects.sh` (runs every 5 minutes) automatically
picks up `~/projects/discounted-groceries/` — no crontab changes were needed.

---

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `hermes: command not found` via SSH | Login shell not loaded | Use `bash -l -c "hermes ..."` |
| Recall returns nothing on first turn | Normal — prefetch fires after turn 1, not before | Send second message; use `-q "hello" -q "real question"` |
| Port 8888 not responding | hindsight-api service not running or still starting | `systemctl --user restart hindsight-api.service` then wait 15s for PostgreSQL |
| Port 4000 not responding | LiteLLM proxy not running | `systemctl --user restart litellm-proxy.service` |
| `hindsight_retain` hangs on first seed | Bank doesn't exist yet; `hermes chat` blocks waiting for creation | Seed via direct API: `curl -X POST http://localhost:8888/v1/default/banks/discounted-groceries/memories ...` |
| `"mode": "local"` silently fails | `local` is legacy alias for `local_embedded`, not `local_external` | Change to `"local_external"` and add `"api_url": "http://localhost:8888"` |
| Azure content filter blocks seeding | Phrases like "critical", "bypass", "inject" trigger false positive | Use short neutral factual statements |
| `HINDSIGHT_API_LLM_API_KEY` empty | Systemd `ExecStart` can't expand `$VAR` from `EnvironmentFile` directly | Use a wrapper shell script that sources `.env` then exports the variable |
| Services stop after VPS reboot | Services not enabled in systemd | `systemctl --user enable litellm-proxy.service hindsight-api.service` + `loginctl enable-linger hermes` |
