#!/usr/bin/env python3
import argparse, json, time
from pathlib import Path
from lofty_cdp import ensure_lofty_cdp_context, get_tabs

try:
    import websocket as websocket_client
except Exception:
    websocket_client = None
    from websockets.sync.client import connect as websockets_connect


def load_json(path):
    return json.loads(Path(path).read_text())


ENDPOINT_HINTS = {
    'get-manager-properties': 'get-manager-properties',
    'update-manager-property': 'update-manager-property',
    'send-property-updates': 'send-property-updates',
}


class SyncWsAdapter:
    def __init__(self, conn):
        self.conn = conn
        self.timeout = 20

    def send(self, data):
        return self.conn.send(data)

    def recv(self):
        return self.conn.recv(timeout=self.timeout)

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self):
        return self.conn.close()


def connect_ws(target_id):
    tabs = get_tabs()
    wsurl = next(t['webSocketDebuggerUrl'] for t in tabs if t['id'] == target_id)
    if websocket_client is not None:
        ws = websocket_client.WebSocket()
        ws.connect(wsurl, timeout=20, origin=None, suppress_origin=True)
        return ws
    return SyncWsAdapter(websockets_connect(wsurl, open_timeout=20, origin=None, max_size=None))


def main():
    ap = argparse.ArgumentParser(description='Capture live Lofty signed auth headers from direct Brave CDP.')
    ap.add_argument('--target-id')
    ap.add_argument('--property-id')
    ap.add_argument('--year', type=int)
    ap.add_argument('--month', type=int)
    ap.add_argument('--endpoint-kind', choices=sorted(ENDPOINT_HINTS.keys()), default='get-manager-properties')
    ap.add_argument('--payload-file')
    ap.add_argument('--out-file')
    ap.add_argument('--close-extra-tabs', action='store_true')
    args = ap.parse_args()

    payload = load_json(args.payload_file) if args.payload_file else None
    mode = 'list' if args.endpoint_kind == 'get-manager-properties' else 'edit'
    ctx = {'targetId': args.target_id} if args.target_id else ensure_lofty_cdp_context(property_id=args.property_id, mode=mode, close_extras=args.close_extra_tabs)
    target_id = ctx['targetId']
    ws = connect_ws(target_id)
    msg_id = 0

    def send(method, params=None):
        nonlocal msg_id
        msg_id += 1
        cid = msg_id
        ws.send(json.dumps({'id': cid, 'method': method, 'params': params or {}}))
        return cid

    def recv_until_id(cid, timeout=20):
        end = time.time() + timeout
        events = []
        while time.time() < end:
            obj = json.loads(ws.recv())
            if obj.get('id') == cid:
                return obj, events
            if 'method' in obj:
                events.append(obj)
        raise TimeoutError(f'timed out waiting for response id {cid}')

    def collect_events(seconds):
        end = time.time() + seconds
        events = []
        while time.time() < end:
            try:
                ws.settimeout(1)
                obj = json.loads(ws.recv())
                if 'method' in obj:
                    events.append(obj)
            except Exception:
                pass
        ws.settimeout(20)
        return events

    send('Page.enable'); recv_until_id(msg_id, 5)
    send('Runtime.enable'); recv_until_id(msg_id, 5)

    hint = ENDPOINT_HINTS[args.endpoint_kind]
    events = []

    if args.endpoint_kind == 'get-manager-properties':
        send('Network.enable'); recv_until_id(msg_id, 5)
        year = args.year or ((payload or {}).get('year')) or time.gmtime().tm_year
        month = args.month or ((payload or {}).get('month')) or time.gmtime().tm_mon
        expr = f"""(async () => {{ let __req; webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]); const mod = __req(51046); const fn = mod.PK; return await fn({{year:{year}, month:{month}}}); }})()"""
        cid = send('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
        _, ev = recv_until_id(cid, 10)
        events.extend(ev)
        events.extend(collect_events(5))
        headers = None
        source = None
        for e in events:
            if e.get('method') == 'Network.requestWillBeSentExtraInfo':
                h = {k.lower(): v for k, v in (e.get('params', {}).get('headers') or {}).items()}
                path = h.get(':path', '')
                if hint in path and h.get('authorization') and h.get('x-amz-date') and h.get('x-amz-security-token'):
                    headers = h
                    source = {'url': path, 'method': h.get(':method', 'GET')}
        if not headers:
            raise SystemExit(f'Did not capture a signed Lofty API request for {args.endpoint_kind}')
        out_headers = {
            'authorization': headers.get('authorization'),
            'x-amz-date': headers.get('x-amz-date'),
            'x-amz-security-token': headers.get('x-amz-security-token'),
            'x-lofty-app-version': headers.get('x-lofty-app-version'),
            'content-type': headers.get('content-type', 'application/json; charset=UTF-8'),
            'origin': headers.get('origin', 'https://www.lofty.ai'),
            'referer': headers.get('referer', 'https://www.lofty.ai/'),
            'user-agent': headers.get('user-agent', 'Mozilla/5.0 OpenClaw Lofty PM Skill'),
        }
        captured_url = source['url']
        captured_method = source['method']
    else:
        hook = r'''(() => {
          const key = '__loftyCapturedRequests';
          sessionStorage.removeItem(key);
          const keep = (entry) => {
            try {
              const cur = JSON.parse(sessionStorage.getItem(key) || '[]');
              cur.push(entry);
              sessionStorage.setItem(key, JSON.stringify(cur.slice(-100)));
            } catch (e) {}
          };
          const hdrsToObj = (h) => {
            const out = {};
            if (!h) return out;
            if (Array.isArray(h)) { for (const [k,v] of h) out[k] = v; }
            else if (typeof Headers !== 'undefined' && h instanceof Headers) { for (const [k,v] of h.entries()) out[k] = v; }
            else if (typeof h === 'object') { for (const k of Object.keys(h)) out[k] = h[k]; }
            return out;
          };
          if (!window.__openclawLoftyHooked) {
            window.__openclawLoftyHooked = true;
            const origFetch = window.fetch;
            window.fetch = async function(input, init) {
              try {
                const url = (typeof input === 'string') ? input : (input && input.url) || '';
                const headers = hdrsToObj((init && init.headers) || (input && input.headers));
                keep({type:'fetch', url, method:(init && init.method) || (input && input.method) || 'GET', headers, body:(init&&init.body)?String(init.body).slice(0,5000):''});
              } catch (e) {}
              return origFetch.apply(this, arguments);
            };
            const xo = XMLHttpRequest.prototype.open;
            const xh = XMLHttpRequest.prototype.setRequestHeader;
            const xs = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url) {
              this.__oc = {method, url, headers:{}};
              return xo.apply(this, arguments);
            };
            XMLHttpRequest.prototype.setRequestHeader = function(k,v) {
              try { if (this.__oc) this.__oc.headers[k] = v; } catch (e) {}
              return xh.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function(body) {
              try { if (this.__oc) keep({type:'xhr', url:this.__oc.url, method:this.__oc.method, headers:this.__oc.headers, body:body?String(body).slice(0,5000):''}); } catch (e) {}
              return xs.apply(this, arguments);
            };
          }
        })();'''
        send('Runtime.evaluate', {'expression': hook}); recv_until_id(msg_id, 5)
        if args.endpoint_kind == 'send-property-updates':
            send_payload = payload or {'propertyId': args.property_id, 'updatesDiff': 'Auto refresh trigger'}
            expr = f"""(async () => {{ let __req; webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]); const mod = __req(51046); return await mod.AB({json.dumps(send_payload)}); }})()"""
            cid = send('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            recv_until_id(cid, 10)
            time.sleep(2)
        elif args.endpoint_kind == 'update-manager-property':
            update_payload = payload or {'propertyId': args.property_id, 'patch': {'id': args.property_id}}
            expr = f"""(async () => {{ let __req; webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]); const mod = __req(51046); return await mod.so({json.dumps(update_payload)}); }})()"""
            cid = send('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            recv_until_id(cid, 15)
            time.sleep(2)
        resp = send('Runtime.evaluate', {'expression': "JSON.parse(sessionStorage.getItem('__loftyCapturedRequests') || '[]')", 'returnByValue': True})
        data, _ = recv_until_id(resp, 10)
        arr = data['result']['result'].get('value', [])
        headers = None
        source = None
        for x in reversed(arr):
            h = {k.lower(): v for k, v in (x.get('headers') or {}).items()}
            if hint in (x.get('url') or '') and h.get('authorization') and h.get('x-amz-date') and h.get('x-amz-security-token'):
                headers = h
                source = x
                break
        if not headers:
            raise SystemExit(f'Did not capture a signed Lofty API request for {args.endpoint_kind}')
        out_headers = {
            'authorization': headers.get('authorization'),
            'x-amz-date': headers.get('x-amz-date'),
            'x-amz-security-token': headers.get('x-amz-security-token'),
            'x-lofty-app-version': headers.get('x-lofty-app-version'),
            'content-type': headers.get('content-type', 'application/json; charset=UTF-8'),
            'origin': headers.get('origin', 'https://www.lofty.ai'),
            'referer': headers.get('referer', 'https://www.lofty.ai/'),
            'user-agent': headers.get('user-agent', 'Mozilla/5.0 OpenClaw Lofty PM Skill'),
        }
        captured_url = source.get('url')
        captured_method = source.get('method')

    out = {
        'targetId': target_id,
        'endpointKind': args.endpoint_kind,
        'capturedUrl': captured_url,
        'capturedMethod': captured_method,
        'headers': out_headers,
    }
    if args.out_file:
        Path(args.out_file).write_text(json.dumps(out['headers'], indent=2))
    print(json.dumps(out, indent=2))
    ws.close()


if __name__ == '__main__':
    main()
