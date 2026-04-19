---
name: lofty-pm-pages
description: Automate Lofty property-management flows through direct Brave CDP and Lofty HAR/runtime replay. Use when getting manager properties, updating Lofty property-owner edit pages, sending property update emails to owners, or building/reusing deterministic Lofty PM scripts that must refresh endpoint-specific auth on demand, reuse a canonical authenticated Lofty tab, avoid duplicate tabs, retry once on 403/expiry, and never use browser relay.
---

# Lofty PM Pages

Use this skill for direct Brave CDP Lofty property-management automation.

## Canonical execution model

**Title misnomer guard:**
- Any page title text — `Password Recovery`, `Confirm Email`, `Log In`, or any other string — is a **misnomer** when the Property Management app content is actually present in-page.
- Never treat the `<title>` alone as an auth failure or navigation error.
- Trust **live PM page evidence** instead: `/property-owners` in the URL, property list rows, edit form fields, `Save changes` buttons, webpack module availability.
- Only treat the session as unauthenticated if the PM app content is **absent** and the page is actually stuck on a login/blocking state (no PM content renders, repeated redirects to `/login`).

This guard is critical because Lofty's SPA often sets the title to `Password Recovery | Lofty AI` or `Confirm Email | Lofty AI` even when the PM dashboard is fully loaded and functional — the title is set by a previous auth step and is never updated by the SPA router.

Use deterministic scripts, not freeform browser clicking.

Execution order:
1. Ensure direct Brave CDP context on `127.0.0.1:9222`
2. Reuse the best existing authenticated Lofty tab
3. Use `/property-owners` as the canonical list tab for `get-manager-properties`
4. Use `/property-owners/edit/{propertyId}` as the canonical edit tab for save/send
5. Open a new Lofty tab only if no reusable tab exists
6. Refresh auth on demand for the exact endpoint being called
7. Execute immediately
8. On auth-related failure, refresh auth and retry once
9. Avoid leaving duplicate Lofty tabs behind

## Tab policy

`ensure_lofty_cdp_context()` behavior:
- inspect existing CDP tabs first
- prefer a matching property edit tab
- otherwise prefer any authenticated Lofty tab
- only open a new tab if needed
- optionally close extra Lofty tabs
- do not use relay

## Decision tree for small models (≤35B parameters)

When running on a small or MoE model, follow these decision rules exactly. Do not improvise or chain multiple operations.

### Step 1: What do you need to do?

```
NEED TO READ PROPERTY DATA?
  → use: webpack_get_manager_properties
     args: {year: 2026, month: 4}
     returns: list of all properties with fields
     NO BROWSER NEEDED if webpack tab is open

NEED TO UPDATE ONE FIELD ON ONE PROPERTY?
  → use: webpack_update_property
     args: {property_id: "01HP0C6P...", patch: {lease_begins_date: "04/13/2025"}}
     NO BROWSER NEEDED if webpack tab is open

NEED TO READ DESCRIPTION.md?
  → use: read_description_md
     args: {property_query: "Wild Olive"}
     reads from local Dropbox files

NEED TO WRITE DESCRIPTION.md?
  → use: write_description_md
     args: {property_query: "Wild Olive", sections: {"Occupancy Status": "..."}}
     OR: {property_query: "Wild Olive", content: "full file content"}

NEED TO ADD AN UPDATE?
  → use: write_property_update
     args: {property_query: "49 Bannbury", text: "update text", date: "04/19/2026"}

NEED TO PUBLISH UPDATE TO LOFTY + EMAIL OWNER?
  → use: publish_latest_property_update
     args: {property_query: "49 Bannbury"}

NEED TO INGEST ATLAS RELAY TEXT?
  → use: ingest_and_publish_atlas_relay_update
     args: {text: "full relay text", property_query: "Wild Olive"}

NEED TO CHECK/PATCH LEASE BEGINS DATES?
  → audit: extract_lease_begins_dates {property_query: "..."}
  → apply: update_lease_begins_dates {property_query: "...", apply: true}

NEED TO REBUILD THE PROPERTY MAP?
  → use: rebuild_property_map {dry_run: true}  (check first)
  → then: rebuild_property_map {apply: true}   (to write)

NEED P&L DATA?
  → config: webpack_get_pl_cutoff_config {}
  → entry: webpack_get_pl_entry {property_id: "...", year: 2026, month: 4}
```

