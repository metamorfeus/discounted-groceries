# Hermes Agent — Complete Installation Guide
**Contabo Cloud VPS 20 (Ubuntu 24.04) + Azure OpenAI GPT-4o**
*All steps verified working — April 2026*

---

## Prerequisites

Before starting, have these ready:
- Contabo Cloud VPS 20 provisioned with Ubuntu 24.04 (NVMe, no setup fee)
- VPS IP address and root password (from Contabo "Your login data!" email)
- Azure OpenAI resource with a gpt-4o deployment (version 2024-11-20)
- Azure OpenAI API key
- Azure OpenAI endpoint URL (e.g. `https://openai-ops-meeting.openai.azure.com/`)
- Azure deployment name (e.g. `gpt-4o`)
- Azure API version — must be tested, `2024-10-21` confirmed working
- PuTTY and PuTTYgen installed on your Windows 11 machine
- GitHub account with Personal Access Token (repo scope)

---

## Phase 1 — Windows Setup & First SSH Connection

### 1.1 Generate SSH Key Pair (PuTTYgen)
1. Open PuTTYgen → select **RSA**, set bits to **4096**
2. Click **Generate**, move mouse over blank area
3. Set Key comment: `hermes-contabo`
4. Enter a passphrase (remember it)
5. Save public key → `hermes_contabo_pub.txt`
6. Save private key → `hermes_contabo.ppk`
7. Copy the public key text from the top box (starts with `ssh-rsa AAAA...`)

Also export OpenSSH format for Claude Code MCP integration:
1. In PuTTYgen → **Conversions → Export OpenSSH key**
2. Save as `hermes_contabo_openssh` to `C:\Users\USERNAME\.ssh\`

### 1.2 First Login with Password
1. Open PuTTY → Host: `YOUR_VPS_IP`, Port: `22`, Connection type: SSH
2. Save session as `contabo-hermes`
3. Click Open → login as `root` with password from Contabo email

### 1.3 Install SSH Public Key on Server
```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
# Paste your public key (right-click to paste in PuTTY), save with Ctrl+X Y Enter
chmod 600 ~/.ssh/authorized_keys
```

### 1.4 Configure PuTTY to Use Private Key
1. In PuTTY → load `contabo-hermes` session
2. Navigate to Connection → SSH → Auth → Credentials
3. Browse to `hermes_contabo.ppk`
4. Go back to Session → Save

### 1.5 Verify Key Login & Disable Password Auth
Open a new PuTTY window, connect with key. Once confirmed working:
```bash
nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no
# Set: PermitRootLogin prohibit-password
# Save: Ctrl+X Y Enter
systemctl restart ssh
```

---

## Phase 2 — Server Hardening (run as root)

### 2.1 Update System
```bash
apt update
apt upgrade -y
```

### 2.2 Install Essential Packages
```bash
apt install -y ufw fail2ban curl git tmux nano unzip
```

### 2.3 Configure Firewall
```bash
ufw allow 2222/tcp comment 'SSH custom port'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable
ufw status
```

### 2.4 Change SSH Port to 2222
```bash
nano /etc/ssh/sshd_config
# Find: #Port 22 → change to: Port 2222
# Save: Ctrl+X Y Enter

# IMPORTANT: Ubuntu 24.04 requires ALL THREE commands:
systemctl daemon-reload
systemctl restart ssh.socket
systemctl restart ssh

# Verify: ss -tlnp | grep ssh  (must show 2222, not 22)
```
> ⚠️ Before continuing: open a NEW PuTTY window on port 2222 and confirm login works.
> Then block old port: `ufw delete allow 22/tcp`

### 2.5 Configure fail2ban
```bash
cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
port = 2222
maxretry = 5
bantime = 3600
findtime = 600
EOF

