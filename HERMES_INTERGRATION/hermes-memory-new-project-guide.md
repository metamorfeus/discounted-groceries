# Integrating a New Claude Code Project with Hermes Persistent Memory
**Generic step-by-step guide for any project**
*Based on verified working setup — April 2026*

---

## What This Gives You

Every Claude Code session working on your project automatically has access to
accumulated knowledge — decisions made, configurations, lessons learned, file paths,
architectural choices — without re-reading documentation at the start of every session.

Hermes acts as the memory backend. It remembers across sessions. Claude Code queries
it via MCP at any time during a session.

---

## Prerequisites

Before starting, confirm you have:

- Hermes Agent installed and running on VPS (`hermes doctor` returns green)
- SSH key on Windows with no passphrase (`C:\Users\USERNAME\.ssh\your_key`)
- Claude Code installed in VS Code (`claude --version` works in terminal)
- A GitHub account for the project repo (recommended transport layer)
- The project folder exists on your Windows workstation

---

## Step 1 — Choose a Profile Name

Each project gets its own isolated Hermes profile. This prevents memory from
different projects mixing together.

**Naming rules** (Hermes enforces these):
- Lowercase only
- Letters, numbers, hyphens, underscores
- Must start with a letter or number
- Max 64 characters
- Pattern: `[a-z0-9][a-z0-9_-]{0,63}`

**Good examples:**
```
my-project
book-research
client-alpha
data-pipeline-2026
```

**Bad examples (will be rejected):**
```
My-Project       ← uppercase
my project       ← space
my.project       ← dot
_myproject       ← starts with underscore
```

Decide your profile name before proceeding. This document uses `my-project` as the
example — replace it with your actual name throughout.

---

## Step 2 — Create the Hermes Profile on VPS

SSH to your VPS:

```bash
# Create profile — clones API keys from default but fresh memory and sessions
hermes profile create my-project --clone

# Verify it was created
hermes profile list
# Should show both default and my-project
```

`--clone` copies your existing API keys and model configuration so you don't have to
reconfigure Azure/OpenAI credentials. Memory and session history start completely fresh.

---

## Step 3 — Configure Hindsight Memory Bank

Each profile needs its own Hindsight memory bank with a unique `bank_id` to keep
memories isolated from other projects.

```bash
mkdir -p ~/.hermes/profiles/my-project/hindsight
cat > ~/.hermes/profiles/my-project/hindsight/config.json << 'EOF'
{
  "mode": "local",
  "bank_id": "my-project",
  "recall_budget": "mid",
  "memory_mode": "hybrid",
  "auto_retain": true,
  "auto_recall": true
}
EOF
```

> The `bank_id` must be unique across all your projects. Use the same name as your
> profile to keep things consistent.

---

## Step 4 — Create a GitHub Repository for the Project

GitHub is the transport layer between your Windows workstation and the VPS. Documents
you create on Windows get pushed to GitHub and pulled on the VPS — no manual SCP.

**On GitHub:**
1. Go to `github.com/YOUR-USERNAME/repositories/new`
2. Name it to match your project (e.g. `MY-PROJECT`)
3. Set to Private
4. Do NOT add README, .gitignore, or license (must be empty)
5. Click Create repository

**On Windows — initialize the local repo:**
```powershell
cd "C:\path\to\your\project\folder"
git init
git remote add origin https://github.com/YOUR-USERNAME/MY-PROJECT.git
```

---

## Step 5 — Create the AGENTS.md File

`AGENTS.md` is Claude Code's primary context file. It's loaded automatically at the
start of every Claude Code session. Put the most important project facts here.

Create `AGENTS.md` in your project folder with at minimum:

```markdown
# PROJECT NAME — Agent Context
**Last updated:** YYYY-MM-DD
**Next session priority:** [what to work on next]

## What This Project Does
[One paragraph description]

## How to Start Every Session
1. Use hermes-my-project to recall what you know about this project
2. Read [key file] for current state
3. Check [status location] for progress

## Current Status
[What's done, what's pending]

## Key Facts
[Important paths, configs, decisions]

## What NOT to Do
[Common mistakes to avoid]
```

---

## Step 6 — Create the MCP Wrapper Script

Create `hermes-my-project-mcp.bat` in your project folder on Windows:

```batch
@echo off
ssh -i C:\Users\USERNAME\.ssh\your_key -p YOUR_SSH_PORT -o StrictHostKeyChecking=no -o BatchMode=yes YOUR_USER@YOUR_VPS_IP "bash -l -c 'hermes -p my-project mcp serve'"
```

Replace:
- `USERNAME` — your Windows username
- `your_key` — your SSH key filename
- `YOUR_SSH_PORT` — your VPS SSH port (commonly 22 or 2222)
- `YOUR_USER` — your VPS username
- `YOUR_VPS_IP` — your VPS IP address
- `my-project` — your profile name

