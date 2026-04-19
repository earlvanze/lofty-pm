#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from extract_lofty_lease_begins_dates import load_json, filter_properties, analyze_property

BOOTSTRAP = SCRIPT_DIR / 'build_lofty_pm_payloads.py'
REPLAY = SCRIPT_DIR / 'update_lofty_pm_property.py'
DEFAULT_MAP = SCRIPT_DIR.parent / 'config' / 'property_update_map.json'


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    for text in reversed([proc.stdout.strip(), proc.stderr.strip()]):
        if text.startswith('{'):
            try:
                return json.loads(text)
            except Exception:
                pass
    return {'ok': True}


def ensure_gmp_payload(path: Path, year: int | None, month: int | None):
    if path.exists():
        return
    now = dt.datetime.now()
    payload = {
        'year': str(year or now.year),
        'month': str(month or now.month),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + '\n')


def build_paths(prop: dict, output_dir: Path | None):
    pid = prop['lofty_property_id']
    if output_dir:
        root = output_dir / pid
        return {
            'gmp_payload_file': root / 'manager.get-manager-properties.payload.json',
            'save_payload_file': root / f'{pid}.update-manager-property.payload.json',
            'patch_file': root / f'{pid}.lease_begins_date.patch.json',
        }
    return {
        'gmp_payload_file': Path(prop.get('get_manager_properties_payload_file') or Path(tempfile.gettempdir()) / f'{pid}.manager.get-manager-properties.payload.json'),
        'save_payload_file': Path(prop.get('save_payload_file') or Path(tempfile.gettempdir()) / f'{pid}.update-manager-property.payload.json'),
        'patch_file': Path(tempfile.gettempdir()) / f'{pid}.lease_begins_date.patch.json',
    }


def main():
    ap = argparse.ArgumentParser(description='Update Lofty PM lease_begins_date from DESCRIPTION.md via API payloads instead of brittle DOM selectors')
    ap.add_argument('--property-map', default=str(DEFAULT_MAP))
    ap.add_argument('--property')
    ap.add_argument('--multi-date-strategy', choices=('ambiguous', 'first', 'earliest', 'latest'), default='earliest')
    ap.add_argument('--output-dir')
    ap.add_argument('--year', type=int)
    ap.add_argument('--month', type=int)
    ap.add_argument('--close-extra-tabs', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report-file')
    ap.add_argument('--apply', action='store_true', help='Actually call update-manager-property. Default mode is dry-run/report only.')
    args = ap.parse_args()

    props = filter_properties(load_json(Path(args.property_map)), args.property)
    if args.property and not props:
        raise SystemExit(f'No property matched {args.property!r}')

    output_dir = Path(args.output_dir) if args.output_dir else None
    rows = []
    for prop in props:
        analysis = analyze_property(prop, args.multi_date_strategy)
        row = {
            'property_name': analysis['property_name'],
            'lofty_property_id': analysis['lofty_property_id'],
            'status': analysis['status'],
            'description_path': analysis['description_path'],
            'chosen': analysis.get('chosen'),
        }
        if not analysis.get('chosen'):
            row['action'] = 'skipped'
            rows.append(row)
            continue

        paths = build_paths(prop, output_dir)
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        ensure_gmp_payload(paths['gmp_payload_file'], args.year, args.month)
        patch = {'lease_begins_date': analysis['chosen']['display']}
        paths['patch_file'].write_text(json.dumps(patch, indent=2) + '\n')
        row['patch_file'] = str(paths['patch_file'])
        row['save_payload_file'] = str(paths['save_payload_file'])
        row['get_manager_properties_payload_file'] = str(paths['gmp_payload_file'])

        bootstrap_cmd = [
            sys.executable, str(BOOTSTRAP),
            '--property-id', prop['lofty_property_id'],
            '--property', prop.get('property_name') or prop.get('full_address') or prop['lofty_property_id'],
            '--get-manager-properties-payload-file', str(paths['gmp_payload_file']),
            '--save-payload-file', str(paths['save_payload_file']),
            '--send-payload-file', str(paths['save_payload_file'].with_name(paths['save_payload_file'].name.replace('update-manager-property', 'send-property-updates'))),
        ]
        if args.close_extra_tabs:
            bootstrap_cmd.append('--close-extra-tabs')
        if not args.apply:
            bootstrap_cmd.append('--dry-run')
        row['bootstrap_cmd'] = bootstrap_cmd

        update_cmd = [
            sys.executable, str(REPLAY),
            '--payload-file', str(paths['save_payload_file']),
            '--patch-file', str(paths['patch_file']),
            '--kind', 'update-manager-property',
            '--property-id', prop['lofty_property_id'],
            '--refresh-on-demand',
            '--retry-on-auth-failure',
        ]
        if args.close_extra_tabs:
            update_cmd.append('--close-extra-tabs')
        if not args.apply:
            update_cmd.append('--dry-run')
        row['update_cmd'] = update_cmd

        try:
            run_json(bootstrap_cmd)
            run_json(update_cmd)
            row['action'] = 'updated' if args.apply else 'dry_run_ready'
        except SystemExit as exc:
            row['action'] = 'failed'
            row['error'] = {'code': exc.code}
        rows.append(row)

    summary = {
        'properties': len(rows),
        'ready_or_updated': sum(1 for row in rows if row['action'] in ('dry_run_ready', 'updated')),
        'skipped': sum(1 for row in rows if row['action'] == 'skipped'),
        'failed': sum(1 for row in rows if row['action'] == 'failed'),
        'applied': bool(args.apply),
        'multi_date_strategy': args.multi_date_strategy,
    }
    payload = {'summary': summary, 'properties': rows}
    rendered = json.dumps(payload, indent=2)
    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + '\n')
    print(rendered)


if __name__ == '__main__':
    main()
