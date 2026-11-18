#!/usr/bin/env python3
"""Offline resource consistency locks. No native, datasheet-semantic or release approval."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import stat

from npi_common import children, finite_tree
from schematic_io import parse


SCOPE = 'project_resource_consistency_only'
ELECTRICAL_TYPES = {'input', 'output', 'bidirectional', 'tri_state', 'passive', 'free',
                    'unspecified', 'power_in', 'power_out', 'open_collector', 'open_emitter', 'no_connect'}
LIMITATIONS = [
    'Local syntax, declared identities, pin/pad mapping and content hashes only.',
    'Manufacturer identity, document applicability, dimensions and electrical semantics require independent review.',
    'Does not prove schematic/PCB usage, KLC/native validity, 3D correctness or manufacturing approval.',
    'A local lock is an unsigned baseline, not an authenticated approval or a malicious-tampering guarantee.',
]


def keys(value, required, optional=()):
    if not isinstance(value, dict):
        raise ValueError('Expected an object')
    missing = set(required) - set(value)
    unknown = set(value) - set(required) - set(optional)
    if missing or unknown:
        raise ValueError('Missing/unknown fields: ' + str(sorted(missing)) + '/' + str(sorted(unknown)))


def text(value, label):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or re.fullmatch(r'(?i)(unknown|tbd|todo|n/a|none|\?)', value)):
        raise ValueError('Explicit non-placeholder ' + label + ' required')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def linked(path):
    """Reject symbolic links, Windows junctions and other reparse points."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))


def no_links(path):
    for candidate in (path, *path.parents):
        if linked(candidate):
            raise ValueError('Linked/reparse path refused: ' + str(candidate))


def project_root(project):
    root = Path(project).absolute()
    no_links(root)
    if not root.is_dir():
        raise ValueError('Existing project directory required')
    return root.resolve()


