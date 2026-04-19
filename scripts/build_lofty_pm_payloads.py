#!/usr/bin/env python3
import argparse, json, os, sys, tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from update_lofty_pm_property import capture_fresh, build_headers, validate_auth, request

ENDPOINT = 'https://api.lofty.ai/prod/property-managers/v2/get-manager-properties'


def load_json(path):
    return json.loads(Path(path).read_text())


def find_property(data, property_id=None, key=None):
    props = (((data or {}).get('data') or {}).get('properties') or [])
    if property_id:
        for p in props:
            if p.get('id') == property_id:
                return p
    if key:
        kl = key.lower()
        for p in props:
            vals = [p.get('id',''), p.get('assetUnit',''), p.get('address',''), p.get('address_line1',''), p.get('assetName','')]
            if any(kl == str(v).lower() or kl in str(v).lower() for v in vals if v):
                return p
    raise SystemExit(f'Property not found in get-manager-properties response: property_id={property_id!r} key={key!r}')


def main():
    ap = argparse.ArgumentParser(description='Build/update Lofty PM save/send payload files from live get-manager-properties data')
    ap.add_argument('--property-id')
    ap.add_argument('--property')
    ap.add_argument('--get-manager-properties-payload-file', required=True)
    ap.add_argument('--save-payload-file', required=True)
    ap.add_argument('--send-payload-file', required=True)
    ap.add_argument('--year', type=int)
    ap.add_argument('--month', type=int)
    ap.add_argument('--close-extra-tabs', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    gmp_payload = load_json(args.get_manager_properties_payload_file)
    if args.year is not None:
        gmp_payload['year'] = str(args.year)
    if args.month is not None:
        gmp_payload['month'] = str(args.month)

    if args.dry_run:
        save_payload = {'propertyId': args.property_id or 'DRY_RUN_PROPERTY_ID', 'patch': {'id': args.property_id or 'DRY_RUN_PROPERTY_ID', 'updates': 'DRY_RUN'}}
        send_payload = {'propertyId': args.property_id or 'DRY_RUN_PROPERTY_ID', 'updatesDiff': 'DRY_RUN'}
        Path(args.save_payload_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.send_payload_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save_payload_file).write_text(json.dumps(save_payload, indent=2))
        Path(args.send_payload_file).write_text(json.dumps(send_payload, indent=2))
        out = {
            'property_id': args.property_id,
            'property': args.property,
            'save_payload_file': args.save_payload_file,
            'send_payload_file': args.send_payload_file,
            'gmp_payload': gmp_payload,
            'mode': 'dry-run-bootstrap'
        }
        print(json.dumps(out, indent=2))
        return

    fresh = capture_fresh('get-manager-properties', property_id=args.property_id, close_extra_tabs=args.close_extra_tabs, payload=gmp_payload)
    headers = build_headers(fresh)
    validate_auth(headers)
    resp = request('GET', ENDPOINT, headers, gmp_payload)
    if not resp.ok:
        raise SystemExit(f'get-manager-properties failed: {resp.status_code} {resp.text[:1000]}')
    data = resp.json()
    prop = find_property(data, property_id=args.property_id, key=args.property)
    pid = prop['id']

    save_payload = {'propertyId': pid, 'patch': prop}
    send_payload = {'propertyId': pid, 'updatesDiff': prop.get('updates', '') or ''}

    Path(args.save_payload_file).parent.mkdir(parents=True, exist_ok=True)
    Path(args.send_payload_file).parent.mkdir(parents=True, exist_ok=True)
    Path(args.save_payload_file).write_text(json.dumps(save_payload, indent=2))
    Path(args.send_payload_file).write_text(json.dumps(send_payload, indent=2))
    print(json.dumps({
        'property_id': pid,
        'property_name': prop.get('address') or prop.get('assetName'),
        'save_payload_file': args.save_payload_file,
        'send_payload_file': args.send_payload_file,
        'updates_len': len(send_payload['updatesDiff']),
    }, indent=2))


if __name__ == '__main__':
    main()
