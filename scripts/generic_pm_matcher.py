#!/usr/bin/env python3
"""
PM-specific Lofty property matcher.

Adapt this script for each Property Manager (PM) under Lofty by:
1. Copy this file: cp generic_pm_matcher.py <pm_name>_matcher.py
2. Update PM_CONFIG with the PM's specific field mappings and corpus layout
3. Customize find_corpus_dirs() for their Dropbox folder structure
4. Adjust matching weights if their naming conventions differ

All PMs use the same Lofty webpack API (module 51046: PK, so, AB, etc.).
The only differences are:
- Which properties appear in each PM's dashboard
- How their Dropbox Real Estate folders are organized
- What custom fields/sections they use in DESCRIPTION.md

Usage:
  # Dry run (default): shows what would be matched
  python3 generic_pm_matcher.py --year 2026 --month 4

  # Apply: writes the map file
  python3 generic_pm_matcher.py --year 2026 --month 4 --apply

  # Specify PM account
  python3 generic_pm_matcher.py --pm eco-systems --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# =============================================================================
# PM_CONFIG — Adapt per Property Manager
#
# Every PM uses the SAME Lofty API. The only differences are:
#   - Which properties appear in their PM dashboard (filtered by PM account)
#   - How their local Dropbox corpus is organized
#   - Which DESCRIPTION.md sections they use
#   - Custom fields they track in UPDATES.md
# =============================================================================

PM_CONFIG = {
    # Display name for this PM configuration
    "name": "default",

    # Lofty webpack module IDs (same for ALL PMs — don't change these)
    "lofty_modules": {
        "property_management": 51046,  # PK (GET), so (POST), AB (POST), SP (POST), b1 (GET), cj (GET), t1 (POST)
    },

    # PM-specific URL patterns for identifying the right authenticated tab
    # Each PM logs into lofty.ai/property-owners — the URL is the same,
    # but the session is tied to their PM account
    "pm_url_patterns": ["lofty.ai/property", "lofty.ai/property-owners"],

    # Corpus (Dropbox) directory structure
    # All PMs share the same Real Estate root, but may organize differently
    "corpus_structure": {
        # Root path: each PM may have their own Dropbox structure
        # e.g., "Dropbox/Real Estate - ECO Systems" vs "Dropbox/Real Estate"
        "root": "${PM_WORKSPACE_ROOT}/Dropbox/Real Estate",

        # Set to True if properties are organized under state folders (FL/, CA/, etc.)
        # Set to False if all properties are in a flat list
        "state_dirs": True,

        # Subdirectory within each property folder containing canonical files
        "public_dir": "Public",

        # Canonical files that the matcher looks for
        "description_file": "DESCRIPTION.md",
        "updates_dir": "Updates",
        "updates_file": "UPDATES.md",
        "details_file": "DETAILS.md",
        "financials_dir": "Financials",
        "financials_file": "FINANCIALS.md",
    },

    # Lofty API field names (same for all PMs — the API shape doesn't change)
    "pm_property_fields": {
        "id": "id",
        "name": "assetName",
        "address": "address",
        "city": "city",
        "state": "state",
        "zip": "zipCode",
        "slug": "slug",
        "unit": "assetUnit",
    },

    # Matching configuration (tune per PM if their naming differs)
    "matching": {
        "exact_match_threshold": 100,
        "substring_match_multiplier": 1,
        "word_overlap_weight": 5,
        "minimum_match_score": 10,
        "prefer_state_match": True,
        "state_match_bonus": 20,
    },
}

# =============================================================================
# Environment / Path Setup
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

WORKSPACE_ROOT = Path(os.environ.get("PM_WORKSPACE_ROOT",
                                      os.environ.get("LOFTY_PM_WORKSPACE_ROOT",
                                                      str(Path.home() / ".openclaw" / "workspace"))))
REAL_ESTATE_ROOT = Path(os.environ.get("PM_REAL_ESTATE_ROOT",
                                        os.environ.get("LOFTY_PM_REAL_ESTATE_ROOT",
                                                        str(WORKSPACE_ROOT / "Dropbox" / "Real Estate"))))
TMP_ROOT = Path(os.environ.get("PM_TMP_ROOT",
                                 os.environ.get("LOFTY_PM_TMP_ROOT",
                                                 "/tmp/pm-matcher")))


def _path_vars() -> dict[str, str]:
    return {
        "PM_WORKSPACE_ROOT": str(WORKSPACE_ROOT),
        "PM_REAL_ESTATE_ROOT": str(REAL_ESTATE_ROOT),
        "PM_TMP_ROOT": str(TMP_ROOT),
        "LOFTY_PM_WORKSPACE_ROOT": str(WORKSPACE_ROOT),
        "LOFTY_PM_REAL_ESTATE_ROOT": str(REAL_ESTATE_ROOT),
        "LOFTY_PM_TMP_ROOT": str(TMP_ROOT),
    }


def resolve_path(value: str | None) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    for old, new in _path_vars().items():
        rendered = rendered.replace(old, new)
    return rendered


def template_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    prefixes = [
        (str(REAL_ESTATE_ROOT), "${PM_REAL_ESTATE_ROOT}"),
        (str(WORKSPACE_ROOT), "${PM_WORKSPACE_ROOT}"),
    ]
    for prefix, repl in prefixes:
        if rendered == prefix:
            return repl
        if rendered.startswith(prefix + os.sep):
            return repl + rendered[len(prefix):]
    return rendered


# =============================================================================
# Fuzzy Matching Engine (same algorithm for all PMs)
# =============================================================================

def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace(",", " ").replace(".", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _norm_addr(addr: str) -> str:
    s = _norm(addr)
    s = re.sub(r"\b(apt|unit|suite|ste|#)\s*\S+", "", s)
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", s)
    return " ".join(s.split())


def _norm_city(city: str) -> str:
    return _norm(city)


def _norm_state(state: str) -> str:
    return _norm(state).strip()


def match_properties(
    pm_properties: list[dict[str, Any]],
    corpus_dirs: list[dict[str, Any]],
    config: dict[str, Any] = None,
) -> list[dict[str, Any]]:
    cfg = (config or PM_CONFIG)["matching"]
    min_score = cfg["minimum_match_score"]
    exact_threshold = cfg["exact_match_threshold"]
    word_weight = cfg["word_overlap_weight"]
    substring_mult = cfg["substring_match_multiplier"]
    prefer_state = cfg["prefer_state_match"]
    state_bonus = cfg["state_match_bonus"]

    fields = PM_CONFIG["pm_property_fields"]
    matched = []
    used_corpus = set()

    for prop in pm_properties:
        addr = prop.get(fields["address"], "") or ""
        city = prop.get(fields["city"], "") or ""
        state = prop.get(fields["state"], "") or ""
        full_addr = f"{addr}, {city} {state}".strip(", ")
        norm_lofty = _norm_addr(full_addr)
        norm_city = _norm_city(city)
        norm_state = _norm_state(state)

        best_score = 0
        best_corpus = None
        best_idx = -1

        for i, cd in enumerate(corpus_dirs):
            if i in used_corpus:
                continue

            norm_cd = cd["norm_addr"]
            norm_cd_city = cd.get("norm_city", "")
            norm_cd_state = cd.get("norm_state", "")

            if norm_cd == norm_lofty:
                score = exact_threshold
            elif norm_cd in norm_lofty or norm_lofty in norm_cd:
                shorter = min(len(norm_cd), len(norm_lofty))
                score = shorter * substring_mult
            else:
                cd_words = set(norm_cd.split())
                lofty_words = set(norm_lofty.split())
                overlap = cd_words & lofty_words
                score = len(overlap) * word_weight

            if prefer_state and norm_state and norm_cd_state:
                if norm_state == norm_cd_state:
                    score += state_bonus
                elif norm_state[:2] == norm_cd_state[:2]:
                    score += state_bonus // 2

            if norm_city and norm_cd_city and norm_city == norm_cd_city:
                score += 10

            if score > best_score:
                best_score = score
                best_corpus = cd
                best_idx = i

        entry: dict[str, Any] = {
            fields["id"]: prop.get(fields["id"], ""),
            "property_name": prop.get(fields["name"]) or addr,
            "full_address": full_addr,
            fields["slug"]: prop.get(fields["slug"], ""),
            fields["unit"]: prop.get(fields["unit"], ""),
            "state": state,
        }

        if best_corpus and best_score >= min_score:
            used_corpus.add(best_idx)
            entry["description_md"] = best_corpus["description_md"]
            if best_corpus.get("updates_md"):
                entry["updates_md"] = best_corpus["updates_md"]
            if best_corpus.get("details_md"):
                entry["details_md"] = best_corpus["details_md"]
            if best_corpus.get("financials_md"):
                entry["financials_md"] = best_corpus["financials_md"]
            entry["corpus_dir"] = best_corpus["public_dir"]
            entry["match_score"] = best_score

        matched.append(entry)

    for i, cd in enumerate(corpus_dirs):
        if i not in used_corpus:
            matched.append({
                "property_name": cd["dir_name"],
                "full_address": cd["dir_name"],
                "description_md": cd["description_md"],
                "updates_md": cd.get("updates_md"),
                "details_md": cd.get("details_md"),
                "financials_md": cd.get("financials_md"),
                "unresolved": True,
            })

    return matched


# =============================================================================
# Corpus Scanner — Adapt per PM's Dropbox structure
# =============================================================================

def find_corpus_dirs() -> list[dict[str, Any]]:
    """
    Scan the local corpus for property directories.

    ALL PMs share the same Lofty API, but each PM may organize their
    Dropbox Real Estate folders differently. Adapt this function if:
    - Your PM uses a different root folder (e.g., "Real Estate - ECO Systems")
    - Properties aren't organized by state
    - File names differ (e.g., "description.md" instead of "DESCRIPTION.md")
    """
    cfg = PM_CONFIG["corpus_structure"]
    results: list[dict[str, Any]] = []
    re_root = REAL_ESTATE_ROOT
    if not re_root.is_dir():
        return results

    desc_file = cfg["description_file"]
    updates_dir = cfg["updates_dir"]
    updates_file = cfg["updates_file"]
    details_file = cfg.get("details_file", "DETAILS.md")
    financials_dir = cfg.get("financials_dir", "Financials")
    financials_file = cfg.get("financials_file", "FINANCIALS.md")
    public_dir_name = cfg["public_dir"]
    state_dirs = cfg["state_dirs"]

    # Level 1: state dirs or direct property dirs
    top_dirs = sorted(re_root.iterdir()) if re_root.is_dir() else []
    for top in top_dirs:
        if not top.is_dir() or top.name.startswith("."):
            continue

        if state_dirs:
            # top is a state directory (FL/, CA/, etc.)
            state_abbr = top.name.upper()
            prop_dirs = sorted(top.iterdir())
        else:
            # top IS the property directory (flat layout)
            prop_dirs = [top]
            state_abbr = ""

        for prop_dir in prop_dirs:
            if not prop_dir.is_dir() or prop_dir.name.startswith("."):
                continue

            # Find the canonical directory
            pub_dir = prop_dir / public_dir_name if (prop_dir / public_dir_name).is_dir() else prop_dir
            desc = pub_dir / desc_file
            upd_file = (pub_dir / updates_dir / updates_file) if updates_dir and updates_file else None
            det = pub_dir / details_file if details_file else None
            fin = (pub_dir / financials_dir / financials_file) if financials_dir and financials_file else None

            if not desc.is_file():
                continue

            dir_name = prop_dir.name
            city_match = re.search(r',\s*([^,]+),\s*([A-Z]{2})\s+\d{3}', dir_name)
            norm_city = _norm_city(city_match.group(1)) if city_match else ""

            results.append({
                "dir_name": dir_name,
                "public_dir": str(pub_dir),
                "description_md": str(desc),
                "updates_md": str(upd_file) if upd_file and upd_file.is_file() else None,
                "details_md": str(det) if det and det.is_file() else None,
                "financials_md": str(fin) if fin and fin.is_file() else None,
                "norm_name": _norm(dir_name),
                "norm_addr": _norm_addr(dir_name),
                "norm_city": norm_city,
                "norm_state": state_abbr,
            })

    return results


# =============================================================================
# Lofty Data Fetcher — Same API for all PMs
# =============================================================================

def fetch_lofty_properties(year: int | None = None, month: int | None = None) -> list[dict[str, Any]]:
    """
    Fetch live properties from Lofty via webpack injection.

    This is the SAME for all PMs — Lofty's API doesn't change.
    The PM account determines which properties appear (based on
    which user is logged in to the browser session).
    """
    from lofty_cdp import ensure_lofty_cdp_context
    from capture_lofty_auth_via_cdp import connect_ws
    import datetime as dt
    import time

    now = dt.datetime.now()
    y = str(year or now.year)
    m = str(month or now.month)

    ctx = ensure_lofty_cdp_context(mode="list")
    tid = ctx["targetId"]
    ws = connect_ws(tid)
    msg_id = 0

    def sr(method, params=None, timeout=30):
        nonlocal msg_id
        msg_id += 1
        cid = msg_id
        ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            try:
                obj = json.loads(ws.recv())
                if obj.get("id") == cid:
                    return obj
            except Exception:
                pass
        raise TimeoutError()

    # Wait for webpack
    for _ in range(15):
        resp = sr("Runtime.evaluate", {
            "expression": 'typeof webpackChunklofty_investing_webapp !== "undefined"',
            "returnByValue": True, "awaitPromise": False,
        })
        if resp.get("result", {}).get("result", {}).get("value") is True:
            break
        time.sleep(2)

    expr = f'''(async () => {{
      let __req;
      webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]);
      const mod = __req(51046);
      const data = await mod.PK({{year: "{y}", month: "{m}"}});
      return JSON.stringify(data?.data?.properties || []);
    }})()'''

    resp = sr("Runtime.evaluate", {
        "expression": expr, "awaitPromise": True, "returnByValue": True, "timeout": 30000,
    })
    ws.close()

    val = resp.get("result", {}).get("result", {}).get("value", "[]")
    return json.loads(val) if isinstance(val, str) else val


# =============================================================================
# Main — Rebuild the property map
# =============================================================================

MAP_FILE = SCRIPT_DIR.parent / "config" / "property_update_map.json"


def rebuild_map(
    map_file: str | None = None,
    dry_run: bool = True,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    target = Path(map_file) if map_file else MAP_FILE

    # Fetch properties from Lofty (same API, PM account determines the portfolio)
    pm_properties = fetch_lofty_properties(year=year, month=month)
    live_count = len(pm_properties)

    # Scan local corpus (PM-specific Dropbox structure)
    corpus_dirs = find_corpus_dirs()
    corpus_count = len(corpus_dirs)

    # Fuzzy-match
    matched = match_properties(pm_properties, corpus_dirs)

    properties = []
    unresolved = []
    for entry in matched:
        if entry.pop("unresolved", False):
            unresolved.append(entry)
        else:
            properties.append(entry)

    # Template-ify paths
    for entry in properties + unresolved:
        for key in ("description_md", "updates_md", "details_md", "financials_md"):
            if entry.get(key):
                entry[key] = template_path(entry[key]) or entry[key]

    output = {
        "properties": properties,
        "unresolved": unresolved,
        "metadata": {
            "pm_platform": "Lofty",
            "pm_config": PM_CONFIG["name"],
            "lofty_module_id": 51046,
            "live_properties": live_count,
            "corpus_dirs": corpus_count,
            "resolved": len(properties),
            "unresolved_count": len(unresolved),
        },
    }

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(output, indent=2) + "\n")

    return {
        "map_file": str(target),
        "dry_run": dry_run,
        "pm_config": PM_CONFIG["name"],
        "live_properties": live_count,
        "corpus_dirs": corpus_count,
        "resolved": len(properties),
        "unresolved": len(unresolved),
        "written": not dry_run,
    }


def main():
    ap = argparse.ArgumentParser(description="PM-specific Lofty property matcher — rebuild property_update_map.json")
    ap.add_argument("--map-file", default=str(MAP_FILE))
    ap.add_argument("--year", type=int)
    ap.add_argument("--month", type=int)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true", help="Write the rebuilt map file")
    args = ap.parse_args()

    result = rebuild_map(
        map_file=args.map_file,
        dry_run=not args.apply,
        year=args.year,
        month=args.month,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()