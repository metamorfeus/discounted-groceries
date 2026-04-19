# Hermes Persistent Memory Integration

This document describes how the BG Food Prices pipeline project is connected to a persistent AI memory system running on a VPS, so that project knowledge survives across Claude Code sessions.

---

## What Is Hermes

Hermes is an AI agent framework with persistent, session-crossing memory. It runs on a private VPS and stores structured facts using **Hindsight** — a knowledge-graph memory system with semantic recall.

For this project, Hermes stores pipeline state, weekly run decisions, configuration, and lessons learned. At the start of a new Claude Code session, the assistant can recall this accumulated knowledge without re-reading all the documentation.

---

## Architecture

```
Claude Code (Windows laptop)
    │
    ├── SSH → Hermes VPS (62.146.169.66:2222, user: hermes)
    │             │
    │             ├── LiteLLM proxy (localhost:4000)
    │             │     └── routes to Azure OpenAI gpt-4o
    │             │
    │             └── Hindsight API server (localhost:8888)
    │                   └── PostgreSQL backend
    │                   └── bank: discounted-groceries
    │
    └── hermes-discounted-groceries MCP server
          └── bat file: hermes-discounted-groceries-mcp.bat
```

---

## Components and Locations

| Component | Location / Command |
|---|---|
| Hermes profile name | `discounted-groceries` |
| VPS SSH | `hermes@62.146.169.66:2222`, key at `C:\Users\PVELINOV\.ssh\hermes_contabo_openssh` |
| Profile config | `~/.hermes/profiles/discounted-groceries/config.yaml` on VPS |
| Hindsight config | `~/.hermes/profiles/discounted-groceries/hindsight/config.json` on VPS |
| LiteLLM config | `~/.hermes/litellm_config.yaml` on VPS |
| LiteLLM service | `systemctl --user status litellm-proxy.service` |
| Hindsight service | `systemctl --user status hindsight-api.service` |
| Memory bank ID | `discounted-groceries` |
| Startup wrapper | `~/.hermes/start-hindsight-api.sh` |
| MCP bat file | `hermes-discounted-groceries-mcp.bat` in project dir |

---

## Key Configuration Details

### Hindsight config (`~/.hermes/profiles/discounted-groceries/hindsight/config.json`)

```json
{
  "mode": "local_external",
  "api_url": "http://localhost:8888",
  "bank_id": "discounted-groceries",
  "recall_budget": "mid",
  "memory_mode": "hybrid",
  "auto_retain": true,
  "auto_recall": true
}
```

**Important:** `mode` must be `"local_external"` (not `"local"` — that is a legacy alias for `local_embedded` and would try to start a new embedded server instead of connecting to the existing one).

### LiteLLM proxy (`~/.hermes/litellm_config.yaml`)

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_base: https://openai-ops-meeting.openai.azure.com/
      api_key: os.environ/AZURE_OPENAI_API_KEY
      api_version: "2024-02-01"
```

The Azure API key is sourced from `~/.hermes/.env` as `AZURE_OPENAI_API_KEY`.

### Hermes profile config (`config.yaml`) — key sections

```yaml
model:
  default: gpt-4o
  provider: custom
  base_url: http://localhost:4000/v1
  api_key_env: AZURE_OPENAI_API_KEY
  api_version: '2024-02-01'
memory:
  memory_enabled: true
  provider: hindsight
```

---

## How Memory Recall Works

- Memory is recalled starting from **the second turn** of each chat session.
- On turn 1: Hermes responds without memory context (no prior prefetch).
- After turn 1: Hindsight runs a background recall and caches results.
- From turn 2 onwards: recalled memories are injected into the system context automatically.

In single-turn (`-Q -q`) sessions, recall never fires. Use multi-turn interactive sessions for full memory recall.

---

## Starting a Session

### Interactive chat (recommended)

```bash
ssh -i /c/Users/PVELINOV/.ssh/hermes_contabo_openssh -p 2222 hermes@62.146.169.66
hermes -p discounted-groceries chat
```

The first message is a warm-up; from the second message onwards, the assistant recalls project facts.

### Quick query (no recall on first turn)

```bash
hermes -p discounted-groceries chat -Q -q "hello" -q "your actual question here"
```

Use two `-q` flags: the first warms the prefetch cache, the second benefits from recall.

---

## Systemd Services (auto-start on VPS reboot)

Both services are enabled as systemd user units with linger:

```bash
# Check status
systemctl --user status litellm-proxy.service
systemctl --user status hindsight-api.service

# Restart if needed
systemctl --user restart litellm-proxy.service
systemctl --user restart hindsight-api.service

# View logs
journalctl --user -u litellm-proxy.service -n 50
journalctl --user -u hindsight-api.service -n 50
```

The hindsight-api service uses `~/.hermes/start-hindsight-api.sh` as its wrapper to properly source env vars and set `HINDSIGHT_API_LLM_API_KEY`.

---

## Memory Bank Contents (seeded 2026-04-17)

The `discounted-groceries` bank was seeded with the following fact groups (54 memory items total):

1. Project overview — working directory, master JSON, CW16 stats, output file
2. Pipeline order — 6 scripts, run Wednesday/Thursday each week
3. Excel report sheets — 7 sheets and their purpose
4. Data sources — per-store scraping method and URL type
5. CW16 issues — Glovo blocked by bot detection, needs Bulgarian VPN IP
6. `generate_cheapest_xlsx.py` features — _METHOD_MAP, audit, URL columns, Метод column
7. Azure/LiteLLM config — endpoint, deployment, api_version

---

## Seeding New Memories

To add facts to the memory bank directly via API:

```bash
curl -X POST http://localhost:8888/v1/default/banks/discounted-groceries/memories \
  -H "Content-Type: application/json" \
  -d '{"items": [{"content": "Your fact here"}]}'
```

Or start a chat session and just tell Hermes what to remember — `auto_retain: true` will store it automatically.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `hermes: command not found` | Use `bash -l -c "hermes ..."` in SSH to load the login profile |
| Recall not working on first turn | Normal — send a second message; recall fires from turn 2 |
| Port 8888 not responding | `systemctl --user restart hindsight-api.service` and wait 15s for PostgreSQL |
| LiteLLM 404 / auth errors | Check `~/.hermes/.env` has `AZURE_OPENAI_API_KEY` set correctly |
| `mode: "local"` silently fails | Change to `"local_external"` in hindsight/config.json |
