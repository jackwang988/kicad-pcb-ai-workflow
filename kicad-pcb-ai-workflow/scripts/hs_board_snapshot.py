#!/usr/bin/env python3
"""Read a saved KiCad PCB into a limited, auditable geometry snapshot.

The native path uses pcbnew.LoadBoard and never saves a board.  The optional
static path is a preview only, refuses transforms it does not implement, and
cannot grant native verification.  Neither path models filled reference-plane
continuity, return currents, thermal behaviour, or SI/PI performance.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import uuid


class SnapshotError(ValueError):
    """An unsupported, ambiguous, inconsistent, or changing board input."""


class _Quoted(str):
    pass


def _finite(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SnapshotError('Invalid numeric geometry: ' + label) from exc
    if isinstance(value, bool) or not math.isfinite(result):
        raise SnapshotError('Nonfinite numeric geometry: ' + label)
    return result


def _positive(value, label, allow_zero=False):
    result = _finite(value, label)
    if result < 0 or (not allow_zero and result == 0):
        raise SnapshotError('Invalid geometric dimension: ' + label)
    return result


def _parse(text):
    # Preserve quoted net names: KiCad 10 allows (net "12"), which must not be
    # confused with a legacy numeric reference (net 12).
    pattern = re.compile(r';[^\n\r]*|"(?:\\.|[^"\\])*"|[()]|[^\s()"]+')
    root, stack = [], []
    current, position = root, 0
    for match in pattern.finditer(text):
        if text[position:match.start()].strip():
            raise SnapshotError('Unrecognized PCB syntax')
        position = match.end()
        token = match.group()
        if token.startswith(';'):
            continue
        if token == '(':
            item = []
            current.append(item)
            stack.append(current)
            current = item
        elif token == ')':
            if not stack:
                raise SnapshotError('Unbalanced PCB syntax')
            current = stack.pop()
        elif token.startswith('"'):
            try:
                current.append(_Quoted(json.loads(token)))
            except (ValueError, TypeError) as exc:
                raise SnapshotError('Invalid quoted PCB string') from exc
        else:
            current.append(token)
    if text[position:].strip() or stack or len(root) != 1 or not isinstance(root[0], list):
        raise SnapshotError('Invalid PCB syntax')
    tree = root[0]
    if not tree or tree[0] != 'kicad_pcb':
        raise SnapshotError('Expected a kicad_pcb document')
    return tree


def _children(node, tag):
    return [x for x in node if isinstance(x, list) and x and x[0] == tag]


def _child(node, tag, default=None):
    found = _children(node, tag)
    if len(found) > 1:
        raise SnapshotError('Duplicate PCB field: ' + tag)
    return found[0] if found else default


def _value(node, tag, default=None):
    item = _child(node, tag)
    return item[1] if item and len(item) > 1 else default


def _walk(node):
    yield node
    for item in node:
        if isinstance(item, list):
            yield from _walk(item)


def _point(node, tag):
    item = _child(node, tag)
    if not item or len(item) < 3:
        raise SnapshotError('Missing point: ' + tag)
    return [_finite(item[1], tag + '.x'), _finite(item[2], tag + '.y')]


def _uuid(node):
    value = _value(node, 'uuid', _value(node, 'tstamp'))
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise SnapshotError('Missing or invalid object UUID') from exc


def _inventory(tree):
    ids = set()
    code_to_name, name_to_code, names = {0: ''}, {'': 0}, set()

    def declare(code, name):
        if not isinstance(name, str) or (code != 0 and not name):
            raise SnapshotError('Invalid net declaration')
        if code < 0 or (code == 0 and name):
            raise SnapshotError('Invalid net code')
        if code in code_to_name and code_to_name[code] != name:
            raise SnapshotError('One net code has conflicting names')
        if name in name_to_code and name_to_code[name] != code:
            raise SnapshotError('One net name has conflicting codes')
        code_to_name[code], name_to_code[name] = name, code
        if name:
            names.add(str(name))

    for node in _walk(tree):
        if node and node[0] in ('uuid', 'tstamp'):
            if len(node) != 2:
                raise SnapshotError('Invalid UUID field')
            try:
                identity = str(uuid.UUID(str(node[1])))
            except ValueError as exc:
                raise SnapshotError('Invalid object UUID') from exc
            if identity in ids:
                raise SnapshotError('Duplicate object UUID: ' + identity)
            ids.add(identity)
        if not node or node[0] != 'net':
            continue
        if len(node) == 3:
            try:
                code = int(node[1])
            except (ValueError, TypeError) as exc:
                raise SnapshotError('Invalid net code') from exc
            declare(code, str(node[2]))
        elif len(node) == 2 and isinstance(node[1], _Quoted):
            if node[1]:
                names.add(str(node[1]))
        elif len(node) != 2:
            raise SnapshotError('Invalid net field')
    # Older zone records may pair (net CODE) with (net_name NAME).
    for zone in _children(tree, 'zone'):
        net = _child(zone, 'net')
        name = _value(zone, 'net_name')
        if net and len(net) == 2 and not isinstance(net[1], _Quoted) and name is not None:
            try:
                declare(int(net[1]), str(name))
            except (ValueError, TypeError) as exc:
                raise SnapshotError('Invalid zone net mapping') from exc
    for node in _walk(tree):
        if node and node[0] == 'net' and len(node) == 2 and not isinstance(node[1], _Quoted):
            try:
                code = int(node[1])
            except (ValueError, TypeError) as exc:
                raise SnapshotError('Unrecognized net reference') from exc
            if code not in code_to_name:
                raise SnapshotError('Undeclared numeric net reference: ' + str(code))
    layers = _child(tree, 'layers')
    if not layers:
        raise SnapshotError('Missing board layer inventory')
    layer_ids, copper_layers = {}, []
    for row in layers[1:]:
        if not isinstance(row, list) or len(row) < 3:
            raise SnapshotError('Invalid layer inventory')
        try:
            code = int(row[0])
        except (ValueError, TypeError) as exc:
            raise SnapshotError('Invalid layer code') from exc
        name = str(row[1])
        if code in layer_ids or name in layer_ids.values():
            raise SnapshotError('Duplicate layer identity')
        layer_ids[code] = name
        if name.endswith('.Cu'):
            copper_layers.append(name)
    if not copper_layers:
        raise SnapshotError('No copper layers declared')
    return code_to_name, name_to_code, names, layer_ids, copper_layers


def _resolve_net(node, code_to_name):
    item = _child(node, 'net')
    if item is None:
        return ''
    if len(item) == 3:
        return str(item[2])
    if isinstance(item[1], _Quoted):
        return str(item[1])
    return str(code_to_name[int(item[1])])


def _layer(name, copper):
    result = str(name)
    if result not in copper:
        raise SnapshotError('Track or via references an undeclared copper layer: ' + result)
    return result


def _pad_layers(node, all_layers, copper):
    item = _child(node, 'layers')
    if not item or len(item) < 2:
        raise SnapshotError('Pad has no layer set')
    result = []
    for raw in item[1:]:
        name = str(raw)
        if name == '*.Cu':
            result.extend(copper)
        elif name == 'F&B.Cu':
            result.extend(x for x in ('F.Cu', 'B.Cu') if x in copper)
        elif name.startswith('*.'):
            suffix = name[1:]
            matches = [x for x in all_layers if x.endswith(suffix)]
            if not matches:
                raise SnapshotError('Unsupported pad wildcard: ' + name)
            result.extend(matches)
        elif name in all_layers:
            result.append(name)
        else:
            raise SnapshotError('Pad references an undeclared layer: ' + name)
    return list(dict.fromkeys(result))


def _arc_length(start, mid, end):
    ax, ay = start
    bx, by = mid
    cx, cy = end
    determinant = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(determinant) < 1e-12:
        raise SnapshotError('Degenerate arc cannot be previewed')
    aa, bb, cc = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / determinant
    uy = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / determinant
    a, m, e = [math.atan2(y - uy, x - ux) for x, y in (start, mid, end)]
    ccw = (e - a) % (2 * math.pi)
    through_mid = (m - a) % (2 * math.pi)
    angle = ccw if through_mid <= ccw + 1e-12 else 2 * math.pi - ccw
    return _positive(math.hypot(ax - ux, ay - uy) * angle, 'arc length')


def _static(tree, inventory):
    codes, named_codes, names, layers, copper = inventory
    tracks, vias, pads, references = [], [], [], set()
    for kind in ('segment', 'arc'):
        for item in _children(tree, kind):
            start, end = _point(item, 'start'), _point(item, 'end')
            row = {'uuid': _uuid(item), 'net': _resolve_net(item, codes),
                   'layer': _layer(_value(item, 'layer'), copper),
                   'width_mm': _positive(_value(item, 'width'), 'track width'),
                   'kind': kind, 'start_mm': start, 'end_mm': end}
            if kind == 'arc':
                row['mid_mm'] = _point(item, 'mid')
                row['length_mm'] = _arc_length(start, row['mid_mm'], end)
            else:
                row['length_mm'] = _positive(math.dist(start, end), 'track length', True)
            tracks.append(row)
    for item in _children(tree, 'via'):
        point, pair = _point(item, 'at'), _child(item, 'layers')
        if not pair or len(pair) != 3:
            raise SnapshotError('Via must declare two endpoint layers')
        padstack = _child(item, 'padstack')
        if padstack and any(n and n[0] in ('size', 'diameter') for n in _walk(padstack)):
            raise SnapshotError('Custom via padstack geometry requires native extraction')
        vias.append({'uuid': _uuid(item), 'net': _resolve_net(item, codes),
                     'x_mm': point[0], 'y_mm': point[1],
                     'diameter_mm': _positive(_value(item, 'size'), 'via diameter'),
                     'drill_mm': _positive(_value(item, 'drill'), 'via drill'),
                     'start_layer': _layer(pair[1], copper), 'end_layer': _layer(pair[2], copper)})
    for footprint in _children(tree, 'footprint'):
        ref = next((str(p[2]) for p in _children(footprint, 'property') if len(p) > 2 and p[1] == 'Reference'), None)
        if ref is None:
            ref = next((str(p[2]) for p in _children(footprint, 'fp_text') if len(p) > 2 and p[1] == 'reference'), None)
        if not ref or ref in references:
            raise SnapshotError('Missing or duplicate footprint reference')
        references.add(ref)
        at = _child(footprint, 'at')
        origin = _point(footprint, 'at')
        angle = _finite(at[3], 'footprint angle') if len(at) > 3 else 0.0
        if _value(footprint, 'layer') != 'F.Cu' or abs(angle % 360) > 1e-9:
            raise SnapshotError('Static preview supports only unrotated front footprints; use native geometry')
        for pad in _children(footprint, 'pad'):
            point = _point(pad, 'at')
            pads.append({'uuid': _uuid(pad), 'ref': ref, 'number': str(pad[1]),
                         'net': _resolve_net(pad, codes), 'x_mm': origin[0] + point[0],
                         'y_mm': origin[1] + point[1],
                         'layers': _pad_layers(pad, list(layers.values()), copper)})
    nets = [{'name': name, 'code': named_codes.get(name)} for name in sorted(names)]
    return nets, tracks, vias, pads


def _native(path, inventory):
    try:
        import pcbnew
    except ImportError as exc:
        raise SnapshotError('Native pcbnew is unavailable; static preview must be requested explicitly') from exc
    board = pcbnew.LoadBoard(str(path))
    if board is None:
        raise SnapshotError('Native pcbnew.LoadBoard could not load the PCB')
    _, _, file_names, layer_ids, copper = inventory

    def mm(value, label='coordinate'):
        return _finite(pcbnew.ToMM(value), label)

    def layer(code):
        if int(code) not in layer_ids:
            raise SnapshotError('Native object references an undeclared board layer')
        return layer_ids[int(code)]

    native_copper = [layer(x) for x in board.GetEnabledLayers().CuStack()]
    if native_copper != copper:
        raise SnapshotError('Native and file copper-layer inventories differ')
    nets, net_codes, net_names = [], {0: ''}, set()
    for code, net in board.GetNetsByNetcode().items():
        code, name = int(code), str(net.GetNetname())
        if code == 0 and not name:
            continue
        if code <= 0 or not name or code in net_codes or name in net_names:
            raise SnapshotError('Ambiguous native net identity')
        net_codes[code] = name
        net_names.add(name)
        nets.append({'name': name, 'code': code})
    if net_names != file_names:
        raise SnapshotError('Native and file net inventories differ')

    def net_name(item):
        code, name = int(item.GetNetCode()), str(item.GetNetname())
        if code not in net_codes or net_codes[code] != name:
            raise SnapshotError('Native object has an unresolved net identity')
        return name

    tracks, vias, pads, seen, refs = [], [], [], set(), set()

    def identity(item):
        try:
            result = str(uuid.UUID(item.m_Uuid.AsString()))
        except (AttributeError, ValueError) as exc:
            raise SnapshotError('Native object has no valid UUID') from exc
        if result in seen:
            raise SnapshotError('Duplicate native object UUID')
        seen.add(result)
        return result

    for item in board.GetTracks():
        uid, name = identity(item), net_name(item)
        if isinstance(item, pcbnew.PCB_VIA):
            pos = item.GetPosition()
            top, bottom = _layer(layer(item.TopLayer()), copper), _layer(layer(item.BottomLayer()), copper)
            first, last = sorted((copper.index(top), copper.index(bottom)))
            diameters = {layer(code): _positive(mm(item.GetWidth(code)), 'via diameter')
                         for code in board.GetEnabledLayers().CuStack()
                         if layer(code) in copper[first:last + 1]}
            vias.append({'uuid': uid, 'net': name, 'x_mm': mm(pos.x), 'y_mm': mm(pos.y),
                         'diameter_mm': min(diameters.values()),
                         'diameter_by_layer_mm': diameters,
                         'diameter_scope': 'minimum_nominal_pad_diameter_across_span',
                         'drill_mm': _positive(mm(item.GetDrillValue()), 'via drill'),
                         'start_layer': top, 'end_layer': bottom})
            continue
        if not isinstance(item, pcbnew.PCB_TRACK):
            raise SnapshotError('Unsupported native track type')
        kind = 'arc' if isinstance(item, pcbnew.PCB_ARC) else 'segment'
        start, end = item.GetStart(), item.GetEnd()
        row = {'uuid': uid, 'net': name, 'layer': _layer(layer(item.GetLayer()), copper),
               'width_mm': _positive(mm(item.GetWidth()), 'track width'),
               'length_mm': _positive(mm(item.GetLength()), 'track length', True),
               'kind': kind, 'start_mm': [mm(start.x), mm(start.y)],
               'end_mm': [mm(end.x), mm(end.y)]}
        if kind == 'arc':
            mid = item.GetMid()
            row['mid_mm'] = [mm(mid.x), mm(mid.y)]
        tracks.append(row)
    for footprint in board.GetFootprints():
        identity(footprint)
        ref = str(footprint.GetReference())
        if not ref or ref in refs:
            raise SnapshotError('Missing or duplicate native footprint reference')
        refs.add(ref)
        for pad in footprint.Pads():
            pos = pad.GetPosition()
            pads.append({'uuid': identity(pad), 'ref': ref, 'number': str(pad.GetNumber()),
                         'net': net_name(pad), 'x_mm': mm(pos.x), 'y_mm': mm(pos.y),
                         'layers': [layer(x) for x in pad.GetLayerSet().Seq()]})
    return sorted(nets, key=lambda x: x['name']), tracks, vias, pads, str(pcbnew.GetBuildVersion())


def extract_board(path, native=True):
    """Return a saved-board snapshot; ``native=False`` is an explicit preview.

    A native snapshot is source verification for the listed primitives only,
    never a DRC, electrical pass, live-editor proof, or manufacturing approval.
    Named-only KiCad 10 nets have ``code=None`` in a static preview because the
    file contains no numeric code to report.
    """
    if not isinstance(native, bool):
        raise SnapshotError('native must be a boolean')
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() != '.kicad_pcb' or not path.is_file():
        raise SnapshotError('An existing .kicad_pcb file is required')
    before = path.read_bytes()
    if not before:
        raise SnapshotError('PCB file is empty')
    tree = _parse(before.decode('utf-8-sig'))
    inventory = _inventory(tree)
    if native:
        nets, tracks, vias, pads, version = _native(path, inventory)
    else:
        nets, tracks, vias, pads = _static(tree, inventory)
        version = None
    if path.read_bytes() != before:
        raise SnapshotError('PCB changed while extracting geometry; discard this snapshot')
    return {'schema_version': 1, 'board_file': str(path),
            'board_sha256': hashlib.sha256(before).hexdigest(),
            'engine': 'pcbnew' if native else 'static_preview',
            'native_tool_version': version,
            'native_geometry_verified': native, 'scope': 'saved_board_primitives_only',
            'copper_layers': inventory[4], 'nets': nets,
            'tracks': sorted(tracks, key=lambda x: x['uuid']),
            'vias': sorted(vias, key=lambda x: x['uuid']),
            'pads': sorted(pads, key=lambda x: x['uuid']),
            'capabilities': {'saved_board_geometry': native,
                             'live_editor_state': False, 'track_width_and_length': True,
                             'via_dimensions_and_span': True, 'pad_centers_and_nets': True,
                             'full_pad_shapes': False, 'full_plane_geometry': False,
                             'return_path': False, 'connectivity_proof': False,
                             'thermal': False, 'si': False, 'pi': False},
            'limitations': ['No board writes or saves performed',
                            'Static preview cannot grant native engineering verification',
                            'No filled-plane continuity, return-current, SI/PI, thermal or full DFM proof']}
