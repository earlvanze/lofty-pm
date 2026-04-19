#!/usr/bin/env python3
"""
Extract property details and financial data from Lofty owner pages.

Saves:
- DETAILS.md → Public folder root
- FINANCIALS.md → Public/Financials folder

Usage:
  # Batch mode (all properties in map)
  python extract_lofty_property_data.py --batch --property-map <json_path>
  
  # Single property
  python extract_lofty_property_data.py --property-id <id> --output-dir <path>

Fields extracted:
DETAILS.md:
- Address, legal description, property specs
- Leasing/occupancy status, rent roll
- Property manager info

FINANCIALS.md:
- Purchase price, date, closing costs
- Tax assessment history
- Insurance details
- Operating expenses (if available)
- Income data (rent, other income)
- Cash flow metrics (if available)
"""

import argparse
import json
import os
import sys
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from lofty_pm_paths import load_property_map

SCRIPT_DIR = Path(__file__).resolve().parent
CAPTURE = SCRIPT_DIR / 'capture_lofty_auth_via_cdp.py'

DEFAULT_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'content-type': 'application/json; charset=UTF-8',
    'origin': 'https://www.lofty.ai',
    'referer': 'https://www.lofty.ai/',
    'user-agent': 'Mozilla/5.0 OpenClaw Lofty PM Skill'
}

ENV_HEADER_MAP = {
    'authorization': 'LOFTY_PM_AUTHORIZATION',
    'x-amz-date': 'LOFTY_PM_AMZ_DATE',
    'x-amz-security-token': 'LOFTY_PM_AMZ_SECURITY_TOKEN',
    'x-lofty-app-version': 'LOFTY_PM_APP_VERSION'
}

def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def build_headers(seed_headers=None):
    headers = dict(DEFAULT_HEADERS)
    if seed_headers:
        for k, v in seed_headers.items():
            if v:
                headers[k.lower()] = v
    for hk, envk in ENV_HEADER_MAP.items():
        if os.environ.get(envk):
            headers[hk] = os.environ[envk]
    return headers

def capture_fresh_auth(property_id, close_extra_tabs=False):
    """Capture fresh auth headers via CDP"""
    fd, outp = tempfile.mkstemp(prefix='lofty-details-', suffix='.headers.json')
    os.close(fd)
    
    cmd = [
        sys.executable, str(CAPTURE),
        '--endpoint-kind', 'get-manager-properties',
        '--out-file', outp,
        '--property-id', property_id
    ]
    
    if close_extra_tabs:
        cmd.append('--close-extra-tabs')
    
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    content = Path(outp).read_text().strip()
    
    if not content:
        raise RuntimeError(f'Fresh auth capture produced empty headers. stdout={result.stdout[:500]!r}')
    
    return json.loads(content)

def get_property_details(property_id, headers):
    """Fetch property details from Lofty API"""
    import requests
    
    endpoint = 'https://api.lofty.ai/prod/property-managers/v2/get-manager-properties'
    
    payload = {
        'propertyId': property_id,
        'limit': 1
    }
    
    response = requests.get(endpoint, headers=headers, params=payload, timeout=60)
    
    if response.status_code != 200:
        raise RuntimeError(f'API request failed: {response.status_code} - {response.text[:500]}')
    
    data = response.json()
    properties = ((data.get('data') or {}).get('properties') or data.get('properties') or [])
    
    if not properties:
        raise RuntimeError(f'No property found for ID {property_id}')
    
    return properties[0]

