# Lofty PM — Property Management Automation

MCP server + CLI scripts for automating Lofty property-management workflows: property data extraction, lease date backfills, Atlas Relay ingest, DESCRIPTION.md editing, and bidirectional sync between Lofty and local markdown files.

## Quick Start

### 1. Install

```bash
git clone https://github.com/earlvanze/lofty-pm.git
cd lofty-pm
pip install -e .
```

Requires Python ≥ 3.11. Dependencies (`mcp`, `requests`, `websocket-client`, `websockets`) install automatically.

### 2. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LOFTY_PM_WORKSPACE_ROOT` | Yes | Path to workspace containing `Dropbox/Real Estate/` |
| `LOFTY_PM_REAL_ESTATE_ROOT` | No | Override path to Real Estate corpus (defaults to `$LOFTY_PM_WORKSPACE_ROOT/Dropbox/Real Estate`) |
| `LOFTY_PM_TMP_ROOT` | No | Override temp directory (defaults to `/tmp/lofty-pm`) |
| `BASELANE_CDP_PORT` | No | CDP base URL for webpack injection (defaults to `http://127.0.0.1:9222`) |

### 3. MCP Server (OpenClaw / Claude Desktop / Cursor)

Add to your MCP config:

```json
{
  "mcpServers": {
    "lofty-pm": {
      "command": "python3",
      "args": ["-m", "lofty_pm_mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/lofty-pm/scripts",
        "LOFTY_PM_WORKSPACE_ROOT": "/path/to/workspace",
        "BASELANE_CDP_PORT": "http://127.0.0.1:9222"
      },
      "cwd": "/path/to/lofty-pm"
      }
}
```

For Claude Desktop, add this to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

For Cursor, add to `.cursor/mcp.json` in your project root.

### 4. Claude Code / Codex (ACP)

OpenClaw's ACP integration lets Claude Code or Codex call Lofty PM tools directly:

```bash
# In your OpenClaw config (openclaw.json):
{
  "mcp": {
    "servers": {
      "lofty-pm": {
        "command": "python3.14",
        "args": ["-m", "lofty_pm_mcp.server"],
        "env": {
          "PYTHONPATH": "/path/to/lofty-pm/scripts",
          "LOFTY_PM_WORKSPACE_ROOT": "/path/to/workspace"
        },
        "cwd": "/path/to/lofty-pm"
      }
    }
  }
}
```

Then spawn an ACP session from OpenClaw:

```
/claude "Update lease_begins_date for 49 Bannbury Ln"
```

Or use `sessions_spawn` with `runtime="acp"` and `agentId="claude-code"` to delegate tasks.

### 5. CLI (mcporter)

```bash
# Install mcporter
npm install -g mcporter

# Register the server
mcporter config add lofty-pm \
  --command "python3" \
  --arg "-m" \
  --arg "lofty_pm_mcp.server" \
  --env "PYTHONPATH=/path/to/lofty-pm/scripts" \
  --env "LOFTY_PM_WORKSPACE_ROOT=/path/to/workspace"

# Call tools
mcporter call "lofty-pm.webpack_get_manager_properties" --args '{"year":2026,"month":4}'
mcporter call "lofty-pm.extract_lease_begins_dates" --args '{"property_query":"Wild Olive"}'
mcporter call "lofty-pm.read_description_md" --args '{"property_query":"49 Bannbury"}'
```

## MCP Tools (18)

### Core CRUD

| # | Tool | Description |
|---|------|-------------|
| 1 | `get_manager_properties` | Fetch live Lofty manager property list (auth-capture) |
| 2 | `build_property_payloads` | Build save/send payloads for a property |
| 3 | `update_manager_property` | Apply update-manager-property mutation (runtime-direct) |
| 4 | `send_property_updates` | Send the owner update email |

### Atlas Relay → Lofty

| # | Tool | Description |
|---|------|-------------|
| 5 | `ingest_atlas_relay_update` | Clean Atlas Relay text → UPDATES.md |
| 6 | `ingest_and_publish_atlas_relay_update` | End-to-end ingest + publish |

### File-backed Updates

| # | Tool | Description |
|---|------|-------------|
| 7 | `write_property_update` | Write canonical dated entry into UPDATES.md |
| 8 | `publish_latest_property_update` | Push update history to Lofty + send email |

### Property Map & Sync

| # | Tool | Description |
|---|------|-------------|
| 9 | `rebuild_property_map` | Rebuild property_update_map.json from live Lofty + corpus |

### Lease Dates

| # | Tool | Description |
|---|------|-------------|
| 10 | `extract_lease_begins_dates` | Audit lease_begins_date candidates from DESCRIPTION.md |
| 11 | `update_lease_begins_dates` | Prepare or apply lease_begins_date patches |

### Webpack Injection (No Auth Capture)

| # | Tool | Description |
|---|------|-------------|
| 12 | `webpack_get_manager_properties` | Fetch all properties via webpack (no auth) |
| 13 | `webpack_update_property` | Update a property via webpack (no auth) |

### Property Data Round-Trip

| # | Tool | Description | Direction |
|---|------|-------------|-----------|
| 14 | `extract_property_data` | Extract DETAILS.md + FINANCIALS.md | Lofty → local |
| 15 | `backfill_updates_history` | Backfill UPDATES.md from live data | Lofty → local |
| 16 | `read_description_md` | Read/parse DESCRIPTION.md into sections | local read |
| 17 | `write_description_md` | Write/update DESCRIPTION.md (full or section merge) | local write |
| 18 | `push_property_data` | Push DETAILS.md / FINANCIALS.md to Lofty | local → Lofty |
| 19 | `webpack_get_pl_cutoff_config` | Get P\u0026L cutoff config | Lofty read |
| 20 | `webpack_get_pl_entry` | Get P\u0026L entry for a property | Lofty read |
| 21 | `webpack_create_pl_entry` | Create P\u0026L entry | Lofty write |
| 22 | `webpack_update_pl_entry` | Update P\u0026L entry (SP) | Lofty write |

