#!/usr/bin/env python3
"""Experimental offline octile A* for one normalized ordinary connection.

This plans in an explicitly supplied conservative grid. It does not extract a
PCB grid, edit KiCad, run DRC, prove electrical validity, or register an accepted
routing backend. No subprocesses, shell, or external executables are called.
"""
import argparse
import heapq
import math
import time
from pathlib import Path

from routing_policy import PolicyError, need, local, load_json, bound, strings, digest, COPPER

MOVES = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
NO_HEADING = 8
SUPPORTED_CONSTRAINTS = {'grid_clearance', 'layer_restrictions', 'protected_planes', 'via_budget'}
SOURCE_KINDS = {'board', 'rules', 'normalization_basis'}
MAX_GRID_CELLS = 1000000
MAX_SEARCH_STATES = 200000


def _number(number, label, zero=False, maximum=None):
    need(type(number) in (int, float) and math.isfinite(number)
         and (number >= 0 if zero else number > 0)
         and (maximum is None or number <= maximum), 'INVALID_NUMBER', label)
    return number


def _integer(number, label, low, high):
    need(type(number) is int and low <= number <= high, 'INVALID_INTEGER', label)
    return number


def _coordinate(item, width, height, label):
    need(isinstance(item, list) and len(item) == 2, 'INVALID_GRID_COORDINATE', label)
    return (_integer(item[0], label + '.x', 0, width - 1),
            _integer(item[1], label + '.y', 0, height - 1))


def octile(dx, dy):
    """A lower bound when diagonal moves cost sqrt(2), ignoring penalties/vias."""
    small, large = sorted((abs(dx), abs(dy)))
    return large + (math.sqrt(2) - 1) * small


