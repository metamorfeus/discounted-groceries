#!/usr/bin/env python3
"""
new-project.py — Automate Hermes persistent memory setup for any new project.

Usage:
    python new-project.py --name my-project --github-repo username/MY-REPO
    python new-project.py --name my-project --github-repo username/MY-REPO --project-dir C:\\path\\to\\project

What it does:
    1. Creates a Hermes profile on VPS  (hermes profile create {name} --clone)
    2. Configures Hindsight memory bank for the profile
    3. Creates hermes-{name}-mcp.bat in the project folder
    4. Registers the MCP server in Claude Code  (claude mcp add)
    5. Creates an AGENTS.md template if one does not exist
    6. Clones the GitHub repo on VPS into ~/projects/
    7. Prints a summary with next steps

Requirements:
    - SSH key at C:\\Users\\PVELINOV\\.ssh\\hermes_contabo_openssh (no passphrase)
    - 'claude' CLI available in PATH
    - VPS accessible at 62.146.169.66:2222 as user hermes
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# ── VPS configuration ───────────────────────────────────────────────────────────
VPS_IP = "62.146.169.66"
VPS_PORT = "2222"
VPS_USER = "hermes"
SSH_KEY_WIN = r"C:\Users\PVELINOV\.ssh\hermes_contabo_openssh"
# Unix-style path for use inside bash/ssh calls from Git Bash / WSL
SSH_KEY_UNIX = "/c/Users/PVELINOV/.ssh/hermes_contabo_openssh"


def ssh_run(command: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a command on the VPS via SSH (login shell to load PATH)."""
    # Escape single quotes inside the command
    safe_cmd = command.replace("'", "'\\''")
    return subprocess.run(
        [
            "ssh",
            "-i", SSH_KEY_UNIX,
            "-p", VPS_PORT,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15",
            "-o", "StrictHostKeyChecking=no",
            f"{VPS_USER}@{VPS_IP}",
            f"bash -l -c '{safe_cmd}'",
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def run_local(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, cwd=cwd)


def ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠  {msg}")


def fail(msg: str) -> None:
    print(f"  ✗  {msg}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up Hermes persistent memory for a new Claude Code project"
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Hermes profile name — lowercase, hyphens/underscores ok (e.g. my-project)",
    )
    parser.add_argument(
        "--github-repo",
        required=True,
        help="GitHub repo in owner/name format (e.g. metamorfeus/MY-REPO)",
    )
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Local project directory (default: current directory)",
    )
    args = parser.parse_args()

    name = args.name
    github_repo = args.github_repo
    project_dir = Path(args.project_dir).resolve()

    # ── Validate profile name ───────────────────────────────────────────────────
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", name):
        fail(
            f"Profile name '{name}' is invalid.\n"
            "  Must match [a-z0-9][a-z0-9_-]{0,63} — lowercase only, no dots or spaces."
        )

    repo_name = github_repo.split("/")[-1]
    today = date.today().isoformat()

    print(f"\n{'='*60}")
    print(f"  Hermes memory setup — {name}")
    print(f"  Project dir : {project_dir}")
    print(f"  GitHub repo : {github_repo}")
    print(f"{'='*60}\n")

    # ── Step 1: Create Hermes profile on VPS ───────────────────────────────────
    print("[1/6] Creating Hermes profile on VPS...")
    result = ssh_run(f"hermes profile list 2>&1 | grep -q '^.*{name}' && echo EXISTS || hermes profile create {name} --clone 2>&1")
    if "EXISTS" in result.stdout:
        warn(f"Profile '{name}' already exists — skipping creation")
    elif result.returncode != 0:
        warn(f"Profile creation returned non-zero: {result.stderr.strip()}")
    else:
        ok(f"Profile '{name}' created")

    # ── Step 2: Configure Hindsight memory bank ─────────────────────────────────
    print("[2/6] Configuring Hindsight memory bank...")
    config = {
        "mode": "local",
        "bank_id": name,
        "recall_budget": "mid",
        "memory_mode": "hybrid",
        "auto_retain": True,
        "auto_recall": True,
    }
    config_json = json.dumps(config, indent=2).replace('"', '\\"')
    result = ssh_run(
        f'mkdir -p ~/.hermes/profiles/{name}/hindsight && '
        f'echo "{config_json}" > ~/.hermes/profiles/{name}/hindsight/config.json'
    )
    if result.returncode != 0:
        warn(f"Hindsight config write issue: {result.stderr.strip()}")
    else:
        ok(f"Hindsight bank_id='{name}' configured")

    # ── Step 3: Create MCP wrapper bat file ────────────────────────────────────
    print("[3/6] Creating MCP wrapper bat file...")
    bat_path = project_dir / f"hermes-{name}-mcp.bat"
    bat_content = (
        "@echo off\n"
        f'ssh -i {SSH_KEY_WIN} -p {VPS_PORT} '
        f"-o StrictHostKeyChecking=no -o BatchMode=yes "
        f'{VPS_USER}@{VPS_IP} '
        f'"bash -l -c \'hermes -p {name} mcp serve\'"\n'
    )
    bat_path.write_text(bat_content, encoding="utf-8")
    ok(f"Created {bat_path.name}")

    # ── Step 4: Register MCP server in Claude Code ─────────────────────────────
    print("[4/6] Registering MCP server in Claude Code...")
    result = run_local(
        ["claude", "mcp", "add", f"hermes-{name}", "--transport", "stdio", str(bat_path)],
        cwd=str(project_dir),
    )
    if result.returncode != 0:
        warn(f"claude mcp add issue: {(result.stderr or result.stdout).strip()}")
        warn("You may need to run this manually — see Step 4 in the docs")
    else:
        ok(f"MCP server 'hermes-{name}' registered")

    # ── Step 5: Create AGENTS.md template if missing ───────────────────────────
    print("[5/6] Checking AGENTS.md...")
    agents_md = project_dir / "AGENTS.md"
    if agents_md.exists():
        ok("AGENTS.md already exists — skipping")
    else:
        display_name = name.replace("-", " ").replace("_", " ").title()
        agents_md.write_text(
            f"# {display_name} — Agent Context\n"
            f"**Last updated:** {today}\n"
            f"**Next session priority:** [define next task]\n\n"
            "---\n\n"
            "## What This Project Does\n\n"
            "[One paragraph description]\n\n"
            "---\n\n"
            "## How to Start Every Session\n\n"
            f"1. Use `hermes-{name}` to recall what you know about this project\n"
            "2. Check current status below\n"
            "3. Continue from \"Next session priority\"\n\n"
            "---\n\n"
            "## Current Status\n\n"
            "[What is done, what is pending]\n\n"
            "---\n\n"
            "## Key Facts\n\n"
            "[Important paths, configs, decisions, conventions]\n\n"
            "---\n\n"
            "## Tech Stack\n\n"
            "[Languages, frameworks, external services]\n\n"
            "---\n\n"
            "## What NOT to Do\n\n"
            "[Common mistakes or gotchas to avoid]\n\n"
            "---\n\n"
            "## How to Update This File\n\n"
            "After each session: update **Current Status** and **Next session priority**, then:\n"
            "```bash\n"
            "git add AGENTS.md && git commit -m \"Update AGENTS.md\" && git push\n"
            "```\n"
            "VPS auto-syncs within 5 minutes — no manual `git pull` needed.\n",
            encoding="utf-8",
        )
        ok("AGENTS.md template created — fill in the project-specific sections")

    # ── Step 6: Clone repo on VPS ──────────────────────────────────────────────
    print("[6/6] Cloning repo on VPS...")
    result = ssh_run(
        f"cd ~/projects && "
        f"if [ -d '{repo_name}/.git' ]; then "
        f"  echo ALREADY_CLONED; "
        f"else "
        f"  git clone https://github.com/{github_repo}.git 2>&1; "
        f"fi"
    )
    if "ALREADY_CLONED" in result.stdout:
        ok(f"Repo already at ~/projects/{repo_name} — running git pull")
        ssh_run(f"cd ~/projects/{repo_name} && git pull --quiet")
    elif result.returncode != 0:
        warn(f"Clone issue: {result.stderr.strip()}")
        warn("Push to GitHub first, then re-run or clone manually on VPS")
    else:
        ok(f"Cloned into ~/projects/{repo_name}")

    # ── Done ───────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  Setup complete!")
    print(f"{'='*60}")
    print(f"""
  Profile     : {name}
  MCP server  : hermes-{name}
  VPS repo    : ~/projects/{repo_name}
  Bat file    : hermes-{name}-mcp.bat

  Next steps:
    1. Fill in AGENTS.md with project-specific content (if newly created)
    2. Commit and push:
         git add . && git commit -m "Add Hermes memory integration" && git push
    3. Start a NEW Claude Code session — MCP loads only at session start
    4. In that session, seed memory:
         Use hermes-{name} to save these facts: [key facts about the project]

  To recall context at the start of every future session:
    Use hermes-{name} to recall what you know about this project
""")


if __name__ == "__main__":
    main()