### Step 2: NEVER do these

```
NEVER: chain 3+ tool calls without returning intermediate results to the user
NEVER: use update_manager_property (use webpack_update_property instead)
NEVER: use get_manager_properties (use webpack_get_manager_properties instead)
NEVER: use browser automation for tasks that have a dedicated MCP tool
NEVER: guess property_id — always look it up via webpack_get_manager_properties first
NEVER: call rebuild_property_map with apply=true without a dry_run first
NEVER: call write_description_md with content= unless you have the FULL file text
```

### Step 3: Error recovery

```
WEBPACK TOOLS RETURN ERROR?
  → Check if Brave is running: curl -s http://127.0.0.1:9222/json/version
  → If not: launch Brave headless (see scripts/lofty_cdp.py)
  → If Brave is up but tab is on login: user must re-authenticate

PROPERTY NOT FOUND?
  → Use webpack_get_manager_properties first to get the property_id
  → Then use the exact ID in subsequent calls

WRITE CONFLICTS?
  → read_description_md first to see current content
  → Use sections= mode instead of content= for partial updates
```

## Scripts

### Core helpers
- `scripts/lofty_cdp.py`
  - direct Brave CDP bootstrap
  - canonical Lofty tab reuse
  - duplicate-tab avoidance
- `scripts/capture_lofty_auth_via_cdp.py`
  - on-demand endpoint-specific auth capture for:
    - `get-manager-properties`
    - `update-manager-property`
    - `send-property-updates`
- `scripts/update_lofty_pm_property.py`
  - execute one Lofty endpoint
  - supports on-demand auth refresh and one retry on auth failure
- `scripts/save_and_send_lofty_pm_update.py`
  - low-ambiguity full flow for smaller local/MoE models:
    - optional `get-manager-properties`
    - save
    - send owner update email
- `scripts/extract_lofty_lease_begins_dates.py`
  - extracts `lease_begins_date` candidates from `Public/DESCRIPTION.md`
  - supports safe multi-unit handling with `ambiguous|first|earliest|latest`
- `scripts/update_lofty_pm_lease_begins_dates.py`
  - writes `lease_begins_date` through `update-manager-property`
  - avoids brittle DOM interaction with `input[name="lease_begins_date"]`

### MCP server surface
- `src/lofty_pm_mcp/server.py`
  - exposes the core Lofty PM flows as MCP tools
  - wraps live manager-property fetches, Atlas Relay ingest, property-map rebuilds, update writing/publishing, save/send mutations, and lease date backfills
- `scripts/rebuild_property_update_map.py`
  - rebuilds `config/property_update_map.json` from live Lofty manager properties plus the Dropbox Real Estate corpus
- `scripts/generic_pm_matcher.py`
  - parameterized fuzzy matcher template for adapting to other PM portfolios
  - same Lofty API, different Dropbox corpus structure per PM
- `pyproject.toml`
  - packages the repo as an installable MCP server entry point: `lofty-pm-mcp`
- environment notes
  - set `LOFTY_PM_WORKSPACE_ROOT` when the Dropbox/Real Estate corpus lives outside the repo checkout
  - optionally set `LOFTY_PM_REAL_ESTATE_ROOT` directly to override the property-document search root
  - `config/property_update_map.json` is gitignored (contains real property data)
  - `config/property_update_map.template.json` provides the structure template

### MCP tools (22 total)

**Prefer webpack tools over auth-capture tools.** Webpack tools (12-13, 19-22) work without auth header capture and are more reliable.