systemctl enable fail2ban
systemctl restart fail2ban
```

### 2.6 Create Hermes User
```bash
useradd -m -s /bin/bash hermes
usermod -aG sudo hermes
echo "hermes ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/hermes
chmod 440 /etc/sudoers.d/hermes
mkdir -p /home/hermes/.ssh
cp ~/.ssh/authorized_keys /home/hermes/.ssh/authorized_keys
chown -R hermes:hermes /home/hermes/.ssh
chmod 700 /home/hermes/.ssh
chmod 600 /home/hermes/.ssh/authorized_keys
```
> ⚠️ Test login as `hermes` on port 2222 before continuing.

### 2.7 Install Docker (run as root)
```bash
curl -fsSL https://get.docker.com | sh
usermod -aG docker hermes
systemctl daemon-reload
systemctl enable docker
systemctl start docker
```
> Log out and back in as `hermes` for group membership to take effect.
> Verify: `docker run hello-world`

---

## Phase 3 — Hermes Agent Installation (run as hermes user)

### 3.1 Install Hermes Agent
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc
hermes --version
```

### 3.2 Add Azure OpenAI API Key
```bash
echo "AZURE_OPENAI_API_KEY=your_actual_key_here" >> ~/.hermes/.env
chmod 600 ~/.hermes/.env
```

### 3.3 Find Your Working Azure API Version
Test which api-version returns HTTP 200:
```bash
curl -s -o /dev/null -w "%{http_code}" \
  "https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT/chat/completions?api-version=2024-10-21" \
  -H "api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
# Must return 200 before proceeding
```

### 3.4 Configure Hermes config.yaml
```bash
# Set model to gpt-4o
sed -i 's/default: "anthropic\/claude-opus-4.6"/default: "gpt-4o"/' ~/.hermes/config.yaml

# Set provider to custom (pointing at LiteLLM proxy)
sed -i 's/  provider: "auto"/  provider: "custom"/' ~/.hermes/config.yaml
sed -i 's|  base_url: "https://openrouter.ai/api/v1"|  base_url: "http://localhost:4000/v1"|' ~/.hermes/config.yaml

# Add api_key_env, api_version, and context_length
sed -i '/base_url: "http:\/\/localhost:4000\/v1"/a\  api_key_env: "AZURE_OPENAI_API_KEY"\n  api_version: "2024-10-21"\n  context_length: 128000' ~/.hermes/config.yaml

# Set Docker terminal backend
hermes config set terminal.backend docker
```

---

## Phase 4 — LiteLLM Proxy (Required for Azure OpenAI)

> **Why needed:** Hermes uses `openai.OpenAI` (not `AzureOpenAI`). Azure requires
> an `api-version` query parameter. LiteLLM runs on localhost:4000 and handles this.

### 4.1 Install LiteLLM into Hermes venv
```bash
~/.local/bin/uv pip install 'litellm[proxy]' --python ~/.hermes/hermes-agent/venv/bin/python
```

### 4.2 Test LiteLLM
```bash
AZURE_API_KEY=$(grep AZURE_OPENAI_API_KEY ~/.hermes/.env | cut -d= -f2) \
~/.hermes/hermes-agent/venv/bin/litellm \
  --model azure/gpt-4o \
  --api_base https://YOUR-RESOURCE.openai.azure.com \
  --api_version 2024-10-21 \
  --port 4000 &

sleep 8

curl -s http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fake-key" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
# Must return JSON with content field
```

### 4.3 Create LiteLLM systemd Service (run as root)
```bash
cat > /etc/systemd/system/litellm.service << EOF
[Unit]
Description=LiteLLM Azure OpenAI Proxy
After=network.target

[Service]
User=hermes
WorkingDirectory=/home/hermes
Environment="AZURE_API_KEY=$(grep AZURE_OPENAI_API_KEY /home/hermes/.hermes/.env | cut -d= -f2)"
ExecStart=/home/hermes/.hermes/hermes-agent/venv/bin/litellm --model azure/gpt-4o --api_base https://YOUR-RESOURCE.openai.azure.com --api_version 2024-10-21 --port 4000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable litellm
systemctl start litellm
systemctl status litellm
```

