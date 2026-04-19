#!/usr/bin/env python3
import argparse, datetime as dt, json, re
from pathlib import Path


def slugify_date(d):
    return d.strftime('%m/%d/%Y')


def clean_text(text):
    text = text.strip().replace('\r\n', '\n').replace('\r', '\n')
    lines = [ln.rstrip() for ln in text.split('\n')]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


def ensure_updates_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text('# Property Updates\n\n')


def parse_entries(text: str):
    parts = re.split(r'(?m)^##\s+(\d{4}-\d{2}-\d{2})\s*\n', text)
    if len(parts) < 3:
        return []
    entries = []
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break
        entries.append({'date': parts[i], 'body': parts[i + 1].strip()})
    return entries


def main():
    ap = argparse.ArgumentParser(description='Write a canonical property update entry into UPDATES.md')
    ap.add_argument('--file', required=True)
    ap.add_argument('--date', help='YYYY-MM-DD; defaults today')
    ap.add_argument('--text', help='Update body text')
    ap.add_argument('--text-file', help='Read update body from file')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    body = args.text if args.text is not None else Path(args.text_file).read_text()
    body = clean_text(body)
    if not body:
        raise SystemExit('Empty update text')
    d = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    header = f'- Property Update ({slugify_date(d)}):'
    entry_body = f'{header}\n{body}'.strip()
    entry = f'## {d.isoformat()}\n\n{entry_body}\n\n'

    path = Path(args.file)
    ensure_updates_file(path)
    existing = path.read_text()
    entries = parse_entries(existing)
    for e in entries:
        if e['date'] == d.isoformat() and clean_text(e['body']) == clean_text(entry_body):
            print(json.dumps({'file': str(path), 'date': d.isoformat(), 'header': header, 'deduped': True, 'dry_run': args.dry_run}, indent=2))
            return

    if existing.startswith('# Property Updates'):
        rest = existing[len('# Property Updates'):].lstrip('\n')
        rendered = '# Property Updates\n\n' + entry + rest
    else:
        rendered = '# Property Updates\n\n' + entry + existing
    if not args.dry_run:
        path.write_text(rendered)
    print(json.dumps({'file': str(path), 'date': d.isoformat(), 'header': header, 'deduped': False, 'dry_run': args.dry_run}, indent=2))


if __name__ == '__main__':
    main()
