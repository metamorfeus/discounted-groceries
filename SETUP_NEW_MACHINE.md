# New Machine Setup — BG Food Prices Pipeline

Complete setup guide for running this project on a brand-new Windows 11 computer.

---

## 1. Core Software

### Python
- **Version:** 3.10 or newer (3.14 confirmed working)
- **Download:** https://www.python.org/downloads/
- During install: check **"Add Python to PATH"**
- Verify: `python --version` and `pip --version`

### Git
- **Download:** https://git-scm.com/download/win
- Used to clone the repo and track weekly changes

### Visual Studio Code
- **Download:** https://code.visualstudio.com/
- Install the **Claude Code** extension from the VS Code marketplace
- Claude Code enables AI-assisted editing and MCP tool access

### Node.js (LTS)
- **Download:** https://nodejs.org/
- Required by Claude Code MCP servers (FireCrawl, Hermes)
- Verify: `node --version` and `npx --version`

---

## 2. Python Packages

Run these after Python is installed:

```bash
pip install requests pdfplumber openpyxl playwright PyPDF2 azure-ai-documentintelligence openai paramiko
playwright install chromium
```

| Package | Used by |
|---|---|
| `requests` | gladen_html_scraper.py, billa_scraper.py, HTTP fetches |
| `pdfplumber` | fantastico_pipeline.py — text-layer PDF extraction |
| `openpyxl` | generate_cheapest_xlsx.py — Excel report builder |
| `playwright` | fantastico_pipeline.py — headless browser for FlippingBook |
| `PyPDF2` | PDF utilities |
| `azure-ai-documentintelligence` | billa_pdf_pipeline.py, fantastico_pipeline.py — OCR |
| `openai` | generate_cheapest_xlsx.py, translator.py — GPT-4o classification |
| `paramiko` | HERMES_INTERGRATION/seed_hermes_memory.py — SSH to VPS |

`playwright install chromium` downloads the headless Chromium browser — required for Fantastico.

---

## 3. Clone the Repository

```bash
git clone https://github.com/metamorfeus/discounted-groceries.git "C:\AHA\OneDrive - AHA\BG\FOOD-PRICES"
```

Or clone to any path — all scripts use relative paths within the project directory.

---

## 4. Credentials & Secret Files

These files are **not in git** and must be created manually.

### `secrets.py` (Azure Document Intelligence)

Create `secrets.py` in the project root:

```python
# Azure Document Intelligence API key
AZURE_KEY = "YOUR_AZURE_DI_KEY_HERE"
```

- Used by: `billa_pdf_pipeline.py`, `fantastico_pipeline.py`, `fantastico_ocr_pipeline.py`
- The endpoint is already set in `config.py` — only the key goes here

### `azure_secrets.json` (Azure OpenAI / GPT-4o)

Create `azure_secrets.json` in the project root:

```json
{
  "_comment": "API key for Azure OpenAI — fill once.",
  "api_key": "YOUR_AZURE_OPENAI_KEY_HERE"
}
```

- Used by: `generate_cheapest_xlsx.py` (product classification), `translator.py` (English translation)
- The endpoint, deployment name, and API version are in `azure_config.json` — already committed

### SSH Key (Hermes VPS access)

- Place the private key at: `C:\Users\YOUR_USERNAME\.ssh\hermes_contabo_openssh`
- Used by: `hermes-discounted-groceries-mcp.bat`, `seed_hermes_memory.py`
- Get this key from the existing machine or the VPS admin

---

## 5. MCP Server Configuration (Claude Code)

MCP servers extend Claude Code with external tool access. Configure them in Claude Code's global MCP settings.

### FireCrawl MCP
Used for scraping JavaScript-heavy pages (Glovo). Configure via Claude Code:

```json
{
  "mcpServers": {
    "firecrawl": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": {
        "FIRECRAWL_API_KEY": "YOUR_FIRECRAWL_API_KEY"
      }
    }
  }
}
```

