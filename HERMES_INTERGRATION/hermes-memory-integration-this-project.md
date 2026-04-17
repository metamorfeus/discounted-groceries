# Hermes Persistent Memory Integration — BOOK-GRAPH-RAG Project
**How this specific project was set up with Hermes as Claude Code memory backend**
*April 2026 — Verified working*

---

## Overview

This document records exactly how the BOOK-GRAPH-RAG infrastructure project was
integrated with Hermes Agent as a persistent memory backend for Claude Code. It
covers every decision made, every problem encountered, and the final working state.

The goal was: every Claude Code session working on this project automatically has
access to accumulated knowledge about the infrastructure — VPS details, Azure
configuration, ingestion pipeline state, lessons learned — without re-reading
documentation files at the start of every session.

---

## Architecture

```
Claude Code (VS Code)
    ↓ MCP via hermes-book-rag-anything-mcp.bat
Hermes Agent on VPS (book-rag-anything profile)
    ↓ persistent memory
MEMORY.md + USER.md (always in system prompt)
Hindsight plugin (semantic search across all sessions)
```

**Key insight from the Hermes docs:** Hermes already has two memory layers built in —
`MEMORY.md` (always injected into every session) and Hindsight (semantic search across
all past sessions). Claude Code gets access to both automatically via MCP. No separate
memory plugin for Claude Code is needed.

---

## Why a Separate Profile

You already had other projects running under the default Hermes profile. To prevent
memory contamination between projects, a dedicated Hermes profile was created for this
project. Each profile is a completely isolated environment with its own:

- `MEMORY.md` — only facts about this project
- `USER.md` — blank (fresh)
- Hindsight memory bank — separate `bank_id: "book-rag-anything"`
- Session history — completely separate SQLite database

The default profile and its projects are completely unaffected.

---

## What Was Done — Step by Step

### Step 1 — Confirmed only one profile existed

```bash
hermes profile list
# Only showed: default
```

### Step 2 — Created the book-rag-anything profile

```bash
hermes profile create book-rag-anything --clone
```

`--clone` copies API keys and model config from default but gives a completely fresh
memory and session history. This avoids reconfiguring Azure/LiteLLM credentials.

**Profile name constraint discovered:** Hermes requires profile names to match
`[a-z0-9][a-z0-9_-]{0,63}` — lowercase only, no uppercase, no special characters.
`BOOK-RAG-Anything` failed; `book-rag-anything` worked.

### Step 3 — Configured Hindsight memory bank

```bash
mkdir -p ~/.hermes/profiles/book-rag-anything/hindsight
cat > ~/.hermes/profiles/book-rag-anything/hindsight/config.json << 'EOF'
{
  "mode": "local",
  "bank_id": "book-rag-anything",
  "recall_budget": "mid",
  "memory_mode": "hybrid",
  "auto_retain": true,
  "auto_recall": true
}
EOF
```

A unique `bank_id` ensures Hindsight stores this project's memories separately from
any other project's memories.

### Step 4 — Created the GitHub repository

All infrastructure documentation was committed to a dedicated GitHub repo:
`github.com/metamorfeus/BOOK-GRAPH-RAG` (private)

**On Windows:**
```powershell
cd "C:\AHA\OneDrive - AHA\METAMORFEUS\AI_CYBORG\PLAYBOOK\BOOK-GRAPH_RAG"
git init
git remote add origin https://github.com/metamorfeus/BOOK-GRAPH-RAG.git
git add .
git commit -m "Initial commit — infrastructure handoff docs and scripts"
git push -u origin main
```

**On VPS:**
```bash
cd ~/projects
git clone https://github.com/metamorfeus/BOOK-GRAPH-RAG.git
```

GitHub is the transport layer — documents are pushed from Windows and pulled on VPS.
No manual SCP needed. VPS always gets latest with `git pull`.

### Step 5 — Created the MCP wrapper script

