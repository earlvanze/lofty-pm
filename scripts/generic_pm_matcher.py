#!/usr/bin/env python3
"""
Generic Property Manager fuzzy matcher template.

Adapt this script for any PM (Property Manager) platform by:
1. Copy this file and rename (e.g., acme_pm_matcher.py)
2. Update the PM_CONFIG section with your platform's specifics
3. Customize the corpus scanner for your Dropbox/folder structure
4. Adjust the matching weights for your naming conventions

This script:
- Fetches live property data from the PM platform
- Scans a local corpus (Dropbox/Real Estate/...) for property directories
- Fuzzy-matches them by address similarity
- Outputs a property_update_map.json with portable path templates

Usage:
  # Dry run (default): shows what would be matched
  python3 generic_pm_matcher.py --year 2026 --month 4

  # Apply: writes the map file
  python3 generic_pm_matcher.py --year 2026 --month 4 --apply

  # Custom PM fetch function
  python3 generic_pm_matcher.py --fetch-script my_pm_fetch.py --apply
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
# PM_CONFIG — Adapt this section for your platform
# =============================================================================

PM_CONFIG = {
    # Display name for the PM platform
    "name": "Lofty",
    # PM-specific URL patterns for identifying authenticated tabs
    "pm_url_patterns": ["lofty.ai/property", "lofty.ai/property-owners"],
    # Canonical directory structure within each property folder
    # {property_name} and {state} are substituted at runtime
    "corpus_structure": {
        "root": "${PM_WORKSPACE_ROOT}/Dropbox/Real Estate",
        "state_dirs": True,  # Properties are organized under state folders (FL/, CA/, etc.)
        "public_dir": "Public",  # Subdirectory containing DESCRIPTION.md, Updates/, etc.
        "description_file": "DESCRIPTION.md",
        "updates_dir": "Updates",
        "updates_file": "UPDATES.md",
    },
    # Fields the PM platform uses to identify properties
    "pm_property_fields": {
        "id": "id",              # Unique PM identifier
        "name": "assetName",    # Human-readable name
        "address": "address",   # Street address
        "city": "city",         # City
        "state": "state",       # State abbreviation
        "zip": "zipCode",       # ZIP code
        "slug": "slug",          # URL slug
        "unit": "assetUnit",    # Token unit identifier
    },
    # Matching configuration
    "matching": {
        "exact_match_threshold": 100,       # Score for exact address match
        "substring_match_multiplier": 1,    # Score per matching char in substring match
        "word_overlap_weight": 5,            # Score per overlapping word
        "minimum_match_score": 10,           # Minimum score to consider a match
        "prefer_state_match": True,          # Boost matches in the same state
        "state_match_bonus": 20,             # Bonus for same-state match
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
# Fuzzy Matching Engine
# =============================================================================

def _norm(s: str) -> str:
    """Normalize a string for matching: lowercase, replace special chars, collapse whitespace."""
    s = s.lower().replace("&", " and ").replace(",", " ").replace(".", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _norm_addr(addr: str) -> str:
    """Normalize an address for matching: strip unit/suite, ordinal suffixes."""
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
    """
    Fuzzy-match PM platform properties to local corpus directories.

    Args:
        pm_properties: List of property dicts from the PM platform API
        corpus_dirs: List of corpus directory dicts from _find_corpus_dirs()
        config: PM_CONFIG matching section (uses defaults if None)

    Returns:
        List of matched property dicts with corpus paths resolved
    """
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

            # Score computation
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

            # State bonus
            if prefer_state and norm_state and norm_cd_state:
                if norm_state == norm_cd_state:
                    score += state_bonus
                elif norm_state[:2] == norm_cd_state[:2]:
                    score += state_bonus // 2

            # City bonus
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
            entry["corpus_dir"] = best_corpus["public_dir"]
            entry["match_score"] = best_score

        matched.append(entry)

    # Add unmatched corpus dirs as unresolved
    for i, cd in enumerate(corpus_dirs):
        if i not in used_corpus:
            matched.append({
                "property_name": cd["dir_name"],
                "full_address": cd["dir_name"],
                "description_md": cd["description_md"],
                "updates_md": cd.get("updates_md"),
                "unresolved": True,
            })

    return matched


# =============================================================================
# Corpus Scanner — Adapt for your directory structure
# =============================================================================

def find_corpus_dirs() -> list[dict[str, Any]]:
    """
    Scan the local corpus (Dropbox/Real Estate/...) for property directories.

    Expected structure:
      Real Estate/
        FL/
          49 Bannbury Ln, Palm Coast, FL 32137/
            Public/
              DESCRIPTION.md
              Updates/
                UPDATES.md
        CA/
          ...

    Adapt this function if your corpus uses a different layout.
    """
    results: list[dict[str, Any]] = []
    re_root = REAL_ESTATE_ROOT
    if not re_root.is_dir():
        return results

    desc_file = PM_CONFIG["corpus_structure"]["description_file"]
    updates_dir = PM_CONFIG["corpus_structure"]["updates_dir"]
    updates_file = PM_CONFIG["corpus_structure"]["updates_file"]
    public_dir_name = PM_CONFIG["corpus_structure"]["public_dir"]

    for state_dir in sorted(re_root.iterdir()):
        if not state_dir.is_dir() or state_dir.name.startswith("."):
            continue
        # Skip non-state directories (template files, etc.)
        if state_dir.name.lower() in ("lofty pm",) or state_dir.suffix.lower() in (".xlsx", ".csv", ".pdf"):
            continue

        for prop_dir in sorted(state_dir.iterdir()):
            if not prop_dir.is_dir() or prop_dir.name.startswith("."):
                continue

            # Find the Public directory
            pub_dir = prop_dir / public_dir_name if (prop_dir / public_dir_name).is_dir() else prop_dir
            desc = pub_dir / desc_file
            upd_dir = pub_dir / updates_dir if updates_dir else None
            upd_file = upd_dir / updates_file if upd_dir and updates_file else None

            if not desc.is_file():
                continue

            # Extract city/state from directory name for better matching
            dir_name = prop_dir.name
            norm_state = state_dir.name.upper()
            # Try to parse "123 Main St, City, ST 12345" from dir name
            city_match = re.search(r',\s*([^,]+),\s*([A-Z]{2})\s+\d{3}', dir_name)
            norm_city = _norm_city(city_match.group(1)) if city_match else ""

            results.append({
                "dir_name": dir_name,
                "public_dir": str(pub_dir),
                "description_md": str(desc),
                "updates_md": str(upd_file) if upd_file and upd_file.is_file() else None,
                "norm_name": _norm(dir_name),
                "norm_addr": _norm_addr(dir_name),
                "norm_city": norm_city,
                "norm_state": norm_state,
            })

    return results


# =============================================================================
# PM Data Fetcher — Replace with your platform's fetch function
# =============================================================================

def fetch_pm_properties(year: int | None = None, month: int | None = None) -> list[dict[str, Any]]:
    """
    Fetch live properties from the PM platform.

    REPLACE THIS FUNCTION with your platform's data fetch.
    Options:
    1. Use webpack injection (like Lofty) if the platform uses a SPA
    2. Use direct API calls if you have API credentials
    3. Use Selenium/Playwright for platforms without accessible APIs

    The function must return a list of property dicts with at least:
      - id: unique property identifier
      - assetName (or equivalent): human-readable name
      - address, city, state: for fuzzy matching
    """
    # Example: Lofty webpack injection
    try:
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
          webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]]);
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
    except ImportError:
        print("WARNING: Lofty CDP modules not available. Using empty property list.", file=sys.stderr)
        return []


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

    # Fetch live properties from PM platform
    pm_properties = fetch_pm_properties(year=year, month=month)
    live_count = len(pm_properties)

    # Scan local corpus
    corpus_dirs = find_corpus_dirs()
    corpus_count = len(corpus_dirs)

    # Fuzzy-match
    matched = match_properties(pm_properties, corpus_dirs)

    # Separate matched from unresolved
    properties = []
    unresolved = []
    for entry in matched:
        if entry.pop("unresolved", False):
            unresolved.append(entry)
        else:
            properties.append(entry)

    # Template-ify paths
    for entry in properties + unresolved:
        for key in ("description_md", "updates_md"):
            if entry.get(key):
                entry[key] = template_path(entry[key]) or entry[key]

    output = {
        "properties": properties,
        "unresolved": unresolved,
        "metadata": {
            "pm_platform": PM_CONFIG["name"],
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
        "pm_platform": PM_CONFIG["name"],
        "live_properties": live_count,
        "corpus_dirs": corpus_count,
        "resolved": len(properties),
        "unresolved": len(unresolved),
        "written": not dry_run,
    }


def main():
    ap = argparse.ArgumentParser(description="Generic PM fuzzy matcher — rebuild property_update_map.json")
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