---

## Phase 5 — Self-Hosted Firecrawl (Web Search & Scraping)

> No API costs, no rate limits. Uses DuckDuckGo. Requires ~1 GB RAM.
> Runs 5 Docker containers: API, Playwright, Redis, RabbitMQ, PostgreSQL.

### 5.1 Clone and Configure (as hermes user)
```bash
cd ~
git clone https://github.com/firecrawl/firecrawl.git
cd firecrawl

cat > .env << 'EOF'
PORT=3002
HOST=0.0.0.0
USE_DB_AUTHENTICATION=false
BULL_AUTH_KEY=your-chosen-admin-password
EOF
```

### 5.2 Build and Start
```bash
docker compose build
docker compose up -d
docker compose ps   # All 5 containers must show "Up"

# Test:
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:3002/v1/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'
# Must return 200
```

### 5.3 Connect to Hermes
```bash
echo "FIRECRAWL_API_URL=http://localhost:3002" >> ~/.hermes/.env
```

### 5.4 Create Firecrawl systemd Service (run as root)
```bash
cat > /etc/systemd/system/firecrawl.service << EOF
[Unit]
Description=Firecrawl Web Scraping Service
After=docker.service
Requires=docker.service

[Service]
User=hermes
WorkingDirectory=/home/hermes/firecrawl
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable firecrawl
```

---

## Phase 6 — GitHub Integration & Project Context

### 6.1 Configure Git on VPS (as hermes user)
```bash
git config --global user.name "Hermes Agent"
git config --global user.email "your@email.com"
git config --global credential.helper store

git credential-store --file ~/.git-credentials store << 'EOF'
protocol=https
host=github.com
username=YOUR_GITHUB_USERNAME
password=YOUR_GITHUB_TOKEN
EOF
chmod 600 ~/.git-credentials
```

### 6.2 Clone Projects
```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/YOUR_USERNAME/YOUR_REPO
```

### 6.3 Create AGENTS.md per Project
Create in each project root on Windows PC. Claude Code reads it automatically.
Minimum required sections:
```markdown
# Project Name — Agent Context
**Last updated:** YYYY-MM-DD
**Next session priority:** [current task]

## What This Project Does
## Tech Stack
## How to Start Every Session
## Current Status
## Conventions & Architecture
## Project Structure
## What NOT to Do
## How to Update This File
```
Commit, push, then on VPS: `cd ~/projects/REPO && git pull`

### 6.4 Start Hermes in Project Context
```bash
cd ~/projects/YOUR_REPO
hermes   # auto-loads AGENTS.md from current directory
```

---

## Phase 7 — Persistent tmux Session

```bash
tmux new-session -s hermes
hermes
```

**tmux commands:**
- Detach (keep running): `Ctrl+B` then `D`
- Reattach: `tmux attach -t hermes`
- List sessions: `tmux ls`

---

## Phase 8 — Hindsight Memory Provider (Local Embedded)

> Adds semantic/vector search, knowledge graph, and entity relationships to Hermes memory.
> Runs entirely on your VPS — no data leaves the server.
> Uses your existing Azure OpenAI (via LiteLLM) for memory extraction.
> Daemon auto-manages an embedded PostgreSQL instance.

### 8.1 Install and Configure
```bash
hermes memory setup
# Navigate to: hindsight
# Select mode: local_embedded
# LLM endpoint URL: http://localhost:4000/v1
# LLM model: gpt-4o
# LLM API key: (your Azure OpenAI key)
```

The wizard installs `hindsight-client` via uv and writes config automatically.

### 8.2 Verify Installation
```bash
hermes memory status
# Should show:
# Provider:  hindsight
# Status:    available ✓
# hindsight  (API key / local) ← active
```