def _read_problem(root, problem_file):
    path = Path(problem_file)
    if path.is_absolute():
        need(path.resolve().is_relative_to(root), 'UNSAFE_PATH', 'Problem must be inside project')
        path = local(root, str(path.relative_to(root)))
    else:
        path = local(root, str(path))
    problem = load_json(path)
    seen = {str(path): digest(path)}
    allowed = {'schema_version', 'problem_id', 'scope', 'net_category', 'source_files',
               'normalization', 'grid', 'layers', 'allowed_signal_layers',
               'protected_plane_layers', 'blocked_cells', 'via_sites', 'via_cost',
               'bend_penalty', 'start', 'goal', 'required_constraints', 'budgets'}
    need(isinstance(problem, dict) and not set(problem) - allowed, 'UNKNOWN_PROBLEM_FIELD', 'Unsupported problem fields')
    need(type(problem.get('schema_version')) is int and problem['schema_version'] == 1,
         'SCHEMA_VERSION', 'route-problem schema_version=1 required')
    need(isinstance(problem.get('problem_id'), str) and bool(problem['problem_id'].strip()),
         'PROBLEM_ID_MISSING', 'problem_id required')
    need(problem.get('scope') == 'ordinary_single_connection'
         and problem.get('net_category') in {'LOW_SPEED_DIGITAL', 'GENERAL_SIGNAL'},
         'UNSUPPORTED_NETWORK_SCOPE', 'Only one explicitly ordinary connection is supported')
    sources = problem.get('source_files', {})
    need(isinstance(sources, dict) and set(sources) == SOURCE_KINDS,
         'SOURCE_BINDINGS_MISSING', 'Bind board, rules and normalization_basis')
    for label, entry in sources.items():
        bound(root, entry, seen, label)
    grid = problem.get('grid', {})
    need(isinstance(grid, dict) and set(grid) == {'width', 'height'}, 'INVALID_GRID', 'width/height required')
    width = _integer(grid['width'], 'width', 1, 1024)
    height = _integer(grid['height'], 'height', 1, 1024)
    normal = problem.get('normalization', {})
    need(isinstance(normal, dict) and set(normal) == {'grid_pitch_mm', 'origin_mm', 'trace_width_mm',
         'clearance_mm', 'trace_envelope_inflated', 'via_envelope_all_layers_inflated'},
         'NORMALIZATION_MISSING', 'Explicit conservative normalization required')
    _number(normal['grid_pitch_mm'], 'grid_pitch_mm')
    _number(normal['trace_width_mm'], 'trace_width_mm')
    _number(normal['clearance_mm'], 'clearance_mm', zero=True)
    need(isinstance(normal['origin_mm'], list) and len(normal['origin_mm']) == 2
         and all(type(v) in (int, float) and math.isfinite(v) for v in normal['origin_mm']),
         'INVALID_ORIGIN', 'Finite x/y origin required')
    need(normal['trace_envelope_inflated'] is True, 'OBSTACLES_NOT_NORMALIZED',
         'Trace envelope and applicable clearance must already be included')
    need(type(normal['via_envelope_all_layers_inflated']) is bool,
         'INVALID_NORMALIZATION', 'via_envelope_all_layers_inflated must be boolean')
    layers = problem.get('layers')
    need(isinstance(layers, list) and 1 <= len(layers) <= 8, 'INVALID_LAYERS', '1..8 physical copper layers')
    need(width * height * len(layers) <= MAX_GRID_CELLS, 'GRID_TOO_LARGE', 'Physical grid cell limit exceeded')
    names, signals, planes = [], set(), set()
    for layer in layers:
        need(isinstance(layer, dict) and set(layer) == {'name', 'role', 'signal_enabled',
             'preferred_direction', 'nonpreferred_penalty'}, 'INVALID_LAYER', 'Explicit layer policy required')
        name = layer.get('name')
        need(isinstance(name, str) and name not in names and COPPER.fullmatch(name), 'INVALID_LAYER', str(name))
        need(layer['role'] in {'signal', 'mixed', 'reference_plane', 'power_plane'}
             and type(layer['signal_enabled']) is bool, 'INVALID_LAYER', name)
        need(layer['preferred_direction'] in {'horizontal', 'vertical', 'none'}, 'INVALID_DIRECTION', name)
        _number(layer['nonpreferred_penalty'], name + ' nonpreferred_penalty', zero=True, maximum=1000000)
        names.append(name)
        if layer['role'] in {'reference_plane', 'power_plane'}:
            need(not layer['signal_enabled'], 'PROTECTED_PLANE_SIGNAL_ENABLED', name)
            planes.add(name)
        if layer['signal_enabled']:
            signals.add(name)
    if len(names) > 1:
        need(names == ['F.Cu'] + ['In' + str(i) + '.Cu' for i in range(1, len(names) - 1)] + ['B.Cu'],
             'PHYSICAL_LAYER_ORDER', 'Declare all physical copper layers in F/In1/.../B order')
    allowed_signals = strings(problem.get('allowed_signal_layers'), 'allowed_signal_layers')
    protected = strings(problem.get('protected_plane_layers'), 'protected_plane_layers', True)
    need(allowed_signals <= signals and planes <= protected and protected <= set(names)
         and not protected & allowed_signals, 'PROTECTED_PLANE_ROUTING', 'Invalid signal/plane policy')
    constraints = strings(problem.get('required_constraints'), 'required_constraints')
    need(constraints <= SUPPORTED_CONSTRAINTS, 'UNSUPPORTED_REQUIRED_CONSTRAINT',
         ', '.join(sorted(constraints - SUPPORTED_CONSTRAINTS)))
    need({'grid_clearance', 'layer_restrictions', 'protected_planes', 'via_budget'} <= constraints,
         'CONSTRAINT_DECLARATION_MISSING', 'Declare each supported grid constraint')
    blocked = problem.get('blocked_cells')
    need(isinstance(blocked, dict) and set(blocked) == set(names), 'OBSTACLE_LAYERS_MISSING',
         'Every physical copper layer needs an explicit blocked-cell inventory')
    obstacles = []
    for name in names:
        cells = blocked[name]
        need(isinstance(cells, list) and len(cells) <= width * height, 'INVALID_OBSTACLES', name)
        points = {_coordinate(item, width, height, name) for item in cells}
        need(len(points) == len(cells), 'DUPLICATE_OBSTACLE', name)
        obstacles.append(points)
    sites = problem.get('via_sites')
    need(isinstance(sites, list) and len(sites) <= width * height, 'INVALID_VIA_SITES', 'Explicit via landing whitelist required')
    via_sites = {_coordinate(item, width, height, 'via_site') for item in sites}
    need(len(via_sites) == len(sites), 'DUPLICATE_VIA_SITE', 'via_sites')
    _number(problem.get('via_cost'), 'via_cost', maximum=1000000)
    _number(problem.get('bend_penalty'), 'bend_penalty', zero=True, maximum=1000000)
    budgets = problem.get('budgets', {})
    need(isinstance(budgets, dict) and set(budgets) == {'max_vias', 'max_expansions', 'max_states', 'max_seconds'},
         'BUDGET_MISSING', 'Explicit via/expansion/state/time budgets required')
    _integer(budgets['max_vias'], 'max_vias', 0, 8)
    _integer(budgets['max_expansions'], 'max_expansions', 1, MAX_SEARCH_STATES)
    _integer(budgets['max_states'], 'max_states', 2, MAX_SEARCH_STATES)
    _number(budgets['max_seconds'], 'max_seconds', maximum=60)
    if budgets['max_vias']:
        need(normal['via_envelope_all_layers_inflated'] is True, 'VIA_CLEARANCE_NOT_NORMALIZED',
             'Through-via envelope must account for every physical layer')
    endpoints = []
    for key in ('start', 'goal'):
        endpoint = problem.get(key, {})
        need(isinstance(endpoint, dict) and set(endpoint) == {'x', 'y', 'layer'}, 'INVALID_ENDPOINT', key)
        x, y = _coordinate([endpoint['x'], endpoint['y']], width, height, key)
        need(endpoint['layer'] in allowed_signals, 'ENDPOINT_LAYER_DISABLED', key)
        layer = names.index(endpoint['layer'])
        need((x, y) not in obstacles[layer], 'ENDPOINT_BLOCKED', key)
        endpoints.append((x, y, layer))
    need(endpoints[0] != endpoints[1], 'IDENTICAL_ENDPOINTS', 'Already-coincident endpoints need connectivity review, not routing')
    return problem, seen, (width, height, names, allowed_signals, obstacles, via_sites, endpoints)


