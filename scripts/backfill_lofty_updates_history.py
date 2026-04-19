#!/usr/bin/env python3
import argparse, datetime as dt, json, re, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from update_lofty_pm_property import capture_fresh, build_headers, validate_auth, request

MAP_FILE = SCRIPT_DIR.parent / 'config' / 'property_update_map.json'
GMP_ENDPOINT = 'https://api.lofty.ai/prod/property-managers/v2/get-manager-properties'
GMP_PAYLOAD_FILE = Path('/home/umbrel/.openclaw/workspace/tmp/lofty-pm-gmp-test/manager.get-manager-properties.payload.json')


def load_map(path: Path):
    data = json.loads(path.read_text())
    return data['properties'] if isinstance(data, dict) and 'properties' in data else data


def fetch_live_properties(sample_property_id: str | None = None):
    payload = json.loads(GMP_PAYLOAD_FILE.read_text())
    fresh = capture_fresh('get-manager-properties', property_id=sample_property_id, payload=payload)
    headers = build_headers(fresh)
    validate_auth(headers)
    resp = request('GET', GMP_ENDPOINT, headers, payload)
    resp.raise_for_status()
    data = resp.json()
    return {p['id']: p for p in data['data']['properties']}


def norm_ws(s: str) -> str:
    s = s.replace('\r\n', '\n').replace('\r', '\n').strip()
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def fmt_date_mmddyyyy(date_obj: dt.date) -> str:
    return f'{date_obj.month:02d}/{date_obj.day:02d}/{date_obj.year:04d}'


def parse_flexible_date(s: str) -> dt.date:
    s = s.strip()
    for fmt in ('%m/%d/%Y', '%m/%-d/%Y', '%-m/%d/%Y', '%-m/%-d/%Y'):
        try:
            # %-m may not work on all platforms; keep fallbacks below
            return dt.datetime.strptime(s, fmt).date()
        except Exception:
            pass
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    raise ValueError(f'unrecognized date: {s!r}')


def canonicalize_entry(date_obj: dt.date, body_text: str) -> dict:
    body_text = norm_ws(body_text)
    # remove leading duplicate header if present
    body_text = re.sub(r'^-\s*\*{0,2}Property Update \([^\)]+\):\*{0,2}\s*', '', body_text, flags=re.I)
    cleaned_lines = []
    for ln in body_text.split('\n'):
        t = ln.strip()
        if not t:
            cleaned_lines.append('')
            continue
        if re.match(r'^[-*]\s+', t):
            t = '- ' + re.sub(r'^[-*]\s+', '', t)
        cleaned_lines.append(t)
    body_text = '\n'.join(cleaned_lines).strip()
    body_text = re.sub(r'\n{3,}', '\n\n', body_text)
    canonical_body = f'- Property Update ({fmt_date_mmddyyyy(date_obj)}):'
    if body_text:
        canonical_body += '\n' + body_text
    return {
        'date': date_obj.isoformat(),
        'body': canonical_body.strip(),
    }


def dedupe_key(entry: dict) -> tuple[str, str]:
    body = entry['body']
    body = body.replace('**', '')
    body = re.sub(r'\s+', ' ', body).strip().lower()
    return (entry['date'], body)


def parse_local_updates(text: str):
    parts = re.split(r'(?m)^##\s+(\d{4}-\d{2}-\d{2})\s*\n', text)
    entries = []
    if len(parts) < 3:
        return entries
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break
        date_s = parts[i]
        body = parts[i + 1].strip()
        if not body:
            continue
        d = dt.date.fromisoformat(date_s)
        entries.append(canonicalize_entry(d, body))
    return entries


def parse_lofty_updates(text: str):
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return []
    pattern = re.compile(r'(?m)^-\s*\*{0,2}Property Update \((\d{1,2}/\d{1,2}/\d{4})\):\*{0,2}\s*')
    matches = list(pattern.finditer(text))
    if not matches:
        # maybe already canonical single-entry body without ## header
        m = re.match(r'(?ms)^-\s*Property Update \((\d{1,2}/\d{1,2}/\d{4})\):\s*(.*)$', text)
        if m:
            d = parse_flexible_date(m.group(1))
            return [canonicalize_entry(d, m.group(2))]
        return []
    entries = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        d = parse_flexible_date(m.group(1))
        entries.append(canonicalize_entry(d, chunk))
    return entries


def render(entries: list[dict]) -> str:
    out = ['# Property Updates', '']
    for e in entries:
        out.append(f"## {e['date']}")
        out.append('')
        out.append(e['body'])
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def merge_entries(existing: list[dict], lofty: list[dict]):
    merged = []
    seen = set()
    for src in (existing, lofty):
        for e in src:
            k = dedupe_key(e)
            if k in seen:
                continue
            seen.add(k)
            merged.append(e)
    merged.sort(key=lambda e: (e['date'], dedupe_key(e)[1]), reverse=True)
    return merged


def main():
    ap = argparse.ArgumentParser(description='Backfill Lofty-side update history into local UPDATES.md files and dedupe canonically')
    ap.add_argument('--map-file', default=str(MAP_FILE))
    ap.add_argument('--property')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    props = load_map(Path(args.map_file))
    if args.property:
        q = args.property.lower()
        props = [p for p in props if q in p.get('property_name', '').lower() or q == p.get('lofty_property_id', '').lower() or q == p.get('slug', '').lower()]
        if not props:
            raise SystemExit(f'No mapped property matched {args.property!r}')

    live = fetch_live_properties(props[0]['lofty_property_id'] if props else None)

    summary = {'properties': 0, 'updated_files': 0, 'entries_written': 0, 'live_entries_seen': 0, 'existing_entries_seen': 0, 'missing_live_records': 0}
    per = []
    for p in props:
        summary['properties'] += 1
        lp = live.get(p['lofty_property_id'])
        if not lp:
            summary['missing_live_records'] += 1
            per.append({'property': p['property_name'], 'status': 'missing_live_record'})
            continue
        path = Path(p['updates_md'])
        existing_text = path.read_text() if path.exists() else '# Property Updates\n\n'
        existing_entries = parse_local_updates(existing_text)
        lofty_entries = parse_lofty_updates(lp.get('updates', '') or '')
        summary['existing_entries_seen'] += len(existing_entries)
        summary['live_entries_seen'] += len(lofty_entries)
        merged = merge_entries(existing_entries, lofty_entries)
        rendered = render(merged)
        changed = (not path.exists()) or (existing_text != rendered)
        if changed and not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered)
        if changed:
            summary['updated_files'] += 1
            summary['entries_written'] += len(merged)
        per.append({
            'property': p['property_name'],
            'lofty_property_id': p['lofty_property_id'],
            'live_updates_len': len(lp.get('updates', '') or ''),
            'existing_entries': len(existing_entries),
            'live_entries': len(lofty_entries),
            'merged_entries': len(merged),
            'changed': changed,
            'updates_md': str(path),
        })
    print(json.dumps({'summary': summary, 'properties': per}, indent=2))


if __name__ == '__main__':
    main()