### 8.3 Verify Daemon Started
```bash
tail -5 ~/.hermes/logs/hindsight-embed.log
# Should show: === Daemon started successfully ===
# Database: ~/.pg0/instances/hindsight-embed-hermes
```

### 8.4 Seed Project Knowledge
Start Hermes from your project directory and seed it:
```bash
cd ~/projects/BOOK
hermes
```
Then in Hermes chat:
```
Read the AGENTS.md file in this directory and extract the key facts about this project into your memory using hindsight_retain
```

### 8.5 Memory Stack After Setup
```
Built-in (MEMORY.md + USER.md)   ← always active, fast facts in system prompt
Hindsight (local embedded)        ← knowledge graph, vector search, entity relationships
Session SQLite (state.db)         ← full conversation history, searchable
```

**Hindsight tools available to Hermes:**
- `hindsight_retain` — store facts with automatic entity extraction
- `hindsight_recall` — multi-strategy search (semantic vector + entity graph)
- `hindsight_reflect` — synthesise patterns across all memories (unique capability)

**Key file locations:**
- Config: `~/.hermes/hindsight/config.json`
- Daemon log: `~/.hermes/logs/hindsight-embed.log`
- Runtime log: `~/.hindsight/profiles/hermes.log`
- Database: `~/.pg0/instances/hindsight-embed-hermes`

---

## Phase 8 — Persistent tmux Session

```bash
tmux new-session -s hermes
hermes
```

**tmux commands:**
- Detach (keep running): `Ctrl+B` then `D`
- Reattach: `tmux attach -t hermes`
- List sessions: `tmux ls`

---

## Phase 9 — Claude Code MCP Integration (Windows)

Connects Claude Code in VS Code to Hermes via SSH tunnel using MCP protocol.
Claude Code becomes the MCP client; Hermes runs as the MCP server.

