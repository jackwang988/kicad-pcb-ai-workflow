#!/usr/bin/env python3
"""Opt-in high-speed/PDN audit of an explicitly saved KiCad candidate.

Never edits a board, starts an editor, runs DRC, or invokes a solver implicitly.
"""
import argparse
import json
from pathlib import Path
import sys

from engineering_gate import local
from npi_common import runtime_inventory, sha256

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    def invalid_constant(value):
        raise ValueError('Non-finite JSON constant: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=invalid_constant)


def bound_inputs(root, policy):
    if not isinstance(policy, dict) or type(policy.get('schema_version')) is not int or policy.get('schema_version') != 1:
        raise ValueError('High-speed policy schema_version=1 required')
    inputs = policy.get('inputs')
    if not isinstance(inputs, dict) or 'board' not in inputs:
        raise ValueError('Policy must bind the actual saved board')
    hashes = {}
    for name, entry in inputs.items():
        if not isinstance(entry, dict) or set(entry) != {'file', 'sha256'}:
            raise ValueError('Input binding needs exactly file/sha256: ' + str(name))
        path = local(root, entry['file'])
        if not path.is_file() or not path.stat().st_size or sha256(path) != entry['sha256']:
            raise ValueError('Missing or changed input: ' + str(name))
        hashes[entry['file']] = entry['sha256']
    board = local(root, inputs['board']['file'])
    if board.suffix != '.kicad_pcb':
        raise ValueError('Explicit .kicad_pcb input required')
    return board, hashes


def audit_project(root, policy_file, native=True):
    from hs_board_snapshot import extract_board
    from hs_rule_engine import audit
    root = Path(root).resolve()
    path = local(root, policy_file)
    policy_hash = sha256(path)
    policy = read_json(path)
    board, hashes = bound_inputs(root, policy)
    catalog_path = ROOT / 'references/high-speed/rules.json'
    catalog = read_json(catalog_path)
    snapshot = extract_board(board, native=native)
    result = audit(policy, snapshot, root, catalog)
    if sha256(path) != policy_hash or any(sha256(local(root, n)) != h for n, h in hashes.items()):
        raise ValueError('Inputs changed during audit; discard result and re-read')
    result.setdefault('inputs_sha256', {}).update(hashes)
    result.update(schema_version=1, scope='declared_high_speed_checks_only',
                  production_authorized=False, package_ready_authorized=False,
                  board_sha256=snapshot['board_sha256'],
                  policy_sha256=policy_hash, catalog_sha256=sha256(catalog_path),
                  source_registry_sha256=sha256(ROOT / 'references/high-speed/source_registry.json'),
                  native_geometry_verified=snapshot['native_geometry_verified'],
                  snapshot=snapshot,
                  runtime_sha256={name: sha256(ROOT / 'scripts' / (name + '.py'))
                                  for name in ('high_speed', 'hs_board_snapshot', 'hs_rule_engine', 'hs_solver')})
    return result


def intake(root, board_file, native=True):
    from hs_board_snapshot import extract_board
    root = Path(root).resolve()
    board = local(root, board_file)
    snapshot = extract_board(board, native=native)
    inputs = {'board': {'file': board.relative_to(root).as_posix(), 'sha256': snapshot['board_sha256']}}
    for name, suffix in (('project', '.kicad_pro'), ('rules', '.kicad_dru')):
        sibling = board.with_suffix(suffix)
        if sibling.is_file() and sibling.stat().st_size:
            sibling = local(root, sibling.relative_to(root))
            inputs[name] = {'file': sibling.relative_to(root).as_posix(), 'sha256': sha256(sibling)}
    return {'schema_version': 1, 'phase': 'pre_route', 'inputs': inputs,
            'nets': [{'name': n['name'], 'kind': 'unknown'} for n in snapshot['nets']],
            'differential_pairs': [], 'power_rails': [], 'manufacturing': {},
            'stackup': {}, 'requirements': [], 'evidence': [],
            'scope_note': 'Derived from actual board inventory. Classify from real pin/interface evidence; no inferred defaults.'}


def write_report(result, directory):
    directory = Path(directory).absolute()
    if directory.exists() or any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('A new non-symlink report directory is required')
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'high-speed-audit.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('audit', 'init', 'snapshot'):
        item = sub.add_parser(name)
        item.add_argument('project')
        item.add_argument('--policy' if name == 'audit' else '--board', required=True)
        item.add_argument('--static-preview', action='store_true', help='Parser preview only; never native geometry proof')
        if name == 'init':
            item.add_argument('--output-file')
            item.add_argument('--apply', action='store_true')
        else:
            item.add_argument('--output-dir')
    for name in ('solver-plan', 'solver-run'):
        item = sub.add_parser(name)
        item.add_argument('project')
        item.add_argument('--request', required=True)
        item.add_argument('--board', required=True, help='Current saved board whose hash must match the model request')
        if name == 'solver-run':
            item.add_argument('--solver-executable', required=True)
            item.add_argument('--solver-sha256', required=True)
            item.add_argument('--output-dir', required=True)
            item.add_argument('--timeout-seconds', type=int, default=60)
    args = parser.parse_args()
    try:
        runtime_inventory(ROOT)
        root = Path(args.project).resolve()
        if not root.is_dir():
            raise ValueError('Existing project directory required')
        if args.command == 'audit':
            result = audit_project(root, args.policy, native=not args.static_preview)
        elif args.command == 'snapshot':
            from hs_board_snapshot import extract_board
            result = extract_board(local(root, args.board), native=not args.static_preview)
            result.update(status='BOARD_SNAPSHOT_ONLY', production_authorized=False)
        elif args.command == 'init':
            result = {'status': 'POLICY_PREVIEW', 'policy': intake(root, args.board, native=not args.static_preview),
                      'production_authorized': False}
            if args.apply:
                if not args.output_file:
                    raise ValueError('Writing intake needs explicit --output-file')
                path = local(root, args.output_file)
                if path.exists() or path.parent != root and not path.parent.is_dir():
                    raise ValueError('New policy file in an existing project directory required')
                with path.open('x', encoding='utf-8') as stream:
                    json.dump(result['policy'], stream, ensure_ascii=False, indent=2, allow_nan=False)
                result['status'] = 'UNCLASSIFIED_POLICY_CREATED'
        else:
            import hs_solver
            request_path = local(root, args.request)
            request_hash = sha256(request_path)
            request = read_json(request_path)
            solver_board = local(root, args.board)
            board_hash = sha256(solver_board)
            if solver_board.suffix != '.kicad_pcb' or not isinstance(request, dict) or request.get('board_sha256') != board_hash:
                raise ValueError('Solver model must bind this current saved .kicad_pcb input')
            if args.command == 'solver-plan':
                result = hs_solver.plan(request, root=root)
            else:
                result = hs_solver.run(request, Path(args.solver_executable), args.solver_sha256,
                                       Path(args.output_dir), args.timeout_seconds, root=root)
            if sha256(solver_board) != board_hash or sha256(request_path) != request_hash:
                raise ValueError('Board or request changed during model preparation/analysis; result is stale')
            result['board_binding'] = 'current_saved_board_verified'
            result['request_file_sha256'] = request_hash
            if args.command == 'solver-run' and Path(args.output_dir).is_dir() and result.get('external_solver_executed'):
                with (Path(args.output_dir) / 'bound-result.json').open('x', encoding='utf-8') as stream:
                    json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        if getattr(args, 'output_dir', None) and args.command in ('audit', 'snapshot'):
            write_report(result, args.output_dir)
        summary = {k: v for k, v in result.items() if k not in ('snapshot', 'netlist')}
        print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
        if result.get('status', '').startswith('BLOCKED'):
            return 2
        return 1 if result.get('status') in ('REVIEW_REQUIRED', 'FAIL', 'SAMPLED_MODEL_EXCEEDS_TARGET') else 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc), 'production_authorized': False}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
