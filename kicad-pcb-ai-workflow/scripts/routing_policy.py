#!/usr/bin/env python3
"""Read-only constraint routing preflight; only Konnect may apply actual PCB edits.

No router, shell, KiCad mutation, DRC run, or manufacturing authorization is
implemented here. Acceptance files are hash-bound engineering records, not
identity authentication or proof of their authors' assertions.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

from netlist_guard import read_netlist
from npi_common import parse_sexpr, children, child, value

SCHEMA = 1
INPUTS = {'board', 'netlist', 'stackup', 'rules', 'protected_objects'}
CATEGORIES = {
    'LOW_SPEED_DIGITAL', 'GENERAL_SIGNAL', 'GND', 'REFERENCE_PLANE',
    'POWER_DISTRIBUTION', 'POWER_HIGH_CURRENT', 'SWITCHING_HOT_LOOP',
    'DIFFERENTIAL_HIGH_SPEED', 'CLOCK_CRITICAL', 'TIMING_MATCHED_BUS',
    'ANALOG_SENSITIVE', 'KELVIN_SENSE', 'RF_CONTROLLED_IMPEDANCE', 'MANUAL_ONLY',
}
CONSTRAINTS = {
    'copper_clearance', 'track_width', 'via_geometry', 'board_edge_clearance',
    'hole_clearance', 'keepout', 'reference_plane_integrity', 'differential_pair',
    'timing', 'power_thermal', 'rf', 'kelvin', 'return_path', 'safety_creepage',
}
CATEGORY_RULES = {
    'GND': {'return_path'}, 'REFERENCE_PLANE': {'reference_plane_integrity'},
    'POWER_HIGH_CURRENT': {'power_thermal', 'return_path'},
    'SWITCHING_HOT_LOOP': {'power_thermal', 'return_path'},
    'DIFFERENTIAL_HIGH_SPEED': {'differential_pair', 'timing', 'reference_plane_integrity'},
    'CLOCK_CRITICAL': {'timing', 'reference_plane_integrity'},
    'TIMING_MATCHED_BUS': {'timing', 'reference_plane_integrity'},
    'KELVIN_SENSE': {'kelvin'},
    'RF_CONTROLLED_IMPEDANCE': {'rf', 'reference_plane_integrity'},
}
BASE_CAPABILITIES = {
    'native_drc', 'netlist_parity', 'connectivity', 'zone_refill', 'save_reload',
    'protected_object_diff', 'preserve_locked_objects', 'preserve_planes',
    'resolved_rules', 'layer_restrictions', 'create_tracks',
}
CAPABILITIES = BASE_CAPABILITIES | {
    'partial_routing', 'ripup_whitelist', 'through_vias', 'geometry_bottom_pads',
    'geometry_rotated_pads', 'geometry_arcs', 'geometry_slots',
    'geometry_pad_rect', 'geometry_pad_circle', 'geometry_pad_roundrect',
    'geometry_pad_oval', 'geometry_pad_trapezoid', 'geometry_pad_custom',
}
ACCEPTANCE_ARTIFACTS = {'native_drc', 'netlist_parity', 'save_reload',
                        'protected_object_diff', 'rule_hits', 'connectivity'}
ROUTE_TAGS = {'segment', 'arc', 'via'}
SHA = re.compile(r'^[0-9a-f]{64}$')
COPPER = re.compile(r'^(F|B|In[1-9][0-9]*)\.Cu$')


class PolicyError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def need(ok, code, detail):
    if not ok:
        raise PolicyError(code, detail)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pairs(items):
    out = {}
    for key, item in items:
        need(key not in out, 'DUPLICATE_JSON_KEY', key)
        out[key] = item
    return out


def load_json(path):
    def bad_constant(number):
        raise PolicyError('NONFINITE_NUMBER', number)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      object_pairs_hook=_pairs, parse_constant=bad_constant)


def local(root, name):
    need(isinstance(name, str) and name.strip(), 'INVALID_PATH', 'Nonempty project-relative path required')
    # Reject both Windows and POSIX escapes, even when tests run on another OS.
    need(not Path(name).is_absolute() and not re.match(r'^[A-Za-z]:', name)
         and not name.startswith(('\\', '/')) and '..' not in re.split(r'[/\\]', name),
         'UNSAFE_PATH', name)
    raw = root / name
    need(not any(p.is_symlink() for p in [raw, *raw.parents] if p.is_relative_to(root)),
         'UNSAFE_PATH', 'Symlink in input: ' + name)
    path = raw.resolve()
    need(path.is_relative_to(root), 'UNSAFE_PATH', name)
    return path


def bound(root, entry, seen, label):
    need(isinstance(entry, dict) and set(entry) == {'file', 'sha256'},
         'INVALID_BINDING', label + ' needs exactly file/sha256')
    need(isinstance(entry['sha256'], str) and SHA.fullmatch(entry['sha256']),
         'INVALID_HASH', label)
    path = local(root, entry['file'])
    need(path.is_file() and path.stat().st_size > 0, 'MISSING_INPUT', label + ': ' + str(path))
    actual = digest(path)
    need(actual == entry['sha256'], 'HASH_MISMATCH', label + ': ' + entry['file'])
    seen[str(path)] = actual
    return path


def text(item, label):
    need(isinstance(item, str) and bool(item.strip()), 'MISSING_VALUE', label)
    return item


def strings(items, label, allow_empty=False):
    need(isinstance(items, list) and (allow_empty or bool(items)), 'INVALID_LIST', label)
    need(all(isinstance(x, str) and x.strip() for x in items), 'INVALID_LIST', label)
    need(len(items) == len(set(items)), 'DUPLICATE_ITEM', label)
    return set(items)


def finite_parameters(item):
    need(item is not None, 'RULE_PARAMETER_MISSING', 'Constraint parameter is null')
    if isinstance(item, float):
        need(math.isfinite(item), 'NONFINITE_NUMBER', 'Constraint parameter')
    if isinstance(item, dict):
        for value_ in item.values():
            finite_parameters(value_)
    elif isinstance(item, list):
        for value_ in item:
            finite_parameters(value_)


def date_value(item, label):
    try:
        return dt.date.fromisoformat(item)
    except (TypeError, ValueError):
        raise PolicyError('INVALID_DATE', label)


def _node_inventory(tree):
    objects, locked, geometry = {}, set(), set()

    def visit(node, inherited_locked=False):
        if not isinstance(node, list) or not node:
            return
        is_locked = inherited_locked or 'locked' in node or child(node, 'locked') is not None
        uid = value(node, 'uuid')
        if uid:
            need(uid not in objects, 'DUPLICATE_UUID', uid)
            objects[uid] = node
            if is_locked:
                locked.add(uid)
        if node[0] == 'pad':
            need(len(node) > 3, 'INVALID_BOARD', 'Malformed pad')
            feature = 'geometry_pad_' + node[3]
            need(feature in CAPABILITIES, 'UNKNOWN_GEOMETRY', node[3])
            geometry.add(feature)
            if 'B.Cu' in child(node, 'layers', []) or value(node, 'layer') == 'B.Cu':
                geometry.add('geometry_bottom_pads')
            at = child(node, 'at', [])
            if len(at) > 3 and float(at[3]) % 360:
                geometry.add('geometry_rotated_pads')
            if 'oval' in child(node, 'drill', []):
                geometry.add('geometry_slots')
        if node[0] == 'footprint':
            if value(node, 'layer') == 'B.Cu':
                geometry.add('geometry_bottom_pads')
            at = child(node, 'at', [])
            if len(at) > 3 and float(at[3]) % 360:
                geometry.add('geometry_rotated_pads')
        if node[0] in {'arc', 'gr_arc', 'fp_arc'}:
            geometry.add('geometry_arcs')
        for sub in node:
            if isinstance(sub, list):
                visit(sub, is_locked)

    visit(tree)
    return objects, locked, geometry


def _validate_request(root, request_file):
    seen = {}
    request_path = Path(request_file)
    if not request_path.is_absolute():
        request_path = local(root, str(request_file))
    request_path = request_path.resolve()
    need(request_path.is_relative_to(root), 'UNSAFE_PATH', 'Request must be inside project')
    req = load_json(request_path)
    seen[str(request_path)] = digest(request_path)
    allowed = {'schema_version', 'request_id', 'phase', 'strategy', 'runtime', 'inputs',
               'networks', 'constraints', 'pending_connections', 'target_connection_ids',
               'allowed_signal_layers', 'reroutable_uuids', 'budgets', 'backends',
               'required_capabilities', 'acceptance_max_age_days'}
    need(isinstance(req, dict) and not set(req) - allowed, 'UNKNOWN_REQUEST_FIELD', 'Unsupported request fields')
    need(type(req.get('schema_version')) is int and req['schema_version'] == SCHEMA,
         'SCHEMA_VERSION', 'routing request schema_version=1 required')
    text(req.get('request_id'), 'request_id')
    need(req.get('phase') in {'incremental', 'final'}, 'INVALID_PHASE', 'Use incremental or final')
    need(req.get('strategy') == 'script_planned', 'INVALID_STRATEGY', 'Only script_planned is implemented')
    runtime = req.get('runtime', {})
    need(isinstance(runtime, dict) and set(runtime) == {'platform', 'kicad_version', 'api_version'},
         'RUNTIME_IDENTITY_MISSING', 'platform/kicad_version/api_version declarations required')
    for key in runtime:
        text(runtime[key], 'runtime.' + key)
    need(runtime['platform'] in {'windows', 'linux', 'macos'}, 'INVALID_PLATFORM', runtime['platform'])
    bindings = req.get('inputs', {})
    need(isinstance(bindings, dict) and set(bindings) == INPUTS, 'INPUT_BINDINGS_MISSING', ', '.join(sorted(INPUTS)))
    paths = {name: bound(root, entry, seen, name) for name, entry in bindings.items()}
    need(paths['board'].suffix == '.kicad_pcb', 'INVALID_BOARD', 'Expected .kicad_pcb')
    board = parse_sexpr(paths['board'].read_text(encoding='utf-8-sig'))
    need(board and board[0] == 'kicad_pcb', 'INVALID_BOARD', 'Expected kicad_pcb root')
    objects, locked, geometry = _node_inventory(board)
    copper = [str(n[1]) for n in child(board, 'layers', [])[1:]
              if isinstance(n, list) and len(n) > 1 and COPPER.fullmatch(str(n[1]))]
    need(copper and len(copper) == len(set(copper)), 'INVALID_LAYERS', 'Unique PCB copper layers required')
    stack = load_json(paths['stackup'])
    need(stack.get('schema_version') == 1 and isinstance(stack.get('layers'), list),
         'INVALID_STACKUP', 'Versioned layer policy required; no stackup solver is supplied')
    need([layer.get('name') for layer in stack['layers']] == copper,
         'STACKUP_LAYER_MISMATCH', 'Policy copper order must match actual PCB layers')
    plane_layers, signal_layers = set(), set()
    for layer in stack['layers']:
        need(layer.get('role') in {'signal', 'reference_plane', 'power_plane', 'mixed'}
             and type(layer.get('signal_enabled')) is bool, 'INVALID_STACKUP', layer.get('name', '?'))
        if layer['role'] in {'reference_plane', 'power_plane'}:
            need(not layer['signal_enabled'], 'PROTECTED_PLANE_SIGNAL_ENABLED', layer['name'])
            plane_layers.add(layer['name'])
        if layer['signal_enabled']:
            signal_layers.add(layer['name'])
    allowed_layers = strings(req.get('allowed_signal_layers'), 'allowed_signal_layers')
    need(allowed_layers <= signal_layers and not allowed_layers & plane_layers,
         'PROTECTED_PLANE_ROUTING', 'Requested signal layers include disabled/reference/power layer')
    protected = load_json(paths['protected_objects'])
    need(protected.get('schema_version') == 1 and protected.get('locked_policy') == 'preserve_all',
         'INVALID_PROTECTION', 'Versioned protection with locked_policy=preserve_all required')
    protected_ids = strings(protected.get('object_uuids'), 'object_uuids', True)
    need(protected_ids <= set(objects), 'PROTECTED_OBJECT_MISSING', ', '.join(sorted(protected_ids - set(objects))))
    protected_planes = strings(protected.get('plane_layers'), 'plane_layers', True)
    need(plane_layers <= protected_planes and protected_planes <= set(copper),
         'UNPROTECTED_PLANE', 'Every reference/power plane must be protected')
    need(not allowed_layers & protected_planes, 'PROTECTED_PLANE_ROUTING', 'Protected plane requested for signals')
    protected_nets = strings(protected.get('nets'), 'protected nets', True)
    reroutable = strings(req.get('reroutable_uuids'), 'reroutable_uuids', True)
    need(reroutable <= set(objects), 'REROUTABLE_OBJECT_MISSING', ', '.join(sorted(reroutable - set(objects))))
    need(not reroutable & (protected_ids | locked), 'PROTECTED_OBJECT_RIPUP', 'Locked/protected object is reroutable')
    board_nets = {str(n[1]): str(n[2]) for n in children(board, 'net') if len(n) > 2}
    for uid in reroutable:
        node = objects[uid]
        need(node[0] in ROUTE_TAGS, 'ILLEGAL_RIPUP_KIND', uid)
        layers = set(child(node, 'layers', [])[1:]) | {value(node, 'layer')}
        need(not layers & protected_planes, 'PROTECTED_PLANE_RIPUP', uid)
        need(board_nets.get(str(value(node, 'net'))) not in protected_nets, 'PROTECTED_NET_RIPUP', uid)
    graph = read_netlist(paths['netlist'])
    need(protected_nets <= set(graph['nets']), 'UNKNOWN_PROTECTED_NET', ', '.join(sorted(protected_nets - set(graph['nets']))))
    networks = req.get('networks')
    need(isinstance(networks, list) and bool(networks), 'NETWORK_CLASSIFICATION_MISSING', 'networks required')
    classes = {}
    for net in networks:
        name = text(net.get('name'), 'network name')
        need(name not in classes and name in graph['nets'] and name in board_nets.values(),
             'NETWORK_MAPPING_MISMATCH', name)
        categories = strings(net.get('categories'), name + ' categories')
        need(categories <= CATEGORIES, 'UNKNOWN_NETWORK_CATEGORY', name)
        classes[name] = categories
    pending = req.get('pending_connections')
    need(isinstance(pending, list) and bool(pending), 'PENDING_CONNECTIONS_MISSING', 'Explicit unresolved connection inventory required')
    connection_map = {}
    for connection in pending:
        cid, net = text(connection.get('id'), 'connection id'), text(connection.get('net'), 'connection net')
        need(cid not in connection_map and net in classes, 'INVALID_CONNECTION', cid)
        need(not net.startswith('unconnected-'), 'NC_TARGET', cid)
        endpoints = connection.get('endpoints')
        need(isinstance(endpoints, list) and len(endpoints) == 2, 'INVALID_ENDPOINTS', cid)
        endpoint_keys = []
        for endpoint in endpoints:
            need(isinstance(endpoint, dict) and set(endpoint) == {'ref', 'pin'}, 'INVALID_ENDPOINTS', cid)
            point = (text(endpoint['ref'], 'endpoint ref'), text(endpoint['pin'], 'endpoint pin'))
            need(point in graph['nets'][net], 'ENDPOINT_NET_MISMATCH', cid + ': ' + str(point))
            endpoint_keys.append(point)
        need(endpoint_keys[0] != endpoint_keys[1], 'INVALID_ENDPOINTS', cid)
        connection_map[cid] = connection
    targets = strings(req.get('target_connection_ids'), 'target_connection_ids')
    need(targets <= set(connection_map), 'UNKNOWN_TARGET_CONNECTION', ', '.join(sorted(targets - set(connection_map))))
    if req['phase'] == 'final':
        need(targets == set(connection_map), 'FINAL_SCOPE_INCOMPLETE', 'Final planning must target every declared pending connection')
    target_nets = {connection_map[cid]['net'] for cid in targets}
    need(not target_nets & protected_nets, 'PROTECTED_NET_TARGET', ', '.join(sorted(target_nets & protected_nets)))
    need(all('MANUAL_ONLY' not in classes[net] for net in target_nets), 'MANUAL_ONLY_TARGET', 'Manual-only net cannot use automatic backend')
    constraints = req.get('constraints')
    need(isinstance(constraints, list) and bool(constraints), 'RULES_MISSING', 'No required constraints')
    constraint_ids, requirements = set(), set()
    by_net = {net: set() for net in target_nets}
    for constraint in constraints:
        cid, kind = text(constraint.get('id'), 'constraint id'), constraint.get('kind')
        need(cid not in constraint_ids, 'DUPLICATE_CONSTRAINT', cid)
        constraint_ids.add(cid)
        need(kind in CONSTRAINTS, 'UNKNOWN_REQUIRED_CONSTRAINT', str(kind))
        nets = strings(constraint.get('nets'), cid + ' nets')
        need(nets <= set(classes), 'UNKNOWN_CONSTRAINT_NET', cid)
        parameters = constraint.get('parameters')
        need(isinstance(parameters, dict) and bool(parameters), 'RULES_MISSING', cid + ' needs explicit parameters')
        finite_parameters(parameters)
        source = constraint.get('source', {})
        text(source.get('locator'), cid + ' source locator')
        bound(root, {'file': source.get('file'), 'sha256': source.get('sha256')}, seen, cid + ' source')
        for net in nets & target_nets:
            by_net[net].add(kind)
            requirements.add(kind)
    for net in target_nets:
        required = {'copper_clearance', 'track_width', 'board_edge_clearance', 'keepout'}
        for category in classes[net]:
            required |= CATEGORY_RULES.get(category, set())
        need(required <= by_net[net], 'RULES_MISSING', net + ': ' + ', '.join(sorted(required - by_net[net])))
    budgets = req.get('budgets', {})
    need(isinstance(budgets, dict) and set(budgets) == {'total_seconds', 'max_iterations', 'max_vias', 'seed'},
         'BUDGET_MISSING', 'Explicit time/iteration/via/seed budgets required')
    for key, limit in {'total_seconds': 86400, 'max_iterations': 10000, 'max_vias': 100000, 'seed': 2147483647}.items():
        number = budgets[key]
        need(type(number) is int and 0 <= number <= limit and (number > 0 or key in {'seed', 'max_vias'}),
             'INVALID_BUDGET', key)
    capabilities = BASE_CAPABILITIES | geometry
    if req['phase'] == 'incremental':
        capabilities.add('partial_routing')
    if reroutable:
        capabilities.add('ripup_whitelist')
    if budgets['max_vias']:
        capabilities.add('through_vias')
        need(all({'via_geometry', 'hole_clearance'} <= by_net[net] for net in target_nets),
             'RULES_MISSING', 'Via creation needs via_geometry and hole_clearance per target net')
        requirements |= {'via_geometry', 'hole_clearance'}
    extra = strings(req.get('required_capabilities', []), 'required_capabilities', True)
    need(extra <= CAPABILITIES, 'UNKNOWN_REQUIRED_CAPABILITY', ', '.join(sorted(extra - CAPABILITIES)))
    capabilities |= extra
    age = req.get('acceptance_max_age_days')
    need(type(age) is int and 1 <= age <= 365, 'ACCEPTANCE_POLICY_MISSING', 'acceptance_max_age_days must be 1..365')
    need(isinstance(req.get('backends'), list), 'BACKEND_LIST_MISSING', 'backends must be a list')
    return req, seen, {'input_sha256': {key: bindings[key]['sha256'] for key in sorted(INPUTS)},
        'request_sha256': digest(request_path), 'target_connection_ids': sorted(targets),
        'target_nets': sorted(target_nets), 'remaining_connections_after_target_scope': sorted(set(connection_map) - targets),
        'allowed_signal_layers': sorted(allowed_layers), 'protected_planes': sorted(protected_planes),
        'protected_uuids': sorted(protected_ids | locked), 'reroutable_uuids': sorted(reroutable),
        'preserve_all_existing_objects_except': sorted(reroutable),
        'required_constraints': sorted(requirements), 'required_capabilities': sorted(capabilities)}


def _backend(root, backend, req, summary, seen, today):
    identity = backend.get('id', '?') if isinstance(backend, dict) else '?'
    row = {'id': identity, 'eligible': False}
    try:
        need(isinstance(backend, dict) and set(backend) == {'id', 'kind', 'version', 'artifact', 'acceptance'},
             'UNKNOWN_BACKEND_FIELD', 'Only identity, artifact, and acceptance bindings are allowed; no commands')
        text(identity, 'backend id')
        text(backend.get('version'), 'backend version')
        need(backend['kind'] in {'konnect_mcp', 'native_script', 'freerouting'}, 'UNKNOWN_BACKEND_KIND', str(backend['kind']))
        row.update(kind=backend['kind'], version=backend['version'])
        if backend['kind']!='konnect_mcp':
            raise PolicyError('LEGACY_WRITER_DISABLED', 'Only Konnect MCP may execute PCB edits; native_script/Freerouting may produce offline candidates but cannot write KiCad directly')
        bound(root, backend['artifact'], seen, identity + ' artifact')
        need(backend.get('acceptance') is not None, 'BACKEND_ACCEPTANCE_MISSING', identity)
        record_file = bound(root, backend['acceptance'], seen, identity + ' acceptance')
        record = load_json(record_file)
        need(record.get('schema_version') == 1 and record.get('record_type') == 'routing_backend_acceptance'
             and record.get('decision') == 'accepted', 'BACKEND_NOT_ACCEPTED', identity)
        for key in ('id', 'kind', 'version', 'artifact'):
            need(record.get('backend', {}).get(key) == backend[key], 'BACKEND_IDENTITY_MISMATCH', identity + ': ' + key)
        checked = date_value(record.get('checked_on'), 'checked_on')
        expires = date_value(record.get('expires_on'), 'expires_on')
        need(checked <= today <= expires and (today - checked).days <= req['acceptance_max_age_days'],
             'BACKEND_ACCEPTANCE_STALE', identity)
        for key in ('reviewer', 'reason'):
            text(record.get(key), identity + ': ' + key)
        need(record.get('scope') == 'kicad_end_to_end', 'BACKEND_SCOPE_NOT_END_TO_END',
             identity + ': DSN->SES alone cannot serve as verified KiCad routing')
        for key, item in req['runtime'].items():
            supported = strings(record.get('runtime', {}).get(key), 'acceptance runtime.' + key)
            need(item in supported, 'BACKEND_RUNTIME_UNVERIFIED', identity + ': ' + key)
        supported = strings(record.get('constraints'), 'accepted constraints')
        need(supported <= CONSTRAINTS, 'UNKNOWN_BACKEND_CONSTRAINT', identity)
        missing = set(summary['required_constraints']) - supported
        need(not missing, 'BACKEND_CONSTRAINT_UNSUPPORTED', identity + ': ' + ', '.join(sorted(missing)))
        supported = strings(record.get('capabilities'), 'accepted capabilities')
        need(supported <= CAPABILITIES, 'UNKNOWN_BACKEND_CAPABILITY', identity)
        missing = set(summary['required_capabilities']) - supported
        need(not missing, 'BACKEND_CAPABILITY_UNSUPPORTED', identity + ': ' + ', '.join(sorted(missing)))
        artifacts = record.get('evidence')
        need(isinstance(artifacts, list), 'BACKEND_EVIDENCE_MISSING', identity)
        kinds = set()
        for artifact in artifacts:
            kind = artifact.get('kind')
            need(kind in ACCEPTANCE_ARTIFACTS and kind not in kinds, 'INVALID_ACCEPTANCE_ARTIFACT', identity)
            kinds.add(kind)
            bound(root, {'file': artifact.get('file'), 'sha256': artifact.get('sha256')}, seen, identity + ': ' + kind)
        need(kinds == ACCEPTANCE_ARTIFACTS, 'BACKEND_EVIDENCE_MISSING', identity + ': ' + ', '.join(sorted(ACCEPTANCE_ARTIFACTS - kinds)))
        row.update(eligible=True, acceptance_sha256=digest(record_file),
                   evidence_assurance='hash_bound_engineering_record_only')
    except (PolicyError, OSError, ValueError, TypeError, KeyError) as error:
        row.update(reason=getattr(error, 'code', 'INVALID_BACKEND_RECORD'), detail=str(error))
    return row


def _result_base():
    return {'schema_version': SCHEMA, 'tool': 'routing_policy', 'execution_scope': 'planning_only',
            'executed': False, 'production_authorized': False,
            'assurance': 'Declared policy and evidence bytes checked; no native geometry, DRC, electrical or identity certification',
            'remaining': ['actual backend execution on isolated candidate', 'native readback/refill/save/reload',
                          'current DRC/parity/connectivity/protection and applicable electrical review',
                          'existing AI/engineer and manufacturing gates']}


def _run(project, request_file, action, after_attempt=None, today=None):
    out = _result_base()
    out['action'] = action
    seen = {}
    try:
        root = Path(project).resolve()
        need(root.is_dir(), 'PROJECT_MISSING', str(root))
        today = today or dt.date.today()
        req, seen, summary = _validate_request(root, request_file)
        out.update(request_id=req['request_id'], phase=req['phase'], strategy=req['strategy'], **summary)
        identities = [b.get('id') for b in req['backends'] if isinstance(b, dict)]
        need(len(identities) == len(req['backends']) and len(set(identities)) == len(identities),
             'DUPLICATE_BACKEND', 'Backend identities must be unique')
        rows = [_backend(root, backend, req, summary, seen, today) for backend in req['backends']]
        out['backends'] = rows
        eligible = sorted([row for row in rows if row['eligible']],
                          key=lambda row: row['id'])
        if after_attempt is not None:
            need(action == 'plan', 'FALLBACK_ACTION', 'after-attempt is supported only by plan')
            attempt_path = local(root, str(after_attempt))
            attempt = load_json(attempt_path)
            seen[str(attempt_path)] = digest(attempt_path)
            need(attempt.get('schema_version') == 1
                 and attempt.get('request_sha256') == summary['request_sha256']
                 and attempt.get('board_sha256') == summary['input_sha256']['board'],
                 'STALE_ATTEMPT', 'Attempt must bind this exact request and initial board')
            need(attempt.get('status') == 'NO_ROUTE_WITHIN_BUDGET', 'FALLBACK_NOT_ELIGIBLE',
                 'Only search-budget failure permits a backend switch; never missing rules, drift, or unsupported requirements')
            need(eligible and attempt.get('backend_id') == eligible[0]['id'], 'UNKNOWN_ATTEMPT_BACKEND',
                 'Attempt must refer to the currently eligible primary backend')
            ids = strings(attempt.get('remaining_connection_ids'), 'attempt remaining_connection_ids')
            need(ids <= set(summary['target_connection_ids']), 'INVALID_ATTEMPT_SCOPE', 'Unknown remaining connection')
            need(isinstance(attempt.get('evidence'), list) and bool(attempt['evidence']),
                 'ATTEMPT_EVIDENCE_MISSING', 'Bind actual failed-run artifacts')
            for item in attempt['evidence']:
                bound(root, item, seen, 'failed routing attempt')
            primary = eligible[0]['id']
            eligible = [row for row in eligible if row['id'] != primary]
            out.update(previous_outcome='NO_ROUTE_WITHIN_BUDGET', previous_backend=primary,
                       fallback_basis='original_request_checkpoint',
                       reported_remaining_connection_ids=sorted(ids),
                       partial_candidate_reused=False)
            # Partial route preservation needs a NEW request bound to that independently
            # verified candidate. A failure log alone cannot authorize reusing its copper.
        if eligible:
            out.update(status='PREFLIGHT_READY_NOT_EXECUTED' if action == 'preflight' else 'PLAN_READY_NOT_EXECUTED',
                       selected_backend={key: eligible[0][key] for key in ('id', 'kind', 'version', 'acceptance_sha256')},
                       fallback_candidates=[row['id'] for row in eligible[1:]], budgets=req['budgets'])
        else:
            pending_reasons = {'BACKEND_ACCEPTANCE_MISSING', 'BACKEND_ACCEPTANCE_STALE',
                               'BACKEND_NOT_ACCEPTED', 'BACKEND_EVIDENCE_MISSING'}
            pending = not rows or all(row.get('reason') in pending_reasons for row in rows)
            out.update(status='PENDING_BACKEND_ACCEPTANCE' if pending else 'BLOCKED',
                       reason='NO_ELIGIBLE_ACCEPTED_BACKEND', selected_backend=None)
        for name, expected in seen.items():
            need(Path(name).is_file() and digest(name) == expected, 'INPUT_CHANGED_DURING_PLAN', name)
        out['checked_files_sha256'] = seen
    except (PolicyError, OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        out.update(status='BLOCKED', reason=getattr(error, 'code', 'INVALID_ROUTING_REQUEST'), detail=str(error),
                   selected_backend=None)
    return out


def preflight(project, request_file, today=None):
    return _run(project, request_file, 'preflight', today=today)


def plan(project, request_file, after_attempt=None, today=None):
    return _run(project, request_file, 'plan', after_attempt=after_attempt, today=today)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight', 'plan'))
    parser.add_argument('project', type=Path)
    parser.add_argument('--request', required=True, help='Project-relative versioned routing request')
    parser.add_argument('--after-attempt', help='Project-relative, hash-bound budget-failure record (plan only)')
    parser.add_argument('--output-dir', type=Path, help='Optional NEW directory for this read-only report')
    args = parser.parse_args()
    result = _run(args.project, args.request, args.action, args.after_attempt)
    if args.output_dir is not None:
        try:
            destination = args.output_dir.resolve()
            need(not destination.exists(), 'OUTPUT_EXISTS', str(destination))
            need(not any(destination.is_relative_to(Path(name)) or Path(name).is_relative_to(destination)
                         for name in result.get('checked_files_sha256', {})),
                 'UNSAFE_OUTPUT', 'Report directory overlaps a checked input')
            destination.mkdir(parents=True, exist_ok=False)
            (destination / 'routing-policy.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except (PolicyError, OSError) as error:
            result.update(status='BLOCKED', reason=getattr(error, 'code', 'OUTPUT_FAILED'), detail=str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in {'PREFLIGHT_READY_NOT_EXECUTED', 'PLAN_READY_NOT_EXECUTED'} else 2


if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