### 9.1 Export OpenSSH Key (if not done in Phase 1)
1. Open PuTTYgen → Load `hermes_contabo.ppk`
2. **Conversions → Export OpenSSH key**
3. Save as `hermes_contabo_openssh` to `C:\Users\USERNAME\.ssh\`

### 9.2 Remove Passphrase from Key (enables fully silent operation)
```powershell
ssh-keygen -p -f C:\Users\USERNAME\.ssh\hermes_contabo_openssh
# Enter old passphrase: your current passphrase
# Enter new passphrase: (press Enter — leave empty)
# Enter same passphrase again: (press Enter)
```

### 9.3 Set Up Windows SSH Agent (PowerShell as Administrator)
```powershell
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service ssh-agent
ssh-add C:\Users\USERNAME\.ssh\hermes_contabo_openssh
# No passphrase prompt — key loads silently
```

### 9.4 Add Key to PowerShell Profile (auto-loads on every new terminal)
```powershell
Add-Content $PROFILE "`nssh-add C:\Users\USERNAME\.ssh\hermes_contabo_openssh 2>`$null"
```

### 9.5 Test Passwordless SSH
```powershell
ssh -i C:\Users\USERNAME\.ssh\hermes_contabo_openssh -p 2222 -o BatchMode=yes hermes@YOUR_VPS_IP "echo connected"
# Must print "connected" instantly with no prompts at all
```

### 9.6 Create MCP Wrapper Script
```powershell
@"
@echo off
ssh -i C:\Users\USERNAME\.ssh\hermes_contabo_openssh -p 2222 -o StrictHostKeyChecking=no -o BatchMode=yes hermes@YOUR_VPS_IP "bash -l -c 'hermes mcp serve'"
"@ | Out-File -FilePath "C:\Users\USERNAME\hermes-mcp.bat" -Encoding ascii
```
> `bash -l -c` is required — plain SSH doesn't load PATH where hermes is installed.

### 9.7 Register in Claude Code (VS Code terminal)
```powershell
claude mcp add hermes --transport stdio "C:\Users\USERNAME\hermes-mcp.bat"
claude mcp list
# Must show: hermes: ... - ✓ Connected
```
> Config saved to: `C:\Users\USERNAME\.claude.json` (project-local scope)
> After adding: start a **new Claude Code session** — MCP loads at session start only.

### 9.8 Test End-to-End
In Claude Code chat:
```
Use the hermes MCP server to list all active conversations
```
Expected response: Hermes returns conversation list (empty if no messaging platforms connected yet).

---

## Phase 10 — LightRAG + RAG-Anything (GraphRAG for Knowledge Gap Analysis)

> Installs LightRAG (GraphRAG system) and RAG-Anything (multimodal document ingestion).
> Used to ingest research documents and compare against the BOOK to find knowledge gaps.
> Two separate workspaces: research (port 9621) and book (port 9622).
> Reranking via Jina AI free tier for improved retrieval quality.

### ⚠️ Critical Azure Configuration Note
LightRAG requires both GPT-4o (LLM) and text-embedding-3-large (embedding) to be deployed
**in the same Azure resource** (`openai-ops-meeting`). This is because the `azure_openai` binding
uses a single `AZURE_OPENAI_API_KEY` environment variable shared by both LLM and embedding calls.
Having them in separate resources causes authentication conflicts that are very difficult to debug.

**Azure resources used:**
- `openai-ops-meeting` → GPT-4o + text-embedding-3-large (both here)
- `lightrag-vps-resource` → originally only had embedding; text-embedding-3-large was also deployed here but causes conflicts — use `openai-ops-meeting` only

### 10.1 Install LightRAG Server
```bash
cd ~
git clone https://github.com/HKUDS/LightRAG.git
cd LightRAG
~/.local/bin/uv tool install "lightrag-hku[api]"
# Verify: /home/hermes/.local/bin/lightrag-server
```

### 10.2 Create Workspace Directories
```bash
mkdir -p ~/lightrag/inputs
mkdir -p ~/lightrag/rag_storage
mkdir -p ~/lightrag-book/inputs
mkdir -p ~/lightrag-book/rag_storage
```

### 10.3 Create Research Workspace Config (~/lightrag/.env)
```
PORT=9621
WORKERS=2

LLM_BINDING=azure_openai
LLM_BINDING_HOST=https://openai-ops-meeting.openai.azure.com/
LLM_BINDING_API_KEY=YOUR_OPENAI_OPS_MEETING_KEY
LLM_MODEL=gpt-4o
AZURE_OPENAI_API_VERSION=2024-10-21
TIMEOUT=150
MAX_ASYNC=4

EMBEDDING_BINDING=azure_openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIM=3072

WORKING_DIR=./rag_storage
INPUT_DIR=./inputs
ENABLE_LLM_CACHE_FOR_EXTRACT=true
MAX_PARALLEL_INSERT=2

LIGHTRAG_API_KEY=your-strong-key-here
RERANK_BINDING=jina
RERANK_MODEL=jina-reranker-v2-base-multilingual
RERANK_BINDING_HOST=https://api.jina.ai/v1/rerank
RERANK_BINDING_API_KEY=your-jina-key-here
```

> **Note:** Do NOT put `AZURE_OPENAI_API_KEY` or `AZURE_OPENAI_ENDPOINT` in the `.env` file.
> These are injected via the systemd service Environment= lines to prevent conflicts.

### 10.4 Create Book Workspace Config
```bash
cp ~/lightrag/.env ~/lightrag-book/.env
sed -i 's/PORT=9621/PORT=9622/' ~/lightrag-book/.env
```

### 10.5 Create systemd Services

**Research workspace service (`/etc/systemd/system/lightrag.service`):**
```ini
[Unit]
Description=LightRAG GraphRAG Server - Research
After=network.target

