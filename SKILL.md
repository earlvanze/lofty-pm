---
name: lofty-pm-pages
description: Automate Lofty property-management flows through direct Brave CDP and Lofty HAR/runtime replay. Use when getting manager properties, updating Lofty property-owner edit pages, sending property update emails to owners, or building/reusing deterministic Lofty PM scripts that must refresh endpoint-specific auth on demand, reuse a canonical authenticated Lofty tab, avoid duplicate tabs, retry once on 403/expiry, and never use browser relay.
---

# Lofty PM Pages

Use this skill for direct Brave CDP Lofty property-management automation.

## Canonical execution model

Title-state guard:
- Treat `Confirm Email | Lofty AI` as a title misnomer when the Property Management app content is present in-page.
- Do not treat the title alone as an auth failure.
- Trust live PM page evidence instead: `/property-owners`, `/property-owners/edit/{propertyId}`, property list rows, edit form fields, and `Save changes`.
- Only treat the Lofty PM context as unauthenticated if the PM app content is absent or the session is actually redirected to a login/blocking state.

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
  - wraps live manager-property fetches, payload building, save/send mutations, and lease date backfills
- `pyproject.toml`
  - packages the repo as an installable MCP server entry point: `lofty-pm-mcp`
- environment notes
  - set `LOFTY_PM_WORKSPACE_ROOT` when the Dropbox/Real Estate corpus lives outside the repo checkout
  - optionally set `LOFTY_PM_REAL_ESTATE_ROOT` directly to override the property-document search root

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

- `51046` — Property management module (`mod.PK` = get-manager-properties)
- Module IDs may change across Lofty deployments; inspect via DevTools Console

### Advantages

1. **No auth header capture needed** — Uses existing browser session auth
2. **Single call for all properties** — `mod.PK()` returns entire portfolio
3. **No AWS Sig v4 complexity** — Browser handles signing automatically
4. **Works with any auth state** — Email confirm, MFA, etc. already resolved in browser

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
