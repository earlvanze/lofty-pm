#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

DATE_TOKEN_RE = re.compile(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b')
DATE_RANGE_RE = re.compile(
    r'\((\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*-\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|month-to-month)\)',
    re.I,
)
OCCUPANCY_SECTION_RE = re.compile(r'(?ms)^##\s+Occupancy Status\s*$\n(.*?)(?=^##\s+|\Z)')
LEASE_FILENAME_RANGE_RE = re.compile(r'(\d{2})[-.](\d{2})[-.](\d{4})\s*-\s*(\d{2})[-.](\d{2})[-.](\d{4}|month-to-month)', re.I)
DOCX_CREATED_RE = re.compile(r'<dcterms:created[^>]*>([^<]+)</dcterms:created>', re.I)
MONTH_NAME_DATE_RE = re.compile(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:\s*(?:st|nd|rd|th))?\s*,\s*(\d{4})', re.I)
TERM_RE = re.compile(r'beginning\s+(.{1,40}?)\s+and\s+ending\s+(.{1,40}?)(?:\.|\n)', re.I)
STR_EXCLUDE_RE = re.compile(r'\b724\b')
WORKSPACE_ROOT = Path(os.environ.get('LOFTY_PM_WORKSPACE_ROOT') or Path(__file__).resolve().parents[3])
REAL_ESTATE_ROOT = Path(os.environ.get('LOFTY_PM_REAL_ESTATE_ROOT') or (WORKSPACE_ROOT / 'Dropbox' / 'Real Estate'))


def load_json(path: Path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return data
    properties = list(data.get('properties') or [])
    unresolved = list(data.get('unresolved') or [])
    return properties + unresolved if (properties or unresolved) else data


def normalize_mmddyyyy(value: str) -> str:
    value = value.strip().replace('-', '/')
    parts = value.split('/')
    if len(parts) != 3:
        raise ValueError(f'unrecognized date: {value!r}')
    month, day, year = [int(x) for x in parts]
    if year < 100:
        year += 2000
    return f'{month:02d}/{day:02d}/{year:04d}'


def to_iso(value: str) -> str:
    mmddyyyy = normalize_mmddyyyy(value)
    month, day, year = [int(x) for x in mmddyyyy.split('/')]
    return dt.date(year, month, day).isoformat()


def normalize_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def property_needles(prop: dict) -> list[str]:
    needles = [
        normalize_key(prop.get('full_address') or ''),
        normalize_key(prop.get('property_name') or ''),
        normalize_key(prop.get('assetUnit') or ''),
    ]
    full_address = (prop.get('full_address') or '').strip()
    if full_address:
        street_only = full_address.split(',', 1)[0].strip()
        needles.append(normalize_key(street_only))
    return [needle for needle in dict.fromkeys(needles) if needle]


def derive_description_path(prop: dict) -> Path | None:
    explicit = prop.get('description_md') or prop.get('description_file') or prop.get('description_path')
    if explicit:
        return Path(explicit)
    updates_md = prop.get('updates_md')
    candidate = None
    search_root = None
    if updates_md:
        updates_path = Path(updates_md)
        candidate = updates_path.parent.parent / 'DESCRIPTION.md'
        if candidate.exists():
            return candidate
        public_dir = updates_path.parent.parent
        matches = sorted(public_dir.glob('DESCRIPTION*.md'))
        if matches:
            return matches[0]
        search_root = updates_path.parents[4] if len(updates_path.parents) >= 5 else None

    search_root = search_root if search_root and search_root.exists() else REAL_ESTATE_ROOT if REAL_ESTATE_ROOT.exists() else None
    if search_root and search_root.exists():
        needles = property_needles(prop)
        scored = []
        for path in search_root.rglob('DESCRIPTION*.md'):
            hay = normalize_key(str(path.parent.parent))
            score = sum(1 for needle in needles if needle and needle in hay)
            if score:
                scored.append((score, len(str(path)), path))
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            return scored[0][2]
    return candidate


def extract_occupancy_sections(text: str) -> list[str]:
    return [m.group(1).strip() for m in OCCUPANCY_SECTION_RE.finditer(text)]


def derive_property_root(prop: dict, description_path: Path | None) -> Path | None:
    if description_path:
        return description_path.parent.parent
    updates_md = prop.get('updates_md')
    return Path(updates_md).parent.parent if updates_md else None


def related_property_roots(prop: dict, description_path: Path | None, prop_root: Path | None) -> list[Path]:
    roots = []

    def add(path: Path | None):
        if path and path.exists() and path not in roots:
            roots.append(path)

    add(prop_root)
    if description_path:
        add(description_path.parent)

    if not REAL_ESTATE_ROOT.exists():
        return roots

    needles = property_needles(prop)
    scored = []
    for state_dir in REAL_ESTATE_ROOT.iterdir():
        if not state_dir.is_dir():
            continue
        for candidate in state_dir.iterdir():
            if not candidate.is_dir():
                continue
            hay = normalize_key(str(candidate))
            score = sum(1 for needle in needles if needle and needle in hay)
            if score:
                scored.append((score, len(str(candidate)), candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    for _, _, candidate in scored[:8]:
        add(candidate)
    return roots


def normalize_doc_text(text: str) -> str:
    text = text.replace('\r', '\n')
    text = re.sub(r'\s+', ' ', text)
    text = text.replace(' / ', '/').replace('/ ', '/').replace(' /', '/')
    return text.strip()


def parse_date_loose(value: str) -> str | None:
    value = value.strip()
    m = MONTH_NAME_DATE_RE.search(value)
    if m:
        month = dt.datetime.strptime(m.group(1)[:3], '%b').month
        day = int(m.group(2))
        year = int(m.group(3))
        return f'{month:02d}/{day:02d}/{year:04d}'
    m = DATE_TOKEN_RE.search(value)
    if m:
        return normalize_mmddyyyy(m.group(1))
    return None


def read_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read('word/document.xml').decode('utf-8', 'ignore')
        return normalize_doc_text(re.sub(r'<[^>]+>', ' ', xml))
    except Exception:
        return ''


def docx_created_date(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as zf:
            core = zf.read('docProps/core.xml').decode('utf-8', 'ignore')
        m = DOCX_CREATED_RE.search(core)
        if not m:
            return None
        return dt.datetime.fromisoformat(m.group(1).replace('Z', '+00:00')).date().strftime('%m/%d/%Y')
    except Exception:
        return None


def pdf_created_date(path: Path) -> str | None:
    try:
        out = subprocess.check_output(['pdfinfo', str(path)], text=True, stderr=subprocess.STDOUT)
    except Exception:
        return None
    for line in out.splitlines():
        lowered = line.lower()
        if not (lowered.startswith('creationdate:') or lowered.startswith('moddate:')):
            continue
        value = line.split(':', 1)[1].strip()
        for fmt in ('%a %b %d %H:%M:%S %Y %Z', '%Y-%m-%dT%H:%M:%S%z'):
            try:
                return dt.datetime.strptime(value, fmt).strftime('%m/%d/%Y')
            except Exception:
                pass
        m = re.search(r'(\d{4})(\d{2})(\d{2})', value)
        if m:
            return f"{int(m.group(2)):02d}/{int(m.group(3)):02d}/{int(m.group(1)):04d}"
    return None


def latest_active_lease_start(search_roots: list[Path], as_of: dt.date | None = None) -> tuple[str | None, str | None]:
    if not search_roots:
        return None, None
    as_of = as_of or dt.date.today()
    candidates = []
    seen = set()
    for root in search_roots:
        for path in root.rglob('*'):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            lower = path.name.lower()
            if 'lease' not in lower or path.suffix.lower() not in {'.pdf', '.docx', '.doc'}:
                continue
            start = end = None
            m = LEASE_FILENAME_RANGE_RE.search(path.name)
            if m:
                start = f'{int(m.group(1)):02d}/{int(m.group(2)):02d}/{int(m.group(3)):04d}'
                if m.group(6).lower() == 'month-to-month':
                    end = 'month-to-month'
                else:
                    end = f'{int(m.group(4)):02d}/{int(m.group(5)):02d}/{int(m.group(6)):04d}'
            elif path.suffix.lower() == '.docx':
                text = read_docx_text(path)
                term = TERM_RE.search(text)
                if term:
                    start = parse_date_loose(term.group(1) or '')
                    end_value = (term.group(2) or '').strip()
                    end = 'month-to-month' if 'month-to-month' in end_value.lower() else parse_date_loose(end_value)
            if not start:
                continue
            active = end == 'month-to-month' or (end and dt.date.fromisoformat(to_iso(end)) >= as_of)
            if active:
                sort_end = dt.date.max if end == 'month-to-month' else dt.date.fromisoformat(to_iso(end))
                candidates.append((sort_end, dt.date.fromisoformat(to_iso(start)), path))
    if not candidates:
        return None, None
    candidates.sort(reverse=True)
    _, start_date, path = candidates[0]
    return start_date.strftime('%m/%d/%Y'), str(path)


def is_short_term_rental(prop: dict, description_text: str) -> bool:
    full = ' '.join(filter(None, [prop.get('property_name', ''), prop.get('full_address', ''), description_text]))
    norm = normalize_key(full)
    if STR_EXCLUDE_RE.search(full):
        return False
    if any(token in norm for token in ['22164 umland', '27 pillar', '402 n wild olive', 'madison ave', '85 104 alawa']):
        return True
    if any(token in norm for token in [' vacation rental', ' short term rental', ' airbnb']):
        state = (prop.get('full_address') or '').upper()
        return any(mark in state for mark in [', CA ', ', HI ', ', NY '])
    return False


def pma_creation_date(search_roots: list[Path]) -> tuple[str | None, str | None]:
    if not search_roots:
        return None, None
    candidates = []
    seen = set()
    for root in search_roots:
        for path in root.rglob('*'):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            name = path.name.lower()
            path_lower = str(path).lower()
            if 'management agreement' not in name and 'property_management_agreement' not in name and 'property management agreement' not in name:
                continue
            if any(bad in path_lower for bad in ['archive', '/transfer/', ' transfer/']) or any(bad in name for bad in ['amendment', 'addendum']):
                continue
            created = docx_created_date(path) if path.suffix.lower() == '.docx' else pdf_created_date(path) if path.suffix.lower() == '.pdf' else None
            if not created:
                continue
            penalty = 0 if ('property management agreement' in name or 'property_management_agreement' in name) else 1
            if '/public/' not in path_lower and ' public/' not in path_lower:
                penalty += 1
            if 'short-term' in name or 'co-host' in name:
                penalty += 1
            candidates.append((penalty, dt.date.fromisoformat(to_iso(created)), path))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, created_date, path = candidates[0]
    return created_date.strftime('%m/%d/%Y'), str(path)


def infer_status(section_text: str, candidates: list[str]) -> str:
    lowered = section_text.lower()
    if candidates:
        return 'extractable'
    if 'vacant' in lowered:
        return 'vacant'
    if 'month-to-month' in lowered:
        return 'month_to_month_no_start'
    if 'occupied' in lowered or 'lease' in lowered or 'leased' in lowered:
        return 'mentioned_but_unparseable'
    return 'empty_occupancy_status'


def choose_candidate(candidates: list[str], strategy: str) -> str | None:
    if not candidates:
        return None
    unique = list(dict.fromkeys(candidates))
    if len(unique) == 1:
        return unique[0]
    if strategy == 'ambiguous':
        return None
    if strategy == 'first':
        return unique[0]
    if strategy == 'earliest':
        return min(unique, key=to_iso)
    if strategy == 'latest':
        return max(unique, key=to_iso)
    raise ValueError(f'unsupported strategy: {strategy}')


def analyze_property(prop: dict, strategy: str) -> dict:
    description_path = derive_description_path(prop)
    prop_root = derive_property_root(prop, description_path)
    search_roots = related_property_roots(prop, description_path, prop_root)
    base = {
        'property_name': prop.get('property_name') or prop.get('full_address') or prop.get('slug') or prop.get('lofty_property_id'),
        'full_address': prop.get('full_address'),
        'assetUnit': prop.get('assetUnit'),
        'lofty_property_id': prop.get('lofty_property_id'),
        'slug': prop.get('slug'),
        'description_path': str(description_path) if description_path else None,
        'property_root': str(prop_root) if prop_root else None,
        'search_roots': [str(path) for path in search_roots],
    }
    if not description_path:
        return {**base, 'status': 'missing_description_path', 'candidates': [], 'chosen': None}
    if not description_path.exists():
        return {**base, 'status': 'description_missing', 'candidates': [], 'chosen': None}

    text = description_path.read_text(encoding='utf-8', errors='ignore')
    sections = extract_occupancy_sections(text)

    raw_candidates = []
    section_statuses = []
    for section in sections:
        section_candidates = [normalize_mmddyyyy(m.group(1)) for m in DATE_RANGE_RE.finditer(section)]
        if not section_candidates:
            for line in section.splitlines():
                lowered = line.lower()
                if 'lease' not in lowered and 'leased' not in lowered:
                    continue
                tokens = DATE_TOKEN_RE.findall(line)
                if tokens:
                    section_candidates.append(normalize_mmddyyyy(tokens[0]))
        raw_candidates.extend(section_candidates)
        section_statuses.append(infer_status(section, section_candidates))

    candidates = list(dict.fromkeys(raw_candidates))
    chosen = choose_candidate(candidates, strategy)
    fallback_source = None
    if chosen:
        status = 'extractable' if len(candidates) == 1 else f'extractable_{strategy}'
    elif candidates:
        status = 'ambiguous_multiple_dates'
    else:
        status = next((s for s in section_statuses if s != 'empty_occupancy_status'), 'missing_occupancy_section' if not sections else 'empty_occupancy_status')
        lease_start, lease_source = latest_active_lease_start(search_roots)
        if lease_start:
            chosen = lease_start
            status = 'extractable_active_lease'
            fallback_source = lease_source
        elif is_short_term_rental(prop, text):
            pma_start, pma_source = pma_creation_date(search_roots)
            if pma_start:
                chosen = pma_start
                status = 'extractable_pma_creation_date'
                fallback_source = pma_source

    return {
        **base,
        'status': status,
        'candidates': [
            {'display': value, 'iso': to_iso(value)}
            for value in candidates
        ],
        'chosen': {'display': chosen, 'iso': to_iso(chosen)} if chosen else None,
        'occupancy_sections': len(sections),
        'fallback_source': fallback_source,
    }


def summarize(results: list[dict]) -> dict:
    counts = {}
    for row in results:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    return {
        'properties': len(results),
        'extractable': sum(1 for r in results if r.get('chosen')),
        'ambiguous': sum(1 for r in results if r['status'] == 'ambiguous_multiple_dates'),
        'missing_or_unusable': sum(1 for r in results if not r.get('chosen')),
        'by_status': counts,
    }


def filter_properties(props: list[dict], query: str | None) -> list[dict]:
    if not query:
        return props
    q = query.lower()
    out = []
    for prop in props:
        haystacks = [
            prop.get('property_name', ''),
            prop.get('full_address', ''),
            prop.get('assetUnit', ''),
            prop.get('lofty_property_id', ''),
            prop.get('slug', ''),
        ]
        if any(q in str(h).lower() for h in haystacks if h):
            out.append(prop)
    return out


def main():
    ap = argparse.ArgumentParser(description='Extract lease_begins_date candidates from Lofty property DESCRIPTION.md files')
    ap.add_argument('--property-map', default=str(Path(__file__).resolve().parent.parent / 'config' / 'property_update_map.json'))
    ap.add_argument('--property')
    ap.add_argument('--multi-date-strategy', choices=('ambiguous', 'first', 'earliest', 'latest'), default='ambiguous')
    ap.add_argument('--report-file')
    ap.add_argument('--status')
    args = ap.parse_args()

    props = filter_properties(load_json(Path(args.property_map)), args.property)
    if args.property and not props:
        raise SystemExit(f'No property matched {args.property!r}')

    results = [analyze_property(prop, args.multi_date_strategy) for prop in props]
    if args.status:
        requested = {token.strip() for token in args.status.split(',') if token.strip()}
        results = [row for row in results if row['status'] in requested]
    payload = {
        'summary': summarize(results),
        'properties': results,
    }
    rendered = json.dumps(payload, indent=2)
    if args.report_file:
        out = Path(args.report_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + '\n')
    print(rendered)


if __name__ == '__main__':
    main()