def _path_result(state, parents, names, normal, gscore):
    chain = [state]
    while state in parents:
        state = parents[state]
        chain.append(state)
    chain.reverse()
    path, operations, length = [], [], 0.0
    for node in chain:
        x, y, layer, used_vias, _ = node
        path.append({'x': x, 'y': y, 'layer': names[layer], 'used_vias': used_vias,
                     'position_mm': [normal['origin_mm'][0] + x * normal['grid_pitch_mm'],
                                     normal['origin_mm'][1] + y * normal['grid_pitch_mm']]})
    for a, b in zip(chain, chain[1:]):
        if a[2] != b[2]:
            operations.append({'kind': 'through_via_candidate', 'at_grid': [a[0], a[1]],
                               'from_layer': names[a[2]], 'to_layer': names[b[2]],
                               'physical_span_layers': names[:]})
        else:
            length += math.hypot(b[0] - a[0], b[1] - a[1]) * normal['grid_pitch_mm']
            operations.append({'kind': 'track_candidate', 'layer': names[a[2]],
                               'start_grid': [a[0], a[1]], 'end_grid': [b[0], b[1]]})
    return {'grid_path': path, 'candidate_operations': operations, 'composite_grid_cost': gscore,
            'trace_length_mm': length, 'via_count': chain[-1][3]}


def _astar(problem, model, timer):
    width, height, names, signals, obstacles, via_sites, endpoints = model
    start, goal = endpoints
    budgets, normal = problem['budgets'], problem['normalization']
    signal_ids = {names.index(name) for name in signals}
    first = (*start, 0, NO_HEADING)
    best, parents = {first: 0.0}, {}
    frontier = [(octile(goal[0] - start[0], goal[1] - start[1]), 0, 0.0, first)]
    counter, expansions = 0, 0
    begun = timer()

    def status(name, reason=None):
        return {'status': name, 'reason': reason, 'expanded_states': expansions,
                'discovered_states': len(best), 'frontier_entries': len(frontier)}

    def clear(x, y, layer):
        return 0 <= x < width and 0 <= y < height and (x, y) not in obstacles[layer]

    while frontier:
        if timer() - begun >= budgets['max_seconds']:
            return status('NO_ROUTE_WITHIN_BUDGET', 'TIME_BUDGET')
        _, _, cost, state = heapq.heappop(frontier)
        if cost != best.get(state):
            continue
        x, y, layer, used_vias, heading = state
        if (x, y, layer) == goal:
            return {**status('GRID_ROUTE_FOUND_NOT_NATIVE_VERIFIED'),
                    **_path_result(state, parents, names, normal, cost)}
        if expansions >= budgets['max_expansions']:
            return status('NO_ROUTE_WITHIN_BUDGET', 'EXPANSION_BUDGET')
        expansions += 1
        moves = []
        layer_policy = problem['layers'][layer]
        for direction, (dx, dy) in enumerate(MOVES):
            nx, ny = x + dx, y + dy
            if not clear(nx, ny, layer):
                continue
            # Inflated-cell obstacles are closed: a diagonal cannot squeeze
            # between blocked orthogonal neighbors or cross their corners.
            if dx and dy and (not clear(x + dx, y, layer) or not clear(x, y + dy, layer)):
                continue
            length = math.sqrt(2) if dx and dy else 1.0
            nonpreferred = ((layer_policy['preferred_direction'] == 'horizontal' and dy != 0)
                            or (layer_policy['preferred_direction'] == 'vertical' and dx != 0))
            extra = length * layer_policy['nonpreferred_penalty'] if nonpreferred else 0.0
            bend = problem['bend_penalty'] if heading != NO_HEADING and heading != direction else 0.0
            moves.append(((nx, ny, layer, used_vias, direction), length + extra + bend))
        # A single through-via candidate spans ALL physical copper layers.
        # It may connect allowed signal layers only; it cannot evade an inner
        # layer obstacle or route a signal along a protected plane.
        if used_vias < budgets['max_vias'] and (x, y) in via_sites \
                and all(clear(x, y, physical) for physical in range(len(names))):
            for other in sorted(signal_ids - {layer}):
                moves.append(((x, y, other, used_vias + 1, NO_HEADING), problem['via_cost']))
        for next_state, step_cost in moves:
            candidate_cost = cost + step_cost
            if candidate_cost >= best.get(next_state, math.inf):
                continue
            if next_state not in best and len(best) >= budgets['max_states']:
                return status('NO_ROUTE_WITHIN_BUDGET', 'STATE_BUDGET')
            if len(frontier) >= budgets['max_states']:
                return status('NO_ROUTE_WITHIN_BUDGET', 'FRONTIER_BUDGET')
            best[next_state] = candidate_cost
            parents[next_state] = state
            counter += 1
            heuristic = octile(goal[0] - next_state[0], goal[1] - next_state[1])
            heapq.heappush(frontier, (candidate_cost + heuristic, counter, candidate_cost, next_state))
    return status('NO_ROUTE_IN_DECLARED_GRID', 'FRONTIER_EXHAUSTED')


