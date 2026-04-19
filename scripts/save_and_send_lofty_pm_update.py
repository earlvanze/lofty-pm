#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPLAY = SCRIPT_DIR / 'update_lofty_pm_property.py'

def load_json(path): return json.loads(Path(path).read_text())
def derive_updates_diff(save_patch_file):
    obj = load_json(save_patch_file)
    if isinstance(obj, dict):
        if isinstance(obj.get('updates'), str) and obj['updates'].strip(): return obj['updates']
        patch = obj.get('patch')
        if isinstance(patch, dict) and isinstance(patch.get('updates'), str) and patch['updates'].strip(): return patch['updates']
        for key in ('updatesDiff','message','body','text'):
            if isinstance(obj.get(key), str) and obj.get(key).strip(): return obj[key]
    return None

def write_temp(obj, suffix):
    fd, path = tempfile.mkstemp(prefix='lofty-pm-', suffix=suffix); os.close(fd); Path(path).write_text(json.dumps(obj, indent=2)); return path

def run(cmd):
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.stdout: print(p.stdout)
    if p.returncode != 0:
        if p.stderr: print(p.stderr, file=sys.stderr)
        raise SystemExit(p.returncode)

def main():
    ap = argparse.ArgumentParser(description='Canonical low-ambiguity Lofty PM flow: optional list fetch, save, then optional send owner update.')
    ap.add_argument('--get-manager-properties-payload-file')
    ap.add_argument('--save-payload-file', required=True)
    ap.add_argument('--save-patch-file', required=True)
    ap.add_argument('--send-payload-file', required=True)
    ap.add_argument('--updates-diff')
    ap.add_argument('--send-patch-file')
    ap.add_argument('--derive-updates-diff', action='store_true')
    ap.add_argument('--property-id')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--close-extra-tabs', action='store_true')
    ap.add_argument('--skip-send', action='store_true')
    args = ap.parse_args()
    send_patch = load_json(args.send_patch_file) if args.send_patch_file else {}
    derived_updates = derive_updates_diff(args.save_patch_file) if args.derive_updates_diff and args.updates_diff is None else None
    if args.updates_diff is not None: send_patch['updatesDiff'] = args.updates_diff
    elif derived_updates: send_patch['updatesDiff'] = derived_updates
    send_patch_file = write_temp(send_patch, '.send.json') if send_patch else None
    canonical_property_id = args.property_id or load_json(args.save_payload_file).get('propertyId')
    common = ['--refresh-on-demand', '--retry-on-auth-failure'] + (['--close-extra-tabs'] if args.close_extra_tabs else [])
    if args.get_manager_properties_payload_file:
        get_cmd = [sys.executable, str(REPLAY), '--payload-file', args.get_manager_properties_payload_file, '--kind', 'get-manager-properties', *common]
        if canonical_property_id: get_cmd += ['--property-id', canonical_property_id]
        if args.dry_run: get_cmd.append('--dry-run')
        print(json.dumps({'step':'get-manager-properties','cmd':get_cmd}, indent=2)); run(get_cmd)
    save_cmd = [sys.executable, str(REPLAY), '--payload-file', args.save_payload_file, '--patch-file', args.save_patch_file, '--kind', 'update-manager-property', *common]
    send_cmd = [sys.executable, str(REPLAY), '--payload-file', args.send_payload_file, '--kind', 'send-property-updates', *common]
    if send_patch_file: send_cmd += ['--patch-file', send_patch_file]
    if canonical_property_id:
        save_cmd += ['--property-id', canonical_property_id]
        send_cmd += ['--property-id', canonical_property_id]
    if args.dry_run:
        save_cmd.append('--dry-run'); send_cmd.append('--dry-run')
    print(json.dumps({'step':'save','cmd':save_cmd}, indent=2)); run(save_cmd)
    if args.skip_send:
        print(json.dumps({'step':'send','skipped':True,'reason':'skip-send'}, indent=2))
        return
    print(json.dumps({'step':'send','cmd':send_cmd}, indent=2)); run(send_cmd)
if __name__ == '__main__': main()
