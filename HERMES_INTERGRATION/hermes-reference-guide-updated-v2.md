# Hermes Agent — System Reference & User Guide
**VPS: vmi3230629 | IP: 62.146.169.66 | SSH Port: 2222 | User: hermes**
*Updated: April 2026*

---

## Architecture Overview

```
Windows PC (VS Code + Claude Code)
    ↓ MCP over SSH (hermes-mcp.bat)              ← default profile, existing projects
    ↓ MCP over SSH (hermes-book-rag-anything-mcp.bat) ← book-rag-anything profile
    ↓ SSH tunnel for LightRAG UI (ports 9621/9622)
    ↓
Contabo VPS (62.146.169.66:2222)
    ├── Hermes Agent (default profile)  ← tmux session, BOOK project
    ├── Hermes Agent (book-rag-anything profile) ← infrastructure project
    ├── LiteLLM Proxy :4000   ← Azure OpenAI shim (systemd)
    ├── Firecrawl :3002        ← Web search & scraping (systemd → Docker)
    ├── LightRAG :9621         ← Research GraphRAG workspace (systemd)
    ├── LightRAG :9622         ← Book GraphRAG workspace (systemd)
    ├── RAG-Anything           ← Multimodal document ingestion (~/raganything-venv)
    ├── Hindsight daemon       ← Agent memory knowledge graph (auto, per profile)
    ├── sync-projects.sh       ← Cron job: git pull all ~/projects/ every 5 min
    └── Docker                ← Terminal sandbox for Hermes commands
    ↓
Azure OpenAI (openai-ops-meeting resource)
    ├── gpt-4o                ← LLM for Hermes + LightRAG entity extraction
    └── text-embedding-3-large ← Embeddings for LightRAG vector search

GitHub
    ├── metamorfeus/BOOK       ← AI Playbook book project
    └── metamorfeus/BOOK-GRAPH-RAG ← Infrastructure docs + scripts (auto-synced)
```

---

## What Each Component Does

### Hermes Agent
An autonomous AI agent by Nous Research. Executes terminal commands, reads/writes files, searches the web, schedules tasks, and maintains persistent memory across sessions. Runs as the `hermes` Linux user, stores all state in `~/.hermes/`.

**Key files:**
| Path | Purpose |
|---|---|
| `~/.hermes/.env` | API keys and secrets |
| `~/.hermes/config.yaml` | All configuration |
| `~/.hermes/memories/MEMORY.md` | Agent's persistent memory (environment facts, conventions) |
| `~/.hermes/memories/USER.md` | Agent's memory about you (preferences, style) |
| `~/.hermes/sessions/` | Full conversation history (SQLite, searchable) |
| `~/.hermes/skills/` | Installed skills |
| `~/.hermes/logs/` | Agent and gateway logs |
| `~/.hermes/SOUL.md` | Agent persona |
| `~/projects/` | Cloned GitHub repos |

### LiteLLM Proxy
Runs on `localhost:4000`. Translates Hermes's standard OpenAI API calls into Azure OpenAI format by adding the required `api-version=2024-10-21` parameter. Without this, Hermes cannot talk to Azure OpenAI. Runs as systemd service `litellm`.

### Firecrawl
Self-hosted web scraping and search service on `localhost:3002`. Gives Hermes web search (via DuckDuckGo) and page scraping without API costs or rate limits. Runs as 5 Docker containers managed by systemd service `firecrawl`.

### LightRAG (Research & Book Workspaces)
GraphRAG system for document knowledge graph ingestion and semantic gap analysis. Two instances run simultaneously — research workspace on port 9621 (for research documents) and book workspace on port 9622 (for AI_PLAYBOOK_REV8.txt). Both use Azure OpenAI GPT-4o for entity extraction and `text-embedding-3-large` for vector search. Jina AI reranker improves retrieval quality. Web UI accessible via SSH tunnel.

**Critical:** Both GPT-4o and text-embedding-3-large must be in the **same** Azure resource (`openai-ops-meeting`). The `azure_openai` binding uses a single `AZURE_OPENAI_API_KEY` for both. The key is injected via systemd `Environment=` lines — NOT via `.env` — to prevent the system environment from overriding it.

**Key files:**
| Path | Purpose |
|---|---|
| `~/lightrag/.env` | Research workspace config |
| `~/lightrag-book/.env` | Book workspace config |
| `/etc/systemd/system/lightrag.service` | Research service (contains AZURE_OPENAI_API_KEY) |
| `/etc/systemd/system/lightrag-book.service` | Book service (contains AZURE_OPENAI_API_KEY) |
| `~/lightrag/rag_storage/` | Research knowledge graph data |
| `~/lightrag-book/rag_storage/` | Book knowledge graph data |
| `~/lightrag/inputs/` | Drop documents here, click Scan/Retry in web UI |
| `/tmp/test_lightrag_config.py` | Diagnostic script — run before config changes |