def local(root, name):
    text(name, 'project-relative path')
    if ('\\' in name or ':' in name or '${' in name or '\x00' in name
            or PureWindowsPath(name).drive or Path(name).is_absolute()
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Use a normalized relative path with forward slashes: ' + name)
    path = root / name
    no_links(path)
    if not path.resolve().is_relative_to(root):
        raise ValueError('Path escapes project: ' + name)
    return path


def read_bytes(path):
    no_links(path)
    if not path.is_file():
        raise ValueError('Missing resource file: ' + str(path))
    data = path.read_bytes()
    if not data:
        raise ValueError('Empty resource file: ' + str(path))
    return data


def json_bytes(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result

    return finite_tree(json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs))


def file_record(root, record, inputs, extra=()):
    keys(record, ('file', 'sha256', *extra))
    path = local(root, record['file'])
    if not re.fullmatch('[0-9a-f]{64}', str(record['sha256'])):
        raise ValueError('Explicit lowercase SHA-256 required: ' + record['file'])
    data = read_bytes(path)
    actual = digest(data)
    if actual != record['sha256']:
        raise ValueError('Missing/changed resource hash: ' + record['file'])
    inputs[record['file']] = actual
    return path, data


def symbol_pins(data, name):
    tree = parse(data.decode('utf-8-sig'))
    if not tree or tree[0] != 'kicad_symbol_lib':
        raise ValueError('Expected kicad_symbol_lib')
    matches = [node for node in children(tree, 'symbol') if len(node) > 1 and node[1] == name]
    if len(matches) != 1:
        raise ValueError('Missing/ambiguous symbol name: ' + name)
    symbol = matches[0]
    if children(symbol, 'extends'):
        raise ValueError('Inherited symbols require an independently resolved candidate; unsupported here')
    pins = {}

    def visit(node):
        for entry in node[1:]:
            if not isinstance(entry, list) or not entry:
                continue
            if entry[0] == 'pin':
                numbers, names = children(entry, 'number'), children(entry, 'name')
                if len(numbers) != 1 or len(names) != 1 or len(numbers[0]) < 2 or len(names[0]) < 2 or len(entry) < 3:
                    raise ValueError('Unsupported symbol pin structure')
                number = text(numbers[0][1], 'symbol pin number')
                if number in pins:
                    raise ValueError('Repeated symbol pin number/alternate unit unsupported: ' + number)
                if entry[1] not in ELECTRICAL_TYPES:
                    raise ValueError('Unknown symbol electrical type: ' + str(entry[1]))
                pins[number] = {'name': text(names[0][1], 'symbol pin name'),
                                'electrical_type': text(entry[1], 'symbol electrical type')}
            elif entry[0] == 'symbol':
                visit(entry)

    visit(symbol)
    if not pins:
        raise ValueError('Symbol has no supported explicit pins')
    footprint_props = [node[2] for node in children(symbol, 'property')
                       if len(node) > 2 and node[1] == 'Footprint']
    if len(footprint_props) > 1:
        raise ValueError('Ambiguous Footprint property')
    return pins, footprint_props[0] if footprint_props else ''


def footprint_pads(data, name):
    tree = parse(data.decode('utf-8-sig'))
    if not tree or tree[0] != 'footprint' or len(tree) < 2 or tree[1] != name:
        raise ValueError('Footprint name/root mismatch: ' + name)
    pads = Counter()
    mechanical = 0
    for pad in children(tree, 'pad'):
        if len(pad) < 4:
            raise ValueError('Unsupported footprint pad')
        if pad[2] == 'np_thru_hole' and pad[1] == '':
            mechanical += 1
            continue
        if pad[2] not in ('smd', 'thru_hole', 'connect'):
            raise ValueError('Unsupported/unmapped mechanical pad type')
        pads[text(pad[1], 'electrical pad number')] += 1
    if not pads:
        raise ValueError('Footprint has no supported electrical pads')
    return dict(sorted(pads.items())), mechanical


def audit(project, manifest):
    root = project_root(project)
    manifest_path = local(root, manifest)
    manifest_data = read_bytes(manifest_path)
    config = json_bytes(manifest_data)
    keys(config, ('schema_version', 'project_id', 'resources'))
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ValueError('Unknown resource manifest schema')
    text(config['project_id'], 'project_id')
    if not isinstance(config['resources'], list) or not config['resources']:
        raise ValueError('Explicit nonempty resources required')
    inputs = {manifest: digest(manifest_data)}
    results, identifiers = [], set()
    for resource in config['resources']:
        keys(resource, ('id', 'manufacturer', 'mpn', 'package', 'basis', 'symbol', 'footprint', 'pin_pad_map'), ('models',))
        for field in ('id', 'manufacturer', 'mpn', 'package'):
            text(resource[field], field)
        if resource['id'] in identifiers:
            raise ValueError('Duplicate resource id: ' + resource['id'])
        identifiers.add(resource['id'])
        basis = resource['basis']
        for field in ('document', 'revision', 'locator'):
            text(basis.get(field) if isinstance(basis, dict) else None, 'manufacturer basis ' + field)
        if basis.get('authority') != 'manufacturer':
            raise ValueError('Explicit manufacturer basis required; supplier CAD is not independent pinout evidence')
        file_record(root, basis, inputs, ('document', 'revision', 'locator', 'authority'))
        symbol, footprint = resource['symbol'], resource['footprint']
        symbol_path, symbol_data = file_record(root, symbol, inputs, ('name',))
        footprint_path, footprint_data = file_record(root, footprint, inputs, ('name', 'library_id'))
        text(symbol['name'], 'exact symbol name')
        text(footprint['name'], 'exact footprint name')
        text(footprint['library_id'], 'exact footprint library_id')
        if (symbol_path.suffix != '.kicad_sym' or footprint_path.suffix != '.kicad_mod'
                or footprint['library_id'].count(':') != 1
                or not footprint['library_id'].split(':')[0]
                or footprint['library_id'].split(':')[1] != footprint['name']):
            raise ValueError('Wrong resource suffix or footprint library identity')
        pins, footprint_property = symbol_pins(symbol_data, symbol['name'])
        pads, mechanical = footprint_pads(footprint_data, footprint['name'])
        if footprint_property and footprint_property != footprint['library_id']:
            raise ValueError('Symbol Footprint property differs from declared footprint')
        mapping = resource['pin_pad_map']
        if not isinstance(mapping, list) or not mapping:
            raise ValueError('Explicit full pin_pad_map required')
        mapped_pins, mapped_pads = set(), set()
        for entry in mapping:
            keys(entry, ('pin', 'name', 'electrical_type', 'pads'))
            number = text(entry['pin'], 'mapped pin')
            if number in mapped_pins or pins.get(number) != {key: entry[key] for key in ('name', 'electrical_type')}:
                raise ValueError('Missing/duplicate/mismatched symbol pin mapping: ' + number)
            mapped_pins.add(number)
            if not isinstance(entry['pads'], list) or not entry['pads']:
                raise ValueError('Every symbol pin must map to explicit physical pad numbers')
            for pad in entry['pads']:
                text(pad, 'mapped pad')
                if pad not in pads or pad in mapped_pads:
                    raise ValueError('Missing/duplicate/ambiguous pad mapping: ' + pad)
                mapped_pads.add(pad)
        if mapped_pins != set(pins) or mapped_pads != set(pads):
            raise ValueError('Mapping does not cover every symbol pin and electrical pad number')
        models = resource.get('models', [])
        if not isinstance(models, list):
            raise ValueError('models must be a list')
        model_files = set()
        for model in models:
            path, _ = file_record(root, model, inputs)
            if path.suffix.lower() not in ('.step', '.stp', '.wrl') or model['file'] in model_files:
                raise ValueError('Unsupported/duplicate model resource')
            model_files.add(model['file'])
        results.append({'id': resource['id'], 'manufacturer': resource['manufacturer'],
                        'mpn': resource['mpn'], 'package': resource['package'],
                        'symbol_name': symbol['name'], 'symbol_pins': dict(sorted(pins.items())),
                        'footprint_library_id': footprint['library_id'], 'pad_instances': pads,
                        'unnumbered_np_thru_holes': mechanical, 'pin_pad_map': mapping,
                        'models': sorted(model_files)})
    return {'schema_version': 1, 'kind': 'project-resource-lock', 'scope': SCOPE,
            'project_id': config['project_id'], 'manifest': manifest,
            'manifest_sha256': digest(manifest_data), 'inputs_sha256': dict(sorted(inputs.items())),
            'resources': results, 'limitations': LIMITATIONS, 'production_authorized': False}


def output_path(root, output):
    path = Path(output)
    if not path.is_absolute():
        path = local(root, str(output))
    path = path.absolute()
    no_links(path)
    if path.exists() or path.is_symlink():
        raise ValueError('Output already exists; use a NEW independent JSON file')
    if path.suffix.lower() != '.json' or not path.parent.is_dir():
        raise ValueError('Output must be a new JSON file in an existing explicit directory')
    return path


def write_new(path, value):
    no_links(path)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def lock(project, manifest, output, apply=False):
    root = project_root(project)
    result = audit(root, manifest)
    destination = output_path(root, output)
    if apply:
        if audit(root, manifest) != result:
            raise ValueError('Resource inputs changed during lock; retry from current inputs')
        write_new(destination, result)
    return {'status': 'RESOURCE_LOCK_CREATED_NOT_APPROVED' if apply else 'PREVIEW',
            'scope': SCOPE, 'written': apply, 'output': str(destination),
            'production_authorized': False, 'lock': result}


def check(project, lock_file, output=None, apply=False, review_config=None):
    root = project_root(project)
    path = Path(lock_file)
    if not path.is_absolute():
        path = local(root, lock_file)
    baseline_data = read_bytes(path)
    baseline = json_bytes(baseline_data)
    keys(baseline, ('schema_version', 'kind', 'scope', 'project_id', 'manifest', 'manifest_sha256',
                    'inputs_sha256', 'resources', 'limitations', 'production_authorized'))
    current = audit(root, baseline['manifest'])
    if (json.dumps(baseline, sort_keys=True, separators=(',', ':'), allow_nan=False)
            != json.dumps(current, sort_keys=True, separators=(',', ':'), allow_nan=False)):
        raise ValueError('Resource lock differs from current declaration/files or has been changed')
    if read_bytes(path) != baseline_data:
        raise ValueError('Lock changed during check')
    result = {'status': 'RESOURCE_CONSISTENCY_CHECKED_NOT_APPROVED', 'scope': SCOPE,
              'production_authorized': False, 'written': False, 'lock_sha256': digest(baseline_data),
              'resource_count': len(current['resources']), 'inputs_sha256': current['inputs_sha256'],
              'limitations': LIMITATIONS}
    if review_config is not None:
        from device_knowledge import project_stage_brief
        config_path = Path(review_config).resolve()
        # A compiled workflow bundle may reside outside the project; this is an
        # explicit trusted caller-supplied configuration, never a download URL.
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
        binding = config.get('device_knowledge')
        if config.get('require_device_knowledge') is True and not binding:
            raise ValueError('G2 needs the project-frozen device knowledge binding')
        if binding:
            stage_brief, _ = project_stage_brief(root, binding, 'g2')
            if stage_brief['coverage_gaps']:
                raise ValueError('G2 stage knowledge missing: ' + json.dumps(stage_brief['coverage_gaps'], ensure_ascii=False))
            # No approximate MPN/package matches; a project resource lock must
            # cover every core device described by the frozen device bundle.
            locked = {(x['manufacturer'], x['mpn'], x['package']) for x in current['resources']}
            unmatched = [x['ref'] for x in stage_brief['devices']
                         if (x['manufacturer'], x['mpn'], x['package']) not in locked]
            if unmatched:
                raise ValueError('Frozen core devices lack exact symbol/footprint resource lock: '+','.join(unmatched))
            result['g2_device_knowledge'] = stage_brief
            result['g2_state']='VERIFIED_SOURCE_CANDIDATES_CURRENT_PROJECT_PIN_PAD_REVIEW_REQUIRED'
            result['limitations'] = LIMITATIONS + [
                'Manufacturer card reuse is not an automated pinout, land-pattern or physical design approval.']
    if apply and output is None:
        raise ValueError('--apply requires an explicit NEW --output report file')
    if output is not None:
        destination = output_path(root, output)
        result['output'] = str(destination)
        if apply:
            result['written'] = True
            write_new(destination, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('lock', help='Validate explicit resources; preview unless --apply')
    create.add_argument('project')
    create.add_argument('--manifest', required=True, help='Project-relative JSON manifest')
    create.add_argument('--output', required=True, help='NEW JSON file; relative to project unless absolute')
    create.add_argument('--apply', action='store_true')
    verify = sub.add_parser('check', help='Offline read-only consistency verification')
    verify.add_argument('project')
    verify.add_argument('--lock', required=True, dest='lock_file')
    verify.add_argument('--output', help='Optional NEW report; preview unless --apply')
    verify.add_argument('--apply', action='store_true')
    verify.add_argument('--review-config', help='Compiled static-review config with frozen device_knowledge, for G2')
    args = parser.parse_args(argv)
    try:
        if args.command == 'lock':
            result = lock(args.project, args.manifest, args.output, args.apply)
        else:
            result = check(args.project, args.lock_file, args.output, args.apply, args.review_config)
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as exc:
        result = {'status': 'BLOCKED', 'scope': SCOPE, 'production_authorized': False,
                  'written': False, 'findings': [{'rule': 'RESOURCE.CONSISTENCY', 'level': '\u963b\u65ad\u7ea7',
                    'description': str(exc), 'suggestion': 'Restore explicit current resources and independent manufacturer evidence; do not weaken the mapping or overwrite a prior lock.'}]}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
