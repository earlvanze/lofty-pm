#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

TARGETS = {
    'get-manager-properties': '/prod/property-managers/v2/get-manager-properties',
    'update-manager-property': '/prod/property-managers/v2/update-manager-property',
    'send-property-updates': '/prod/property-managers/v2/send-property-updates',
}

KEEP_HEADERS = {
    'authorization',
    'x-amz-date',
    'x-amz-security-token',
    'x-lofty-app-version',
    'content-type',
    'origin',
    'referer',
    'user-agent',
}


def main():
    ap = argparse.ArgumentParser(description='Extract Lofty PM requests from a HAR file.')
    ap.add_argument('har')
    ap.add_argument('--out-dir', default='.')
    args = ap.parse_args()

    har_path = Path(args.har)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(har_path.read_text())
    entries = data.get('log', {}).get('entries', [])
    found = []

    for entry in entries:
        req = entry.get('request', {})
        url = req.get('url', '')
        method = req.get('method', '')
        kind = None
        for k, target in TARGETS.items():
            if target in url:
                kind = k
                break
        if not kind:
            continue

        if method == 'POST':
            raw_body = (req.get('postData') or {}).get('text') or ''
            if not raw_body:
                continue
            body = json.loads(raw_body)
            property_id = body.get('propertyId') or body.get('patch', {}).get('id') or 'manager'
        elif method == 'GET' and kind == 'get-manager-properties':
            qs = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
            body = qs
            property_id = 'manager'
        else:
            continue

        headers = {}
        for h in req.get('headers', []):
            name = h.get('name', '').lower()
            if name in KEEP_HEADERS:
                headers[name] = h.get('value', '')

        safe_id = ''.join(c for c in property_id if c.isalnum() or c in ('-', '_'))
        payload_path = out_dir / f'{safe_id}.{kind}.payload.json'
        headers_path = out_dir / f'{safe_id}.{kind}.headers.json'
        payload_path.write_text(json.dumps(body, indent=2))
        headers_path.write_text(json.dumps(headers, indent=2))
        found.append({
            'kind': kind,
            'method': method,
            'propertyId': property_id,
            'endpoint': url,
            'savedPayload': str(payload_path),
            'savedHeaders': str(headers_path),
            'headerKeys': sorted(headers.keys()),
            'bodyKeys': sorted(body.keys()) if isinstance(body, dict) else None,
        })

    if not found:
        raise SystemExit('No supported Lofty PM requests found in HAR')
    print(json.dumps(found, indent=2))


if __name__ == '__main__':
    main()
