#!/usr/bin/env python3
"""Resolve the installed package's task-specific reading modules, never approvals.

No network access, nested-skill discovery, external execution or project writes.
"""
import argparse
import json
from pathlib import Path

from npi_common import runtime_inventory, sha256

ROOT = Path(__file__).resolve().parents[1]
MODULE_IDS = ('environment', 'requirements', 'resources', 'schematic',
              'pcb', 'manufacturing', 'lifecycle')
GATES = ('G1', 'G2', 'G3', 'G4', 'G5', 'G6')
STATES = ('implemented', 'experimental', 'pending_native_validation', 'not_integrated')


def _file(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Package-relative POSIX path required')
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or rel.parts[0] != 'references':
        raise ValueError('Module references must stay in package references')
    raw = root / rel
    if any(p.is_symlink() for p in (raw, *raw.parents) if p == root or root in p.parents):
        raise ValueError('Symlinked module resource refused')
    target = raw.resolve()
    if not target.is_relative_to(root) or not target.is_file() or not target.stat().st_size:
        raise ValueError('Missing module reference: ' + relative)
    return target


def registry(root=ROOT):
    root = Path(root).resolve()
    tools = runtime_inventory(root)
    path = _file(root, 'references/component-manifest.json')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if (data.get('schema_version') != 1 or data.get('skill_name') != 'kicad-pcb-ai-workflow'
            or data.get('release_channel') not in ('alpha', 'stable')
            or data.get('engineering_gates') != list(GATES)):
        raise ValueError('Unsupported component contract or engineering gates removed')
    rows = data.get('modules')
    if not isinstance(rows, list) or [r.get('id') for r in rows] != list(MODULE_IDS):
        raise ValueError('Complete ordered module registry required')
    for row in rows:
        if row.get('state') not in STATES or not row.get('label'):
            raise ValueError('Module needs explicit implementation state and label')
        references = row.get('references')
        if not isinstance(references, list) or not references or len(set(references)) != len(references):
            raise ValueError('Module needs unique focused references')
        for name in references:
            _file(root, name)
        names = row.get('tools')
        if not isinstance(names, list) or len(names) != len(set(names)) or not set(names).issubset(tools):
            raise ValueError('Unknown or duplicate module runtime tool')
        if not isinstance(row.get('intents'), list) or not row['intents']:
            raise ValueError('Module needs explicit intent routing')
    for name, route in data.get('specialist_routes', {}).items():
        if not isinstance(name, str) or not name or route.get('module') not in MODULE_IDS:
            raise ValueError('Invalid optional specialist route')
        if not route.get('references') or not route.get('tools') or not set(route['tools']).issubset(tools):
            raise ValueError('Specialist route needs explicit references and known tools')
        for reference in route['references']:
            _file(root, reference)
    return data


def fingerprint(root=ROOT):
    """Bind installed instructions/rules, without loading them into model context."""
    root = Path(root).resolve()
    data = registry(root)
    names = {'references/component-manifest.json'}
    names.update(name for row in data['modules'] for name in row['references'])
    names.update(p.relative_to(root).as_posix() for p in (root / 'references').rglob('*')
                 if p.is_file() and p.suffix in ('.md', '.json'))
    result = {name: sha256(_file(root, name)) for name in sorted(names)}
    entry = root / 'SKILL.md'
    if entry.is_symlink() or not entry.is_file():
        raise ValueError('Missing or symlinked Skill entry')
    result['SKILL.md'] = sha256(entry)
    return result


def select(module=None, intent=None, root=ROOT):
    data = registry(root)
    if module is not None and intent is not None:
        raise ValueError('Choose a module OR an intent')
    if module is not None and module not in MODULE_IDS:
        raise ValueError('Unknown module')
    rows = data['modules']
    if module:
        rows = [r for r in rows if r['id'] == module]
    elif intent in data.get('specialist_routes', {}):
        route = data['specialist_routes'][intent]
        rows = [{**r, 'references': route['references'], 'tools': route['tools'],
                 'specialist_intent': intent} for r in rows if r['id'] == route['module']]
    elif intent:
        rows = [r for r in rows if intent in r['intents']]
        if not rows:
            raise ValueError('Unknown intent; list supported module intents first')
    root = Path(root).resolve()
    selected = []
    for row in rows:
        selected.append({**row, 'reference_sha256': {
            p: sha256(_file(root, p)) for p in row['references']}})
    return {'status': 'MODULE_READING_PLAN', 'version': data['version'],
            'scope': 'reading_and_tool_discovery_only', 'production_authorized': False,
            'executed': False, 'runtime_tools': len(runtime_inventory(root)),
            'manifest_sha256': sha256(root / 'references/component-manifest.json'),
            'modules': selected,
            'note': 'Read only selected references. Tools share project state; no module or external Skill grants gate approval.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    item = sub.add_parser('select')
    group = item.add_mutually_exclusive_group(required=True)
    group.add_argument('--module', choices=MODULE_IDS)
    group.add_argument('--intent')
    args = parser.parse_args()
    try:
        result = select(getattr(args, 'module', None), getattr(args, 'intent', None))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc),
                          'production_authorized': False}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
