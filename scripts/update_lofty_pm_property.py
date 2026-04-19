#!/usr/bin/env python3
import argparse, json, os, sys, tempfile, subprocess, time
from pathlib import Path
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from lofty_cdp import ensure_lofty_cdp_context, get_tabs
from capture_lofty_auth_via_cdp import connect_ws
CAPTURE = SCRIPT_DIR / 'capture_lofty_auth_via_cdp.py'
ENDPOINTS = {'get-manager-properties': 'https://api.lofty.ai/prod/property-managers/v2/get-manager-properties', 'update-manager-property': 'https://api.lofty.ai/prod/property-managers/v2/update-manager-property', 'send-property-updates': 'https://api.lofty.ai/prod/property-managers/v2/send-property-updates'}
METHODS = {'get-manager-properties': 'GET', 'update-manager-property': 'POST', 'send-property-updates': 'POST'}
DEFAULT_HEADERS = {'accept': 'application/json, text/plain, */*', 'content-type': 'application/json; charset=UTF-8', 'origin': 'https://www.lofty.ai', 'referer': 'https://www.lofty.ai/', 'user-agent': 'Mozilla/5.0 OpenClaw Lofty PM Skill'}
ENV_HEADER_MAP = {'authorization': 'LOFTY_PM_AUTHORIZATION', 'x-amz-date': 'LOFTY_PM_AMZ_DATE', 'x-amz-security-token': 'LOFTY_PM_AMZ_SECURITY_TOKEN', 'x-lofty-app-version': 'LOFTY_PM_APP_VERSION'}