[Service]
User=hermes
WorkingDirectory=/home/hermes/lightrag
ExecStart=/home/hermes/.local/bin/lightrag-server
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="AZURE_OPENAI_API_KEY=YOUR_OPENAI_OPS_MEETING_KEY"
Environment="AZURE_OPENAI_ENDPOINT=https://openai-ops-meeting.openai.azure.com/"
Environment="AZURE_OPENAI_API_VERSION=2024-10-21"

[Install]
WantedBy=multi-user.target
```

**Book workspace service (`/etc/systemd/system/lightrag-book.service`):**
```ini
[Unit]
Description=LightRAG GraphRAG Server - Book
After=network.target

[Service]
User=hermes
WorkingDirectory=/home/hermes/lightrag-book
ExecStart=/home/hermes/.local/bin/lightrag-server
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="AZURE_OPENAI_API_KEY=YOUR_OPENAI_OPS_MEETING_KEY"
Environment="AZURE_OPENAI_ENDPOINT=https://openai-ops-meeting.openai.azure.com/"
Environment="AZURE_OPENAI_API_VERSION=2024-10-21"

[Install]
WantedBy=multi-user.target
```

> **Why Environment= in systemd?** LightRAG's `azure_openai` binding reads `AZURE_OPENAI_API_KEY`
> and `AZURE_OPENAI_ENDPOINT` from the process environment with higher priority than `.env`.
> Setting them in systemd ensures the correct values are always used regardless of any other
> environment variables that might be set on the system (e.g. from LiteLLM's service).

```bash
sudo systemctl daemon-reload
sudo systemctl enable lightrag lightrag-book
sudo systemctl start lightrag lightrag-book
```

### 10.6 Verify Both Services Running
```bash
sudo journalctl -u lightrag -n 5 --no-pager | grep -E "running|rerank|embed"
sudo journalctl -u lightrag-book -n 5 --no-pager | grep -E "running|rerank|embed"
# Both must show: Reranking is enabled: jina-reranker-v2-base-multilingual

# Verify the correct Azure key is in the process environment
sudo cat /proc/$(systemctl show -p MainPID lightrag | cut -d= -f2)/environ | tr '\0' '\n' | grep AZURE_OPENAI
# AZURE_OPENAI_API_KEY must start with the openai-ops-meeting key prefix
# AZURE_OPENAI_ENDPOINT must be https://openai-ops-meeting.openai.azure.com/
```

### 10.7 Test Configuration Before Ingestion
Use the diagnostic script to verify all connections before ingesting documents:
```bash
cd ~/lightrag
~/raganything-venv/bin/python /tmp/test_lightrag_config.py
# All 4 tests must PASS before proceeding
```

### 10.8 Install RAG-Anything + Docling + MinerU
```bash
# Create dedicated virtual environment
sudo apt install python3-venv python3-full -y
python3 -m venv ~/raganything-venv

# Install RAG-Anything (pulls in MinerU automatically)
~/raganything-venv/bin/pip install raganything
~/raganything-venv/bin/pip install docling

# Verify all installed
~/raganything-venv/bin/python -c "from raganything import RAGAnything; print('RAG-Anything OK')"
~/raganything-venv/bin/python -c "import docling; print('Docling OK')"
~/raganything-venv/bin/mineru --version
```

### 10.9 Prepare Research Documents
Copy only research documents (PDFs, DOCX, MD files) — no system files, images, scripts:
```powershell
# Windows PowerShell — copy specific file types only
$key = "C:\Users\PVELINOV\.ssh\hermes_contabo_openssh"
$dest = "hermes@62.146.169.66:~/lightrag/inputs/"
$extensions = @("*.pdf", "*.docx", "*.doc", "*.pptx", "*.ppt", "*.txt", "*.md")

$folders = @(
    "C:\path\to\research\documents",
    "C:\path\to\subfolder1",
    "C:\path\to\subfolder2"
)

