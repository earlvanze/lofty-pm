#!/usr/bin/env python3
import argparse, datetime as dt, hashlib, json, re, tempfile, subprocess, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WRAPPER = SCRIPT_DIR / 'save_and_send_lofty_pm_update.py'
BOOTSTRAP = SCRIPT_DIR / 'build_lofty_pm_payloads.py'
DEFAULT_MAP = SCRIPT_DIR.parent / 'config' / 'property_update_map.json'
SEND_INTERVAL_DAYS = 7


def load_map(path):
    data = json.loads(Path(path).read_text())
    props = data['properties'] if isinstance(data, dict) and 'properties' in data else data
    return props


def parse_entries(md_text):
    parts = re.split(r'(?m)^##\s+(\d{4}-\d{2}-\d{2})\s*$', md_text)
    entries = []
    if len(parts) < 3:
        raise SystemExit('No dated update entries found in UPDATES.md')
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break
        date = parts[i]
        body = parts[i + 1].strip()
        if body:
            entries.append({'date': date, 'body': body})
    return entries


def entry_lofty_text(entry):
    m = re.search(r'(?ms)^- Property Update \((\d{2}/\d{2}/\d{4})\):\s*(.*)$', entry['body'])
    if m:
        return f'- Property Update ({m.group(1)}):\n{m.group(2).strip()}'.strip()
    return entry['body'].strip()


def combined_lofty_updates(entries):
    return '\n\n'.join(entry_lofty_text(e) for e in entries if entry_lofty_text(e)).strip()


def find_property(props, key):
    keyl = key.lower()
    for p in props:
        if key == p.get('lofty_property_id') or key == p.get('updates_md'):
            return p
        if keyl in (p.get('property_name', '').lower(), Path(p.get('updates_md', '')).parent.parent.parent.name.lower(), p.get('slug', '').lower()):
            return p
        if Path(p.get('updates_md', '')).name == key:
            return p
    raise SystemExit(f'No property mapping found for {key!r}')


def state_path(prop):
    return Path(prop['updates_md']).parent / '.lofty_publish_state.json'


def load_state(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + '\n')


def digest_for_entry(prop, entry):
    s = json.dumps({
        'lofty_property_id': prop['lofty_property_id'],
        'date': entry['date'],
        'updates_text': entry_lofty_text(entry).strip(),
    }, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()


def digest_for_field(prop, loft_text):
    s = json.dumps({
        'lofty_property_id': prop['lofty_property_id'],
        'updates_field': loft_text.strip(),
    }, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()


def parse_iso_z(s):
    if not s:
        return None
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def collect_unsent_entries(prop, entries, last_sent_digest):
    unsent = []
    for e in entries:
        d = digest_for_entry(prop, e)
        if last_sent_digest and d == last_sent_digest:
            break
        unsent.append(e)
    return unsent


def main():
    ap = argparse.ArgumentParser(description='Publish canonical UPDATES.md history to Lofty PM and batch owner emails to at most once per week')
    ap.add_argument('--property', required=True, help='property_name, lofty_property_id, slug, or updates_md path')
    ap.add_argument('--map-file', default=str(DEFAULT_MAP))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--close-extra-tabs', action='store_true')
    ap.add_argument('--force', action='store_true', help='Ignore duplicate-safe state and send again')
    args = ap.parse_args()

    props = load_map(args.map_file)
    prop = find_property(props, args.property)
    md_path = Path(prop['updates_md'])
    entries = parse_entries(md_path.read_text())
    latest = entries[0]
    latest_digest = digest_for_entry(prop, latest)
    loft_field_text = combined_lofty_updates(entries)
    field_digest = digest_for_field(prop, loft_field_text)

    sp = state_path(prop)
    state = load_state(sp)

    # bootstrap send baseline to avoid emailing historical backfill on first run
    bootstrap_seeded = False
    if not state.get('last_sent_digest') and not args.force:
        state['last_sent_digest'] = latest_digest
        state['last_sent_at'] = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds') + 'Z'
        bootstrap_seeded = True

    last_sent_at = parse_iso_z(state.get('last_sent_at'))
    now = dt.datetime.now(dt.timezone.utc)
    weekly_window_open = args.force or last_sent_at is None or (now - last_sent_at) >= dt.timedelta(days=SEND_INTERVAL_DAYS)
    unsent_entries = collect_unsent_entries(prop, entries, None if args.force else state.get('last_sent_digest'))
    batched_send_text = combined_lofty_updates(unsent_entries)
    should_send = bool(batched_send_text) and weekly_window_open and not bootstrap_seeded

    with tempfile.TemporaryDirectory() as td:
        save_patch_file = Path(td) / 'save.patch.json'
        save_payload_file = Path(td) / 'save.payload.json'
        send_payload_file = Path(td) / 'send.payload.json'
        save_patch_file.write_text(json.dumps({'updates': loft_field_text}, indent=2))

        bootstrap_cmd = [sys.executable, str(BOOTSTRAP),
            '--property-id', prop['lofty_property_id'],
            '--property', prop['property_name'],
            '--get-manager-properties-payload-file', prop['get_manager_properties_payload_file'],
            '--save-payload-file', str(save_payload_file),
            '--send-payload-file', str(send_payload_file)]
        if args.close_extra_tabs:
            bootstrap_cmd.append('--close-extra-tabs')
        if args.dry_run:
            bootstrap_cmd.append('--dry-run')
        print(json.dumps({'step': 'bootstrap-payloads', 'cmd': bootstrap_cmd}, indent=2))
        subprocess.run(bootstrap_cmd, check=True)

        cmd = [sys.executable, str(WRAPPER),
            '--get-manager-properties-payload-file', prop['get_manager_properties_payload_file'],
            '--save-payload-file', str(save_payload_file),
            '--save-patch-file', str(save_patch_file),
            '--send-payload-file', str(send_payload_file),
            '--property-id', prop['lofty_property_id']]
        if should_send:
            cmd += ['--updates-diff', batched_send_text]
        else:
            cmd += ['--skip-send']
        if args.close_extra_tabs:
            cmd.append('--close-extra-tabs')
        if args.dry_run:
            cmd.append('--dry-run')
        print(json.dumps({
            'property': prop['property_name'],
            'updates_md': str(md_path),
            'latest_date': latest['date'],
            'latest_digest': latest_digest,
            'field_digest': field_digest,
            'bootstrap_seeded': bootstrap_seeded,
            'weekly_window_open': weekly_window_open,
            'unsent_entries': len(unsent_entries),
            'will_send': should_send,
            'cmd': cmd
        }, indent=2))
        subprocess.run(cmd, check=True)

    if not args.dry_run:
        state.update({
            'property_name': prop['property_name'],
            'lofty_property_id': prop['lofty_property_id'],
            'slug': prop.get('slug'),
            'updates_md': str(md_path),
            'last_entry_date': latest['date'],
            'last_posted_digest': field_digest,
            'last_posted_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds') + 'Z',
            'last_posted_text': loft_field_text,
        })
        if should_send:
            state.update({
                'last_sent_digest': latest_digest,
                'last_sent_text': batched_send_text,
                'last_sent_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds') + 'Z',
                'last_sent_entry_count': len(unsent_entries),
            })
        save_state(sp, state)
    print(json.dumps({
        'state_file': str(sp),
        'latest_digest': latest_digest,
        'field_digest': field_digest,
        'will_send': should_send,
        'bootstrap_seeded': bootstrap_seeded,
        'dry_run': args.dry_run
    }, indent=2))


if __name__ == '__main__':
    main()
