#!/usr/bin/env python3
"""
Push local property data (DETAILS.md / FINANCIALS.md) back to Lofty.

Reads structured markdown files, extracts fields, and builds a patch dict
compatible with the update-manager-property mutation.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import sys
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lofty_pm_paths import load_property_map, REAL_ESTATE_ROOT, resolve_path
from read_write_description_md import find_description_md


def find_details_md(
    property_query: str | None = None,
    property_id: str | None = None,
    property_map: str | None = None,
) -> Path | None:
    """Locate DETAILS.md for a property."""
    # Try via the map — description_md is usually in Public/, DETAILS.md is also there
    desc_path = find_description_md(
        property_query=property_id or property_query,
        property_map=property_map,
    )
    if desc_path:
        public_dir = desc_path.parent
        details = public_dir / "DETAILS.md"
        if details.is_file():
            return details
        # Maybe one level up
        details = public_dir.parent / "Public" / "DETAILS.md"
        if details.is_file():
            return details

    # Fallback: filesystem search
    if property_query and REAL_ESTATE_ROOT.is_dir():
        q = property_query.lower()
        for state_dir in sorted(REAL_ESTATE_ROOT.iterdir()):
            if not state_dir.is_dir():
                continue
            for prop_dir in sorted(state_dir.iterdir()):
                if q in prop_dir.name.lower():
                    for candidate in [
                        prop_dir / "Public" / "DETAILS.md",
                        prop_dir / "DETAILS.md",
                    ]:
                        if candidate.is_file():
                            return candidate
    return None


def find_financials_md(
    property_query: str | None = None,
    property_id: str | None = None,
    property_map: str | None = None,
) -> Path | None:
    """Locate FINANCIALS.md for a property."""
    desc_path = find_description_md(
        property_query=property_id or property_query,
        property_map=property_map,
    )
    if desc_path:
        public_dir = desc_path.parent
        financials = public_dir / "Financials" / "FINANCIALS.md"
        if financials.is_file():
            return financials
        financials = public_dir / "FINANCIALS.md"
        if financials.is_file():
            return financials
    return None


def _parse_money(value: str) -> float | None:
    """Parse a dollar value like '$1,850.00/month' or '$297,415'."""
    m = re.search(r'\$([0-9,]+(?:\.[0-9]+)?)', value)
    if m:
        return float(m.group(1).replace(',', ''))
    return None


def _parse_int(value: str) -> int | None:
    m = re.search(r'(\d+)', value)
    return int(m.group(1)) if m else None


def _parse_float(value: str) -> float | None:
    m = re.search(r'([0-9,]+(?:\.[0-9]+)?)', value)
    return float(m.group(1).replace(',', '')) if m else None


def parse_details_md(content: str) -> dict[str, Any]:
    """Parse DETAILS.md back into structured fields."""
    result: dict[str, Any] = {}

    # Extract sections
    sections: dict[str, str] = {}
    current_section = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        m = re.match(r"^## (.+)$", line)
        if m:
            if current_section:
                sections[current_section] = "\n".join(current_lines)
            current_section = m.group(1).strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines)

    # Basic Information
    basic = sections.get("Basic Information", "")
    for line in basic.split("\n"):
        if "**Address:**" in line:
            result["address"] = line.split("**Address:**", 1)[1].strip()
        elif "**County:**" in line:
            result["county"] = line.split("**County:**", 1)[1].strip()
        elif "**Legal Description:**" in line:
            result["legalDescription"] = line.split("**Legal Description:**", 1)[1].strip()
        elif "**Property Type:**" in line:
            result["propertyType"] = line.split("**Property Type:**", 1)[1].strip()
        elif "**Year Built:**" in line:
            result["yearBuilt"] = _parse_int(line.split("**Year Built:**", 1)[1].strip())

    # Property Specifications
    specs = sections.get("Property Specifications", "")
    for line in specs.split("\n"):
        if "**Units:**" in line:
            result["units"] = _parse_int(line.split("**Units:**", 1)[1].strip())
        elif "**Bedrooms:**" in line:
            result["bedrooms"] = _parse_int(line.split("**Bedrooms:**", 1)[1].strip())
        elif "**Bathrooms:**" in line:
            result["bathrooms"] = _parse_int(line.split("**Bathrooms:**", 1)[1].strip())
        elif "**Square Feet:**" in line:
            result["squareFeet"] = _parse_int(line.split("**Square Feet:**", 1)[1].strip())
        elif "**Lot Size:**" in line:
            result["lotSize"] = line.split("**Lot Size:**", 1)[1].strip()

    # Leasing & Occupancy
    leasing = sections.get("Leasing & Occupancy", "")
    for line in leasing.split("\n"):
        if "**Occupancy Status:**" in line:
            result["occupancyStatus"] = line.split("**Occupancy Status:**", 1)[1].strip()
        elif "**Leasing Status:**" in line:
            result["leasingStatus"] = line.split("**Leasing Status:**", 1)[1].strip()
        elif "**Current Rent:**" in line:
            result["currentRent"] = _parse_money(line)
        elif "**Market Rent:**" in line:
            result["marketRent"] = _parse_money(line)

    # Property Management
    mgmt = sections.get("Property Management", "")
    pm: dict[str, str] = {}
    for line in mgmt.split("\n"):
        if "**Manager:**" in line:
            pm["name"] = line.split("**Manager:**", 1)[1].strip()
        elif "**Company:**" in line:
            pm["company"] = line.split("**Company:**", 1)[1].strip()
        elif "**Email:**" in line:
            pm["email"] = line.split("**Email:**", 1)[1].strip()
        elif "**Phone:**" in line:
            pm["phone"] = line.split("**Phone:**", 1)[1].strip()
        elif "**Management Type:**" in line:
            result["managementType"] = line.split("**Management Type:**", 1)[1].strip()
    if pm:
        result["propertyManager"] = pm

    return result


def parse_financials_md(content: str) -> dict[str, Any]:
    """Parse FINANCIALS.md back into structured fields."""
    result: dict[str, Any] = {}

    sections: dict[str, str] = {}
    current_section = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        m = re.match(r"^## (.+)$", line)
        if m:
            if current_section:
                sections[current_section] = "\n".join(current_lines)
            current_section = m.group(1).strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines)

    # Purchase Information
    purchase = sections.get("Purchase Information", "")
    for line in purchase.split("\n"):
        if "**Purchase Price:**" in line:
            result["purchasePrice"] = _parse_money(line)
        elif "**Purchase Date:**" in line:
            result["purchaseDate"] = line.split("**Purchase Date:**", 1)[1].strip()
        elif "**Closing Costs:**" in line:
            result["closingCosts"] = _parse_money(line)
        elif "**Acquisition Fees:**" in line:
            result["acquisitionFees"] = _parse_money(line)

    # Tax Assessment
    tax = sections.get("Tax Assessment", "")
    assessment: dict[str, Any] = {}
    for line in tax.split("\n"):
        if "**Assessment Year:**" in line:
            assessment["year"] = _parse_int(line.split("**Assessment Year:**", 1)[1].strip())
        elif "**Assessed Value:**" in line:
            assessment["value"] = _parse_money(line)
        elif "**Land Value:**" in line:
            assessment["landValue"] = _parse_money(line)
        elif "**Improvement Value:**" in line:
            assessment["improvementValue"] = _parse_money(line)
        elif "**Annual Taxes:**" in line:
            result["annualTaxes"] = _parse_money(line)
    if assessment:
        result["taxAssessment"] = assessment

    # Insurance
    ins = sections.get("Insurance", "")
    insurance: dict[str, Any] = {}
    for line in ins.split("\n"):
        if "**Annual Premium:**" in line:
            insurance["annualPremium"] = _parse_money(line)
        elif "**Carrier:**" in line:
            insurance["carrier"] = line.split("**Carrier:**", 1)[1].strip()
        elif "**Policy Number:**" in line:
            insurance["policyNumber"] = line.split("**Policy Number:**", 1)[1].strip()
        elif "**Coverage Amount:**" in line:
            insurance["coverageAmount"] = _parse_money(line)
    if insurance:
        result["insurance"] = insurance

    # Income
    income_sec = sections.get("Income", "")
    for line in income_sec.split("\n"):
        if "**Current Rent:**" in line:
            result["currentRent"] = _parse_money(line)
        elif "**Market Rent:**" in line:
            result["marketRent"] = _parse_money(line)
        elif "**Gross Scheduled Income:**" in line:
            result["grossScheduledIncome"] = _parse_money(line)
        elif "**Gross Operating Income:**" in line:
            result["grossOperatingIncome"] = _parse_money(line)

    # Operating Expenses
    exp_sec = sections.get("Operating Expenses", "")
    expenses: dict[str, float] = {}
    for line in exp_sec.split("\n"):
        m = re.match(r"^- \*\*(.+?)\*\*:\s*(.*)", line)
        if m:
            key, val = m.group(1), m.group(2)
            if key != "Total Operating Expenses":
                parsed = _parse_money(val)
                if parsed is not None:
                    expenses[key] = parsed
        elif "**Total Operating Expenses:**" in line:
            result["totalOperatingExpenses"] = _parse_money(line)
    if expenses:
        result["operatingExpenses"] = expenses

    # Cash Flow
    cf_sec = sections.get("Cash Flow", "")
    for line in cf_sec.split("\n"):
        if "**NOI:**" in line or "**Net Operating Income:**" in line:
            result["noi"] = _parse_money(line)
        elif "**Cap Rate:**" in line:
            m2 = re.search(r'([\d.]+)%?', line)
            result["capRate"] = float(m2.group(1)) if m2 else None
        elif "**Cash Flow:**" in line:
            result["cashFlow"] = _parse_money(line)

    return result


def build_patch_from_local(
    property_query: str | None = None,
    property_id: str | None = None,
    property_map: str | None = None,
    include_details: bool = True,
    include_financials: bool = True,
) -> dict[str, Any]:
    """Read local DETAILS.md / FINANCIALS.md and build a Lofty update patch."""
    patch: dict[str, Any] = {}
    sources: list[str] = []

    if include_details:
        details_path = find_details_md(
            property_query=property_id or property_query,
            property_id=property_id,
            property_map=property_map,
        )
        if details_path and details_path.is_file():
            content = details_path.read_text(encoding="utf-8", errors="ignore")
            details = parse_details_md(content)
            if details:
                patch.update(details)
                sources.append(f"DETAILS.md ({len(details)} fields)")
        else:
            sources.append("DETAILS.md (not found)")

    if include_financials:
        financials_path = find_financials_md(
            property_query=property_id or property_query,
            property_id=property_id,
            property_map=property_map,
        )
        if financials_path and financials_path.is_file():
            content = financials_path.read_text(encoding="utf-8", errors="ignore")
            financials = parse_financials_md(content)
            if financials:
                # Merge financials — don't overwrite details fields unless financials-only
                for k, v in financials.items():
                    if k not in patch or k in ("currentRent", "marketRent"):
                        patch[k] = v
                sources.append(f"FINANCIALS.md ({len(financials)} fields)")
        else:
            sources.append("FINANCIALS.md (not found)")

    return {
        "patch": patch,
        "sources": sources,
        "field_count": len(patch),
        "fields": sorted(patch.keys()),
    }


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Push local property data to Lofty")
    ap.add_argument("--property", required=True)
    ap.add_argument("--property-map")
    ap.add_argument("--details-only", action="store_true")
    ap.add_argument("--financials-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = build_patch_from_local(
        property_query=args.property,
        property_map=args.property_map,
        include_details=not args.financials_only,
        include_financials=not args.details_only,
    )
    print(json.dumps(result, indent=2, default=str))