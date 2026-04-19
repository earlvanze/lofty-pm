#!/usr/bin/env python3
import argparse, json, re, subprocess, sys, tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MAP_FILE = SCRIPT_DIR.parent / 'config' / 'property_update_map.json'
WRITER = SCRIPT_DIR / 'write_property_update_md.py'


def load_map():
    data = json.loads(MAP_FILE.read_text())
    return data.get('properties', [])


def norm(s):
    s = (s or '').lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return ' '.join(s.split())


def property_aliases(p):
    vals = [
        p.get('property_name', ''),
        p.get('full_address', ''),
        p.get('assetUnit', ''),
        p.get('lofty_property_id', ''),
        p.get('slug', '').replace('-', ' ').replace('_', ' '),
    ]
    upd = p.get('updates_md', '')
    if upd:
        up = Path(upd)
        vals += [up.parent.parent.parent.name, up.parent.parent.parent.parent.name]
    return [v for v in vals if v]


def find_property(text, props):
    nt = norm(text)
    scored = []
    for p in props:
        score = 0
        for cand in property_aliases(p):
            nc = norm(cand)
            if nc and nc in nt:
                score = max(score, len(nc.split()))
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1].get('property_name', '')))
    if not scored:
        return None
    return scored[0][1]


def clean_update_text(text):
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    out = []
    for ln in lines:
        if re.match(r'^(source|status|property|property_name|property name|lofty_property_id|assetunit|asset unit|slug)\s*:\s*', ln, re.I):
            continue
        out.append(ln)
    cleaned = '\n'.join(out).strip()
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned


def resolve_explicit_property(name, props):
    np = norm(name)
    for p in props:
        for cand in property_aliases(p):
            if np == norm(cand):
                return p
    return None


def main():
    ap = argparse.ArgumentParser(description='Ingest an Atlas Relay property update into canonical UPDATES.md')
    ap.add_argument('--text')
    ap.add_argument('--text-file')
    ap.add_argument('--property')
    ap.add_argument('--date', help='YYYY-MM-DD')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    raw = args.text if args.text is not None else Path(args.text_file).read_text()
    props = load_map()
    prop = resolve_explicit_property(args.property, props) if args.property else find_property(raw, props)
    if not prop:
        raise SystemExit('Could not resolve property from Atlas Relay text')

    body = clean_update_text(raw)
    if not body:
        raise SystemExit('No usable Atlas update body after cleanup')

    cmd = [sys.executable, str(WRITER), '--file', prop['updates_md']]
    if args.date:
        cmd += ['--date', args.date]
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
        tf.write(body)
        temp = tf.name
    cmd += ['--text-file', temp]
    if args.dry_run:
        cmd += ['--dry-run']
    subprocess.run(cmd, check=True)
    print(json.dumps({
        'property_name': prop['property_name'],
        'lofty_property_id': prop['lofty_property_id'],
        'slug': prop.get('slug'),
        'updates_md': prop['updates_md']
    }, indent=2))


if __name__ == '__main__':
    main()