> **Why `bash -l -c`?** Plain SSH doesn't load `.bashrc`/`.profile` so the `hermes`
> command isn't found. The `-l` flag forces a login shell which loads the full PATH.

---

## Step 7 — Register the MCP Server in Claude Code

In VS Code, open a terminal in your project folder and run:

```powershell
cd "C:\path\to\your\project\folder"
claude mcp add hermes-my-project --transport stdio "C:\path\to\your\project\folder\hermes-my-project-mcp.bat"
```

Verify it's connected:
```powershell
claude mcp list
# Should show: hermes-my-project: ... ✓ Connected
```

> The MCP server is registered at **project scope** — it only appears when Claude Code
> is opened in this specific project folder. Other projects are not affected.

---

## Step 8 — Commit Files and Push to GitHub

```powershell
cd "C:\path\to\your\project\folder"
git add .
git commit -m "Initial commit — project setup with Hermes memory integration"
git push -u origin main
```

---

## Step 9 — Clone the Repo on VPS

```bash
cd ~/projects
git clone https://github.com/YOUR-USERNAME/MY-PROJECT.git
cd MY-PROJECT
ls
# Should show AGENTS.md and other committed files
```

---

## Step 10 — Seed Hermes Memory

Start the project profile on VPS:

```bash
cd ~/projects/MY-PROJECT
my-project
```

Wait for the `my-project ❯` prompt, then provide key facts for Hermes to retain.

> ⚠️ **Important:** If your project documents contain technical security language,
> commands, or configuration details, Azure's content filter may trigger a false
> positive jailbreak detection. Use short, neutral, factual statements instead of
> asking Hermes to read whole documents.

**Safe approach — provide facts directly:**
```
Please save these facts to your memory:
[Fact 1 — one sentence, neutral language]
[Fact 2 — one sentence, neutral language]
[Fact 3 — one sentence, neutral language]
```

**What to seed:**
- Project location and purpose
- Key file paths
- Service names and ports
- Technology stack
- Current status and what's pending
- Any gotchas or important lessons

---

## Step 11 — Start Using in Claude Code

**Open VS Code in the project folder:**
```powershell
cd "C:\path\to\your\project\folder"
claude
```

**At the start of every session:**
```
Use hermes-my-project to recall what you know about this project
```

Hermes will return the retained facts, giving Claude Code immediate project context.

---

## Step 12 — Set Up VPS Auto-Sync

After cloning the repo, set up automatic syncing so the VPS pulls from GitHub
every 5 minutes. This means you never need to manually run `git pull` on the VPS
after pushing from Windows.

**Create the sync script** (do this once — it covers ALL projects automatically):

```bash
cat > ~/sync-projects.sh << 'EOF'
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
EOF

chmod +x ~/sync-projects.sh
```

**Add to crontab** (if you already have the cron line from a previous project,
skip this — it already covers all projects):

```bash
crontab -e
# Choose editor 1 (nano)
# Add this line at the bottom:
*/5 * * * * /home/hermes/sync-projects.sh
# Save: Ctrl+X Y Enter
```

**Verify it works:**
```bash
~/sync-projects.sh
cat ~/.git-sync.log
# Should show: /home/hermes/projects/MY-PROJECT/: already up to date
```

> **Important:** The sync script automatically discovers ALL repos inside `~/projects/`.
> For every new project you add in future, just clone it into `~/projects/` — no
> crontab changes needed ever again.

---

## Ongoing Workflow

### Adding new facts during a session
```
Use hermes-my-project to save this fact: [your fact]
```

### Updating documentation
```powershell
# On Windows — just push, VPS syncs automatically within 5 minutes
git add .
git commit -m "Update docs"
git push
```

### Checking sync status on VPS
```bash
cat ~/.git-sync.log
# Shows all recent sync runs with timestamps
```

### Checking what Hermes remembers
```
Use hermes-my-project to show all memory entries
```

### Updating AGENTS.md after a session
Always update `AGENTS.md` with new status and push — this is what Claude Code reads
automatically at the start of every session.

---

## Profile Summary Table

Keep this updated as you add projects:

| Profile name | Project | MCP server name | GitHub repo | Created |
|---|---|---|---|---|
| `default` | General / existing projects | `hermes` | — | Original |
| `book-rag-anything` | BOOK-GRAPH-RAG infrastructure | `hermes-book-rag-anything` | metamorfeus/BOOK-GRAPH-RAG | Apr 2026 |
| `my-project` | YOUR PROJECT | `hermes-my-project` | YOUR-USERNAME/MY-PROJECT | — |

---

## Troubleshooting

**`hermes: command not found` via SSH**
Add `bash -l -c` wrapper in the .bat file. Plain SSH doesn't load PATH.

**MCP shows "Failed to connect"**
1. Check SSH key is loaded: `ssh-add -l`
2. Test SSH: `ssh -i key -p port user@host "echo ok"`
3. Start a **new** Claude Code session — MCP only connects at session start