| # | Tool | What | Best for |
|---|------|------|----------|
| 1 | `get_manager_properties` | Fetch property list (auth-capture) | Legacy — prefer #12 |
| 2 | `build_property_payloads` | Build save/send payloads | Legacy flow |
| 3 | `update_manager_property` | Apply mutation (runtime-direct) | Legacy — prefer #13 |
| 4 | `send_property_updates` | Send owner update email | After #8 |
| 5 | `ingest_atlas_relay_update` | Atlas text → UPDATES.md | Discord relay ingest |
| 6 | `ingest_and_publish_atlas_relay_update` | End-to-end ingest + publish | One-shot Atlas relay |
| 7 | `write_property_update` | Write dated entry to UPDATES.md | Manual update entry |
| 8 | `publish_latest_property_update` | Push updates + send email | After #7 |
| 9 | `rebuild_property_map` | Rebuild map from live + corpus | After adding properties |
| 10 | `extract_lease_begins_dates` | Audit lease dates from DESCRIPTION.md | Lease date audit |
| 11 | `update_lease_begins_dates` | Apply lease date patches | After #10 |
| 12 | **`webpack_get_manager_properties`** | Fetch properties (no auth) | **Default for reads** |
| 13 | **`webpack_update_property`** | Update property (no auth) | **Default for writes** |
| 14 | `extract_property_data` | Scrape DETAILS.md + FINANCIALS.md | Lofty → local |
| 15 | `backfill_updates_history` | Backfill UPDATES.md from live data | History sync |
| 16 | `read_description_md` | Read/parse DESCRIPTION.md | Local read |
| 17 | `write_description_md` | Write/update DESCRIPTION.md | Local write |
| 18 | `push_property_data` | Push DETAILS/FINANCIALS → Lofty | Local → Lofty |
| 19 | `webpack_get_pl_cutoff_config` | Get P&L cutoff config | P&L config |
| 20 | `webpack_get_pl_entry` | Get P&L entry for a property | P&L read |
| 21 | `webpack_create_pl_entry` | Create P&L entry | P&L write |
| 22 | `webpack_update_pl_entry` | Update P&L entry | P&L write |

### Recommended one-shot flow

```bash
python3 skills/lofty-pm-pages/scripts/save_and_send_lofty_pm_update.py \
  --get-manager-properties-payload-file tmp/lofty-pm/manager.get-manager-properties.payload.json \
  --save-payload-file tmp/lofty-pm/PROPERTY.update-manager-property.payload.json \
  --save-patch-file tmp/lofty-pm/PROPERTY.patch.json \
  --send-payload-file tmp/lofty-pm/PROPERTY.send-property-updates.payload.json \
  --derive-updates-diff \
  --property-id PROPERTY_ID \
  --close-extra-tabs
```

## Notes for smaller local models

Prefer the wrapper script over ad-hoc orchestration.
Keep decisions low-ambiguity:
- one canonical tab
- one endpoint at a time
- one automatic retry on auth failure
- no blind loops

This skill is optimized for deterministic execution by smaller models as long as Brave CDP and an authenticated Lofty session exist.

**For models ≤35B (including MoE):** Use only the MCP tools listed in the decision tree above. Each tool does exactly one thing. Call one tool, return the result, then decide the next step. Never chain more than 2 tool calls without user confirmation.

## References

Read `references/api.md` for endpoint behavior and auth/tab policy.


## File-backed property updates

Canonical property update source of truth:
- `<Property>/Public/Updates/UPDATES.md`

Use:
- `scripts/write_property_update_md.py` to write a canonical update entry
- `scripts/publish_latest_update_to_lofty.py` to publish the latest entry to Lofty PM and then send it to owners
- `scripts/extract_lofty_lease_begins_dates.py` to audit or preview lease start dates parsed from `DESCRIPTION.md`
- `scripts/update_lofty_pm_lease_begins_dates.py` to patch Lofty PM `lease_begins_date` via API payload replay

Required header inside each update entry:
- `- Property Update (MM/DD/YYYY):`

The clean text below that header is what should be used for both:
- the Lofty PM `updates` field
- the owner email `updatesDiff`

Configuration:
- `config/property_update_map.json`
  - maps property name/path to:
    - `lofty_property_id`
    - canonical `UPDATES.md`
    - payload files used by the wrapper

## Lease start workflow

Prefer API payload replay over DOM automation for `lease_begins_date`.

Reason:
- the React edit form can show `input[name="lease_begins_date"]` to a human while CDP DOM queries still fail or race hydration
- patching `update-manager-property` is more deterministic than clicking the edit page

Recommended audit pass:

```bash
python3 skills/lofty-pm/scripts/extract_lofty_lease_begins_dates.py \
  --property-map skills/lofty-pm/config/property_update_map.json \
  --multi-date-strategy ambiguous
```