def search(project, problem_file, timer=None):
    result = {'schema_version': 1, 'tool': 'script_route_search',
              'execution_scope': 'experimental_offline_grid_planning',
              'executed_on_pcb': False, 'production_authorized': False,
              'accepted_execution_backend': False, 'native_validation': 'NOT_RUN',
              'electrical_validation': 'NOT_VERIFIED',
              'remaining': ['independent grid extraction and source applicability review',
                            'actual KiCad candidate projection/readback',
                            'native DRC/parity/connectivity/protection checks',
                            'applicable electrical and engineering gates']}
    try:
        root = Path(project).resolve()
        need(root.is_dir(), 'PROJECT_MISSING', str(root))
        problem, seen, model = _read_problem(root, problem_file)
        result.update(problem_id=problem['problem_id'], scope=problem['scope'],
                      budgets=problem['budgets'], heuristic='octile_lower_bound',
                      assurance='Only the supplied conservative grid model is searched; normalization is declared, not certified')
        result.update(_astar(problem, model, timer or time.monotonic))
        for name, expected in seen.items():
            need(Path(name).is_file() and digest(name) == expected, 'INPUT_CHANGED_DURING_SEARCH', name)
        result['checked_files_sha256'] = seen
    except (PolicyError, OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        # Never expose an obsolete successful plan after inputs changed.
        for key in ('grid_path', 'candidate_operations', 'composite_grid_cost', 'trace_length_mm', 'via_count'):
            result.pop(key, None)
        result.update(status='BLOCKED', reason=getattr(error, 'code', 'INVALID_ROUTE_PROBLEM'), detail=str(error))
    return result


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--problem', required=True, help='Project-relative normalized grid problem JSON')
    parser.add_argument('--output-dir', type=Path, help='Optional NEW directory for route-plan.json')
    args = parser.parse_args()
    result = search(args.project, args.problem)
    if args.output_dir is not None:
        try:
            dest = args.output_dir.resolve()
            need(not dest.exists(), 'OUTPUT_EXISTS', str(dest))
            need(not any(Path(name).is_relative_to(dest) for name in result.get('checked_files_sha256', {})),
                 'UNSAFE_OUTPUT', 'Report directory contains checked inputs')
            dest.mkdir(parents=True, exist_ok=False)
            (dest / 'route-plan.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except (PolicyError, OSError) as error:
            result.update(status='BLOCKED', reason=getattr(error, 'code', 'OUTPUT_FAILED'), detail=str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] == 'GRID_ROUTE_FOUND_NOT_NATIVE_VERIFIED':
        return 0
    if result['status'] in {'NO_ROUTE_WITHIN_BUDGET', 'NO_ROUTE_IN_DECLARED_GRID'}:
        return 1
    return 2


if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