### RAG-Anything + MinerU + Docling
Multimodal document ingestion layer built on top of LightRAG. Processes PDFs extracting text, tables, images, and equations separately — each described by GPT-4o before indexing into the knowledge graph. Required for research PDFs that contain important tables. Installed in dedicated virtual environment at `~/raganything-venv/`. MinerU runs in `pipeline` (CPU) mode.

 Commands execute inside a container, not directly on the VPS host. Configured via `terminal.backend: docker` in Hermes config.

### Azure OpenAI GPT-4o
The AI model powering Hermes. Resource: `openai-ops-meeting`, deployment: `gpt-4o` (2024-11-20), context: 128K tokens. Accessed via LiteLLM proxy.

### Claude Code MCP Integration
Hermes runs as an MCP server via `hermes mcp serve`. Claude Code in VS Code connects to it over an SSH tunnel (`hermes-mcp.bat`). This gives Claude Code 10 Hermes tools including messaging, conversation history, and event polling.

---

## Connecting to Your Server

### PuTTY (primary)
- Host: `62.146.169.66`
- Port: `2222`
- Username: `hermes`
- Private key: `hermes_contabo.ppk`
- Saved session: `contabo-hermes`

### OpenSSH (PowerShell/terminal)
```powershell
ssh -i C:\Users\PVELINOV\.ssh\hermes_contabo_openssh -p 2222 hermes@62.146.169.66
```

> SSH key has no passphrase and loads automatically from PowerShell profile.
> No manual `ssh-add` needed after reboot.

---

## Daily Usage

### Attach to Running Hermes Session
```bash
tmux attach -t hermes
```

### Start Fresh Session
```bash
cd ~/projects/BOOK   # or any project
tmux new-session -s hermes
hermes
```

### Detach Without Stopping
Press `Ctrl+B` then `D`

### Work on a Specific Project
```bash
cd ~/projects/BOOK
git pull              # get latest AGENTS.md
hermes                # Hermes loads AGENTS.md automatically
```

### Update Hermes
```bash
hermes update
```

### Sync Project Context After a Session
In Hermes chat:
```
Update AGENTS.md with today's decisions, then git commit and push
```

---

## Hermes Chat Commands

| Command | What it does |
|---|---|
| `/help` | Show all commands |
| `/tools` | List enabled tools |
| `/model` | Switch LLM provider or model |
| `/new` | Start fresh conversation |
| `/save` | Save current conversation |
| `/compress` | Compress context when window fills up |
| `/usage` | Show token usage |
| `/skills` | Browse installed skills |
| `/exit` | Exit Hermes (type in chat) |
| `Ctrl+C` | Interrupt current task |
| `Ctrl+B D` | Detach from tmux |

---

## Service Management (run with sudo or as root)

### Check All Services
```bash
systemctl status litellm
systemctl status docker
systemctl status firecrawl
systemctl status lightrag
systemctl status lightrag-book
systemctl status fail2ban
ufw status
```

### Restart LiteLLM (if Azure connection fails)
```bash
sudo systemctl restart litellm
sudo journalctl -u litellm -n 50
```

### Restart Firecrawl (if web search fails)
```bash
cd ~/firecrawl
docker compose restart
# or via systemd:
sudo systemctl restart firecrawl
```

### View Logs
```bash
hermes logs                          # Hermes agent log
sudo journalctl -u litellm -f        # LiteLLM log
cd ~/firecrawl && docker compose logs -f   # Firecrawl log
tail -f ~/.hermes/logs/agent.log     # Direct agent log
```

---

## Troubleshooting

### Hermes: "Connection refused" / API errors
LiteLLM isn't running:
```bash
sudo systemctl restart litellm
sleep 8
curl -s -o /dev/null -w "%{http_code}" http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fake-key" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
# Must return 200
```

### Hermes: Web search not working
Firecrawl isn't running:
```bash
cd ~/firecrawl && docker compose ps
docker compose up -d   # if containers are down
```

### Azure API key expired/rotated
```bash
nano ~/.hermes/.env
# Update: AZURE_OPENAI_API_KEY=new_key_here
sudo systemctl restart litellm
```

### Hermes tmux session gone after reboot
```bash
cd ~/projects/BOOK
tmux new-session -s hermes
hermes
```

