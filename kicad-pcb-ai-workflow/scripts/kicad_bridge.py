#!/usr/bin/env python3
"""Optional local KiCad IPC bridge. No TCP, arbitrary code or source-board writes.

The KiCad-launched process retains credentials in memory and serializes typed
requests through a local file inbox. A new candidate, explicit apply, exact
baseline and object readback are required. Software tests are not live approval.
"""
import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import importlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import struct
import time
import traceback
import uuid
import zlib

from kicad_ipc_probe import _board_path, _version, _redact

VERSION = 'R10.0-alpha.2'
KIPY_VERSION = '0.8.0'
MAX_BYTES = 8 * 1024 * 1024


class Refused(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise Refused(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def pairs(rows):
    result = {}
    for key, value in rows:
        need(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def clean_path(value, exists=False):
    p = Path(value).absolute()
    need(Path(value).is_absolute(), 'absolute_path_required')
    for part in (p, *p.parents):
        need(not part.is_symlink(), 'linked_path_refused')
        if part.exists():
            flags = getattr(part.lstat(), 'st_file_attributes', 0)
            need(not flags & 1024, 'reparse_path_refused')
    p = p.resolve()
    if exists:
        need(p.exists(), 'path_missing')
    return p


def read_json(path):
    p = clean_path(str(path), True)
    need(p.is_file() and p.stat().st_size <= MAX_BYTES, 'json_file_size')
    return json.loads(p.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda value: need(False, 'nonfinite_json'))


def new_file(path, data):
    p = clean_path(str(path))
    with p.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def new_json(path, value):
    new_file(path, encoded(value).encode('utf-8'))


def strict(value, required, optional=()):
    need(isinstance(value, dict) and set(required) <= set(value)
         and set(value) <= set(required) | set(optional), 'unknown_or_missing_fields')


def ident(value):
    need(isinstance(value, str), 'uuid_required')
    need(str(uuid.UUID(value)) == value, 'canonical_uuid_required')
    return value


def integer(value):
    need(type(value) is int and -(2 ** 31) < value < 2 ** 31, 'integer_nm_required')
    return value


def fp_id(item):
    return ident(item.id.value)


def proto_hash(item):
    return digest(item.proto.SerializeToString(deterministic=True))


def fp_row(item):
    pads = []
    for pad in item.definition.pads:
        pads.append({'uuid': fp_id(pad), 'number': pad.number, 'net': pad.net.name,
                     'x_nm': pad.position.x, 'y_nm': pad.position.y})
    return {'uuid': fp_id(item), 'reference': item.reference_field.text.value,
            'x_nm': item.position.x, 'y_nm': item.position.y,
            'angle_deg': item.orientation.degrees, 'locked': item.locked,
            'proto_sha256': proto_hash(item), 'pads': pads}


class Engine:
    """Single-process owner. Injected clients are explicitly test evidence."""
    def __init__(self, client, board_path, area, env=None, test_client=False):
        self.client = client
        self.expected = clean_path(str(board_path), True)
        self.area = clean_path(str(area), True)
        self.env = dict(os.environ if env is None else env)
        self.test_client = test_client
        self.code_sha256 = digest(Path(__file__).read_bytes())
        self.session_id = str(uuid.uuid4())
        self.plans = {}
        self.last = None
        self.uncertain = False
        self.seq = 0
        self.version = _version(client.get_version())
        need(self.version == '10.0.8' or test_client, 'unaccepted_kicad_profile')
        self.snapshot()

    def result(self, status, **values):
        return {'status': status, 'version': VERSION, 'session_id': self.session_id,
                'bridge_sha256': self.code_sha256,
                'managed_temp_isolation': bool(self.env.get('PCB_SKILL_RUNTIME_TEMP')),
                'checked_at': now(), 'production_authorized': False,
                'client_source': 'injected_test_client' if self.test_client else 'official_kipy',
                'engineering_approved': False, **values}

    def snapshot(self):
        board = self.client.get_board()
        need(_board_path(board) == self.expected, 'board_identity_changed')
        disk = digest(self.expected.read_bytes())
        memory = board.get_as_string()
        need(isinstance(memory, str) and memory.lstrip().startswith('(kicad_pcb'),
             'invalid_memory_board')
        need(not any(self.env.get(k) and self.env[k] in memory
                     for k in ('KICAD_API_TOKEN', 'KICAD_API_SOCKET')), 'secret_in_board')
        items = list(board.get_footprints())
        need(len({fp_id(x) for x in items}) == len(items), 'duplicate_object_uuid')
        need(board.get_as_string() == memory and _board_path(self.client.get_board()) == self.expected
             and digest(self.expected.read_bytes()) == disk, 'state_changed_during_read')
        return board, memory, {fp_id(x): x for x in items}, disk

    def journal(self, action, stage, **values):
        self.seq += 1
        new_json(self.area / ('journal-%06d.json' % self.seq),
                 self.result(stage, action_id=action, **values))

    def manifest(self, path):
        p = clean_path(path, True)
        data = read_json(p)
        strict(data, ('schema', 'source_board', 'candidate_board', 'source_files',
                      'candidate_files', 'created_at'))
        need(data['schema'] == 'kicad-candidate/1', 'candidate_schema')
        source = clean_path(data['source_board'], True)
        need(type(data['source_files']) is dict and type(data['candidate_files']) is dict
             and source.name in data['source_files']
             and self.expected.name in data['candidate_files'], 'incomplete_candidate_manifest')
        need(clean_path(data['candidate_board'], True) == self.expected
             and source.parent != self.expected.parent
             and not self.expected.is_relative_to(source.parent)
             and not source.is_relative_to(self.expected.parent), 'isolated_candidate_required')
        need(p.parent == self.expected.parent, 'candidate_manifest_location')
        for name, expected in data['source_files'].items():
            f = self.relative_file(source.parent, name)
            need(digest(f.read_bytes()) == expected, 'source_changed')
        # Candidate PCB may change through this bridge, but other captured inputs may not.
        for name, expected in data['candidate_files'].items():
            f = self.relative_file(self.expected.parent, name)
            if f != self.expected:
                need(digest(f.read_bytes()) == expected, 'candidate_resource_changed')
        return data, digest(p.read_bytes())

    @staticmethod
    def relative_file(root, name):
        need(isinstance(name, str) and name and not Path(name).is_absolute()
             and '..' not in Path(name).parts and ':' not in name, 'relative_file_required')
        p = clean_path(str(root / name), True)
        need(p.is_relative_to(root) and p.is_file(), 'project_file_required')
        return p

    def candidate(self, request):
        strict(request, ('op', 'destination', 'files', 'apply'))
        need(request['apply'] is True, 'explicit_apply_required')
        board, memory, items, disk = self.snapshot()
        out = clean_path(request['destination'])
        root = self.expected.parent
        need(not out.exists() and out.parent.is_dir() and not out.is_relative_to(root)
             and not root.is_relative_to(out), 'new_external_candidate_required')
        need(type(request['files']) is list and len(request['files']) <= 500,
             'explicit_project_files_required')
        names = set(request['files']) | {self.expected.name}
        for name in (self.expected.stem + '.kicad_pro', self.expected.stem + '.kicad_sch',
                     'sym-lib-table', 'fp-lib-table'):
            if (root / name).exists():
                need(name in names, 'include_existing_project_and_library_tables')
        sources = {name: self.relative_file(root, name) for name in names}
        payloads = {name: p.read_bytes() for name, p in sources.items()}
        need(sum(map(len, payloads.values())) <= 64 * 1024 * 1024, 'candidate_size_limit')
        need(digest(payloads[self.expected.name]) == disk, 'source_changed')
        # A saved source file is not substituted for the current GUI memory.
        original = {name: digest(data) for name, data in payloads.items()}
        payloads[self.expected.name] = memory.encode('utf-8')
        need(self.snapshot()[1] == memory, 'source_changed')
        out.mkdir()
        for name, data in payloads.items():
            p = out / name
            p.parent.mkdir(parents=True, exist_ok=True)
            new_file(p, data)
        need(all(digest(p.read_bytes()) == original[name] for name, p in sources.items()),
             'source_changed_during_copy')
        manifest = {'schema': 'kicad-candidate/1', 'source_board': str(self.expected),
                    'candidate_board': str(out / self.expected.name),
                    'source_files': original,
                    'candidate_files': {name: digest(data) for name, data in payloads.items()},
                    'created_at': now()}
        new_json(out / 'candidate-manifest.json', manifest)
        return self.result('CANDIDATE_CREATED_NOT_NATIVE_VERIFIED',
                           candidate_board=manifest['candidate_board'],
                           next_step='Open candidate in PCB Editor, connect it and run plan.',
                           resource_scope='explicit files only; external libraries require separate resource audit')

    def plan(self, request):
        strict(request, ('op', 'candidate_manifest', 'targets', 'allowed_box_nm', 'max_delta_nm'))
        _, manifest_hash = self.manifest(request['candidate_manifest'])
        need(type(request['targets']) is list and 1 <= len(request['targets']) <= 100,
             'batch_size_1_to_100')
        box = request['allowed_box_nm']
        need(type(box) is list and len(box) == 4, 'explicit_allowed_box_required')
        box = [integer(x) for x in box]
        need(box[0] < box[2] and box[1] < box[3], 'invalid_allowed_box')
        delta = integer(request['max_delta_nm'])
        need(delta > 0, 'positive_max_delta_required')
        board, memory, items, disk = self.snapshot()
        after = {}
        before = {}
        for target in request['targets']:
            strict(target, ('uuid', 'x_nm', 'y_nm', 'angle_deg'))
            key = ident(target['uuid'])
            need(key in items and key not in before, 'missing_or_duplicate_target')
            item = items[key]
            need(not item.locked, 'locked_footprint')
            x, y = integer(target['x_nm']), integer(target['y_nm'])
            angle = target['angle_deg']
            need(type(angle) in (int, float) and math.isfinite(angle)
                 and -180 <= angle <= 180 and angle % 90 == 0
                 and item.orientation.degrees % 90 == 0, 'orthogonal_rotation_only')
            need(math.hypot(x-item.position.x, y-item.position.y) <= delta,
                 'movement_budget_exceeded')
            changed = copy.deepcopy(item)
            changed.position = type(item.position).from_xy(x, y)
            changed.orientation = type(item.orientation).from_degrees(angle)
            need(len(changed.definition.items) == len(item.definition.items),
                 'unsupported_footprint_children')
            for point in [changed.position] + [p.position for p in changed.definition.pads]:
                need(box[0] <= point.x <= box[2] and box[1] <= point.y <= box[3],
                     'outside_declared_envelope')
            before[key], after[key] = copy.deepcopy(item), changed
        action = str(uuid.uuid4())
        plan = {'action_id': action, 'session_id': self.session_id,
                'candidate_manifest': str(clean_path(request['candidate_manifest'], True)),
                'manifest_sha256': manifest_hash, 'memory_sha256': digest(memory.encode('utf-8')),
                'disk_sha256': disk, 'before': before, 'after': after,
                'all_before': {key: proto_hash(value) for key, value in items.items()}}
        self.plans[action] = plan
        self.journal(action, 'PLANNED', baseline=plan['memory_sha256'],
                     before=[fp_row(v) for v in before.values()],
                     after=[fp_row(v) for v in after.values()])
        new_file(self.area / (action + '-checkpoint.kicad_pcb'), memory.encode('utf-8'))
        return self.result('EDIT_PLAN_READY_NOT_APPLIED', action_id=action,
                           baseline_sha256=plan['memory_sha256'],
                           before=[fp_row(v) for v in before.values()],
                           after=[fp_row(v) for v in after.values()],
                           constraint_scope='declared envelope for centers and pads; not board-edge/courtyard/electrical approval')

    def same_state(self, expected):
        _, memory, items, disk = self.snapshot()
        return digest(memory.encode('utf-8')) == expected

    def transact(self, action, board, before_memory, expected_items, expected_all):
        self.journal(action, 'BEGIN_REQUESTED')
        self.uncertain = True  # If any IPC reply is lost, writes remain disabled.
        commit = None
        push_requested = False
        try:
            commit = board.begin_commit()
            returned = list(board.update_items(list(expected_items.values())))
            need({fp_id(x): proto_hash(x) for x in returned}
                 == {k: proto_hash(v) for k, v in expected_items.items()}, 'update_return_mismatch')
            self.journal(action, 'PUSH_REQUESTED')
            push_requested = True
            board.push_commit(commit, 'PCB Skill ' + action)
            _, memory, actual, _ = self.snapshot()
            need({k: proto_hash(v) for k, v in actual.items()} == expected_all,
                 'post_commit_readback_mismatch')
            self.journal(action, 'APPLIED_READBACK_VERIFIED',
                         memory_sha256=digest(memory.encode('utf-8')))
            self.uncertain = False
            return memory
        except Exception:
            if commit is not None and not push_requested:
                try:
                    board.drop_commit(commit)
                    if self.same_state(digest(before_memory.encode('utf-8'))):
                        self.journal(action, 'CANCELLED_READBACK_VERIFIED')
                        self.uncertain = False
                        return None
                except Exception:
                    pass
            self.journal(action, 'RESULT_UNCERTAIN_WRITES_DISABLED')
            return None

    def apply(self, request):
        strict(request, ('op', 'action_id', 'apply'))
        need(request['apply'] is True, 'explicit_apply_required')
        action = ident(request['action_id'])
        need(action in self.plans, 'unknown_action_for_session')
        plan = self.plans[action]
        need(not plan.get('started'), 'action_already_started_use_reconcile')
        need(self.manifest(plan['candidate_manifest'])[1] == plan['manifest_sha256'],
             'candidate_manifest_changed')
        board, memory, items, disk = self.snapshot()
        need(digest(memory.encode('utf-8')) == plan['memory_sha256']
             and disk == plan['disk_sha256'], 'stale_plan')
        desired = {**plan['all_before'], **{k: proto_hash(v) for k, v in plan['after'].items()}}
        # Mark once before attempting an IPC mutation; never automatically retry.
        plan['started'] = True
        self.last = {'plan': plan, 'expected_all': desired, 'after_hash': None}
        result = self.transact(action, board, memory, plan['after'], desired)
        if result is not None:
            self.last['after_hash'] = digest(result.encode('utf-8'))
            return self.result('APPLIED_READBACK_VERIFIED_NOT_REVIEWED', action_id=action,
                               footprints=[fp_row(x) for x in plan['after'].values()],
                               evidence_update_required=True, saved=False)
        return self.result('RESULT_UNCERTAIN_WRITES_DISABLED' if self.uncertain
                           else 'CANCELLED_READBACK_VERIFIED', action_id=action)

    def reconcile(self):
        need(self.last is not None, 'no_action_in_this_session')
        _, memory, items, _ = self.snapshot()
        actual = {k: proto_hash(v) for k, v in items.items()}
        # Full memory equality required to prove an uncommitted cancellation.
        if digest(memory.encode('utf-8')) == self.last['plan']['memory_sha256']:
            status = 'BASELINE_OBSERVED'
        elif actual == self.last['expected_all']:
            status = 'TARGET_OBJECTS_OBSERVED_REVIEW_REQUIRED'
        else:
            status = 'UNRESOLVED_MANUAL_REVIEW_REQUIRED'
        # Reconciliation is observational. A lost-reply session remains write-disabled.
        return self.result(status, writes_disabled=self.uncertain,
                           action_id=self.last['plan']['action_id'])

    def restore(self, request):
        strict(request, ('op', 'action_id', 'apply'))
        need(request['apply'] is True and self.last is not None, 'explicit_restore_required')
        plan = self.last['plan']
        need(request['action_id'] == plan['action_id'] and not self.last.get('restored'),
             'latest_applied_action_required')
        self.manifest(plan['candidate_manifest'])
        board, memory, items, _ = self.snapshot()
        need(digest(memory.encode('utf-8')) == self.last['after_hash'], 'state_changed_no_auto_restore')
        result = self.transact(str(uuid.uuid4()), board, memory, plan['before'], plan['all_before'])
        if result is not None:
            self.last['restored'] = True
            return self.result('RESTORED_OBJECTS_VERIFIED_NOT_SAVED', saved=False)
        return self.result('RESULT_UNCERTAIN_WRITES_DISABLED' if self.uncertain
                           else 'RESTORE_CANCELLED_READBACK_VERIFIED')

    def save(self, request):
        strict(request, ('op', 'action_id', 'apply'))
        need(request['apply'] is True and self.last is not None, 'explicit_save_required')
        plan = self.last['plan']
        need(request['action_id'] == plan['action_id'] and not self.last.get('restored'),
             'latest_applied_action_required')
        self.manifest(plan['candidate_manifest'])
        board, memory, items, _ = self.snapshot()
        need(digest(memory.encode('utf-8')) == self.last['after_hash'], 'state_changed_before_save')
        self.journal(plan['action_id'], 'SAVE_REQUESTED')
        self.uncertain = True
        board.save()
        _, after, actual, disk = self.snapshot()
        need(after == memory, 'memory_changed_during_save')
        self.manifest(plan['candidate_manifest'])
        self.journal(plan['action_id'], 'CANDIDATE_SAVED', disk_sha256=disk)
        self.uncertain = False
        return self.result('SAVED_CANDIDATE_NATIVE_REVIEW_REQUIRED', disk_sha256=disk,
                           candidate_board=str(self.expected),
                           native_reload_drc_required=True, evidence_update_required=True)

    def handle(self, request):
        try:
            need(isinstance(request, dict), 'object_request_required')
            op = request.get('op')
            need(op in ('inspect', 'candidate', 'plan', 'apply', 'restore', 'reconcile', 'save', 'stop'),
                 'unsupported_operation')
            if op in ('apply', 'restore', 'save', 'plan'):
                need(not self.uncertain, 'uncertain_session_writes_disabled')
            if op == 'inspect':
                strict(request, ('op',))
                _, memory, items, disk = self.snapshot()
                result = self.result('CONNECTED_READONLY', board=str(self.expected),
                                     kicad_version=self.version, memory_sha256=digest(memory.encode('utf-8')),
                                     disk_sha256=disk, footprints=[fp_row(x) for x in items.values()],
                                     writes_disabled=self.uncertain)
            elif op == 'reconcile':
                strict(request, ('op',))
                result = self.reconcile()
            elif op == 'stop':
                strict(request, ('op',))
                result = self.result('STOPPED')
            else:
                result = getattr(self, op)(request)
            return _redact(result, self.env)
        except Refused as exc:
            return self.result('BLOCKED', code=str(exc), writes_disabled=self.uncertain)
        except Exception:
            return self.result('BLOCKED', code='operation_failed_inspect_and_reconcile',
                               writes_disabled=self.uncertain)


def official_client(env):
    need(all(env.get(k) for k in ('KICAD_API_SOCKET', 'KICAD_API_TOKEN')),
         'launch_from_kicad_connection_action')
    if env.get('PCB_SKILL_RUNTIME_TEMP'):
        temporary = clean_path(env['PCB_SKILL_RUNTIME_TEMP'], True)
        need(str(temporary).replace('\\','/').lower() in
             env['KICAD_API_SOCKET'].replace('\\','/').lower(), 'managed_endpoint_isolation_failed')
    try:
        need(importlib.metadata.version('kicad-python') == KIPY_VERSION, 'unaccepted_kipy_version')
        module = importlib.import_module('kipy')
    except importlib.metadata.PackageNotFoundError:
        raise Refused('optional_kipy_unavailable')
    return module.KiCad(socket_path=env['KICAD_API_SOCKET'],
                        kicad_token=env['KICAD_API_TOKEN'], timeout_ms=3000)


@contextlib.contextmanager
def writer_lease(root, board):
    """OS releases this cooperating-writer lock on crash; no stale-lock deletion."""
    lock = clean_path(str(root / ('writer-' + digest(os.path.normcase(str(board)).encode('utf-8')) + '.lock')))
    with lock.open('a+b') as stream:
        module = importlib.import_module('msvcrt' if os.name == 'nt' else 'fcntl')
        try:
            stream.seek(0)
            if not stream.read(1):
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                module.locking(stream.fileno(), module.LK_NBLCK, 1)
            else:
                module.flock(stream.fileno(), module.LOCK_EX | module.LOCK_NB)
        except OSError:
            raise Refused('board_already_owned_in_sessions_root')
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                module.locking(stream.fileno(), module.LK_UNLCK, 1)
            else:
                module.flock(stream.fileno(), module.LOCK_UN)


def serve(session_dir, client=None, env=None, limit=None):
    env = dict(os.environ if env is None else env)
    area = clean_path(str(session_dir))
    need(not area.exists() and area.parent.is_dir(), 'new_session_dir_required')
    # No tokens are persisted. Same OS user is trusted to access this local queue.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        native = client or official_client(env)
        expected = _board_path(native.get_board())
        lease = writer_lease(area.parent, expected)
        lease.__enter__()
        try:
            return serve_owned(area, native, expected, env, client is not None, limit)
        finally:
            lease.__exit__(None, None, None)


def serve_owned(area, native, expected, env, test_client, limit):
        area.mkdir(mode=0o700)
        (area / 'requests').mkdir()
        (area / 'results').mkdir()
        engine = Engine(native, expected, area, env, test_client=test_client)
        new_json(area / 'connection.json', engine.result('SESSION_READY', board=str(expected),
                                                        pid=os.getpid(), kicad_version=engine.version))
        count = 0
        seen = set()
        while limit is None or count < limit:
            requests = sorted((area / 'requests').glob('*.ready'))
            for path in requests:
                if path.name in seen:
                    continue
                key = path.stem
                try:
                    ident(key)
                    need(path.name == key + '.ready' and clean_path(str(path), True).is_dir(),
                         'invalid_request_marker')
                    request = read_json(path.with_suffix('.json'))
                    reply = engine.handle(request)
                except Exception:
                    reply = engine.result('BLOCKED', code='invalid_request_file')
                seen.add(path.name)
                new_json(area / 'results' / (key + '.json'), reply)
                # Atomic directory creation publishes a fully flushed payload.
                # This also works where Windows denies file rename operations.
                (area / 'results' / (key + '.ready')).mkdir()
                count += 1
                if reply['status'] == 'STOPPED':
                    new_json(area / 'stopped.json', {'stopped_at': now()})
                    return
            time.sleep(0.1)


def send_request(session_dir, request, apply=False, wait_seconds=8):
    area = clean_path(str(session_dir), True)
    connection = read_json(area / 'connection.json')
    need(connection.get('bridge_sha256') == digest(Path(__file__).read_bytes()),
         'bridge_build_mismatch_reconnect_updated_plugin')
    need(not (area / 'stopped.json').exists(), 'session_stopped')
    # Source/candidate writes are never authorized merely by a JSON boolean.
    if request.get('op') in ('candidate', 'apply', 'restore', 'save'):
        need(apply, 'explicit_apply_required')
        request = {**request, 'apply': True}
    else:
        need(not apply, 'apply_invalid_for_readonly_operation')
    key = str(uuid.uuid4())
    # Publish only after the payload is flushed; readers watch the directory marker.
    new_json(area / 'requests' / (key + '.json'), request)
    (area / 'requests' / (key + '.ready')).mkdir()
    end = time.monotonic() + wait_seconds
    result = area / 'results' / (key + '.json')
    while time.monotonic() < end:
        if (area / 'results' / (key + '.ready')).is_dir():
            reply = read_json(result)
            need(reply['session_id'] == connection['session_id'], 'session_reply_mismatch')
            return reply
        time.sleep(0.1)
    return {'status': 'PENDING_DO_NOT_RESUBMIT', 'request_id': key,
            'result_file': str(result), 'ready_directory': str(result.with_suffix('.ready')),
            'production_authorized': False}


def plugin_icon():
    """Small original PNG: visible toolbar entry is required by KiCad 10."""
    glyph = ('11110','10001','10001','11110','10000','10000','10000')
    rows = []
    for y in range(32):
        row = bytearray(b'\x00')
        for x in range(32):
            on = 8 <= x < 23 and 5 <= y < 26 and glyph[(y-5)//3][(x-8)//3] == '1'
            row.extend((255,255,255,255) if on else (22,118,81,255))
        rows.append(bytes(row))
    def chunk(kind, value):
        return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',32,32,8,6,0,0,0))
            +chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))


def plugin_package(destination, sessions_root, apply=False, python_executable=None):
    out = clean_path(destination)
    sessions = clean_path(sessions_root, True)
    need(sessions.is_dir() and not out.exists() and out.parent.is_dir(), 'new_plugin_directory_required')
    interpreter = clean_path(python_executable, True) if python_executable else None
    if interpreter:
        need(interpreter.name.lower() in ('python', 'python3', 'python.exe', 'pythonw.exe'),
             'python_interpreter_required')
    result = {'status': 'PLUGIN_INSTALL_PREVIEW', 'destination': str(out),
              'sessions_root': str(sessions), 'version': VERSION, 'production_authorized': False}
    if apply:
        out.mkdir()
        for name in ('kicad_bridge.py', 'kicad_ipc_probe.py', 'npi_common.py'):
            new_file(out / name, Path(__file__).with_name(name).read_bytes())
        # KiCad 10's Python runtime does not forward action args. Use a fixed
        # launcher, rather than depending on behavior of newer/development APIs.
        launcher = ('from kicad_bridge import main\n'
                    "raise SystemExit(main(['launch', '--sessions-root', "
                    + repr(str(sessions)) + ']))\n')
        if interpreter:
            # KiCad also rejects absolute action entrypoints even though its
            # JSON schema accepts them. Keep a relative, standard-library-only
            # bootstrap under KiCad's Python runtime, then invoke the fixed
            # preconfigured interpreter with inherited instance credentials.
            launcher = ('import subprocess\nfrom pathlib import Path\n'
                        'raise SystemExit(subprocess.call([' + repr(str(interpreter))
                        + ", str(Path(__file__).with_name('kicad_bridge.py')), "
                        + "'launch', '--sessions-root', " + repr(str(sessions))
                        + '], shell=False))\n')
        new_file(out / 'connect.py', launcher.encode('utf-8'))
        new_file(out / 'connect.png', plugin_icon())
        plugin = {'identifier': 'org.pcbskill.controlled-bridge', 'name': 'PCB Skill Connection',
                  'description': 'Bind a local read-only session; candidate edits need explicit requests.',
                  'runtime': {'type': 'python'}, 'actions': [{
                      'identifier': 'connect', 'name': 'Connect PCB Skill',
                      'description': 'Connect this PCB Editor to the local PCB Skill bridge.',
                      'show-button': True, 'scopes': ['pcb'], 'entrypoint': 'connect.py',
                      'icons-light': ['connect.png'], 'icons-dark': ['connect.png']}]}
        new_json(out / 'plugin.json', plugin)
        requirements = ('# Standard-library bootstrap; bridge interpreter is preconfigured.\n'
                        if interpreter else 'kicad-python==' + KIPY_VERSION + '\n')
        new_file(out / 'requirements.txt', requirements.encode('ascii'))
        new_json(out / 'package-hashes.json', {
            p.name: digest(p.read_bytes()) for p in out.iterdir() if p.is_file()})
        result['status'] = 'PLUGIN_FILES_CREATED_RESTART_AND_ENABLE_API_REQUIRED'
    return result


def cli_profile(cli):
    version = subprocess.run([str(cli), 'version'],capture_output=True,
                             timeout=15,encoding='utf-8',errors='replace')
    need(version.returncode == 0 and not version.stderr.strip(), 'cli_version_command_failed')
    if version.stdout.strip() == '10.0.8':
        return {'version':'10.0.8','source':'native_version_command'}
    if os.name == 'nt' and not version.stdout.strip():
        from npi_common import windows_cli_version_resource
        metadata = windows_cli_version_resource(cli)
        if metadata and metadata['product_version'] == '10.0.8':
            return {'version':'10.0.8','source':'successful_version_command_and_PE_resource',
                    'metadata':metadata}
    raise Refused('unaccepted_cli_profile')


def native_drc(board, manifest, cli, output_dir):
    """Read-only native reload/DRC. Does not bless or modify the candidate."""
    pcb = clean_path(board, True)
    contract = read_json(manifest)
    need(clean_path(contract['candidate_board'], True) == pcb
         and clean_path(contract['source_board'], True).parent != pcb.parent,
         'candidate_required')
    executable = clean_path(cli, True)
    need(executable.name.lower() in ('kicad-cli', 'kicad-cli.exe'), 'kicad_cli_required')
    out = clean_path(output_dir)
    need(not out.exists() and out.parent.is_dir() and not out.is_relative_to(pcb.parent),
         'new_external_report_required')
    before = digest(pcb.read_bytes())
    profile = cli_profile(executable)
    out.mkdir()
    run = subprocess.run([str(executable), 'pcb', 'drc', '--format', 'json',
                          '--output', str(out / 'drc.json'), str(pcb)],
                         capture_output=True, timeout=45, encoding='utf-8', errors='replace')
    need(digest(pcb.read_bytes()) == before, 'candidate_changed_during_native_review')
    need(run.returncode == 0 and (out / 'drc.json').is_file(), 'native_drc_execution_failed')
    report = read_json(out / 'drc.json')
    result = {'status': 'NATIVE_DRC_RECORDED_NOT_APPROVED', 'production_authorized': False,
              'candidate_sha256': before, 'cli_sha256': digest(executable.read_bytes()),
              'cli_profile':profile,
              'violations': len(report.get('violations', [])),
              'unconnected_items': len(report.get('unconnected_items', [])),
              'schematic_parity': 'separate existing workflow review required',
              'zones_refilled': False, 'engineering_review_required': True}
    new_json(out / 'native-review.json', result)
    return result


def open_editor(board, pcb_editor, runtime_dir, apply=False):
    """Launch an explicitly requested interactive editor with its own IPC temp root.

    KiCad 10 derives the IPC endpoint from the process temporary directory.
    Isolate each launch instead of clearing tokens or selecting another server.
    """
    need(os.name == 'nt','windows_isolated_launcher_only')
    pcb = clean_path(board, True)
    executable = clean_path(pcb_editor, True)
    area = clean_path(runtime_dir)
    need(pcb.suffix.lower() == '.kicad_pcb' and pcb.is_file(), 'existing_pcb_required')
    need(executable.name.lower() in ('pcbnew', 'pcbnew.exe'), 'pcb_editor_required')
    need(not area.exists() and area.parent.is_dir() and not area.is_relative_to(pcb.parent),
         'new_external_runtime_dir_required')
    need(len(str(area / 'tmp' / 'kicad' / 'api.sock')) < 110, 'shorter_runtime_dir_required')
    cli = executable.with_name('kicad-cli.exe' if os.name == 'nt' else 'kicad-cli')
    need(cli.is_file(), 'matching_cli_required')
    profile = cli_profile(cli)
    result = {'status':'EDITOR_LAUNCH_PREVIEW','version':VERSION,'board':str(pcb),
              'editor':str(executable),'editor_sha256':digest(executable.read_bytes()),
              'runtime_dir':str(area),'production_authorized':False,
              'cli_profile':profile,
              'scope':'interactive editor launch only; no connection/edit approval'}
    if apply:
        area.mkdir(mode=0o700)
        temporary = area / 'tmp'
        temporary.mkdir()
        env = {**os.environ, 'TEMP':str(temporary), 'TMP':str(temporary),
               'TMPDIR':str(temporary),'PCB_SKILL_RUNTIME_TEMP':str(temporary)}
        # A stale client session must never be inherited by a new GUI launch.
        env.pop('KICAD_API_SOCKET',None)
        env.pop('KICAD_API_TOKEN',None)
        process = subprocess.Popen([str(executable),str(pcb)],env=env,shell=False,
                                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        result.update(status='EDITOR_STARTED_CONNECT_ACTION_REQUIRED',pid=process.pid)
        new_json(area/'editor-launch.json',result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('plugin')
    a.add_argument('--destination', required=True)
    a.add_argument('--sessions-root', required=True)
    a.add_argument('--apply', action='store_true')
    a.add_argument('--python-executable', help='Optional preconfigured isolated Python with kicad-python 0.8.0')
    a = sub.add_parser('launch')
    a.add_argument('--sessions-root', required=True)
    a = sub.add_parser('serve')
    a.add_argument('--session-dir', required=True)
    a = sub.add_parser('request')
    a.add_argument('--session-dir', required=True)
    a.add_argument('--request', required=True)
    a.add_argument('--apply', action='store_true')
    a = sub.add_parser('open-editor')
    for field in ('board','pcb-editor','runtime-dir'):
        a.add_argument('--'+field,required=True)
    a.add_argument('--apply',action='store_true')
    a = sub.add_parser('drc')
    for field in ('board', 'candidate-manifest', 'kicad-cli', 'output-dir'):
        a.add_argument('--' + field, required=True)
    args = parser.parse_args(argv)
    # Migration policy: an installed legacy IPC bridge must never become a
    # second live writer, even if invoked directly outside workflow.py.
    if args.command != 'drc':
        print(encoded({'status':'BLOCKED','code':'LEGACY_IPC_WRITER_DISABLED',
                      'reason':'Konnect MCP is the only authorized live EDA writer; use Konnect capability discovery and fixture acceptance.',
                      'production_authorized':False}),end='')
        return 2
    try:
        if args.command == 'plugin':
            result = plugin_package(args.destination, args.sessions_root, args.apply, args.python_executable)
        elif args.command in ('serve', 'launch'):
            if args.command == 'launch':
                root = clean_path(args.sessions_root, True)
                serve(root / str(uuid.uuid4()))
            else:
                serve(args.session_dir)
            return 0
        elif args.command == 'request':
            result = send_request(args.session_dir, read_json(args.request), args.apply)
        elif args.command == 'open-editor':
            result = open_editor(args.board,args.pcb_editor,args.runtime_dir,args.apply)
        else:
            result = native_drc(args.board, args.candidate_manifest, args.kicad_cli, args.output_dir)
    except Refused as exc:
        result = {'status': 'BLOCKED', 'code': str(exc), 'production_authorized': False}
    except Exception as exc:
        result = {'status': 'BLOCKED', 'code': 'bridge_unavailable_or_invalid_input',
                  'production_authorized': False,
                  'exception_type': type(exc).__name__}
        frames = [f.name for f in traceback.extract_tb(exc.__traceback__)
                  if Path(f.filename).name in ('kicad_bridge.py', 'kicad_ipc_probe.py')]
        result['failure_stage'] = frames[-1] if frames else 'startup'
        if type(exc).__module__.startswith('kipy.'):
            # Local startup diagnostics only: replace connection secrets before
            # truncation/persistence and never dump the request or environment.
            result['native_error'] = _redact(str(exc), os.environ)[:240]
            code = getattr(exc, 'code', None)
            if type(code) is int and 0 <= code <= 100:
                result['api_status'] = code
    if args.command == 'launch':
        try:
            root = clean_path(args.sessions_root, True)
            new_json(root / ('startup-error-' + str(uuid.uuid4()) + '.json'), result)
        except Exception:
            pass
    print(encoded(_redact(result, os.environ)), end='')
    return 2 if result['status'] in ('BLOCKED', 'RESULT_UNCERTAIN_WRITES_DISABLED',
                                    'PENDING_DO_NOT_RESUBMIT') else 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')
    raise SystemExit(main())
