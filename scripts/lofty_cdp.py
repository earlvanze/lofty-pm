#!/usr/bin/env python3
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

CDP_BASE = os.environ.get('BASELANE_CDP_PORT', 'http://127.0.0.1:9222')
LOFTY_HOST = 'www.lofty.ai'
DEFAULT_LIST_URL = 'https://www.lofty.ai/property-owners'
DEFAULT_EDIT_PREFIX = 'https://www.lofty.ai/property-owners/edit/'
BRAVE_CANDIDATES = [
    os.environ.get('BRAVE_BIN'),
    '/usr/bin/brave-browser',
    '/usr/bin/brave',
    '/snap/bin/brave',
]


def cdp_get(path):
    with urllib.request.urlopen(CDP_BASE + path, timeout=10) as r:
        return json.load(r)


def cdp_available():
    try:
        cdp_get('/json/version')
        return True
    except Exception:
        return False


def get_tabs():
    return cdp_get('/json/list')


def open_tab(url):
    q = urllib.parse.quote(url, safe=':/?&=')
    req = urllib.request.Request(CDP_BASE + '/json/new?' + q, method='PUT')
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def activate_tab(target_id):
    with urllib.request.urlopen(CDP_BASE + f'/json/activate/{target_id}', timeout=10) as r:
        return r.read().decode('utf-8', 'ignore')


def close_tab(target_id):
    with urllib.request.urlopen(CDP_BASE + f'/json/close/{target_id}', timeout=10) as r:
        return r.read().decode('utf-8', 'ignore')


def lofty_tabs():
    tabs = [t for t in get_tabs() if t.get('type') == 'page' and LOFTY_HOST in (t.get('url') or '')]
    return tabs


def looks_authenticated(tab):
    title = (tab.get('title') or '').lower()
    url = (tab.get('url') or '').lower()
    return 'lofty ai' in title and ('property-owners' in url or 'portfolio' in url or 'property management' in title or 'edit/' in url)


def best_lofty_tab(property_id=None, mode='any'):
    tabs = lofty_tabs()
    if not tabs:
        return None, []
    exact = []
    auth = []
    list_tabs = []
    edit_tabs = []
    for t in tabs:
        url = t.get('url') or ''
        if property_id and property_id in url:
            exact.append(t)
        if '/property-owners/edit/' in url:
            edit_tabs.append(t)
        elif '/property-owners' in url:
            list_tabs.append(t)
        if looks_authenticated(t):
            auth.append(t)
    if mode == 'list':
        chosen = (list_tabs[0] if list_tabs else (auth[0] if auth else tabs[0]))
        extras = [t for t in tabs if t.get('id') != chosen.get('id') and '/property-owners' in (t.get('url') or '') and '/property-owners/edit/' not in (t.get('url') or '')]
        return chosen, extras
    if mode == 'edit':
        chosen = exact[0] if exact else (edit_tabs[0] if edit_tabs else (auth[0] if auth else tabs[0]))
        extras = [t for t in tabs if t.get('id') != chosen.get('id') and '/property-owners/edit/' in (t.get('url') or '')]
        return chosen, extras
    chosen = exact[0] if exact else (auth[0] if auth else tabs[0])
    extras = [t for t in tabs if t.get('id') != chosen.get('id')]
    return chosen, extras


def ensure_cdp(brave_url=None):
    if cdp_available():
        return {'cdp': True, 'launched': False}
    brave = next((p for p in BRAVE_CANDIDATES if p and Path(p).exists()), None)
    if not brave:
        raise RuntimeError('Brave binary not found and CDP port 9222 is not available')
    args = [brave, '--remote-debugging-port=9222']
    if brave_url:
        args.append(brave_url)
    else:
        args.append('https://www.lofty.ai/')
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if cdp_available():
            return {'cdp': True, 'launched': True}
        time.sleep(1)
    raise RuntimeError('Brave CDP failed to come up on 9222')


def ensure_lofty_cdp_context(property_id=None, mode='any', open_if_missing=True, close_extras=False):
    if mode == 'list':
        target_url = DEFAULT_LIST_URL
    elif property_id:
        target_url = f'{DEFAULT_EDIT_PREFIX}{property_id}'
    else:
        target_url = DEFAULT_LIST_URL
    ensure_cdp(target_url)
    chosen, extras = best_lofty_tab(property_id=property_id, mode=mode)
    if chosen:
        activate_tab(chosen['id'])
        cur = chosen.get('url') or ''
        needs_new = False
        if mode == 'list' and ('/property-owners' not in cur or '/property-owners/edit/' in cur):
            needs_new = True
        elif mode == 'edit' and property_id and property_id not in cur:
            needs_new = True
        if needs_new:
            open_tab(target_url)
            time.sleep(1)
            chosen, extras = best_lofty_tab(property_id=property_id, mode=mode)
        if close_extras:
            for t in extras:
                try: close_tab(t['id'])
                except Exception: pass
        return {'targetId': chosen['id'], 'url': chosen.get('url'), 'reused': True, 'extraTabs': [t['id'] for t in extras], 'mode': mode}
    if not open_if_missing:
        raise RuntimeError('No Lofty tab found')
    new_tab = open_tab(target_url)
    time.sleep(1)
    chosen, extras = best_lofty_tab(property_id=property_id, mode=mode)
    chosen = chosen or new_tab
    activate_tab(chosen['id'])
    if close_extras:
        for t in extras:
            try: close_tab(t['id'])
            except Exception: pass
    return {'targetId': chosen['id'], 'url': chosen.get('url'), 'reused': False, 'extraTabs': [t['id'] for t in extras], 'mode': mode}