### Data Round-Trip Coverage

All structured property fields round-trip through the extract → local → push pipeline:

- **Address**: streetAddress, city, state, zipCode, county, legalDescription
- **Specs**: bedrooms, bathrooms, squareFeet, lotSize, units, yearBuilt, propertyType
- **Leasing**: occupancyStatus, leasingStatus, currentRent, marketRent, **lease_begins_date**
- **Management**: propertyManager (name/company/email/phone), managementType
- **Purchase**: purchasePrice, purchaseDate, closingCosts, acquisitionFees
- **Tax**: taxAssessment (year/value/landValue/improvementValue), annualTaxes
- **Insurance**: annualPremium, carrier, policyNumber, coverageAmount
- **Income**: grossScheduledIncome, grossOperatingIncome, otherIncome
- **Expenses**: operatingExpenses, totalOperatingExpenses
- **Cash flow**: noi, capRate, cashFlow, cashOnCashReturn
- **Valuation**: currentValue, valuationDate, source
- **Rent roll**: unit-level rent and status

Read-only (Lofty platform-managed): id, assetUnit, assetName, slug, state, tokenPrice, tokenCount, sellout_date

## Architecture

```
Lofty API  ←→  webpack injection (tools 12-13)
     ↕
MCP Server  ←→  CLI scripts (scripts/*.py)
     ↕
Local Files (Dropbox/Real Estate/)
  ├── <Property>/Public/DESCRIPTION.md    (tools 16-17)
  ├── <Property>/Public/DETAILS.md         (tools 14, 18)
  ├── <Property>/Public/Financials/FINANCIALS.md  (tools 14, 18)
  └── <Property>/Public/Updates/UPDATES.md  (tools 5-8, 15)
```

## Prerequisites

- **Python ≥ 3.11** with pip
- **Brave browser** with remote debugging enabled on port 9222 (for webpack injection tools)
- **Authenticated Lofty session** in the browser (for webpack tools)
- **Dropbox Real Estate corpus** at `$LOFTY_PM_WORKSPACE_ROOT/Dropbox/Real Estate/`

## Scripts

All scripts in `scripts/` can be run standalone:

```bash
# Extract lease date candidates
python3 scripts/extract_lofty_lease_begins_dates.py --property-map config/property_update_map.json

# Update lease dates via webpack
python3 scripts/update_lofty_pm_lease_begins_dates.py --apply --property '918 Frederick Blvd'

# Rebuild property map from live data + corpus
python3 scripts/rebuild_property_update_map.py --apply

# Read/write DESCRIPTION.md
python3 scripts/read_write_description_md.py read --property "Wild Olive"
python3 scripts/read_write_description_md.py write --property "Wild Olive" --section "Occupancy Status" "content here"

# Push local data to Lofty
python3 scripts/push_property_data_to_lofty.py --property "Wild Olive" --dry-run
```

## Security

**No secrets in this repo.** All auth is handled via:
- Browser session cookies (webpack injection — no auth headers captured)
- Environment variables (`LOFTY_PM_AUTHORIZATION`, `LOFTY_PM_AMZ_DATE`, etc.) for the older API path
- The `config/property_update_map.json` is gitignored and contains real property addresses/IDs — a template is provided at `config/property_update_map.template.json`

This tool doesn’t make Lofty easier to hack. It:
- Uses your existing authenticated browser session (no credential extraction)
- Calls the same API endpoints the Lofty frontend calls
- Doesn’t expose any Lofty API secrets, AWS sig keys, or private keys
- Module IDs (51046) are just webpack chunk hashes, not security-sensitive

## Adapting for Other Property Managers

All PMs on Lofty use the **same API** (webpack module 51046). The only differences are:

1. **Which properties appear** — each PM account sees its own portfolio when logged in
2. **Dropbox folder structure** — each PM may organize their Real Estate corpus differently
3. **Custom fields** — some PMs track extra sections in DESCRIPTION.md / UPDATES.md

The `scripts/generic_pm_matcher.py` template handles all of this via `PM_CONFIG`:

```python
# Example: ECO Systems (different Dropbox root)
PM_CONFIG = {
    "name": "eco-systems",
    "corpus_structure": {
        # Their Dropbox folder might be named differently
        "root": "${PM_WORKSPACE_ROOT}/Dropbox/Real Estate - ECO Systems",
        "state_dirs": True,
        "public_dir": "Public",
        "description_file": "DESCRIPTION.md",
    },
    # Same Lofty fields — don't change these
    "pm_property_fields": {
        "id": "id",
        "name": "assetName",
        "address": "address",
        # ...
    },
    # Same Lofty API — fetch_lofty_properties() is shared
    "lofty_modules": {
        "property_management": 51046,
    },
}
```

### Steps to set up a new PM

1. **Copy the template**: `cp scripts/generic_pm_matcher.py scripts/eco_systems_matcher.py`
2. **Update `PM_CONFIG`**: Change `name`, `corpus_structure.root` to point to their Dropbox folder
3. **Log in as that PM**: The webpack fetcher returns whichever properties the logged-in PM account manages
4. **Run**: `python3 scripts/eco_systems_matcher.py --apply`

That's it. All 22 MCP tools work the same — they just operate on the PM's own portfolio.

### Multiple PMs on one machine

Each PM gets their own `config/property_update_map.json`. Use `--map-file` to specify:

```bash
python3 scripts/eco_systems_matcher.py --map-file config/eco_systems_property_map.json --apply
```

## License

Private repository. All rights reserved.