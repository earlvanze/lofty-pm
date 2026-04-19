#!/usr/bin/env python3
"""
Enumerate Lofty webpack modules and their exports.

Usage:
  # Must have a Lofty tab open in Brave with CDP on BASELANE_CDP_PORT
  python3 scripts/lofty_webpack_enumerate.py

Outputs a JSON map of module_id -> {export_names, sample_results}
"""
from __future__ import annotations

import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from lofty_cdp import ensure_lofty_cdp_context
from capture_lofty_auth_via_cdp import connect_ws

CDP_BASE = os.environ.get('BASELANE_CDP_PORT', 'http://127.0.0.1:9222')


def main():
    ctx = ensure_lofty_cdp_context(mode='list')
    tid = ctx['targetId']
    ws = connect_ws(tid)

    msg_id = 0

    def sr(method, params=None, timeout=30):
        nonlocal msg_id
        msg_id += 1
        cid = msg_id
        ws.send(json.dumps({'id': cid, 'method': method, 'params': params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            try:
                obj = json.loads(ws.recv())
                if obj.get('id') == cid:
                    return obj
            except Exception:
                pass
        raise TimeoutError()

    # Wait for webpack
    print("Waiting for webpack...", file=sys.stderr)
    for _ in range(15):
        resp = sr('Runtime.evaluate', {
            'expression': 'typeof webpackChunklofty_investing_webapp !== "undefined"',
            'returnByValue': True, 'awaitPromise': False,
        })
        if resp.get('result', {}).get('result', {}).get('value') is True:
            break
        time.sleep(2)

    # Step 1: Find the webpack module registry size
    print("Finding module range...", file=sys.stderr)
    resp = sr('Runtime.evaluate', {
        'expression': '''(async () => {
          // Get a reference to the require function
          let __req;
          webpackChunklofty_investing_webapp.push([[Math.random()], {}, function(req){ __req = req; }]);

          // Known working modules
          const known = {
            51046: 'property-management (PK=fetch, so=update)'
          };

          // Probe a range of module IDs to find exports
          const results = {};
          const probeRange = [];

          // We'll probe common module ID ranges
          // Module IDs in Lofty are typically in the 10000-60000 range
          for (let id = 10000; id < 60000; id += 100) {
            probeRange.push(id);
          }

          // Also try some specific known ones
          for (const id of Object.keys(known).map(Number)) {
            probeRange.push(id);
          }

          for (const id of probeRange) {
            try {
              const mod = __req(id);
              if (mod && typeof mod === 'object') {
                const exports = Object.keys(mod).filter(k => typeof mod[k] === 'function');
                if (exports.length > 0) {
                  results[id] = {
                    exports: exports,
                    two_char_exports: exports.filter(k => k.length <= 3),
                    has_PK: typeof mod.PK === 'function',
                    has_so: typeof mod.so === 'function',
                  };
                }
              }
            } catch(e) {
              // Module doesn't exist or can't be loaded
            }
          }

          return JSON.stringify(results);
        })()''',
        'awaitPromise': True, 'returnByValue': True, 'timeout': 60000,
    })

    val = resp.get('result', {}).get('result', {}).get('value', '{}')
    modules = json.loads(val) if isinstance(val, str) else val

    print(json.dumps(modules, indent=2))

    # Step 2: For modules with short export names, try to identify API-related ones
    print("\n\n=== Potential API modules ===", file=sys.stderr)
    api_modules = {}
    for mid, info in modules.items():
        exports = info.get('exports', [])
        two_char = info.get('two_char_exports', [])
        # Heuristic: modules with PK (fetch) or so (mutate) are API modules
        if info.get('has_PK') or info.get('has_so') or len(two_char) >= 2:
            api_modules[mid] = info

    if api_modules:
        print(json.dumps(api_modules, indent=2))

    ws.close()


if __name__ == '__main__':
    main()