Saved as `hermes-book-rag-anything-mcp.bat` in the project folder
`C:\AHA\OneDrive - AHA\METAMORFEUS\AI_CYBORG\PLAYBOOK\BOOK-GRAPH_RAG\`:

```batch
@echo off
ssh -i C:\Users\PVELINOV\.ssh\hermes_contabo_openssh -p 2222 -o StrictHostKeyChecking=no -o BatchMode=yes hermes@62.146.169.66 "bash -l -c 'hermes -p book-rag-anything mcp serve'"
```

The `-p book-rag-anything` flag targets the isolated profile. The `bash -l -c` wrapper
is required — plain SSH doesn't load PATH where hermes is installed.

### Step 6 — Registered the MCP server in Claude Code

```powershell
claude mcp add hermes-book-rag-anything --transport stdio "C:\AHA\OneDrive - AHA\METAMORFEUS\AI_CYBORG\PLAYBOOK\BOOK-GRAPH_RAG\hermes-book-rag-anything-mcp.bat"
```

Config was written to `C:\Users\PVELINOV\.claude.json` scoped to the project folder.

### Step 7 — Seeded Hermes memory

**Problem encountered:** Sending `CLAUDE-CODE-HANDOFF.md` to Hermes triggered Azure's
content filter (false positive jailbreak detection — the file contained phrases like
"critical fixes", "do not repeat these mistakes" which pattern-matched Azure's filter).

**Workaround:** Short, neutral, factual statements were used instead:

```
Please save these facts to your memory:
VPS is at 62.146.169.66 port 2222, user hermes, Ubuntu 24.04.
Azure resource openai-ops-meeting has gpt-4o and text-embedding-3-large in the same resource.
[... 12 more factual statements ...]
```

All 8 memory entries were successfully saved:
```
+memory: "VPS is at 62.146.169.66 port 2222, user hermes, Ubuntu 24.04."
+memory: "Azure resource openai-ops-meeting has gpt-4o and text-embedding-3-large..."
+memory: "LightRAG research workspace runs on port 9621 at ~/lightrag/..."
+memory: "RAG-Anything venv is at ~/raganything-venv/ with MinerU 3.0.9..."
+memory: "AsyncAzureOpenAI is the only working LLM function for RAG-Anything with Azure."
+memory: "Workstation tool: ingest-manager.py with ingest-manager-config.ini..."
+memory: "Documentation repo: github.com/metamorfeus/BOOK-GRAPH-RAG..."
+memory: "24 of 32 documents completed in LightRAG research workspace."
```

---

## Current State

### Profile
| Item | Value |
|---|---|
| Profile name | `book-rag-anything` |
| Command alias | `book-rag-anything` (on VPS) |
| Profile path | `~/.hermes/profiles/book-rag-anything/` |
| Hindsight bank | `book-rag-anything` |
| Memory entries | 8 facts seeded |
| Sessions | Isolated from default profile |

### Files
| File | Location |
|---|---|
| MCP wrapper | `C:\AHA\OneDrive - AHA\METAMORFEUS\AI_CYBORG\PLAYBOOK\BOOK-GRAPH_RAG\hermes-book-rag-anything-mcp.bat` |
| Hindsight config | `~/.hermes/profiles/book-rag-anything/hindsight/config.json` |
| Documentation repo | `~/projects/BOOK-GRAPH-RAG/` on VPS |
| GitHub repo | `github.com/metamorfeus/BOOK-GRAPH-RAG` (private) |

### Claude Code MCP
```
hermes-book-rag-anything: ... ✓ Connected
```

---

## How to Use in Claude Code

**Start a Claude Code terminal session:**
```powershell
cd "C:\AHA\OneDrive - AHA\METAMORFEUS\AI_CYBORG\PLAYBOOK\BOOK-GRAPH_RAG"
claude
```

**Recall infrastructure facts at start of session:**
```
Use hermes-book-rag-anything to recall what you know about this project
```

**Add new facts to memory during a session:**
```
Use hermes-book-rag-anything to save this fact: [your fact here]
```

**Update the repo after adding new docs:**
```powershell
git add .
git commit -m "Add new documentation"
git push
```

VPS syncs automatically within 5 minutes — no manual `git pull` needed.
See the Auto-Sync section below for how this works.

---

## VPS Auto-Sync Setup

A cron job and a sync script were created so the VPS automatically pulls from GitHub
every 5 minutes. No manual `git pull` needed after pushing from Windows.

### The sync script (`~/sync-projects.sh`)

```bash
#!/bin/bash
# Auto-sync all git repos in ~/projects/
LOG="$HOME/.git-sync.log"
echo "--- Sync run: $(date) ---" >> "$LOG"

for repo in ~/projects/*/; do
    if [ -d "$repo/.git" ]; then
        cd "$repo"
        result=$(git pull --quiet 2>&1)
        echo "$repo: ${result:-already up to date}" >> "$LOG"
    fi
done
```

**Key design decision:** The script loops over ALL folders inside `~/projects/` and
pulls any that contain a `.git` directory. This means adding a new project in future
requires no crontab changes — just clone into `~/projects/` and it gets synced
automatically.

### The crontab entry

```
*/5 * * * * /home/hermes/sync-projects.sh
```

One line covers all current and future projects.

### Checking sync status

```bash
# See all recent sync runs
cat ~/.git-sync.log

# Watch live (updates every 30 seconds)
watch -n 30 cat ~/.git-sync.log
```

Expected output:
```
--- Sync run: Fri Apr 17 02:23:44 CEST 2026 ---
/home/hermes/projects/BOOK-GRAPH-RAG/: already up to date
/home/hermes/projects/BOOK/: already up to date
```

---

## Problems Encountered and Solutions

| Problem | Cause | Solution |
|---|---|---|
| Profile name `BOOK-RAG-Anything` rejected | Hermes requires `[a-z0-9][a-z0-9_-]{0,63}` — lowercase only | Used `book-rag-anything` |
| Azure content filter blocked memory seeding | File content triggered false positive jailbreak detection | Used short neutral factual statements instead of full document |
| Hermes couldn't find `CLAUDE-CODE-HANDOFF.md` | File only existed on Windows, not yet on VPS | Push to GitHub first, then `git pull` on VPS |
| Commands typed in bash instead of Hermes | Accidentally pressed `Ctrl+C` exiting Hermes back to bash | Run `book-rag-anything` to restart the profile |
| MCP registered at project scope | `claude mcp add` writes to `.claude.json` in current directory | This is correct — MCP is project-scoped, not global |
| Cron job content pasted into terminal instead of editor | Selected editor number not typed before pasting | Type `1` first to open nano, then paste inside nano |
| Manual `git pull` required after every push | No sync automation | Created `~/sync-projects.sh` + cron job — auto-syncs every 5 min |
| Cron job would need updating for each new project | Per-repo cron lines | Dynamic script loops over all `~/projects/*/` folders automatically |