### Hermes MCP (persistent AI memory)
The `hermes-discounted-groceries-mcp.bat` file in the project root handles this. Register it in Claude Code MCP settings:

```json
{
  "mcpServers": {
    "hermes-discounted-groceries": {
      "command": "C:\\AHA\\OneDrive - AHA\\BG\\FOOD-PRICES\\hermes-discounted-groceries-mcp.bat"
    }
  }
}
```

Update the path in `hermes-discounted-groceries-mcp.bat` to match the SSH key location on the new machine:

```bat
@echo off
ssh -i C:\Users\YOUR_USERNAME\.ssh\hermes_contabo_openssh -p 2222 -o StrictHostKeyChecking=no -o BatchMode=yes hermes@62.146.169.66 "bash -l -c 'hermes -p discounted-groceries mcp serve'"
```

---

## 6. VPN Requirement

Glovo blocks scraping from non-Bulgarian IP addresses. To run Step 3 (`write_glovo_data.py`) successfully:

- Connect to a **Bulgarian VPN server** before scraping Glovo
- Any VPN provider with a Bulgaria exit node works
- Kaufland Direct data in `write_glovo_data.py` does not require VPN

---

## 7. External API Accounts

| Service | Purpose | Where to get access |
|---|---|---|
| **Azure Document Intelligence** | PDF OCR for Billa and Fantastico brochures | Azure Portal → Cognitive Services → Document Intelligence |
| **Azure OpenAI (GPT-4o)** | Product category classification and English translation | Azure Portal → Azure OpenAI → Deployments |
| **FireCrawl** | JS-rendered page scraping (Glovo) | firecrawl.dev |
| **Hermes VPS** | Persistent AI memory across sessions | SSH access to `hermes@62.146.169.66:2222` (existing VPS) |

The Azure endpoints and deployment names are already in `config.py` and `azure_config.json`. Only API keys need to be provided.

---

## 8. Working Directory Structure

After setup, the project root should contain:

```
FOOD-PRICES/
├── secrets.py                          ← create manually (not in git)
├── azure_secrets.json                  ← create manually (not in git)
├── azure_config.json                   ← already in repo
├── config.py                           ← already in repo
├── manual_overrides.json               ← already in repo
├── bulgarian_promo_prices_merged.json  ← master dataset (in repo)
├── hermes-discounted-groceries-mcp.bat ← update SSH key path
├── gladen_html_scraper.py
├── billa_pdf_pipeline.py
├── billa_scraper.py
├── write_glovo_data.py
├── fantastico_pipeline.py
├── generate_cheapest_xlsx.py
└── ...
```

---

## 9. First Run Checklist

- [ ] Python 3.10+ installed and on PATH
- [ ] `pip install` command completed (all packages installed)
- [ ] `playwright install chromium` completed
- [ ] Git installed, repo cloned
- [ ] VS Code + Claude Code extension installed
- [ ] Node.js installed (for MCP servers)
- [ ] `secrets.py` created with Azure DI key
- [ ] `azure_secrets.json` created with Azure OpenAI key
- [ ] SSH key placed at `C:\Users\<username>\.ssh\hermes_contabo_openssh`
- [ ] `hermes-discounted-groceries-mcp.bat` updated with new SSH key path
- [ ] MCP servers configured in Claude Code settings
- [ ] Bulgarian VPN available for Glovo scraping
- [ ] Test run: `python gladen_html_scraper.py --pages 1 --dry-run`

---

## 10. Weekly Run Order (reference)

```bash
# Update PROMO_PERIOD in gladen_html_scraper.py first
python gladen_html_scraper.py

python billa_pdf_pipeline.py --key YOUR_AZURE_KEY
python billa_scraper.py

# Connect Bulgarian VPN first for Glovo steps
python write_glovo_data.py

python fantastico_pipeline.py

python generate_cheapest_xlsx.py
```

See `PIPELINE_GUIDE.md` for full details on each step.
