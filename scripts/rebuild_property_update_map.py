#!/usr/bin/env python3
"""Rebuild property_update_map.json from live Lofty manager properties and the Dropbox Real Estate corpus.

Strategy:
1. Fetch all live properties from Lofty via webpack injection (CDP)
2. Scan the Real Estate corpus for property directories matching DESCRIPTION.md / UPDATES.md
3. Match Lofty properties to corpus directories by address similarity
4. Emit an updated property_update_map.json with resolved paths
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lofty_pm_paths import (
    REAL_ESTATE_ROOT,
    TMP_ROOT,
    WORKSPACE_ROOT,
    LEGACY_WORKSPACE_ROOT,
    template_path,
    load_property_map,
)


MAP_FILE = SCRIPT_DIR.parent / "config" / "property_update_map.json"
SKILL_DIR = SCRIPT_DIR.parent


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace(",", " ").replace(".", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _norm_addr(addr: str) -> str:
    """Normalize address for matching: strip unit/suite, ordinal suffixes."""
    s = _norm(addr)
    s = re.sub(r"\b(apt|unit|suite|ste|#)\s*\S+", "", s)
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", s)
    return " ".join(s.split())


def _find_corpus_dirs() -> list[dict[str, Any]]:
    """Scan Real Estate corpus for property directories with DESCRIPTION.md."""
    results: list[dict[str, Any]] = []
    re_root = REAL_ESTATE_ROOT
    if not re_root.is_dir():
        return results

    for state_dir in sorted(re_root.iterdir()):
        if not state_dir.is_dir() or state_dir.name.startswith(".") or state_dir.name.lower() in ("lofty pm",):
            continue
        for prop_dir in sorted(state_dir.iterdir()):
            if not prop_dir.is_dir() or "Public" not in [d.name for d in prop_dir.iterdir() if d.is_dir()]:
                # Check if this IS the Public dir
                if prop_dir.name.endswith("Public") and prop_dir.parent.is_dir():
                    pub_dir = prop_dir
                    parent_name = pub_dir.parent.name
                else:
                    continue
            else:
                pub_dir = prop_dir / "Public"
                parent_name = prop_dir.name

            # Look for DESCRIPTION.md
            desc = pub_dir / "DESCRIPTION.md"
            updates_dir = pub_dir / "Updates"
            updates_md = updates_dir / "UPDATES.md" if updates_dir.is_dir() else None

            if not desc.is_file():
                continue

            results.append({
                "dir_name": parent_name,
                "public_dir": str(pub_dir),
                "description_md": str(desc),
                "updates_md": str(updates_md) if updates_md and updates_md.is_file() else None,
                "norm_name": _norm(parent_name),
                "norm_addr": _norm_addr(parent_name),
            })
    return results


def _match_properties(
    lofty_props: list[dict[str, Any]],
    corpus_dirs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match Lofty properties to corpus directories."""
    matched = []
    used_corpus = set()

    for lp in lofty_props:
        addr = lp.get("address") or lp.get("assetName") or ""
        city = lp.get("city") or ""
        state = lp.get("state") or ""
        full_addr = f"{addr}, {city} {state}".strip(", ")
        norm_lofty = _norm_addr(full_addr)

        best_score = 0
        best_corpus = None
        best_idx = -1

        for i, cd in enumerate(corpus_dirs):
            if i in used_corpus:
                continue
            # Score based on address overlap
            norm_cd = cd["norm_addr"]
            if norm_cd == norm_lofty:
                score = 100
            elif norm_cd in norm_lofty or norm_lofty in norm_cd:
                # Substring match — score by length of the shorter
                shorter = min(len(norm_cd), len(norm_lofty))
                score = shorter
            else:
                # Word overlap
                cd_words = set(norm_cd.split())
                lofty_words = set(norm_lofty.split())
                overlap = cd_words & lofty_words
                if len(overlap) >= 2:
                    score = len(overlap) * 5
                else:
                    score = 0

            if score > best_score:
                best_score = score
                best_corpus = cd
                best_idx = i

        entry: dict[str, Any] = {
            "lofty_property_id": lp.get("id", ""),
            "property_name": lp.get("assetName") or addr,
            "full_address": full_addr,
            "slug": lp.get("slug", ""),
            "assetUnit": lp.get("assetUnit", ""),
            "state": state,
        }

        if best_corpus and best_score >= 10:
            used_corpus.add(best_idx)
            entry["description_md"] = best_corpus["description_md"]
            if best_corpus.get("updates_md"):
                entry["updates_md"] = best_corpus["updates_md"]

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


def _fetch_live_properties(year: int | None = None, month: int | None = None) -> list[dict[str, Any]]:
    """Fetch live Lofty manager properties via CDP webpack injection."""
    from lofty_cdp import ensure_lofty_cdp_context, get_tabs
    from capture_lofty_auth_via_cdp import connect_ws

    import datetime as dt

    now = dt.datetime.now()
    y = str(year or now.year)
    m = str(month or now.month)

    ctx = ensure_lofty_cdp_context(mode="list")
    tid = ctx["targetId"]

    ws = connect_ws(tid)
    msg_id = 0

    def sr(method, params=None, timeout=30):
        global msg_id
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
        resp = sr(
            "Runtime.evaluate",
            {
                "expression": 'typeof webpackChunklofty_investing_webapp !== "undefined"',
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        if resp.get("result", {}).get("result", {}).get("value") is True:
            break
        time.sleep(2)

    expr = f"""(async () => {{
      let __req;
      webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]);
      const mod = __req(51046);
      const data = await mod.PK({{year: "{y}", month: "{m}"}});
      return JSON.stringify(data?.data?.properties || []);
    }})()"""

    resp = sr(
        "Runtime.evaluate",
        {"expression": expr, "awaitPromise": True, "returnByValue": True, "timeout": 30000},
    )
    ws.close()

    val = resp.get("result", {}).get("result", {}).get("value", "[]")
    return json.loads(val) if isinstance(val, str) else val


def rebuild_map(
    map_file: str | None = None,
    dry_run: bool = True,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    target = Path(map_file) if map_file else MAP_FILE

    # Fetch live properties
    lofty_props = _fetch_live_properties(year=year, month=month)
    live_count = len(lofty_props)

    # Scan corpus
    corpus_dirs = _find_corpus_dirs()
    corpus_count = len(corpus_dirs)

    # Match
    matched = _match_properties(lofty_props, corpus_dirs)

    # Build output
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
        "live_properties": live_count,
        "corpus_dirs": corpus_count,
        "resolved": len(properties),
        "unresolved": len(unresolved),
        "written": not dry_run,
    }


def main():
    ap = argparse.ArgumentParser(description="Rebuild property_update_map.json from live Lofty data and the Real Estate corpus")
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