**Profile name rejected**
Must match `[a-z0-9][a-z0-9_-]{0,63}` — lowercase only, no uppercase or dots.

**Azure content filter blocks memory seeding**
Use short neutral factual statements. Avoid words like "critical", "exploit",
"bypass", "override", "inject" — even in innocent technical contexts these trigger
Azure's jailbreak detection.

**Memory from another project appearing**
You're using the wrong profile. Check the prompt shows `my-project ❯` not `hermes ❯`.
Check the MCP bat file has `-p my-project` in the SSH command.

**`fatal: destination path already exists`**
Repo was already cloned on VPS. Run `git pull` instead of `git clone`.

**Cron job not syncing**
1. Check crontab is saved: `crontab -l` — must show the line
2. Check cron service is running: `systemctl status cron`
3. If cron is stopped: `sudo systemctl start cron && sudo systemctl enable cron`
4. Check the log: `cat ~/.git-sync.log` — if empty after 10 min, cron isn't firing
5. Test script manually: `~/sync-projects.sh` — if this works, cron will too

**New project not being synced**
The sync script only picks up repos inside `~/projects/`. Make sure you cloned
into `~/projects/MY-PROJECT/` not somewhere else.

---

## Appendix — Improvements and Automation Suggestions

### Current Pain Points

The manual steps in this process are tedious and error-prone:
1. Creating the profile on VPS (SSH required)
2. Writing the Hindsight config JSON manually
3. Creating the MCP .bat file manually with the right parameters
4. Running `claude mcp add` in the terminal
5. Seeding memory manually with neutral phrasing
6. Keeping AGENTS.md, GitHub, and Hermes memory all in sync

### Suggested Improvements

**1. Automation script: `new-project.py`** ← highest priority
A single Python script run from Windows that does everything in one command:

```python
# Usage: python new-project.py --name my-project --github-repo username/MY-PROJECT
# What it does:
# 1. SSHes to VPS and runs: hermes profile create {name} --clone
# 2. Creates hindsight/config.json with unique bank_id
# 3. Creates hermes-{name}-mcp.bat in current folder
# 4. Runs: claude mcp add hermes-{name} --transport stdio path/to/bat
# 5. Creates AGENTS.md template in current folder
# 6. Clones repo on VPS into ~/projects/
# 7. Prints: "Setup complete. Next: commit, push, then seed memory."
```

This reduces 12 manual steps to one command.

**2. AGENTS.md template**

A standard template that Claude Code and Hermes both understand, with consistent
sections: project description, session start checklist, current status, key facts,
what not to do. Makes every project feel familiar from the first session.

**3. Memory seeding script**

Instead of manually typing facts, a script reads `AGENTS.md` and automatically
extracts key facts into short neutral sentences that won't trigger Azure's content
filter, then sends them to Hermes via the CLI:

```bash
hermes -p my-project -q "Save this fact: [extracted fact]"
```

**4. VPS auto-sync via cron** ✅ IMPLEMENTED

A dynamic sync script (`~/sync-projects.sh`) runs every 5 minutes and pulls all
git repos inside `~/projects/`. New projects are picked up automatically — no
crontab changes needed when adding new projects. See Step 12 for setup details.

**5. Profile registry file**

A single `profiles.json` file tracking all projects, their profile names, MCP server
names, GitHub repos, and creation dates. The `new-project.py` script updates this
automatically. Makes it easy to see all projects at a glance and audit what's running.

**6. Session start automation**

A Claude Code settings file (`.claude/settings.json`) in each project that runs
the recall command automatically at session start — so you don't have to type
the recall command manually every time.

**7. Hermes memory health check**

A weekly cron job on VPS that checks each project profile's memory entries and flags
any that are stale or should be updated:

```bash
for profile in book-rag-anything my-project; do
  echo "=== $profile ===" 
  hermes -p $profile memory status
done
```

**8. Unified MCP registration**

Instead of running `claude mcp add` once per project per machine, store MCP
registrations in a shared config file in the GitHub repo that gets applied by a
setup script. New machines or reinstalls apply all project MCPs in one command.

### Priority Order

| Priority | Improvement | Effort | Impact |
|---|---|---|---|
| 1 | `new-project.py` automation script | Medium | Eliminates 12 manual steps |
| 2 | Memory seeding script | Low | Eliminates Azure filter workaround |
| 3 | AGENTS.md template | Low | Consistency across projects |
| 4 | ~~VPS auto-sync~~ | ~~Low~~ | ✅ Done |
| 5 | Session start automation | Low | Saves one command per session |
| 6 | Profile registry file | Low | Visibility across all projects |
| 7 | Hermes memory health check | Low | Memory hygiene |
| 8 | Unified MCP registration | Medium | Multi-machine setup |