def format_details_md(details, property_id):
    """Format property details as Markdown"""
    lines = []
    
    lines.append("# Property Details")
    lines.append("")
    lines.append(f"**Lofty Property ID:** `{property_id}`")
    lines.append(f"**Extracted:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    
    # Basic Info
    lines.append("## Basic Information")
    lines.append("")
    
    if details.get('address'):
        addr = details['address']
        lines.append(f"- **Address:** {addr.get('streetAddress', '')} {addr.get('city', '')}, {addr.get('state', '')} {addr.get('zipCode', '')}")
        if addr.get('county'):
            lines.append(f"- **County:** {addr['county']}")
        if addr.get('legalDescription'):
            lines.append(f"- **Legal Description:** {addr['legalDescription']}")
    
    if details.get('propertyType'):
        lines.append(f"- **Property Type:** {details['propertyType']}")
    
    if details.get('yearBuilt'):
        lines.append(f"- **Year Built:** {details['yearBuilt']}")
    
    lines.append("")
    
    # Property Specs
    lines.append("## Property Specifications")
    lines.append("")
    
    if details.get('units'):
        lines.append(f"- **Units:** {details['units']}")
    if details.get('bedrooms') is not None:
        lines.append(f"- **Bedrooms:** {details['bedrooms']}")
    if details.get('bathrooms') is not None:
        lines.append(f"- **Bathrooms:** {details['bathrooms']}")
    if details.get('squareFeet'):
        lines.append(f"- **Square Feet:** {details['squareFeet']:,}")
    if details.get('lotSize'):
        lines.append(f"- **Lot Size:** {details['lotSize']}")
    
    lines.append("")
    
    # Leasing/Occupancy Status
    lines.append("## Leasing & Occupancy")
    lines.append("")
    
    if details.get('occupancyStatus'):
        lines.append(f"- **Occupancy Status:** {details['occupancyStatus']}")
    if details.get('leasingStatus'):
        lines.append(f"- **Leasing Status:** {details['leasingStatus']}")
    if details.get('lease_begins_date') or details.get('currentLeaseDate'):
        lbd = details.get('lease_begins_date') or details.get('currentLeaseDate', '')
        lines.append(f"- **Lease Begins Date:** {lbd}")
    if details.get('currentRent'):
        lines.append(f"- **Current Rent:** ${details['currentRent']:,.2f}/month")
    if details.get('marketRent'):
        lines.append(f"- **Market Rent:** ${details['marketRent']:,.2f}/month")
    
    if details.get('rentRoll'):
        lines.append("")
        lines.append("### Rent Roll Summary")
        lines.append("")
        rent_roll = details['rentRoll']
        if isinstance(rent_roll, dict):
            for key, value in rent_roll.items():
                lines.append(f"- **{key}:** {value}")
        elif isinstance(rent_roll, list):
            for unit in rent_roll:
                if isinstance(unit, dict):
                    unit_str = f"Unit {unit.get('unit', 'N/A')}"
                    if unit.get('rent'):
                        unit_str += f": ${unit['rent']:,.2f}/month"
                    if unit.get('status'):
                        unit_str += f" ({unit['status']})"
                    lines.append(f"- {unit_str}")
    
    lines.append("")
    
    # Property Manager
    lines.append("## Property Management")
    lines.append("")
    
    if details.get('propertyManager'):
        pm = details['propertyManager']
        if isinstance(pm, dict):
            if pm.get('name'):
                lines.append(f"- **Manager:** {pm['name']}")
            if pm.get('company'):
                lines.append(f"- **Company:** {pm['company']}")
            if pm.get('email'):
                lines.append(f"- **Email:** {pm['email']}")
            if pm.get('phone'):
                lines.append(f"- **Phone:** {pm['phone']}")
        else:
            lines.append(f"- **Manager:** {pm}")
    
    if details.get('managementType'):
        lines.append(f"- **Management Type:** {details['managementType']}")
    
    lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("*Auto-generated from Lofty.ai property data.*")
    lines.append("*Sync with Hemlane/Aligned rent rolls for leasing status updates.*")
    
    return '\n'.join(lines)

def format_financials_md(details, property_id):
    """Format financial data as Markdown"""
    lines = []
    
    lines.append("# Financial Data")
    lines.append("")
    lines.append(f"**Lofty Property ID:** `{property_id}`")
    lines.append(f"**Extracted:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    
    # Purchase Info
    lines.append("## Purchase Information")
    lines.append("")
    
    if details.get('purchasePrice'):
        lines.append(f"- **Purchase Price:** ${details['purchasePrice']:,.2f}")
    if details.get('purchaseDate'):
        lines.append(f"- **Purchase Date:** {details['purchaseDate']}")
    if details.get('closingCosts'):
        lines.append(f"- **Closing Costs:** ${details['closingCosts']:,.2f}")
    if details.get('acquisitionFees'):
        lines.append(f"- **Acquisition Fees:** ${details['acquisitionFees']:,.2f}")
    
    lines.append("")
    
    # Tax Assessment
    lines.append("## Tax Assessment")
    lines.append("")
    
    if details.get('taxAssessment'):
        assessment = details['taxAssessment']
        if isinstance(assessment, dict):
            if assessment.get('year'):
                lines.append(f"- **Assessment Year:** {assessment['year']}")
            if assessment.get('value'):
                lines.append(f"- **Assessed Value:** ${assessment['value']:,.2f}")
            if assessment.get('landValue'):
                lines.append(f"- **Land Value:** ${assessment['landValue']:,.2f}")
            if assessment.get('improvementValue'):
                lines.append(f"- **Improvement Value:** ${assessment['improvementValue']:,.2f}")
        else:
            lines.append(f"- **Assessed Value:** ${assessment:,.2f}")
    
    if details.get('annualTaxes'):
        lines.append(f"- **Annual Taxes:** ${details['annualTaxes']:,.2f}")
    
    lines.append("")
    
    # Insurance
    lines.append("## Insurance")
    lines.append("")
    
    if details.get('insurance'):
        insurance = details['insurance']
        if isinstance(insurance, dict):
            if insurance.get('annualPremium'):
                lines.append(f"- **Annual Premium:** ${insurance['annualPremium']:,.2f}")
            if insurance.get('carrier'):
                lines.append(f"- **Carrier:** {insurance['carrier']}")
            if insurance.get('policyNumber'):
                lines.append(f"- **Policy Number:** {insurance['policyNumber']}")
            if insurance.get('coverageAmount'):
                lines.append(f"- **Coverage Amount:** ${insurance['coverageAmount']:,.2f}")
        else:
            lines.append(f"- **Annual Premium:** ${insurance:,.2f}")
    
    lines.append("")
    
    # Income Data
    lines.append("## Income")
    lines.append("")
    
    if details.get('currentRent'):
        lines.append(f"- **Current Rent:** ${details['currentRent']:,.2f}/month")
    if details.get('marketRent'):
        lines.append(f"- **Market Rent:** ${details['marketRent']:,.2f}/month")
    if details.get('otherIncome'):
        other = details['otherIncome']
        if isinstance(other, dict):
            for key, value in other.items():
                lines.append(f"- **{key}:** ${value:,.2f}/month")
        else:
            lines.append(f"- **Other Income:** ${other:,.2f}/month")
    if details.get('grossScheduledIncome'):
        lines.append(f"- **Gross Scheduled Income:** ${details['grossScheduledIncome']:,.2f}/year")
    if details.get('grossOperatingIncome'):
        lines.append(f"- **Gross Operating Income:** ${details['grossOperatingIncome']:,.2f}/year")
    
    lines.append("")
    
    # Operating Expenses
    lines.append("## Operating Expenses")
    lines.append("")
    
    if details.get('operatingExpenses'):
        expenses = details['operatingExpenses']
        if isinstance(expenses, dict):
            for key, value in expenses.items():
                if value:
                    lines.append(f"- **{key}:** ${value:,.2f}/year")
        elif isinstance(expenses, list):
            for expense in expenses:
                if isinstance(expense, dict):
                    name = expense.get('category', expense.get('name', 'Unknown'))
                    amount = expense.get('amount', 0)
                    lines.append(f"- **{name}:** ${amount:,.2f}/year")
    
    if details.get('totalOperatingExpenses'):
        lines.append(f"- **Total Operating Expenses:** ${details['totalOperatingExpenses']:,.2f}/year")
    
    lines.append("")
    
    # Cash Flow Metrics
    lines.append("## Cash Flow Metrics")
    lines.append("")
    
    if details.get('netOperatingIncome'):
        lines.append(f"- **Net Operating Income (NOI):** ${details['netOperatingIncome']:,.2f}/year")
    if details.get('cashFlow'):
        lines.append(f"- **Cash Flow:** ${details['cashFlow']:,.2f}/month")
    if details.get('cashOnCashReturn'):
        lines.append(f"- **Cash-on-Cash Return:** {details['cashOnCashReturn']:.2f}%")
    if details.get('capRate'):
        lines.append(f"- **Cap Rate:** {details['capRate']:.2f}%")
    
    lines.append("")
    
    # Valuation
    if details.get('valuation'):
        lines.append("## Valuation")
        lines.append("")
        valuation = details['valuation']
        if isinstance(valuation, dict):
            if valuation.get('currentValue'):
                lines.append(f"- **Current Value:** ${valuation['currentValue']:,.2f}")
            if valuation.get('valuationDate'):
                lines.append(f"- **Valuation Date:** {valuation['valuationDate']}")
            if valuation.get('source'):
                lines.append(f"- **Source:** {valuation['source']}")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("*Auto-generated from Lofty.ai financial data.*")
    lines.append("*Sync with Baselane/Hemlane for actuals reconciliation.*")
    
    return '\n'.join(lines)

def main():
    ap = argparse.ArgumentParser(description='Extract Lofty property data to DETAILS.md and FINANCIALS.md')
    ap.add_argument('--property-id')
    ap.add_argument('--output-dir')
    ap.add_argument('--close-extra-tabs', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--batch', action='store_true')
    ap.add_argument('--property-map')
    args = ap.parse_args()
    
    if args.batch:
        if not args.property_map:
            print("ERROR: --property-map required for batch mode")
            return 1
        
        property_list = load_property_map(args.property_map)
        props = property_list.get('properties', []) if isinstance(property_list, dict) else property_list
        
        print(f"Processing {len(props)} properties in batch mode...")
        
        success = 0
        failed = 0
        
        for prop in props:
            prop_id = prop.get('lofty_property_id')
            updates_md = prop.get('updates_md', '')
            
            if not prop_id:
                print(f"  SKIP: No lofty_property_id for {prop.get('property_name', 'unknown')}")
                failed += 1
                continue
            
            if updates_md:
                updates_dir = Path(updates_md).parent
                public_dir = updates_dir.parent
                details_md = public_dir / 'DETAILS.md'
                financials_dir = public_dir / 'Financials'
                financials_md = financials_dir / 'FINANCIALS.md'
            else:
                print(f"  SKIP: No updates_md path for {prop.get('property_name', 'unknown')}")
                failed += 1
                continue
            
            print(f"  Processing: {prop.get('property_name', prop_id)}")
            
            try:
                headers = capture_fresh_auth(prop_id, args.close_extra_tabs)
                details = get_property_details(prop_id, headers)
                
                # Write DETAILS.md
                details_content = format_details_md(details, prop_id)
                if not args.dry_run:
                    details_md.parent.mkdir(parents=True, exist_ok=True)
                    details_md.write_text(details_content, encoding='utf-8')
                    print(f"    ✓ Saved: {details_md}")
                else:
                    print(f"    [DRY-RUN] Would save: {details_md}")
                
                # Write FINANCIALS.md
                financials_content = format_financials_md(details, prop_id)
                if not args.dry_run:
                    financials_dir.mkdir(parents=True, exist_ok=True)
                    financials_md.write_text(financials_content, encoding='utf-8')
                    print(f"    ✓ Saved: {financials_md}")
                else:
                    print(f"    [DRY-RUN] Would save: {financials_md}")
                
                success += 1
            except Exception as e:
                print(f"    ✗ Failed: {e}")
                failed += 1
        
        print(f"\nBatch complete: {success} succeeded, {failed} failed")
        return 0 if failed == 0 else 1
    
    # Single property mode
    if not args.property_id or not args.output_dir:
        print("ERROR: --property-id and --output-dir required for single property mode")
        return 1
    
    print(f"Extracting data for property {args.property_id}...")
    
    try:
        headers = capture_fresh_auth(args.property_id, args.close_extra_tabs)
        details = get_property_details(args.property_id, headers)
        
        output_dir = Path(args.output_dir)
        details_md = output_dir / 'DETAILS.md'
        financials_dir = output_dir / 'Financials'
        financials_md = financials_dir / 'FINANCIALS.md'
        
        if args.dry_run:
            print(f"[DRY-RUN] Would save to: {details_md} and {financials_md}")
        else:
            details_md.write_text(format_details_md(details, args.property_id), encoding='utf-8')
            print(f"✓ Saved: {details_md}")
            
            financials_dir.mkdir(parents=True, exist_ok=True)
            financials_md.write_text(format_financials_md(details, args.property_id), encoding='utf-8')
            print(f"✓ Saved: {financials_md}")
        
        return 0
    except Exception as e:
        print(f"✗ Failed: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