### Claude Code: Hermes MCP "Failed to connect"
1. Check SSH agent has key loaded: `ssh-add -l` (PowerShell)
2. If empty: `ssh-add C:\Users\PVELINOV\.ssh\hermes_contabo_openssh`
3. Test bat file: `C:\Users\PVELINOV\hermes-mcp.bat` (should connect silently)
4. Start new Claude Code session after reconnecting

### Run full diagnostics
```bash
hermes doctor
hermes doctor --fix
```

---

## Project Memory System

### How it works
- **Global memory** (`MEMORY.md`, `USER.md`) — facts about your environment and preferences, auto-managed by Hermes, isolated per profile
- **Project context** (`AGENTS.md` in repo root) — project-specific facts read by both Hermes and Claude Code
- **Session history** (SQLite) — all conversations searchable via `session_search` tool, isolated per profile
- **Hindsight** — semantic knowledge graph, separate bank per profile

### Three-layer memory stack
```
Built-in (MEMORY.md + USER.md)   ← fast facts always in system prompt (~1,300 tokens)
Hindsight (local embedded)        ← knowledge graph, vector search, entity relationships
Session SQLite (state.db)         ← full conversation history, full-text searchable
```

### Hermes Profiles (project isolation)

Each project gets its own Hermes profile — completely isolated memory, sessions, and Hindsight bank. No cross-contamination between projects.

| Profile | Command | Project | MCP server | Hindsight bank |
|---|---|---|---|---|
| `default` | `hermes` | BOOK + general | `hermes-mcp.bat` | `hermes` |
| `book-rag-anything` | `book-rag-anything` | Infrastructure/RAG | `hermes-book-rag-anything-mcp.bat` | `book-rag-anything` |

**Profile commands:**
```bash
hermes profile list                        # show all profiles
hermes profile create my-project --clone   # new profile, clones API keys
hermes -p my-project mcp serve            # serve MCP for specific profile
book-rag-anything                          # start book-rag-anything profile directly
```

**Profile files:**
```
~/.hermes/                              ← default profile home
~/.hermes/profiles/book-rag-anything/  ← book-rag-anything profile home
~/.hermes/profiles/book-rag-anything/hindsight/config.json  ← Hindsight config
```

### Hindsight tools
- `hindsight_retain` — store facts with automatic entity extraction
- `hindsight_recall` — multi-strategy search (semantic vector + entity graph)
- `hindsight_reflect` — synthesise patterns across all memories

### Hindsight key locations
| Path | Purpose |
|---|---|
| `~/.hermes/hindsight/config.json` | Default profile Hindsight config |
| `~/.hermes/profiles/book-rag-anything/hindsight/config.json` | book-rag-anything Hindsight config |
| `~/.hermes/logs/hindsight-embed.log` | Daemon startup log |
| `~/.hindsight/profiles/hermes.log` | Runtime log |
| `~/.pg0/instances/hindsight-embed-hermes` | PostgreSQL database |

### Check memory status
```bash
hermes memory status              # default profile
book-rag-anything memory status   # book-rag-anything profile
```

### Per-project workflow
```bash
# Default profile (BOOK project):
cd ~/projects/BOOK && git pull && hermes

# book-rag-anything profile (infrastructure):
cd ~/projects/BOOK-GRAPH-RAG && book-rag-anything

# Seed new project into memory (first time only):
> Please save these facts to your memory: [key facts as short neutral statements]

# End session (in Hermes chat):
> Update AGENTS.md with today's work, commit and push to GitHub
```

### Search past sessions
In Hermes chat:
```
Search past sessions for anything about Section 10 governance
```

### Reflect across all memories (Hindsight only)
```
Use hindsight_reflect to synthesise everything you know about my writing conventions
```

---

## Claude Code MCP Tools (via Hermes)

Once connected, Claude Code can call these Hermes tools:

| Tool | What it does |
|---|---|
| `conversations_list` | List all Hermes messaging conversations |
| `conversation_get` | Get details of one conversation |
| `messages_read` | Read message history |
| `messages_send` | Send via any connected platform |
| `events_poll` | Check for new messages |
| `events_wait` | Wait for next incoming message |
| `attachments_fetch` | Get media from messages |
| `channels_list` | List all connected platforms |
| `permissions_list_open` | Pending approval requests |
| `permissions_respond` | Approve/deny requests |

**Example Claude Code prompts:**
```
Use hermes to send a WhatsApp message saying "Build complete"
Use hermes to check if there are any new messages
Use hermes to read the last 5 messages from my conversation
```

---

## VPS Auto-Sync (GitHub → VPS)

All repos inside `~/projects/` are automatically synced from GitHub every 5 minutes.
Push from Windows → VPS gets the update within 5 minutes automatically.

**Sync script:** `~/sync-projects.sh`
Loops over all `~/projects/*/` folders and runs `git pull` on any that contain `.git`.
New projects are picked up automatically — no crontab changes needed.