def load_json(path): return json.loads(Path(path).read_text())
def merge_patch(base, updates):
    if not isinstance(base, dict) or not isinstance(updates, dict): return updates
    out = dict(base)
    for k, v in updates.items(): out[k] = merge_patch(out.get(k), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out

def build_headers(seed_headers=None):
    headers = dict(DEFAULT_HEADERS)
    if seed_headers:
        for k, v in seed_headers.items():
            if v: headers[k.lower()] = v
    for hk, envk in ENV_HEADER_MAP.items():
        if os.environ.get(envk): headers[hk] = os.environ[envk]
    return headers

def validate_auth(headers):
    missing = [h for h in ('authorization', 'x-amz-date', 'x-amz-security-token') if not headers.get(h)]
    if missing: raise SystemExit(f'Missing required auth headers: {", ".join(missing)}')

def infer_kind(payload_file, explicit_kind=None):
    if explicit_kind: return explicit_kind
    name = Path(payload_file).name
    for k in ENDPOINTS:
        if k in name: return k
    return 'update-manager-property'

def capture_fresh(kind, property_id=None, close_extra_tabs=False, payload=None):
    fd, outp = tempfile.mkstemp(prefix=f'lofty-{kind}-', suffix='.headers.json'); os.close(fd)
    cmd = [sys.executable, str(CAPTURE), '--endpoint-kind', kind, '--out-file', outp]
    payload_path = None
    if property_id: cmd += ['--property-id', property_id]
    if isinstance(payload, dict):
        pfd, payload_path = tempfile.mkstemp(prefix=f'lofty-{kind}-', suffix='.payload.json'); os.close(pfd)
        Path(payload_path).write_text(json.dumps(payload, indent=2))
        cmd += ['--payload-file', payload_path]
        if kind == 'get-manager-properties':
            if payload.get('year') is not None: cmd += ['--year', str(payload['year'])]
            if payload.get('month') is not None: cmd += ['--month', str(payload['month'])]
    if close_extra_tabs: cmd += ['--close-extra-tabs']
    try:
        p = subprocess.run(cmd, check=True, text=True, capture_output=True)
        content = Path(outp).read_text().strip()
        if not content: raise RuntimeError(f'Fresh auth capture produced empty headers file for {kind}. stdout={p.stdout[:1000]!r} stderr={p.stderr[:1000]!r}')
        return json.loads(content)
    finally:
        if payload_path:
            try: os.unlink(payload_path)
            except Exception: pass

def is_refreshable_failure(resp):
    txt = (resp.text or '')[:4000].lower()
    return resp.status_code == 403 or 'forbidden' in txt or 'signature' in txt or 'security token' in txt or 'expired' in txt

def request(method, endpoint, headers, payload):
    if method == 'GET':
        return requests.get(endpoint, headers=headers, params=payload, timeout=60)
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return requests.post(endpoint, headers=headers, data=body.encode('utf-8'), timeout=60)


def runtime_eval(target_id, expression, await_promise=True, timeout=30):
    ws = connect_ws(target_id)
    msg_id = 0

    def send(method, params=None):
        nonlocal msg_id
        msg_id += 1
        cid = msg_id
        ws.send(json.dumps({'id': cid, 'method': method, 'params': params or {}}))
        return cid

    def recv_until_id(cid, timeout=timeout):
        end = time.time() + timeout
        while time.time() < end:
            obj = json.loads(ws.recv())
            if obj.get('id') == cid:
                return obj
        raise TimeoutError(f'timed out waiting for response id {cid}')

    send('Runtime.enable'); recv_until_id(msg_id, 5)
    cid = send('Runtime.evaluate', {'expression': expression, 'awaitPromise': await_promise, 'returnByValue': True, 'timeout': int(timeout * 1000)})
    try:
        return recv_until_id(cid, timeout)
    finally:
        ws.close()


def wait_for_lofty_runtime(target_id, timeout=30):
    end = time.time() + timeout
    expr = "(() => typeof webpackChunklofty_investing_webapp !== 'undefined')()"
    last = None
    while time.time() < end:
        resp = runtime_eval(target_id, expr, await_promise=False, timeout=5)
        result = resp.get('result', {}).get('result', {})
        last = result.get('value')
        if last is True:
            return True
        time.sleep(1)
    return bool(last)


RUNTIME_FN = {
    'update-manager-property': 'so',
    'send-property-updates': 'AB',
}


def request_via_runtime(kind, payload, property_id=None, close_extra_tabs=False):
    ctx = ensure_lofty_cdp_context(property_id=property_id or payload.get('propertyId'), mode='edit', close_extras=close_extra_tabs)
    if not wait_for_lofty_runtime(ctx['targetId'], timeout=30):
        raise SystemExit(json.dumps({'kind': kind, 'runtime': True, 'ok': False, 'error': 'Lofty runtime did not load on edit page', 'targetId': ctx['targetId'], 'url': ctx.get('url')}, indent=2))
    fn = RUNTIME_FN[kind]
    expr = f"""(async () => {{ let __req; webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]); const mod = __req(51046); return await mod.{fn}({json.dumps(payload)}); }})()"""
    resp = runtime_eval(ctx['targetId'], expr, await_promise=True, timeout=60)
    result = resp.get('result', {}).get('result', {})
    if resp.get('result', {}).get('exceptionDetails'):
        raise SystemExit(json.dumps({'kind': kind, 'runtime': True, 'ok': False, 'exception': resp['result']['exceptionDetails']}, indent=2))
    return {'kind': kind, 'runtime': True, 'ok': True, 'result': result.get('value')}

def main():
    ap = argparse.ArgumentParser(description='Replay Lofty PM requests from captured payloads.')
    ap.add_argument('--payload-file', required=True)
    ap.add_argument('--headers-file')
    ap.add_argument('--patch-file')
    ap.add_argument('--property-id')
    ap.add_argument('--kind', choices=sorted(ENDPOINTS.keys()))
    ap.add_argument('--endpoint')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--refresh-on-demand', action='store_true')
    ap.add_argument('--retry-on-auth-failure', action='store_true')
    ap.add_argument('--close-extra-tabs', action='store_true')
    args = ap.parse_args()
    payload = load_json(args.payload_file)
    kind = infer_kind(args.payload_file, args.kind)
    if args.patch_file:
        patch_updates = load_json(args.patch_file)
        payload['patch'] = merge_patch(payload.get('patch', {}), patch_updates) if kind == 'update-manager-property' else merge_patch(payload, patch_updates)
    if args.property_id:
        payload['propertyId'] = args.property_id
        if kind == 'update-manager-property': payload.setdefault('patch', {})['id'] = args.property_id
    headers_seed = load_json(args.headers_file) if args.headers_file else {}
    headers = build_headers(headers_seed)
    property_id = args.property_id or (payload.get('propertyId') if isinstance(payload, dict) else None)
    endpoint = args.endpoint or ENDPOINTS[kind]
    method = METHODS[kind]
    if args.dry_run:
        print(json.dumps({'kind': kind, 'method': method, 'endpoint': endpoint, 'propertyId': property_id, 'headerKeys': sorted(headers.keys()), 'payloadKeys': sorted(payload.keys()) if isinstance(payload, dict) else None, 'authRefreshPlanned': bool(args.refresh_on_demand), 'retryOnAuthFailure': bool(args.retry_on_auth_failure), 'runtimeDirect': kind != 'get-manager-properties'}, indent=2))
        return
    if kind != 'get-manager-properties':
        out = request_via_runtime(kind, payload, property_id=property_id, close_extra_tabs=args.close_extra_tabs)
        print(json.dumps(out, indent=2))
        return
    if args.refresh_on_demand:
        headers = build_headers(capture_fresh(kind, property_id=property_id, close_extra_tabs=args.close_extra_tabs, payload=payload))
    validate_auth(headers)
    resp = request(method, endpoint, headers, payload)
    if not resp.ok and args.retry_on_auth_failure and is_refreshable_failure(resp):
        headers = build_headers(capture_fresh(kind, property_id=property_id, close_extra_tabs=args.close_extra_tabs, payload=payload))
        resp = request(method, endpoint, headers, payload)
    out = {'kind': kind, 'method': method, 'status_code': resp.status_code, 'ok': resp.ok, 'text': resp.text[:4000]}
    print(json.dumps(out, indent=2))
    if not resp.ok: sys.exit(1)
if __name__ == '__main__': main()