Recommended batch dry-run:

```bash
python3 skills/lofty-pm/scripts/update_lofty_pm_lease_begins_dates.py \
  --property-map skills/lofty-pm/config/property_update_map.json \
  --multi-date-strategy earliest \
  --output-dir tmp/lofty-pm-lease-dates
```

Apply for one property:

```bash
python3 skills/lofty-pm/scripts/update_lofty_pm_lease_begins_dates.py \
  --property '918 Frederick Blvd' \
  --multi-date-strategy earliest \
  --output-dir tmp/lofty-pm-lease-dates \
  --apply
```

Notes:
- `ambiguous` is safest for audit/reporting
- `earliest` is usually the best batch strategy for multi-unit properties when a single Lofty field must be chosen
- vacant or month-to-month properties without a dated lease start are intentionally skipped

## CDP Webpack Module Injection (Auth Bypass)

**Problem:** AWS Sig v4 auth headers are request-specific and cannot be reused across different property IDs or endpoints.

**Solution:** Execute Lofty's webpack modules directly in the authenticated browser context via CDP WebSocket. This bypasses auth header capture entirely by making API calls from within the already-authenticated page.

### Implementation

```python
import json
import websocket

CDP_WS = 'ws://127.0.0.1:9222/devtools/page/{target_id}'

ws = websocket.WebSocket()
ws.connect(CDP_WS, timeout=30)

msg_id = 0

def send(method, params=None):
    global msg_id
    msg_id += 1
    ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params or {}}))
    return msg_id

def recv_until_id(cid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            ws.settimeout(1)
            obj = json.loads(ws.recv())
            if obj.get('id') == cid:
                return obj
        except:
            pass
    return None

# Enable Runtime
send('Runtime.enable')

# Execute webpack module call directly in browser context
expr = """(async () => { 
  let __req; 
  webpackChunklofty_investing_webapp.push([[Math.random()], {}, function(req){ __req = req; }]); 
  const mod = __req(51046);  // Property management module
  return await mod.PK({year: 2026, month: 4});  // Get all properties
})()"""

cid = send('Runtime.evaluate', {
    'expression': expr, 
    'awaitPromise': True, 
    'returnByValue': True, 
    'timeout': 30000
})

result = recv_until_id(cid, 35)
# result['result']['value'] contains the API response
```

### Key Module IDs (subject to change)

Module `51046` — Property Management API wrapper:

| Export | API Endpoint | Method | Description |
|--------|-------------|--------|-------------|
| `PK` | `getManagerProperties` | GET | Fetch all properties for a month |
| `so` | `updateManagerProperty` | POST | Update a property (patch fields) |
| `AB` | `managerSendPropertyUpdates` | POST | Send owner update email |
| `SP` | `managerUpdatePLEntry` | POST | Update a P&L entry |
| `b1` | `managerGetPLEntry` | GET | Get a single P&L entry |
| `cj` | `getPlCutoffConfig` | GET | Get P&L cutoff config |
| `t1` | `managerCreatePLEntry` | POST | Create a P&L entry |

Module `50469` — React hooks composing the above API calls:

| Export | Calls | Description |
|--------|-------|-------------|
| `Bn` | `PK` | Fetch properties for current month |
| `jg` | `so` | Update/modify property |
| `AB` | `AB` | Send property update email |
| `zd` | `b1` | Get single P&L entry |
| `jw` | `t1` | Create P&L entry |
| `et` | `SP` | Update P&L entry |
| `Xl` | `cj` | Get PL cutoff config |

### When to Use

- Batch property data extraction (all properties at once)
- When `capture_lofty_auth_via_cdp.py` fails or returns stale signatures
- For read-only operations that don't require write auth tokens

### Scripts

- `scripts/extract_lofty_property_data.py` — Uses webpack injection for batch extraction
- Creates `Public/DETAILS.md` and `Public/Financials/FINANCIALS.md` for each property

### Limitations

- Module IDs (`51046`) may change — verify via DevTools Console if broken
- Write operations may still need captured auth headers for `send-property-updates`
- Requires active authenticated Lofty tab in Brave CDP context