#!/usr/bin/env python3
"""Optional, read-only KiCad IPC probe and in-memory board snapshot.

Only the official kicad-python (kipy) client is loaded, and only on demand.
This adapter never installs a dependency, opens/saves a KiCad document, or
performs an edit. A successful probe is not PCB or manufacturing approval.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import sys
import uuid


BOARD_METHODS = (
    'get_as_string', 'get_items', 'get_items_by_id', 'get_footprints',
    'get_pads', 'get_tracks', 'get_vias', 'get_zones', 'get_nets',
    'get_stackup', 'get_selection', 'begin_commit', 'push_commit',
    'drop_commit', 'update_items', 'create_items', 'refill_zones',
)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _redact(value, env):
    """Never reflect credentials/endpoints through paths or server responses."""
    if isinstance(value, dict):
        return {key: _redact(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, env) for item in value]
    if isinstance(value, str):
        for key in ('KICAD_API_TOKEN', 'KICAD_API_SOCKET'):
            secret = env.get(key)
            if secret:
                value = value.replace(secret, '<redacted>')
    return value


def _base(mode):
    return {
        'schema': 'kicad-ipc-readonly/1',
        'operation': mode,
        'probe_id': str(uuid.uuid4()),
        'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'status': 'OPTIONAL_UNAVAILABLE',
        'ipc_ready': False,
        'offline_workflow_available': True,
        'production_authorized': False,
        'write_operations_executed': False,
        'manufacturing_backend_ready': False,
        'scope': 'read-only IPC observation; no design or manufacturing approval',
        'validation_scope': 'current observation only; not live editing acceptance',
        'errors': [],
    }


def _failure(report, code, status='OPTIONAL_UNAVAILABLE'):
    report['status'] = status
    report['ipc_ready'] = False
    report['errors'].append({'code': code})
    return report, None


def _absolute_board(value):
    board = Path(value)
    if not board.is_absolute() or board.suffix.lower() != '.kicad_pcb':
        raise ValueError('absolute_board_required')
    return board.resolve()


def _board_path(board):
    # DocumentSpecifier has board_filename + project.path, not a .path field.
    document = board.document
    name = document.board_filename
    project_path = document.project.path
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError('invalid_board_filename')
    if not isinstance(project_path, str) or not Path(project_path).is_absolute():
        raise ValueError('absolute_project_path_unavailable')
    return _absolute_board(Path(project_path) / name)


def _version(value):
    # Do not serialize arbitrary server/client objects or exception text.
    if isinstance(value, str):
        match = re.fullmatch(r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})', value)
        return '.'.join(match.groups()) if match else 'unknown'
    parts = [getattr(value, key, None) for key in ('major', 'minor', 'patch')]
    if all(isinstance(item, int) and not isinstance(item, bool) and 0 <= item < 1000
           for item in parts):
        return '.'.join(str(item) for item in parts)
    return 'unknown'


def _disk_state(board):
    try:
        data = board.read_bytes()
        return {'state': 'read', 'sha256': _sha(data), 'bytes': len(data)}
    except FileNotFoundError:
        return {'state': 'missing', 'sha256': None}
    except OSError:
        return {'state': 'unreadable', 'sha256': None}


def inspect_session(expected_board, mode='probe', env=None, client_factory=None,
                    timeout_ms=2000):
    """Return (JSON-safe report, optional snapshot text).

    client_factory is injectable for software-contract tests; injected clients
    are explicitly marked and never produce live-acceptance evidence.
    """
    env = dict(os.environ if env is None else env)
    report = _base(mode)
    if mode not in ('probe', 'snapshot') or not 1 <= timeout_ms <= 60000:
        return _failure(report, 'invalid_arguments', 'INVALID_ARGUMENTS')
    try:
        expected = _absolute_board(expected_board)
    except (TypeError, ValueError, OSError, RuntimeError):
        return _failure(report, 'absolute_kicad_pcb_path_required', 'INVALID_ARGUMENTS')
    report['expected_board_path'] = str(expected)
    report['dependency'] = {'package': 'kicad-python', 'installed': False}
    report['connection'] = {
        'selection': 'explicit_socket_and_token_only',
        'socket_present': bool(env.get('KICAD_API_SOCKET')),
        'token_present': bool(env.get('KICAD_API_TOKEN')),
        'default_endpoint_discovery': False,
    }
    report['client_source'] = 'injected_test_client' if client_factory else 'official_kipy'
    # Suppress output from the optional library, including connection diagnostics.
    # Failures below expose fixed codes only, never raw exception messages.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if client_factory is None:
            try:
                client_factory = importlib.import_module('kipy').KiCad
                report['dependency']['installed'] = True
                try:
                    report['dependency']['version'] = importlib.metadata.version('kicad-python')
                except importlib.metadata.PackageNotFoundError:
                    report['dependency']['version'] = 'unknown'
            except Exception:
                return _redact(_failure(report, 'optional_kipy_unavailable')[0], env), None
        else:
            report['dependency']['installed'] = True
        if not all((env.get('KICAD_API_SOCKET'), env.get('KICAD_API_TOKEN'))):
            return _redact(_failure(report, 'explicit_socket_and_token_required')[0], env), None
        # Endpoint hash identifies the selected endpoint without publishing its
        # address. The token is never hashed or copied into the report.
        report['connection']['endpoint_sha256'] = _sha(env['KICAD_API_SOCKET'].encode('utf-8'))
        try:
            client = client_factory(socket_path=env['KICAD_API_SOCKET'],
                                    kicad_token=env['KICAD_API_TOKEN'],
                                    timeout_ms=timeout_ms)
            report['kicad_version'] = _version(client.get_version())
        except Exception:
            return _redact(_failure(report, 'ipc_connect_or_version_failed')[0], env), None
        try:
            board = client.get_board()
            observed = _board_path(board)
        except Exception:
            return _redact(_failure(report, 'open_board_identity_unavailable')[0], env), None
        report['observed_board_path'] = str(observed)
        if observed != expected:
            return _redact(_failure(report, 'open_board_does_not_match_expected',
                                   'IDENTITY_MISMATCH')[0], env), None
        try:
            report['board_method_presence'] = {
                name: callable(getattr(board, name, None)) for name in BOARD_METHODS
            }
        except Exception:
            return _redact(_failure(report, 'method_detection_failed')[0], env), None
        report['method_detection_scope'] = 'attribute presence only, not execution verification'
        report['disk'] = _disk_state(expected)
        report['ipc_ready'] = True
        report['status'] = 'READONLY_PROBE_OK'
        if mode == 'probe':
            return _redact(report, env), None
        if not report['board_method_presence']['get_as_string']:
            return _redact(_failure(report, 'memory_snapshot_method_unavailable')[0], env), None
        try:
            memory = board.get_as_string()
            if not isinstance(memory, str) or not memory.lstrip().startswith('(kicad_pcb'):
                return _redact(_failure(report, 'invalid_board_snapshot')[0], env), None
            # Refuse to persist a payload containing connection secrets. Do not
            # alter a board snapshot and then present it as the original state.
            if any(env.get(key) and env[key] in memory
                   for key in ('KICAD_API_TOKEN', 'KICAD_API_SOCKET')):
                return _redact(_failure(report, 'sensitive_value_in_snapshot')[0], env), None
            second = board.get_as_string()
            final_path = _board_path(client.get_board())
        except Exception:
            return _redact(_failure(report, 'memory_snapshot_read_failed')[0], env), None
        final_disk = _disk_state(expected)
        if memory != second or final_path != expected or final_disk != report['disk']:
            return _redact(_failure(report, 'state_changed_during_snapshot',
                                   'STATE_CHANGED')[0], env), None
        payload = memory.encode('utf-8')
        report['memory'] = {'sha256': _sha(payload), 'bytes': len(payload),
                            'two_reads_equal': True, 'encoding': 'utf-8'}
        report['memory_disk_bytes_equal'] = (
            report['disk']['sha256'] == report['memory']['sha256']
            if report['disk']['state'] == 'read' else None
        )
        report['unsaved_changes'] = 'not_determined; serialization may differ from disk'
        report['snapshot_consistency'] = 'two matching reads, no atomic GUI lock'
        report['status'] = 'READONLY_SNAPSHOT_OK'
        return _redact(report, env), memory


def write_report(output_dir, expected_board, report, memory=None):
    """Write only to an explicitly new directory outside the source board folder."""
    target = Path(output_dir)
    if not target.is_absolute():
        raise ValueError('absolute_output_directory_required')
    target = target.resolve()
    source = _absolute_board(expected_board).parent
    if target == source or source in target.parents:
        raise ValueError('report_inside_source_project')
    # No recursive creation and no replacement: the parent must already exist.
    target.mkdir()
    if memory is not None:
        with (target / 'memory-board.kicad_pcb').open('xb') as handle:
            handle.write(memory.encode('utf-8'))
        report['snapshot_file'] = 'memory-board.kicad_pcb'
    with (target / 'ipc-report.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_cli_arguments')


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument('operation', choices=('probe', 'snapshot'))
    parser.add_argument('--board', required=True, type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--timeout-ms', type=int, default=2000)
    parser.add_argument('--require-ipc', action='store_true',
                        help='Return exit 2 when this task requires unavailable IPC.')
    try:
        args = parser.parse_args(argv)
    except ValueError:
        report, _ = _failure(_base('unknown'), 'invalid_cli_arguments', 'INVALID_ARGUMENTS')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    try:
        report, memory = inspect_session(args.board, args.operation, timeout_ms=args.timeout_ms)
    except Exception:
        # Keep a failed optional client from breaking the offline workflow and
        # do not print its potentially credential-bearing traceback.
        report, memory = _failure(_base(args.operation), 'unexpected_optional_probe_failure')
    if args.output_dir:
        try:
            write_report(args.output_dir, args.board, report, memory)
        except (OSError, TypeError, ValueError):
            report['status'] = 'REPORT_WRITE_REFUSED'
            report['errors'].append({'code': 'new_external_report_directory_required_or_write_failed'})
            print(json.dumps(_redact(report, os.environ), ensure_ascii=False, indent=2))
            return 2
    print(json.dumps(_redact(report, os.environ), ensure_ascii=False, indent=2))
    if report['status'] in ('INVALID_ARGUMENTS', 'IDENTITY_MISMATCH', 'STATE_CHANGED'):
        return 2
    return 2 if args.require_ipc and not report['ipc_ready'] else 0


if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