foreach ($folder in $folders) {
    Get-ChildItem -Path $folder -Recurse -Include $extensions -File | ForEach-Object {
        Write-Host "Copying: $($_.Name)"
        scp -i $key -P 2222 $_.FullName $dest
    }
}
```

> ⚠️ Never use `scp -r folder/*` — this copies system files, browser profiles, and other junk.
> Always filter by extension using the PowerShell pattern above.

### 10.10 Ingest Documents via RAG-Anything (Recommended for table-heavy PDFs)

RAG-Anything uses MinerU to properly extract tables, images and structured content from PDFs before entity extraction. This is recommended for the Microsoft Copilot scenario PDFs and other visually structured documents.

**Pre-requisite:** MinerU models must be downloaded first. Run MinerU once manually on any PDF — it downloads models automatically (~2-3 minutes). After first run, models are cached.

**Run ingestion:**
```bash
# Copy documents to inputs folder first (from Windows PowerShell):
# scp -i key -P 2222 "path\to\*.pdf" hermes@62.146.169.66:~/lightrag/inputs/

# Then run RAG-Anything ingestion
tmux new-session -s ingest
AZURE_KEY=your-AkK6Y-openai-ops-meeting-key \
~/raganything-venv/bin/python ~/raganything-work/ingest.py

# Detach: Ctrl+B D
# Reattach: tmux attach -t ingest
```

**The ingest.py script:**
- Uses `openai_complete_if_cache` with full deployment URL as `base_url` (NOT `azure_openai_complete_if_cache`)
- LLM base URL: `https://openai-ops-meeting.openai.azure.com/openai/deployments/gpt-4o`
- Embedding: `azure_openai_embed.func` with `AZURE_OPENAI_ENDPOINT` env var
- Both LLM and embedding use `openai-ops-meeting` resource
- Processes all `.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt`, `.md` files from `DOCS_FOLDER`
- MinerU runs with `pipeline` backend (CPU mode, no GPU needed)

**⚠️ Common errors and fixes:**
- `AsyncCompletions.create() got an unexpected keyword argument 'azure_endpoint'` → Script is using old `azure_openai_complete_if_cache` — update to `openai_complete_if_cache` with `base_url`
- `Mineru command failed with return code 1` on first run → MinerU models not downloaded yet — run `~/raganything-venv/bin/mineru -p yourfile.pdf -o /tmp/test -b pipeline` first to trigger download

### 10.11 Ingest Book via LightRAG Web UI
The book (`AI_PLAYBOOK_REV8.txt`) is plain text — no tables or images. Use LightRAG's native pipeline:
1. Open `http://localhost:9622`
2. Click **Upload** → select `AI_PLAYBOOK_REV8.txt`
3. Drag file into upload dialog — upload starts automatically, no OK button needed
4. Document appears as Processing → Completed in ~20 minutes

### 10.11 Access Web UIs via SSH Tunnel (Windows)
Use the batch file for automatic tunnel opening:
```batch
# C:\Users\PVELINOV\lightrag-tunnels.bat
ssh -i C:\Users\PVELINOV\.ssh\hermes_contabo_openssh -p 2222 ^
  -L 9621:localhost:9621 ^
  -L 9622:localhost:9622 ^
  -N hermes@62.146.169.66
```
Then open `http://localhost:9621` (research) and `http://localhost:9622` (book) in browser.

### 10.12 Gap Analysis Workflow
Once both workspaces are ingested:
1. Upload `AI_PLAYBOOK_REV8.txt` to book workspace (`http://localhost:9622`)
2. Query research workspace in hybrid mode:
```
/hybrid What AI transformation frameworks, methodologies, or case studies appear in 
the research corpus but are absent or underdeveloped in the current content?
```

### Key Facts
| Item | Detail |
|---|---|
| Research workspace | port 9621, `~/lightrag/` |
| Book workspace | port 9622, `~/lightrag-book/` |
| LightRAG binary | `/home/hermes/.local/bin/lightrag-server` |
| LightRAG version | v1.4.14 |
| Azure resource | `openai-ops-meeting` (both GPT-4o AND embedding here) |
| Azure endpoint | `https://openai-ops-meeting.openai.azure.com/` |
| LLM model | `gpt-4o` |
| Embedding model | `text-embedding-3-large` (3072 dims) |
| API version | `2024-10-21` |
| Jina reranker | `jina-reranker-v2-base-multilingual` |
| RAG-Anything venv | `~/raganything-venv/` |
| MinerU version | 3.0.9 (pipeline/CPU mode, models cached after first run) |
| Ingestion script | `~/raganything-work/ingest.py` (uses `openai_complete_if_cache` with base_url) |
| LLM function | `openai_complete_if_cache` with `base_url=https://openai-ops-meeting.openai.azure.com/openai/deployments/gpt-4o` |
| Diagnostic script | `/tmp/test_lightrag_config.py` |
| Tunnel batch file | `C:\Users\PVELINOV\lightrag-tunnels.bat` |
| Research docs status | 72/72 Completed (LightRAG native) — pending RAG-Anything re-ingestion |
| Book status | 1/1 Completed (AI_PLAYBOOK_REV8.txt, 75 chunks) |

---

## Full Verification Checklist

### LightRAG (run on VPS):
```bash
systemctl status lightrag        # active (running) on port 9621
systemctl status lightrag-book   # active (running) on port 9622
sudo journalctl -u lightrag -n 5 --no-pager | grep rerank
# → Reranking is enabled: jina-reranker-v2-base-multilingual
```

### Windows (browser):
```
http://localhost:9621  → Research workspace (requires SSH tunnel)
http://localhost:9622  → Book workspace (requires SSH tunnel)
```

### VPS (PuTTY as hermes user):
```bash
systemctl status litellm        # active (running)
systemctl status docker         # active (running)  
systemctl status fail2ban       # active (running)
systemctl status firecrawl      # active (running)
ufw status                      # active, ports 2222/80/443 allowed

# LiteLLM → Azure
curl -s -o /dev/null -w "%{http_code}" http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fake-key" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
# → 200

# Firecrawl
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:3002/v1/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'
# → 200

hermes doctor   # all green
```

### Windows (VS Code terminal):
```powershell
claude mcp list   # hermes: ✓ Connected
```

---

## Key Facts & Lessons Learned

| Item | Detail |
|---|---|
| VPS IP | 62.146.169.66 |
| SSH port | 2222 |
| SSH user | hermes |
| Azure resource | openai-ops-meeting |
| Azure endpoint | https://openai-ops-meeting.openai.azure.com/ |
| Azure deployment | gpt-4o (version 2024-11-20) |
| Working API version | 2024-10-21 (others return 404) |
| LiteLLM port | 4000 (localhost only) |
| Firecrawl port | 3002 (localhost only) |
| Hermes config | ~/.hermes/config.yaml |
| Hermes env | ~/.hermes/.env |
| Projects dir | ~/projects/ |
| Windows SSH key | `C:\Users\PVELINOV\.ssh\hermes_contabo_openssh` (no passphrase) |
| MCP bat file | `C:\Users\PVELINOV\hermes-mcp.bat` |
| Claude Code MCP config | `C:\Users\PVELINOV\.claude.json` |
| PowerShell profile | `C:\Users\PVELINOV\OneDrive - Government of BC\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1` |

**Critical reminders:**
- Regenerate Azure API key — it was exposed during setup
- SSH key has no passphrase and auto-loads from PowerShell profile — no manual action needed after reboot
- SSH port change on Ubuntu 24.04 needs all three: `daemon-reload` + `restart ssh.socket` + `restart ssh`
- LiteLLM proxy is permanently required — Azure OpenAI won't work without it
- New Claude Code session required after MCP config changes
