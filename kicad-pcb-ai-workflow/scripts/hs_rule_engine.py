"""Scope-aware high-speed rule audit over a bound, read-only PCB snapshot.

This module never writes a board, launches a solver, or issues engineering or
manufacturing approval. External reports are recorded as evidence, not promoted
to locally executed physics verification.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

PREFIX = 'HSPCB-'
CHECKS = {
    'STACK-001': 'stackup_complete', 'STACK-002': 'solver_evidence_required',
    'IMP-001': 'controlled_impedance_targets', 'IMP-002': 'solver_evidence_required',
    'ROUTE-001': 'high_speed_net_metadata', 'ROUTE-002': 'differential_pair_definition',
    'ROUTE-003': 'length_budget_source', 'RET-001': 'return_path_review',
    'VIA-001': 'via_transition_evidence', 'XTALK-001': 'crosstalk_evidence',
    'PI-001': 'pdn_target_impedance', 'PI-002': 'pdn_evidence',
    'EMI-001': 'loop_area_review', 'THERM-001': 'current_thermal_evidence',
    'DFM-001': 'manufacturing_limits', 'VERIFY-001': 'release_evidence_gate',
}
NET_KINDS = {'high_speed', 'low_speed', 'power', 'ground', 'analog', 'unknown'}
PHASES = {'pre_route', 'post_route', 'handoff'}
SHA = re.compile(r'^[0-9a-f]{64}$')
POST_ROUTE = {'ROUTE-003', 'RET-001', 'VIA-001', 'XTALK-001', 'PI-002', 'EMI-001', 'THERM-001'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object')
    return value


def _list(value, label):
    if not isinstance(value, list):
        raise ValueError(label + ' must be an array')
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be nonempty text')
    return value


def _positive(value, label, zero=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or (not zero and value == 0)):
        raise ValueError(label + ' must be a finite ' + ('nonnegative' if zero else 'positive') + ' number')
    return float(value)


def _local(root, relative):
    _text(relative, 'file')
    part = Path(relative)
    if part.is_absolute() or part.drive or '..' in part.parts or '\\' in relative:
        raise ValueError('Evidence/input paths must be project-relative POSIX paths')
    raw = root / part
    for candidate in (raw, *raw.parents):
        if candidate == root.parent:
            break
        if candidate.is_symlink() or (candidate.exists() and getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Symlink/reparse point refused: ' + relative)
    resolved = raw.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError('Missing/empty input or evidence: ' + relative)
    return resolved


def _bind(root, entry, bindings=None):
    _object(entry, 'file binding')
    name, expected = entry.get('file'), entry.get('sha256')
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError('A lowercase SHA-256 is required')
    path = _local(root, name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Changed input/evidence: ' + str(name))
    if bindings is not None:
        bindings[name] = expected
    return path


def _source(root, value, bindings):
    _object(value, 'source')
    _text(value.get('locator'), 'source.locator')
    _bind(root, value, bindings)


def _catalog(catalog):
    data = _object(catalog, 'catalog')
    rows = _list(data.get('rules'), 'catalog.rules')
    result = {}
    for row in rows:
        _object(row, 'catalog rule')
        rid = _text(row.get('id'), 'catalog rule.id')
        short = rid.removeprefix(PREFIX)
        if rid in result or short not in CHECKS or row.get('check_type') != CHECKS[short]:
            raise ValueError('Unknown, duplicate, or mismatched rule/check_type: ' + rid)
        _text(row.get('title'), 'catalog rule.title')
        result[rid] = row
    if set(result) != {PREFIX + key for key in CHECKS}:
        raise ValueError('Catalog must contain the complete supported 16-rule inventory')
    return result


def audit(policy, snapshot, root, catalog):
    """Return scoped declared checks; malformed contracts return structured BLOCKED."""
    report = {'schema_version': 1, 'status': 'BLOCKED', 'scope': 'declared_high_speed_checks',
              'production_authorized': False, 'design_package_ready': False,
              'rules': [], 'findings': [], 'inputs_sha256': {},
              'limitations': ['No automatic placement/routing or electromagnetic/thermal proof',
                              'External evidence records do not prove local solver execution or reviewer identity']}
    try:
        return _audit(policy, snapshot, Path(root).resolve(), catalog, report)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        report['findings'].append({'rule_id': 'HSPCB-INPUT', 'status': 'BLOCKED',
                                   'code': 'INVALID_INPUT', 'message': str(exc), 'objects': []})
        report['status'] = 'BLOCKED'
        return report


def _audit(policy, snapshot, root, catalog, report):
    rows = _catalog(catalog)
    _object(policy, 'policy'); _object(snapshot, 'snapshot')
    # Reject NaN/Infinity anywhere, including optional future model fields.
    report['policy_sha256'] = _digest(policy)
    report['catalog_sha256'] = _digest(catalog)
    _digest(snapshot)
    if (type(policy.get('schema_version')) is not int or type(snapshot.get('schema_version')) is not int
            or policy.get('schema_version') != 1 or snapshot.get('schema_version') != 1):
        raise ValueError('Unsupported policy/snapshot schema_version')
    phase = policy.get('phase')
    if phase not in PHASES:
        raise ValueError('Unknown phase')
    report['phase'] = phase
    bindings = report['inputs_sha256']
    inputs = _object(policy.get('inputs'), 'inputs')
    if 'board' not in inputs:
        raise ValueError('Explicit current board input binding required')
    for key, binding in inputs.items():
        _text(key, 'input name'); _bind(root, binding, bindings)
    if inputs['board']['sha256'] != snapshot.get('board_sha256'):
        raise ValueError('Board snapshot does not match the bound current board')
    for field in ('nets', 'tracks', 'vias', 'pads', 'copper_layers'):
        _list(snapshot.get(field), 'snapshot.' + field)
    layer_names = snapshot['copper_layers']
    if (not all(isinstance(x, str) and x.endswith('.Cu') for x in layer_names)
            or len(layer_names) != len(set(layer_names))):
        raise ValueError('Invalid snapshot copper layer inventory')
    actual_names = []
    for net in snapshot['nets']:
        _object(net, 'snapshot net'); actual_names.append(_text(net.get('name'), 'snapshot net name'))
    if len(actual_names) != len(set(actual_names)):
        raise ValueError('Duplicate actual net')
    nets = {}
    for net in _list(policy.get('nets'), 'nets'):
        _object(net, 'net')
        name = _text(net.get('name'), 'net.name')
        if name in nets:
            raise ValueError('Duplicate declared net: ' + name)
        if net.get('kind') not in NET_KINDS:
            raise ValueError('Unknown net.kind: ' + name)
        if 'allowed_layers' in net:
            allowed = _list(net['allowed_layers'], name + '.allowed_layers')
            if (not allowed or not all(isinstance(layer, str) and layer in layer_names for layer in allowed)
                    or len(allowed) != len(set(allowed))):
                raise ValueError('Invalid/duplicate allowed routing layer: ' + name)
        nets[name] = net
    if set(nets) != set(actual_names):
        raise ValueError('Declared/actual net coverage mismatch; missing=' + repr(sorted(set(actual_names)-set(nets)))
                         + ', extra=' + repr(sorted(set(nets)-set(actual_names))))
    if any(n['kind'] == 'unknown' for n in nets.values()):
        raise ValueError('Unclassified actual network remains unknown')
    pairs = _list(policy.get('differential_pairs', []), 'differential_pairs')
    rails = _list(policy.get('power_rails', []), 'power_rails')
    requirements = {}
    for req in _list(policy.get('requirements', []), 'requirements'):
        _object(req, 'requirement')
        rid = req.get('rule_id')
        if rid not in rows or rid in requirements:
            raise ValueError('Unknown/duplicate required rule: ' + str(rid))
        if req.get('applicability') not in ('required', 'not_applicable', 'unknown'):
            raise ValueError('Invalid requirement applicability')
        _text(req.get('reason'), 'requirement.reason')
        objects = _list(req.get('objects', []), 'requirement.objects')
        if not all(isinstance(x, str) and x in nets for x in objects) or len(objects) != len(set(objects)):
            raise ValueError('Requirement objects must be unique actual net names')
        if req.get('applicability') == 'not_applicable':
            _source(root, req.get('source'), bindings)
        requirements[rid] = req
    evidence = _list(policy.get('evidence', []), 'evidence')
    for item in evidence:
        _object(item, 'evidence')
        eids = _list(item.get('rule_ids'), 'evidence.rule_ids')
        if not eids or len(eids) != len(set(eids)) or not set(eids).issubset(rows):
            raise ValueError('Evidence needs unique supported rule_ids')

    high = {name for name, n in nets.items() if n['kind'] == 'high_speed'}
    controlled = {name for name, n in nets.items() if n.get('impedance') is not None}
    pair_names = set()
    pair_ids = set()
    pair_errors = []
    for pair in pairs:
        _object(pair, 'differential pair')
        pid = _text(pair.get('id'), 'pair.id')
        pos, neg = pair.get('positive_net'), pair.get('negative_net')
        if pid in pair_ids or not isinstance(pos, str) or not isinstance(neg, str) or pos == neg or pos not in nets or neg not in nets:
            pair_errors.append('Duplicate pair id or invalid P/N identity: ' + pid)
        elif {pos, neg} & pair_names:
            pair_errors.append('A net is assigned to more than one pair: ' + pid)
        else:
            pair_names.update((pos, neg))
        pair_ids.add(pid)
    if pair_errors:
        raise ValueError('; '.join(pair_errors))
    controlled |= pair_names
    high |= pair_names
    rail_names = set()
    for rail in rails:
        _object(rail, 'power rail')
        name = _text(rail.get('name'), 'power rail.name')
        if name in rail_names or name not in nets or nets[name]['kind'] != 'power':
            raise ValueError('Power rails must uniquely identify actual power nets: ' + name)
        rail_names.add(name)
    native = snapshot.get('native_geometry_verified') is True and snapshot.get('engine') == 'pcbnew'
    tracks = snapshot['tracks']; vias = snapshot['vias']
    for obj in tracks + vias:
        _object(obj, 'copper object')
        if obj.get('net') not in nets and obj.get('net') not in ('', None):
            raise ValueError('Copper object names an unknown net')
    high_vias = {v['net'] for v in vias if v.get('net') in high}
    actual_high_tracks = {t['net'] for t in tracks if t.get('net') in high}
    auto = {
        'STACK-001': set(high), 'STACK-002': set(controlled), 'IMP-001': set(controlled),
        'IMP-002': set(controlled), 'ROUTE-001': set(high), 'ROUTE-002': set(pair_names),
        'ROUTE-003': set(pair_names), 'RET-001': set(high), 'VIA-001': high_vias,
        'XTALK-001': actual_high_tracks if len(actual_high_tracks) > 1 else set(),
        'PI-001': set(rail_names), 'PI-002': set(rail_names), 'EMI-001': set(high),
        'THERM-001': {n for n, spec in nets.items() if spec.get('current_a') is not None},
        'DFM-001': set(nets), 'VERIFY-001': set(nets) if phase == 'handoff' else set(),
    }
    # Manufacturing constraints apply even to a board without named networks.
    mandatory = {'DFM-001', 'STACK-001', 'STACK-002', 'IMP-001', 'IMP-002',
                 'ROUTE-001', 'ROUTE-002', 'RET-001', 'VERIFY-001'}
    source_checks = []

    def valid_source(value):
        _source(root, value, bindings)
        source_checks.append(value['file'])

    def issue(row, code, message, status='BLOCKED', objects=None):
        finding = {'rule_id': row['rule_id'], 'status': status, 'code': code,
                   'message': message, 'objects': objects if objects is not None else row['objects']}
        row['findings'].append(finding); report['findings'].append(finding)

    def use_evidence(row):
        selected = [e for e in evidence if row['rule_id'] in e['rule_ids']]
        valid = []
        for item in selected:
            try:
                artifact = _bind(root, item.get('artifact'), bindings)
                tool = _object(item.get('tool'), 'evidence.tool')
                _text(tool.get('name'), 'evidence.tool.name'); _text(tool.get('version'), 'evidence.tool.version')
                _text(item.get('method'), 'evidence.method'); _text(item.get('reviewer'), 'evidence.reviewer')
                created = datetime.fromisoformat(_text(item.get('created_at'), 'evidence.created_at').replace('Z', '+00:00'))
                if created.tzinfo is None:
                    raise ValueError('Evidence timestamp requires a time zone')
                declared = _object(item.get('inputs_sha256'), 'evidence.inputs_sha256')
                for entry in inputs.values():
                    if declared.get(entry['file']) != entry['sha256']:
                        raise ValueError('Evidence not bound to every current engineering input')
                for filename, fingerprint in declared.items():
                    _bind(root, {'file': filename, 'sha256': fingerprint}, bindings)
                scope = _list(item.get('scope'), 'evidence.scope')
                if not all(isinstance(x, str) and (x in nets or x == '*') for x in scope):
                    raise ValueError('Evidence scope names unknown objects')
                if '*' not in scope and not set(row['objects']).issubset(scope):
                    raise ValueError('Evidence does not cover the rule object scope')
                outcome = item.get('result')
                if outcome not in ('PASS', 'FAIL', 'REVIEW'):
                    raise ValueError('Unknown evidence result')
                if outcome == 'FAIL':
                    issue(row, 'EXTERNAL_FAILURE', 'Bound external evidence reports failure', 'FAIL')
                elif outcome == 'REVIEW':
                    issue(row, 'EXTERNAL_REVIEW', 'Bound evidence requires review', 'REVIEW_REQUIRED')
                valid.append({'artifact': str(artifact.relative_to(root)), 'result': outcome,
                              'tool': tool, 'method': item['method'], 'verification': 'recorded_external_evidence_only'})
            except (ValueError, OSError, TypeError) as exc:
                issue(row, 'INVALID_EVIDENCE', str(exc))
        row['evidence'] = valid
        return bool(valid) and all(v['result'] == 'PASS' for v in valid)

    def physical_review(row, short):
        if use_evidence(row):
            row['status'] = 'EXTERNAL_EVIDENCE_RECORDED'
        else:
            row['status'] = 'REVIEW_REQUIRED'
            row['checks'].append({'method': 'pending_external_or_engineering_review',
                                  'implemented_physics': False})
            if phase == 'pre_route' and short in POST_ROUTE:
                row['deferred_until'] = 'post_route'

    for rid, catalog_row in rows.items():
        short = rid[len(PREFIX):]
        req = requirements.get(rid)
        applicable = bool(auto[short]) or short == 'DFM-001' or (short == 'VERIFY-001' and phase == 'handoff')
        objects = sorted(auto[short])
        row = {'rule_id': rid, 'title': catalog_row['title'], 'check_type': catalog_row['check_type'],
               'applicability': 'required' if applicable else 'not_applicable',
               'status': 'CONFIG_CHECKED', 'objects': objects, 'checks': [], 'findings': [],
               'limitations': catalog_row.get('limitations', '')}
        report['rules'].append(row)
        if req:
            if req['applicability'] == 'unknown':
                row['applicability'] = 'unknown'; issue(row, 'UNKNOWN_APPLICABILITY', req['reason'])
            elif req['applicability'] == 'not_applicable':
                if applicable and short in mandatory:
                    issue(row, 'APPLICABILITY_CONFLICT', 'N/A conflicts with actual objects or a mandatory stage check')
                else:
                    applicable = False; row['applicability'] = 'not_applicable'; row['reason'] = req['reason']
            else:
                applicable = True; row['applicability'] = 'required'
                if req.get('objects'):
                    if set(objects) - set(req['objects']) and short in mandatory:
                        issue(row, 'SCOPE_OMISSION', 'Explicit scope excludes automatically applicable objects')
                    objects = sorted(set(objects) | set(req['objects'])); row['objects'] = objects
        if not applicable and not row['findings']:
            row['status'] = 'NOT_APPLICABLE'
            continue
        try:
            if short == 'STACK-001':
                st = _object(policy.get('stackup'), 'stackup'); valid_source(st.get('source'))
                if len(layer_names) < 2:
                    raise ValueError('At least two actual copper layers are needed for this profile')
                row['checks'].append({'copper_layers': layer_names, 'method': 'source_and_actual_layer_inventory',
                                      'dielectric_model_validated': False})
            elif short in ('STACK-002', 'IMP-002'):
                physical_review(row, short)
            elif short == 'IMP-001':
                seen = 0
                for name in objects:
                    spec = _object(nets[name].get('impedance'), name + '.impedance')
                    _positive(spec.get('target_ohm'), name + '.target_ohm'); valid_source(spec.get('source'))
                    low = _positive(spec.get('min_width_mm'), name + '.min_width_mm')
                    high_width = _positive(spec.get('max_width_mm'), name + '.max_width_mm')
                    if low > high_width:
                        raise ValueError('Inverted width range: ' + name)
                    for track in tracks:
                        if track.get('net') == name:
                            width = _positive(track.get('width_mm'), 'actual track width')
                            seen += 1
                            row['checks'].append({'net': name, 'uuid': track.get('uuid'), 'width_mm': width,
                                                  'min_width_mm': low, 'max_width_mm': high_width})
                            if native and not low-1e-9 <= width <= high_width+1e-9:
                                issue(row, 'IMPEDANCE_GEOMETRY_WIDTH', 'Actual width is outside the approved geometry range', 'FAIL', [name])
                if seen:
                    row['status'] = 'GEOMETRY_CHECKED' if native else 'REVIEW_REQUIRED'
                elif phase != 'pre_route':
                    row['status'] = 'REVIEW_REQUIRED'
                    row['checks'].append({'method': 'no_routed_track_geometry_available'})
                row['checks'].append({'actual_impedance_solved': False})
            elif short == 'ROUTE-001':
                for name in objects:
                    net = nets[name]
                    _text(net.get('interface'), name + '.interface'); valid_source(net.get('source'))
                    _text(net.get('signal_edge_or_rate'), name + '.signal_edge_or_rate')
                    layers = _list(net.get('allowed_layers'), name + '.allowed_layers')
                    if not layers or len(layers) != len(set(layers)) or not set(layers).issubset(layer_names):
                        raise ValueError('Allowed routing layers are empty, duplicated, or absent from the actual stackup: ' + name)
                    for track in tracks:
                        if track.get('net') == name and track.get('layer') not in layers:
                            issue(row, 'ACTUAL_ROUTING_LAYER', 'Actual track is on a disallowed layer', 'FAIL' if native else 'REVIEW_REQUIRED', [name])
                row['checks'].append({'method': 'metadata_and_actual_layer_check', 'classification_is_project_declared': True})
            elif short in ('ROUTE-002', 'ROUTE-003'):
                if pair_errors:
                    raise ValueError('; '.join(pair_errors))
                if not pairs:
                    row['status'] = 'REVIEW_REQUIRED'
                    row['checks'].append({'method': 'explicit_timing_requirement_without_supported_pair_contract'})
                for pair in pairs:
                    pos, neg = pair['positive_net'], pair['negative_net']
                    valid_source(pair.get('source'))
                    skew = _positive(pair.get('max_skew_mm'), 'pair.max_skew_mm', zero=True)
                    lengths = {name: sum(_positive(t.get('length_mm'), 'track.length_mm', zero=True)
                                         for t in tracks if t.get('net') == name) for name in (pos, neg)}
                    row['checks'].append({'pair': pair['id'], 'copper_total_lengths_mm': lengths,
                                          'max_skew_mm': skew, 'scope': 'sum_of_board_tracks_only',
                                          'excludes': ['package', 'vias', 'connectors', 'propagation_models', 'endpoint_topology']})
                    if phase != 'pre_route':
                        if not all(lengths.values()):
                            row['status'] = 'REVIEW_REQUIRED'
                        elif native:
                            row['checks'][-1]['proxy_exceeds_budget'] = abs(lengths[pos]-lengths[neg]) > skew+1e-9
                            row['checks'][-1]['endpoint_skew_verified'] = False
                        else:
                            row['status'] = 'REVIEW_REQUIRED'
                if short == 'ROUTE-003':
                    row['checks'].append({'timing_model_validated': False, 'native_mm_budget_preserved': True})
                    physical_review(row, short)
            elif short == 'RET-001':
                for name in objects:
                    refs = _object(nets[name].get('reference_by_layer'), name + '.reference_by_layer')
                    allowed = _list(nets[name].get('allowed_layers'), name + '.allowed_layers')
                    if not allowed or not set(allowed).issubset(refs):
                        raise ValueError('Every allowed routing layer needs an explicit reference mapping: ' + name)
                    if any(not isinstance(ref, str) or ref not in layer_names or ref == layer for layer, ref in refs.items()):
                        raise ValueError('Invalid reference layer mapping: ' + name)
                row['checks'].append({'method': 'reference_mapping_only', 'filled_plane_geometry_checked': False})
                physical_review(row, short)
            elif short == 'PI-001':
                for rail in rails:
                    if rail['name'] not in objects:
                        continue
                    valid_source(rail.get('source'))
                    voltage = _positive(rail.get('voltage_v'), 'rail.voltage_v')
                    ripple = _positive(rail.get('ripple_percent'), 'rail.ripple_percent')
                    if ripple > 100:
                        raise ValueError('ripple_percent exceeds 100')
                    current = _positive(rail.get('transient_current_a'), 'rail.transient_current_a')
                    limit = _positive(rail.get('target_impedance_limit_mohm'), 'rail.target_impedance_limit_mohm')
                    target = voltage * ripple / 100 / current * 1000
                    if not math.isfinite(target) or target <= 0:
                        raise ValueError('PDN target is outside the supported finite numeric range')
                    row['checks'].append({'rail': rail['name'], 'initial_z_target_mohm': target, 'limit_mohm': limit,
                                          'frequency_domain_impedance_verified': False})
                    if limit > target * (1+1e-9):
                        issue(row, 'PDN_LIMIT', 'Declared limit is less strict than the initial target', 'FAIL', [rail['name']])
            elif short == 'DFM-001':
                m = _object(policy.get('manufacturing'), 'manufacturing'); valid_source(m.get('source'))
                thresholds = {key: _positive(m.get(key), 'manufacturing.' + key) for key in
                              ('min_track_width_mm', 'min_clearance_mm', 'min_via_drill_mm', 'min_via_diameter_mm', 'min_annulus_mm')}
                measured = 0
                for track in tracks:
                    width = _positive(track.get('width_mm'), 'track.width_mm'); measured += 1
                    row['checks'].append({'uuid': track.get('uuid'), 'width_mm': width, 'min_width_mm': thresholds['min_track_width_mm']})
                    if width+1e-9 < thresholds['min_track_width_mm']:
                        issue(row, 'TRACK_WIDTH', 'Track width is below the manufacturing minimum', 'FAIL' if native else 'REVIEW_REQUIRED')
                for via in vias:
                    diameter = _positive(via.get('diameter_mm'), 'via.diameter_mm')
                    drill = _positive(via.get('drill_mm'), 'via.drill_mm'); measured += 1
                    ring = (diameter-drill)/2
                    row['checks'].append({'uuid': via.get('uuid'), 'diameter_mm': diameter, 'drill_mm': drill, 'annulus_mm': ring})
                    if (diameter+1e-9 < thresholds['min_via_diameter_mm'] or drill+1e-9 < thresholds['min_via_drill_mm']
                            or ring+1e-9 < thresholds['min_annulus_mm']):
                        issue(row, 'VIA_GEOMETRY', 'Actual via diameter, drill, or annulus violates manufacturing constraints', 'FAIL' if native else 'REVIEW_REQUIRED')
                row['status'] = ('GEOMETRY_CHECKED' if native else 'REVIEW_REQUIRED') if measured else 'CONFIG_CHECKED'
                row['checks'].append({'not_checked': ['clearance', 'hole_to_hole', 'copper_to_edge', 'soldermask', 'connectivity'],
                                      'next_verifier': 'existing native DRC and project-specific DFM'})
            elif short == 'VERIFY-001':
                physical_review(row, short)
                row['checks'].append({'does_not_replace': 'existing G3/G4 and design-package handoff gates'})
            else:
                physical_review(row, short)
        except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
            issue(row, 'INVALID_RULE_INPUT', str(exc))
        # Contradictory evidence is not hidden by a config/geometry-only check.
        if short not in {'STACK-002', 'IMP-002', 'RET-001', 'VIA-001', 'XTALK-001', 'PI-002', 'EMI-001', 'THERM-001', 'VERIFY-001'}:
            use_evidence(row)
        states = {f['status'] for f in row['findings']}
        if 'BLOCKED' in states:
            row['status'] = 'BLOCKED'
        elif 'FAIL' in states:
            row['status'] = 'FAIL'
        elif 'REVIEW_REQUIRED' in states:
            row['status'] = 'REVIEW_REQUIRED'

    # Recheck bound inputs so an audit cannot mix concurrent source revisions.
    for filename, fingerprint in dict(bindings).items():
        _bind(root, {'file': filename, 'sha256': fingerprint})
    states = {row['status'] for row in report['rules'] if not row.get('deferred_until')}
    if states & {'BLOCKED', 'FAIL'}:
        report['status'] = 'BLOCKED'
    elif states & {'REVIEW_REQUIRED'}:
        report['status'] = 'REVIEW_REQUIRED'
    else:
        report['status'] = 'DECLARED_CHECKS_COMPLETE'
    # A failure is never deferred, even when the associated physical work is later.
    if any(row['status'] in ('BLOCKED', 'FAIL') for row in report['rules']):
        report['status'] = 'BLOCKED'
    report['native_geometry_verified'] = native
    report['deferred_rules'] = [r['rule_id'] for r in report['rules'] if r.get('deferred_until')]
    report['source_files_checked'] = sorted(set(source_checks))
    return report
