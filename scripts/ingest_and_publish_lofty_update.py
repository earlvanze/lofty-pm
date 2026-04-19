#!/usr/bin/env python3
import argparse, json, subprocess, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
INGEST = SCRIPT_DIR / 'ingest_atlas_relay_update.py'
PUBLISH = SCRIPT_DIR / 'publish_latest_update_to_lofty.py'


def extract_meta(stdout: str):
    objs = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                objs.append(json.loads(line))
            except Exception:
                pass
    return objs[-1] if objs else {}


def main():
    ap = argparse.ArgumentParser(description='End-to-end Atlas Relay text -> canonical UPDATES.md -> Lofty PM save+send')
    ap.add_argument('--text')
    ap.add_argument('--text-file')
    ap.add_argument('--property')
    ap.add_argument('--date')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--close-extra-tabs', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    ingest_cmd = [sys.executable, str(INGEST)]
    if args.text is not None:
        ingest_cmd += ['--text', args.text]
    elif args.text_file:
        ingest_cmd += ['--text-file', args.text_file]
    else:
        raise SystemExit('Provide --text or --text-file')
    if args.property:
        ingest_cmd += ['--property', args.property]
    if args.date:
        ingest_cmd += ['--date', args.date]
    if args.dry_run:
        ingest_cmd += ['--dry-run']

    print(json.dumps({'step': 'ingest', 'cmd': ingest_cmd}, indent=2))
    ingest = subprocess.run(ingest_cmd, check=True, text=True, capture_output=True)
    if ingest.stdout:
        print(ingest.stdout)

    meta = extract_meta(ingest.stdout)
    publish_key = args.property or meta.get('lofty_property_id') or meta.get('slug') or meta.get('property_name')
    if not publish_key:
        raise SystemExit('Could not determine property key for publish step')

    publish_cmd = [sys.executable, str(PUBLISH), '--property', publish_key]
    if args.close_extra_tabs:
        publish_cmd.append('--close-extra-tabs')
    if args.dry_run:
        publish_cmd.append('--dry-run')
    if args.force:
        publish_cmd.append('--force')
    print(json.dumps({'step': 'publish', 'cmd': publish_cmd}, indent=2))
    subprocess.run(publish_cmd, check=True)


if __name__ == '__main__':
    main()
