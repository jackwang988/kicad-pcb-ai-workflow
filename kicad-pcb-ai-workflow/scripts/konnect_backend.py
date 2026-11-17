#!/usr/bin/env python3
"""Pinned Konnect MCP connection check; never changes an engineering document."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

VERSION = '0.14.1'
COMMIT = 'af1d81b0b45c33d0185a21cca7747f7c3a64f476'
BINARY_SHA256 = '2582b21ad6db171885bf34f2006fe630ebdf4592b3d9de7c24841f34a075fcf2'


def backend_profile(digest):
    """Only package-owned, pinned builds are eligible; project files cannot add trust."""
    path = Path(__file__).resolve().parents[1] / 'references/konnect-backends.json'
    if path.is_symlink():
        raise ValueError('Symlinked backend profiles refused')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported backend profile contract')
    matches = [p for p in data.get('profiles', []) if p.get('executable_sha256') == digest]
    if len(matches) != 1:
        raise ValueError('Konnect executable does not match a pinned Windows release')
    profile = matches[0]
    if profile.get('server_name') != 'konnect' or not profile.get('version') or not profile.get('build_commit'):
        raise ValueError('Incomplete pinned backend identity')
    return profile


class McpError(RuntimeError):
    pass


class McpSession:
    """A bounded newline JSON-RPC stdio session. A timed-out write is never retried."""
    def __init__(self, executable, config, timeout=25, env=None):
        self.timeout = timeout
        self.pending = queue.Queue()
        self.logs = []
        self.serial = 0
        self.notifications = []
        self.process = subprocess.Popen(
            [str(executable), '--client', 'codex', '--config', str(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            cwd=str(Path(config).resolve().parent), env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._stdout, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()
        try:
            self.server = self.request('initialize', {
                'protocolVersion': '2025-06-18', 'capabilities': {},
                'clientInfo': {'name': 'pcb-skill-validation', 'version': '1.0.0'}})
            self.notify('notifications/initialized', {})
        except BaseException:
            self.close()
            raise

    def _stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    self.pending.put(json.loads(line))
                except ValueError:
                    self.pending.put(McpError('Non-JSON MCP stdout'))
        finally:
            self.pending.put(McpError('MCP stdout closed'))

    def _stderr(self):
        for line in self.process.stderr:
            self.logs.append(line.rstrip())
            del self.logs[:-80]

    def notify(self, method, params):
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': method,
                                            'params': params}) + '\n')
        self.process.stdin.flush()

    def request(self, method, params):
        self.serial += 1
        request_id = self.serial
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': request_id,
                                            'method': method, 'params': params}) + '\n')
        self.process.stdin.flush()
        end = time.monotonic() + self.timeout
        while True:
            try:
                response = self.pending.get(timeout=max(.01, end - time.monotonic()))
            except queue.Empty:
                raise McpError('MCP timeout; result unknown; inspect before retrying') from None
            if isinstance(response, Exception):
                raise response
            if response.get('id') == request_id:
                if 'error' in response:
                    raise McpError(json.dumps(response['error'], ensure_ascii=False))
                return response.get('result', {})
            self.notifications.append(response)
            if time.monotonic() >= end:
                raise McpError('MCP response deadline exceeded')

    def tools(self):
        return self.request('tools/list', {}).get('tools', [])

    def call(self, name, arguments=None):
        result = self.request('tools/call', {'name': name, 'arguments': arguments or {}})
        if result.get('isError'):
            raise McpError(json.dumps(result, ensure_ascii=False))
        return result

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        for stream in (self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def body(result):
    if isinstance(result.get('structuredContent'), dict):
        return result['structuredContent']
    for item in result.get('content', []):
        if item.get('type') == 'text':
            try:
                return json.loads(item['text'])
            except ValueError:
                continue
    return result


def require_live_board(session, board, eligible_versions=('10.0.8',)):
    """Prove exact target identity at this endpoint; never treat file fallback as live."""
    state = body(session.call('get_editor_state'))
    if state.get('evidence_source') != 'kicad_ipc':
        raise McpError('No live KiCad IPC editor evidence')
    if state.get('kicad_version', {}).get('full_version') not in eligible_versions:
        raise McpError('KiCad version not approved for this Konnect build; require explicit version enrollment and fixture test')
    documents = [d for e in state.get('editors', []) if e.get('editor') == 'pcb'
                 and e.get('addressable') for d in e.get('documents', [])]
    target = Path(board).resolve()
    if len(documents) != 1 or Path(documents[0].get('document_path', '')).resolve() != target:
        raise McpError('Target board mismatch or ambiguous PCB documents; refuse live operation')
    info = body(session.call('get_board_info', {'board': str(target)}))
    if info.get('source') != 'ipc':
        raise McpError('Board was read from a saved file rather than live IPC')
    return {'editor_state': state, 'board': info}


def placement_preflight(session, board, references):
    """Read-only saved/live position and lock preflight without pcbnew.

    KiCad's file-format footprint parser only checks explicitly supported fields;
    ambiguous saved state blocks, and it never grants design approval.
    """
    import math
    from npi_common import parse_sexpr, children, child, value
    target = Path(board).resolve()
    if not references or len(references) != len(set(references)):
        raise ValueError('Unique explicit placement references required')
    require_live_board(session, target)
    before_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    tree = parse_sexpr(target.read_text(encoding='utf-8-sig'))
    if not tree or tree[0] != 'kicad_pcb':
        raise McpError('Expected KiCad board file')
    footprints = {}
    for fp in children(tree, 'footprint'):
        props = [p[2] for p in children(fp, 'property') if len(p)>2 and p[1]=='Reference']
        if not props:
            props = [p[2] for p in children(fp, 'fp_text') if len(p)>2 and p[1]=='reference']
        if len(props) != 1 or props[0] in footprints:
            raise McpError('Saved board reference missing/ambiguous/duplicated')
        at = child(fp, 'at', [])
        if len(at) < 3:
            raise McpError('Saved footprint missing position: ' + props[0])
        footprints[props[0]] = {'x':float(at[1]), 'y':float(at[2]),
                'rotation':float(at[3]) if len(at)>3 else 0.0,
                'layer':value(fp,'layer'),
                'locked':any(v=='locked' or (isinstance(v,list) and v and v[0]=='locked'
                                and len(v)>1 and v[1] not in ('no','false')) for v in fp[2:])}
    live = body(session.call('get_component_list', {'board': str(target)}))
    rows = live.get('components', [])
    if (len(rows) != len(footprints) or len({r.get('reference') for r in rows}) != len(rows)
            or {r.get('reference') for r in rows} != set(footprints)):
        raise McpError('Saved/live component inventory differs; save and re-plan first')
    for row in rows:
        fp = footprints[row['reference']]
        if (not math.isclose(fp['x'], row['x'], abs_tol=1e-6)
                or not math.isclose(fp['y'], row['y'], abs_tol=1e-6)
                or not math.isclose(fp['rotation'] % 360, row['rotation'] % 360, abs_tol=1e-6)
                or fp['layer'] != row['layer']):
            raise McpError('Saved/live placement differs; save and re-plan first')
    for ref in references:
        if ref not in footprints:
            raise McpError('Requested placement reference missing: ' + ref)
        if footprints[ref]['locked']:
            raise McpError('Locked footprint refused before mutation: ' + ref)
    if before_hash != hashlib.sha256(target.read_bytes()).hexdigest():
        raise McpError('Saved board changed during placement preflight')
    return {'status': 'PLACEMENT_PREFLIGHT_PASSED', 'board_sha256': before_hash,
            'references': references, 'scope': 'saved_file_lock_and_live_placement_consistency',
            'engine': 'read_only_kicad_file_parser+konnect_ipc',
            'executed': False, 'production_authorized': False}


def probe(executable, config, expected_board=None, placement_refs=None):
    executable, config = Path(executable).resolve(), Path(config).resolve()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    profile = backend_profile(digest)
    settings = json.loads(config.read_text(encoding='utf-8-sig'))
    if settings.get('transport') != 'stdio':
        raise ValueError('Connection checker requires explicit local stdio transport')
    if settings.get('ipc_address') and not settings['ipc_address'].startswith('ipc://'):
        raise ValueError('Only a local KiCad IPC address is supported')
    with McpSession(executable, config) as session:
        server = session.server.get('serverInfo', {})
        if server.get('name') != profile['server_name'] or server.get('version') != profile['version']:
            raise McpError('Unexpected MCP server identity')
        installation = body(session.call('get_installation_info'))
        build = installation.get('build', {})
        if build.get('version') != profile['version'] or build.get('commit') != profile['build_commit']:
            raise McpError('Serving Konnect build does not match the pinned build identity')
        report = {'server': server, 'protocol': session.server.get('protocolVersion'),
                  'executable_sha256': digest, 'tools': session.tools(),
                  'installation': installation, 'toolboxes': body(session.call('list_toolboxes')),
                  'backend_profile': profile['id'], 'backend_license': profile['license'],
                  'native_edit_tested': False, 'production_authorized': False}
        if expected_board:
            session.call('load_toolset', {'name': ['editor_navigation', 'pcb_board', 'pcb_components']})
            report['live'] = require_live_board(session, expected_board)
            report['status'] = 'LIVE_TARGET_READ_VERIFIED'
            if placement_refs:
                report['placement_preflight'] = placement_preflight(session, expected_board, placement_refs)
        else:
            report['status'] = 'MCP_CONNECTED_LIVE_BOARD_NOT_VERIFIED'
        return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--executable', type=Path)
    p.add_argument('--config', type=Path)
    p.add_argument('--installation', type=Path, help='Installer receipt; defaults to LOCALAPPDATA/PCB-Skill/install-receipt.json')
    p.add_argument('--expected-board', type=Path)
    p.add_argument('--placement-refs', nargs='+', help='Read-only native lock and saved/live placement preflight before an authorized edit')
    p.add_argument('--output-dir', required=True, type=Path)
    args = p.parse_args()
    out = args.output_dir.resolve()
    if out.exists():
        p.error('A new output directory is required')
    report = {'scope': 'mcp_read_only_connection', 'production_authorized': False,
              'native_edit_tested': False}
    try:
        if bool(args.executable) != bool(args.config):
            raise ValueError('Supply both --executable and --config, or an installation receipt')
        if not args.executable:
            receipt_root = (Path.home() / 'AppData/Local/PCB-Skill' if os.name == 'nt'
                            else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PCB-Skill')
            receipt_path = args.installation or receipt_root / 'install-receipt.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            args.executable, args.config = Path(receipt['executable']), Path(receipt['konnect_config'])
            if hashlib.sha256(args.config.read_bytes()).hexdigest() != receipt['konnect_config_sha256']:
                raise ValueError('Installed Konnect config changed; rerun installer check before use')
        if args.expected_board and (not args.expected_board.is_file() or args.expected_board.suffix != '.kicad_pcb'):
            raise ValueError('An existing expected .kicad_pcb board is required')
        if args.placement_refs and not args.expected_board:
            raise ValueError('--placement-refs requires an exact --expected-board')
        report.update(probe(args.executable, args.config, args.expected_board, args.placement_refs))
        code = 0
    except Exception as exc:
        report.update(status='BLOCKED', reason=str(exc))
        code = 2
    out.mkdir(parents=True, exist_ok=False)
    (out / 'connection.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('server', 'tools', 'installation', 'toolboxes')}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
