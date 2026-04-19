#!/usr/bin/env python3
"""
Read and write DESCRIPTION.md files for Lofty properties.

DESCRIPTION.md has a canonical structure:
  - Opening line (bold summary)
  - ## Offering Details
  - ## Property Details
  - ## Property Management and Insurance
  - ## Property Leverage
  - ## Occupancy Status
  - ## Location Data
  - ## Due Diligence Documents

This module provides:
- read_description_md: parse into sections + raw content
- write_description_md: full replace or section-level merge
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import sys
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lofty_pm_paths import load_property_map, REAL_ESTATE_ROOT, WORKSPACE_ROOT, resolve_path


SECTION_PATTERN = re.compile(r"^## (.+)$", re.MULTILINE)
OPTIONAL_SECTIONS = {
    "Property Leverage",
    "Location Data",
    "Due Diligence Documents",
    "Occupancy Status",
}


def find_description_md(
    property_query: str | None = None,
    property_map: str | None = None,
) -> Path | None:
    """Locate DESCRIPTION.md for a property from the map or by filesystem search."""
    if property_query and property_map:
        props = load_property_map(Path(property_map))
        candidates = props if isinstance(props, list) else props.get("properties", [])
        for p in candidates:
            name = p.get("property_name", "")
            addr = p.get("full_address", "")
            pid = p.get("lofty_property_id", "")
            if (property_query.lower() in name.lower()
                    or property_query.lower() in addr.lower()
                    or property_query == pid):
                desc = p.get("description_md") or p.get("description_path")
                if desc:
                    return Path(resolve_path(desc))
    # Fallback: search Real Estate corpus
    if property_query and REAL_ESTATE_ROOT.is_dir():
        q = property_query.lower()
        for state_dir in sorted(REAL_ESTATE_ROOT.iterdir()):
            if not state_dir.is_dir():
                continue
            for prop_dir in sorted(state_dir.iterdir()):
                if q in prop_dir.name.lower():
                    # Check Public/DESCRIPTION.md
                    pub = prop_dir if prop_dir.name == "Public" else prop_dir / "Public"
                    if not pub.is_dir():
                        pub = prop_dir
                    desc = pub / "DESCRIPTION.md"
                    if desc.is_file():
                        return desc
                    # Maybe the dir itself is named "Public"
                    if prop_dir.name.endswith("Public"):
                        desc = prop_dir / "DESCRIPTION.md"
                        if desc.is_file():
                            return desc
    return None


def parse_description_md(content: str) -> dict[str, Any]:
    """Parse DESCRIPTION.md into structured sections."""
    lines = content.split("\n")

    # Extract opening (lines before first ##)
    opening_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        opening_lines.append(line)
    opening = "\n".join(opening_lines).strip()

    # Split into sections
    sections: dict[str, str] = {}
    current_section = None
    current_lines: list[str] = []

    for line in lines:
        m = re.match(r"^## (.+)$", line)
        if m:
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = m.group(1).strip()
            current_lines = []
        elif current_section is not None:
            current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return {
        "opening": opening,
        "sections": sections,
        "section_order": list(sections.keys()),
        "raw": content,
    }


def read_description_md(
    property_query: str | None = None,
    property_id: str | None = None,
    property_map: str | None = None,
) -> dict[str, Any]:
    """Read and parse a property's DESCRIPTION.md."""
    # Try property_map first
    path = find_description_md(
        property_query=property_id or property_query,
        property_map=property_map,
    )

    if path is None or not path.is_file():
        return {
            "found": False,
            "path": str(path) if path else None,
            "error": f"DESCRIPTION.md not found for {property_query!r}",
        }

    content = path.read_text(encoding="utf-8", errors="ignore")
    parsed = parse_description_md(content)

    return {
        "found": True,
        "path": str(path),
        **parsed,
    }


def write_description_md(
    property_query: str | None = None,
    property_id: str | None = None,
    property_map: str | None = None,
    content: str | None = None,
    sections: dict[str, str] | None = None,
    opening: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write or update a property's DESCRIPTION.md.

    Modes:
    - content=... : full replacement
    - sections={...} and/or opening=... : merge into existing (section-level update)
    """
    path = find_description_md(
        property_query=property_id or property_query,
        property_map=property_map,
    )

    if path is None:
        return {
            "found": False,
            "path": None,
            "error": f"DESCRIPTION.md path not found for {property_query!r}",
        }

    # Full replacement mode
    if content is not None:
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return {
            "found": True,
            "path": str(path),
            "mode": "full_replace",
            "dry_run": dry_run,
            "written": not dry_run,
            "content_length": len(content),
        }

    # Section merge mode
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8", errors="ignore")

    parsed = parse_description_md(existing)
    current_sections = parsed["sections"]
    current_opening = parsed["opening"]
    section_order = parsed["section_order"]

    # Apply merges
    new_opening = opening if opening is not None else current_opening
    new_sections = dict(current_sections)
    new_order = list(section_order)

    if sections:
        for sec_name, sec_content in sections.items():
            if sec_name not in new_sections and sec_name not in new_order:
                new_order.append(sec_name)
            new_sections[sec_name] = sec_content

    # Reconstruct
    parts = [new_opening] if new_opening else []
    for sec in new_order:
        if sec in new_sections:
            parts.append(f"\n## {sec}\n{new_sections[sec]}")

    result_content = "\n\n".join(parts) + "\n"

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result_content, encoding="utf-8")

    return {
        "found": True,
        "path": str(path),
        "mode": "section_merge",
        "dry_run": dry_run,
        "written": not dry_run,
        "updated_sections": list(sections.keys()) if sections else [],
        "opening_updated": opening is not None,
        "content_length": len(result_content),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Read/write Lofty property DESCRIPTION.md")
    sub = ap.add_subparsers(dest="command")

    rp = sub.add_parser("read", help="Read and parse DESCRIPTION.md")
    rp.add_argument("--property", required=True)
    rp.add_argument("--property-map")

    wp = sub.add_parser("write", help="Write/update DESCRIPTION.md")
    wp.add_argument("--property", required=True)
    wp.add_argument("--property-map")
    wp.add_argument("--content", help="Full replacement content")
    wp.add_argument("--section", action="append", nargs=2, metavar=("NAME", "CONTENT"), help="Update a single section")
    wp.add_argument("--opening", help="Update the opening line(s)")
    wp.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()

    if args.command == "read":
        result = read_description_md(property_query=args.property, property_map=args.property_map)
    elif args.command == "write":
        sec_dict = {k: v for k, v in args.section} if args.section else None
        result = write_description_md(
            property_query=args.property,
            property_map=args.property_map,
            content=args.content,
            sections=sec_dict,
            opening=args.opening,
            dry_run=args.dry_run,
        )
    else:
        ap.print_help()
        raise SystemExit(1)

    import json
    # Don't dump raw content in output (too large), just metadata
    out = {k: v for k, v in result.items() if k != "raw"}
    print(json.dumps(out, indent=2, ensure_ascii=False))