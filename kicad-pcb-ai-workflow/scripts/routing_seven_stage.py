#!/usr/bin/env python3
"""Read-only seven-stage PCB routing plan and native board-result audit.

Freerouting prepares an offline DSN/SES candidate. Konnect/KiCad performs all
live board writes and final native checks. This utility NEVER imports SES,
edits copper, runs DRC or authorizes a manufacturing release.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from npi_common import child, children, parse_sexpr, value
import routing_policy as policy
from freerouting_adapter import specctra_netclasses

SAFE_NETS = {'LOW_SPEED_DIGITAL', 'GENERAL_SIGNAL'}
PROTECTED_CATEGORIES = {
    'GND', 'REFERENCE_PLANE', 'POWER_DISTRIBUTION', 'POWER_HIGH_CURRENT',
    'SWITCHING_HOT_LOOP', 'DIFFERENTIAL_HIGH_SPEED', 'CLOCK_CRITICAL',
    'TIMING_MATCHED_BUS', 'ANALOG_SENSITIVE', 'KELVIN_SENSE',
    'RF_CONTROLLED_IMPEDANCE', 'MANUAL_ONLY'
}
SHA_RE = re.compile(r'^[0-9a-f]{64}$')


class RoutingBlocked(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail)


def require(predicate, code, detail):
    if not predicate:
        raise RoutingBlocked(code, detail)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(root, rel):
    require(isinstance(rel, str) and rel and not re.match(r'^[A-Za-z]:', rel)
            and not rel.startswith(('/', '\\')), 'UNSAFE_PATH', str(rel))
    parts = re.split(r'[/\\]', rel)
    require('..' not in parts and '.' not in parts and all(parts), 'UNSAFE_PATH', rel)
    candidate = root.joinpath(*parts)
    require(not candidate.is_symlink(), 'UNSAFE_PATH', rel)
    p = candidate.resolve()
    require(p.is_relative_to(root) and p.is_file(), 'MISSING_INPUT', rel)
    return p


def checked(root, binding):
    require(isinstance(binding, dict) and set(binding) == {'file', 'sha256'},
            'INVALID_BINDING', 'file/sha256 required')
    require(isinstance(binding['sha256'], str) and SHA_RE.fullmatch(binding['sha256']),
            'INVALID_HASH', str(binding['sha256']))
    p = local(root, binding['file'])
    require(sha(p) == binding['sha256'], 'HASH_MISMATCH', binding['file'])
    return p


def load(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'DUPLICATE_JSON_KEY', k)
            result[k] = v
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      object_pairs_hook=pairs)


def plan(root, config_path):
    config = load(local(root, config_path))
    require(config.get('schema_version') == 1 and config.get('stage') == 'plan',
            'INVALID_STAGE', 'plan requires schema_version=1, stage=plan')
    request_path = local(root, config.get('routing_request'))
    req, seen, details = policy._validate_request(root, config['routing_request'])
    dsn = checked(root, config.get('dsn'))
    classes_file = checked(root, config.get('netclass_map'))
    netclasses = load(classes_file)
    require(netclasses.get('schema_version') == 1
            and netclasses.get('board_sha256') == req['inputs']['board']['sha256']
            and netclasses.get('dsn_sha256') == sha(dsn)
            and isinstance(netclasses.get('net_to_class'), dict),
            'STALE_NATIVE_CLASS_MAP', 'Native board/DSN mapping must match source hashes')
    known = specctra_netclasses(dsn)
    class_map = netclasses['net_to_class']
    inventory = {n['name']: set(n['categories']) for n in req['networks']}
    require(set(class_map) == set(inventory), 'INCOMPLETE_CLASS_MAP',
            'Every classified net must have a native effective NetClass mapping')
    require(all(isinstance(v, str) and v in known for v in class_map.values()),
            'DSN_CLASS_MISMATCH', 'Mapped class must be declared in DSN')
    gnd, critical, ordinary = [], [], []
    for name, tags in sorted(inventory.items()):
        if tags & {'GND', 'REFERENCE_PLANE'}:
            gnd.append(name)
        elif tags & PROTECTED_CATEGORIES or not tags <= SAFE_NETS:
            critical.append(name)
        else:
            ordinary.append(name)
    excluded_classes = sorted({class_map[n] for n in gnd + critical})
    overlap = sorted(n for n in ordinary if class_map[n] in excluded_classes)
    require(not overlap, 'MIXED_NETCLASS_NOT_ISOLATED',
            'Critical/GND and ordinary nets share a Freerouting NetClass: ' + ', '.join(overlap))
    require(gnd and excluded_classes, 'GND_CLASS_NOT_EXCLUDED',
            'Provide a dedicated GND NetClass before ordinary autorouting')
    steps = [
        '01_FULL_NET_INVENTORY',
        '02_NATIVE_RULES_APPLIED_AND_READ_BACK',
        '03_CRITICAL_NETS_ROUTED_AND_PROTECTED',
        '04_FREEROUTING_2_5_0_ORDINARY_DSN_SES',
        '05_ISOLATED_SES_IMPORT_AND_GEOMETRY_AUDIT',
        '06_BOUNDED_REPAIR_WITHOUT_RULE_RELAXATION',
        '07_GND_ZONE_FILL_SAVE_RELOAD_NATIVE_DRC_G4',
    ]
    return {
        'status': 'PLAN_READY_NOT_EXECUTED', 'production_authorized': False,
        'execution_scope': 'read_only_planning',
        'routing_request_sha256': sha(request_path), 'dsn_sha256': sha(dsn),
        'native_class_map_sha256': sha(classes_file),
        'priority': {'P0_P1_P2_critical_protected': critical,
                     'P3_freerouting_ordinary': ordinary,
                     'P4_gnd_zone_no_ordinary_tracks': gnd},
        'freerouting_exclude_netclasses': excluded_classes,
        'stages': steps,
        'required_external_acceptance': [
            'Native KiCad effective NetClass memberships and applied factory rules',
            'Critical traces and all protected-object snapshots before external routing',
            'Approved Freerouting v2.5.0/JAR/DSN/rules versions and source hashes',
            'Konnect-only isolated SES import, save and reloaded board readback',
            'Native DRC, actual connectivity, zone fill, G4 and engineer sign-off'
        ],
        'warning': 'A source-bound mapping is not proof of native tool provenance. '
                   'This plan cannot authorize unattended writes or G4 release.'
    }


def board_snapshot(path):
    tree = parse_sexpr(path.read_text(encoding='utf-8-sig'))
    require(tree and tree[0] == 'kicad_pcb', 'INVALID_BOARD', str(path))
    codes = {str(n[1]): str(n[2]) for n in children(tree, 'net') if len(n) > 2}
    require(codes, 'BOARD_NETS_MISSING', str(path))
    objects = {}
    traces = {}
    segments = []
    vias = []
    arcs = []
    zones = []
    for kind in ('footprint', 'segment', 'arc', 'via', 'zone'):
        for node in children(tree, kind):
            uid = value(node, 'uuid')
            if uid:
                require(uid not in objects, 'DUPLICATE_UUID', str(uid))
                objects[uid] = json.dumps(node, sort_keys=True, ensure_ascii=True)
            n = str(value(node, 'net') or '0')
            name = codes.get(n)
            if kind in {'segment', 'via', 'arc'}:
                require(name is not None, 'UNKNOWN_TRACK_NET', str(n))
                track = {'kind': kind, 'net': name, 'node': node, 'id': uid}
                traces.setdefault(name, []).append(
                    json.dumps(node, sort_keys=True, ensure_ascii=True))
                if kind == 'segment':
                    segments.append(track)
                elif kind == 'via':
                    vias.append(track)
                else:
                    arcs.append(track)
            elif kind == 'zone':
                zones.append({'net': name, 'node': node})
    return {'codes': codes, 'objects': objects, 'traces': traces,
            'segments': segments, 'vias': vias, 'arcs': arcs, 'zones': zones}


def number(x, code):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise RoutingBlocked(code, str(x))
    require(math.isfinite(v), code, str(x))
    return v


def segments_45(s):
    start, end = child(s, 'start'), child(s, 'end')
    require(start and end and len(start) >= 3 and len(end) >= 3,
            'TRACK_GEOMETRY_MISSING', str(s)[:100])
    dx = abs(number(end[1], 'INVALID_COORD') - number(start[1], 'INVALID_COORD'))
    dy = abs(number(end[2], 'INVALID_COORD') - number(start[2], 'INVALID_COORD'))
    # 1 um tolerance prevents floating-point serialization from false positives.
    return dx < 0.001 or dy < 0.001 or abs(dx - dy) <= 0.001


def _counter(items):
    return Counter(json.dumps(x['node'], sort_keys=True, ensure_ascii=True) for x in items)


def audit(root, config_path, phase):
    config = load(local(root, config_path))
    require(config.get('schema_version') == 1 and config.get('stage') == phase,
            'INVALID_STAGE', 'Expected stage=' + phase)
    before_path = checked(root, config.get('before_board'))
    after_path = checked(root, config.get('after_board'))
    require(before_path != after_path, 'SAME_SOURCE_AND_CANDIDATE',
            'SES must be imported into a separate PCB candidate')
    before, after = board_snapshot(before_path), board_snapshot(after_path)
    before_names, after_names = set(before['codes'].values()), set(after['codes'].values())
    require(before_names == after_names, 'NET_INVENTORY_CHANGED',
            'Net names changed across SES import')
    config_nets = config.get('networks')
    require(isinstance(config_nets, dict) and bool(config_nets),
            'MISSING_NETWORK_RULES', 'Explicit ordinary network width/layer constraints required')
    protected = config.get('protected_nets')
    gnd = config.get('gnd_nets')
    require(isinstance(protected, list) and isinstance(gnd, list)
            and bool(gnd) and len(protected) == len(set(protected))
            and len(gnd) == len(set(gnd)) and set(gnd) <= set(protected),
            'INVALID_PROTECTED_NETS', 'GND must be explicitly protected')
    require(set(config_nets).isdisjoint(protected)
            and set(config_nets) | set(protected) == after_names - {''},
            'UNCLASSIFIED_OR_OVERLAPPING_NET',
            'All actual nets must be classified ordinary or protected')
    for net in protected:
        require(_counter([x for x in before['segments'] + before['vias'] + before['arcs']
                          if x['net'] == net])
                == _counter([x for x in after['segments'] + after['vias'] + after['arcs']
                              if x['net'] == net]),
                'PROTECTED_NET_COPPER_CHANGED', net)
    for uid in config.get('protected_object_uuids', []):
        require(uid in before['objects'] and
                before['objects'][uid] == after['objects'].get(uid),
                'PROTECTED_OBJECT_CHANGED', str(uid))
    added_segments = []
    added_vias = []
    added_arcs = []
    for category, out in (('segments', added_segments), ('vias', added_vias), ('arcs', added_arcs)):
        existing = _counter(before[category])
        for tr in after[category]:
            sign = json.dumps(tr['node'], sort_keys=True, ensure_ascii=True)
            if existing[sign]:
                existing[sign] -= 1
            else:
                out.append(tr)
    require(not added_arcs, 'NEW_ARC_REQUIRES_SPECIAL_REVIEW',
            'Ordinary H/V/45 profile does not permit new arcs')
    require(type(config.get('max_new_vias')) is int and config['max_new_vias'] >= 0,
            'VIA_BUDGET_MISSING', 'max_new_vias required')
    require(len(added_vias) <= config['max_new_vias'], 'VIA_BUDGET_EXCEEDED',
            str(len(added_vias)))
    for tr in added_segments:
        net = tr['net']
        require(net in config_nets, 'UNAUTHORIZED_NEW_TRACK', net)
        rule = config_nets[net]
        minw = number(rule.get('minimum_width_mm'), 'MINIMUM_WIDTH_MISSING')
        actual = number(value(tr['node'], 'width'), 'WIDTH_MISSING')
        require(minw > 0 and actual + 1e-6 >= minw, 'TRACK_WIDTH_UNDERSIZED', net)
        require(segments_45(tr['node']), 'NON_45_SEGMENT', net)
        require(value(tr['node'], 'layer') in rule.get('allowed_layers', []),
                'TRACK_LAYER_NOT_ALLOWED', net)
    for tr in added_vias:
        net = tr['net']
        require(net in config_nets, 'UNAUTHORIZED_NEW_VIA', net)
        rule = config_nets[net]
        min_d = number(rule.get('min_via_diameter_mm'), 'VIA_RULE_MISSING')
        min_drill = number(rule.get('min_via_drill_mm'), 'VIA_RULE_MISSING')
        require(number(value(tr['node'], 'size'), 'VIA_SIZE_MISSING') >= min_d
                and number(value(tr['node'], 'drill'), 'VIA_DRILL_MISSING') >= min_drill,
                'VIA_GEOMETRY_UNDERSIZED', net)
        layers = child(tr['node'], 'layers', [])[1:]
        require(len(layers) >= 2 and set(layers) <= set(rule.get('allowed_layers', [])),
                'VIA_LAYER_NOT_ALLOWED', net)
    output = {'status': 'IMPORTED_CANDIDATE_GEOMETRY_CHECKED_NOT_APPROVED',
              'phase': phase, 'production_authorized': False,
              'before_sha256': sha(before_path), 'after_sha256': sha(after_path),
              'added_segments': len(added_segments), 'added_vias': len(added_vias),
              'protected_nets': sorted(protected),
              'remaining': ['real native connectivity and G4 validation']}
    if phase == 'final':
        require(config.get('zone_refill_completed') is True,
                'ZONE_REFILL_NOT_ATTESTED', 'Native refill receipt required')
        for net in gnd:
            require(any(z['net'] == net and
                        (children(z['node'], 'filled_polygon') or
                         children(z['node'], 'filled_polygons'))
                        for z in after['zones']),
                    'GND_FILLED_ZONE_NOT_FOUND', net)
        drc_path = checked(root, config.get('native_drc_json'))
        drc = load(drc_path)
        require(isinstance(drc, dict) and isinstance(drc.get('violations'), list)
                and isinstance(drc.get('unconnected_items'), list),
                'INVALID_NATIVE_DRC_REPORT', 'KiCad DRC JSON must include violations/unconnected_items')
        blockers = [x for x in drc['violations']
                    if x.get('severity', '').lower() in {'error', 'warning'}]
        require(not blockers and not drc['unconnected_items'],
                'NATIVE_DRC_NOT_CLEAN', 'Native DRC violations/unconnected remain')
        output.update(status='NATIVE_DRC_CLEAN_REQUIRES_G4_ENGINEER_REVIEW',
                      native_drc_sha256=sha(drc_path),
                      remaining=['independent rule completeness, SI/PI, thermal, plane-return, G4 and engineer approval'])
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('plan', 'audit-import', 'audit-final'))
    p.add_argument('project', type=Path)
    p.add_argument('--config', required=True, help='Project-local, source-hash-bound routing stage config')
    args = p.parse_args()
    try:
        root = args.project.resolve()
        require(root.is_dir(), 'MISSING_PROJECT', str(root))
        if args.action == 'plan':
            out = plan(root, args.config)
        else:
            out = audit(root, args.config, 'import' if args.action == 'audit-import' else 'final')
    except (RoutingBlocked, policy.PolicyError, OSError, ValueError, KeyError, TypeError) as exc:
        out = {'status': 'BLOCKED', 'reason': getattr(exc, 'code', 'ROUTING_STAGE_INVALID'),
               'detail': str(exc), 'production_authorized': False}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 2 if out['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