**Cron entry:**
```
*/5 * * * * /home/hermes/sync-projects.sh
```

**Check sync log:**
```bash
cat ~/.git-sync.log          # see all recent runs
~/sync-projects.sh           # trigger manually right now
```

**To add a new project to auto-sync:**
```bash
cd ~/projects
git clone https://github.com/metamorfeus/NEW-REPO.git
# That's it — next cron run picks it up automatically
```

---

## Security Notes

- SSH: key-only, port 2222, password auth disabled
- fail2ban: bans after 5 failed attempts for 1 hour
- UFW: only ports 2222, 80, 443 open
- Docker: sandboxes all Hermes terminal commands
- LiteLLM: localhost only, not exposed externally
- Firecrawl: localhost only, not exposed externally
- API keys: `~/.hermes/.env` with chmod 600

### Rotate Azure API Key
When rotating the `openai-ops-meeting` key, update ALL of these:
1. Azure Portal → openai-ops-meeting → Keys → Regenerate Key 1
2. `nano ~/.hermes/.env` → update `AZURE_OPENAI_API_KEY`
3. `sudo nano /etc/systemd/system/litellm.service` → update `AZURE_API_KEY`
4. `sudo nano /etc/systemd/system/lightrag.service` → update `AZURE_OPENAI_API_KEY`
5. `sudo nano /etc/systemd/system/lightrag-book.service` → update `AZURE_OPENAI_API_KEY`
6. `nano ~/lightrag/.env` → update `LLM_BINDING_API_KEY`
7. `nano ~/lightrag-book/.env` → update `LLM_BINDING_API_KEY`
8. `nano ~/.lightrag-ingest.env` → update `AZURE_KEY`
9. ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart litellm lightrag lightrag-book
   ```

---

## Quick Reference Card

```
CONNECT (PuTTY):           hermes@62.146.169.66:2222 → hermes_contabo.ppk
ATTACH HERMES SESSION:     tmux attach -t hermes
START HERMES (BOOK):       cd ~/projects/BOOK && tmux new-session -s hermes && hermes
START HERMES (INFRA):      cd ~/projects/BOOK-GRAPH-RAG && book-rag-anything
DETACH:                    Ctrl+B then D
UPDATE HERMES:             hermes update
DIAGNOSTICS:               hermes doctor
LOGS:                      hermes logs
MEMORY STATUS (default):   hermes memory status
MEMORY STATUS (infra):     book-rag-anything memory status
PROFILE LIST:              hermes profile list
RESTART LLM:               sudo systemctl restart litellm
RESTART FIRECRAWL:         cd ~/firecrawl && docker compose restart
RESTART LIGHTRAG:          sudo systemctl restart lightrag lightrag-book
LIGHTRAG LOGS:             sudo journalctl -u lightrag -f --no-pager
CHECK INGEST:              python ingest-manager.py --status  (from Windows)
INGEST (workstation):      python ingest-manager.py
INGEST RECONNECT:          python ingest-manager.py --reconnect
INGEST (VPS direct):       AZURE_KEY=... ~/raganything-venv/bin/python ~/raganything-work/ingest.py
TEST CONFIG:               cd ~/lightrag && ~/raganything-venv/bin/python /tmp/test_lightrag_config.py
GIT SYNC STATUS:           cat ~/.git-sync.log
GIT SYNC ALL REPOS:        ~/sync-projects.sh
MCP STATUS:                claude mcp list  (in VS Code terminal)
HINDSIGHT LOG:             tail -f ~/.hindsight/profiles/hermes.log
LIGHTRAG UI:               http://localhost:9621 (research) / :9622 (book) via SSH tunnel
LIGHTRAG TUNNELS:          C:\Users\PVELINOV\lightrag-tunnels.bat (Windows)
```

---

## Pending / Future Setup

- [ ] **Complete re-ingestion** — check `python ingest-manager.py --status` from Windows; run again for remaining documents
- [ ] **Run gap analysis** — query both workspaces in hybrid mode once ingestion complete
- [ ] **Regenerate Azure API key** — exposed in chat; update in 7 locations (see Rotate Azure API Key above) + `~/.lightrag-ingest.env`
- [ ] **WhatsApp gateway** — `hermes whatsapp` then `sudo hermes gateway install --system`
- [ ] **Seed Hindsight for BOOK project** — start Hermes in `~/projects/BOOK` and say: `Read AGENTS.md and extract key facts using hindsight_retain`
- [ ] **Security updates** — `sudo apt upgrade -y`
- [ ] **New projects** — see `hermes-memory-new-project-guide.md` for step-by-step process

