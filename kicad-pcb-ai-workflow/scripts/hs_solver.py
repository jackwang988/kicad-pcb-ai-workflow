#!/usr/bin/env python3
"""Optional ngspice adapter for a declared, lumped passive RLC PDN model.

This does not extract PCB parasitics or certify full-board PI/SI/EMC. No user
netlist, shell command, or project-provided executable is accepted. ``root``
defaults to the caller's working directory; all model sources stay under it.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess


SCOPE = 'lumped_rlc_pdn_only'
MAX_CAPACITORS = 256
MAX_SAMPLES = 20000
MAX_DATA_BYTES = 8 * 1024 * 1024
HASH = re.compile(r'^[0-9a-fA-F]{64}$')
IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_.:-]{0,63}$')
REQUEST_KEYS = {
    'schema_version', 'kind', 'board_sha256', 'rail', 'voltage_v',
    'ripple_percent', 'transient_current_a', 'frequency_start_hz',
    'frequency_stop_hz', 'points_per_decade', 'vrm', 'capacitors', 'model_source',
}
ASSUMPTIONS = [
    'One lumped rail node and ideal AC ground; a 1 A small-signal current is injected at that node.',
    'VRM is represented only by the declared series R/L; each capacitor by declared series R/L/C.',
    'C/ESR/ESL and VRM values are fixed over this sweep; bias, temperature and frequency dependence are not inferred.',
    'PCB plane, mounting, spreading, package and connector parasitics are not extracted; include effective values explicitly in the reviewed model.',
    'The target is the initial voltage-ripple/load-step budget, not a verified allocation of all rail tolerances.',
    'A finite AC sweep checks sampled points only; it does not establish continuous-band convergence, transient response, regulator stability or EMC compliance.',
]


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _positive(value, name, zero=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (value < 0 if zero else value <= 0)):
        raise ValueError(name + (' must be a finite nonnegative number' if zero else ' must be a finite positive number'))
    return float(value)


def _contained(root, name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Model source file is required')
    raw = Path(name)
    if '..' in raw.parts:
        raise ValueError('Parent traversal in model source refused')
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError('Model source must remain inside the selected project root')
    for ancestor in (candidate, *candidate.parents):
        if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Symlink or reparse-point model source refused')
        if ancestor == root:
            break
    if not resolved.is_file() or not resolved.stat().st_size:
        raise ValueError('Model source must be a nonempty file')
    return resolved


def _validated(request, root):
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
        raise ValueError('Solver request requires exactly the documented fields; arbitrary argv/netlists are unsupported')
    if isinstance(request['schema_version'], bool) or request['schema_version'] != 1 or request['kind'] != 'pdn_rlc_ac':
        raise ValueError('Unsupported solver request schema or analysis kind')
    if not isinstance(request['board_sha256'], str) or not HASH.fullmatch(request['board_sha256']):
        raise ValueError('board_sha256 must identify the reviewed board input')
    rail = request['rail']
    if not isinstance(rail, str) or not rail.strip() or len(rail) > 128 or any(ord(c) < 32 for c in rail):
        raise ValueError('rail must be a nonempty, single-line identity')
    v = _positive(request['voltage_v'], 'voltage_v')
    ripple = _positive(request['ripple_percent'], 'ripple_percent')
    if ripple > 100:
        raise ValueError('ripple_percent must be <= 100')
    current = _positive(request['transient_current_a'], 'transient_current_a')
    first = _positive(request['frequency_start_hz'], 'frequency_start_hz')
    last = _positive(request['frequency_stop_hz'], 'frequency_stop_hz')
    if first >= last:
        raise ValueError('Frequency stop must exceed start')
    ppd = request['points_per_decade']
    if isinstance(ppd, bool) or not isinstance(ppd, int) or not 1 <= ppd <= 1000:
        raise ValueError('points_per_decade must be an integer from 1 to 1000')
    span = math.log10(last) - math.log10(first)
    samples = math.ceil(span * ppd) + 3  # Independent two-point sweep covers exact endpoints.
    if not math.isfinite(span) or span > 20 or samples > MAX_SAMPLES:
        raise ValueError('Requested AC sweep exceeds the supported frequency/sample budget')
    vrm = request['vrm']
    if not isinstance(vrm, dict) or set(vrm) != {'r_ohm', 'l_h'}:
        raise ValueError('vrm requires only r_ohm and l_h')
    _positive(vrm['r_ohm'], 'vrm.r_ohm')
    _positive(vrm['l_h'], 'vrm.l_h', zero=True)
    caps = request['capacitors']
    if not isinstance(caps, list) or not 1 <= len(caps) <= MAX_CAPACITORS:
        raise ValueError('Provide 1 to 256 reviewed capacitor branches')
    refs = set()
    for cap in caps:
        if not isinstance(cap, dict) or set(cap) != {'ref', 'c_f', 'esr_ohm', 'esl_h'}:
            raise ValueError('Capacitor requires only ref/c_f/esr_ohm/esl_h')
        if not isinstance(cap['ref'], str) or not IDENTIFIER.fullmatch(cap['ref']) or cap['ref'] in refs:
            raise ValueError('Capacitor references must be unique single-line identifiers')
        refs.add(cap['ref'])
        _positive(cap['c_f'], 'capacitor.c_f')
        _positive(cap['esr_ohm'], 'capacitor.esr_ohm', zero=True)
        _positive(cap['esl_h'], 'capacitor.esl_h', zero=True)
    source = request['model_source']
    if not isinstance(source, dict) or set(source) != {'file', 'sha256', 'locator'}:
        raise ValueError('model_source requires file/sha256/locator')
    if not isinstance(source['locator'], str) or not source['locator'].strip():
        raise ValueError('model_source locator is required')
    if not isinstance(source['sha256'], str) or not HASH.fullmatch(source['sha256']):
        raise ValueError('model_source SHA-256 is required')
    path = _contained(root, source['file'])
    if _digest(path) != source['sha256'].lower():
        raise ValueError('Model source hash mismatch')
    z_target = v * (ripple / 100) / current
    if not math.isfinite(z_target) or z_target <= 0:
        raise ValueError('Initial target impedance is outside the supported numeric range')
    return path, z_target, samples


def _netlist(request):
    def n(value):
        return format(float(value), '.17g')
    # Names are generated locally. User rail/reference strings never enter SPICE syntax.
    lines = ['Reviewed lumped RLC PDN AC model', '* 1 A injection; V(rail) in V equals Z in ohms', 'Itest 0 rail AC 1']
    vrm = request['vrm']
    if vrm['l_h']:
        lines += ['Rvrm rail vrm_node ' + n(vrm['r_ohm']), 'Lvrm vrm_node 0 ' + n(vrm['l_h'])]
    else:
        lines += ['Rvrm rail 0 ' + n(vrm['r_ohm'])]
    for index, cap in enumerate(request['capacitors'], 1):
        previous = 'rail'
        if cap['esr_ohm']:
            node = 'r' + str(index)
            lines.append('Rcap%d %s %s %s' % (index, previous, node, n(cap['esr_ohm'])))
            previous = node
        if cap['esl_h']:
            node = 'l' + str(index)
            lines.append('Lcap%d %s %s %s' % (index, previous, node, n(cap['esl_h'])))
            previous = node
        lines.append('Ccap%d %s 0 %s' % (index, previous, n(cap['c_f'])))
    lines += ['.control', 'set noaskquit', 'set nomoremode', 'set wr_singlescale',
              'set wr_vecnames', 'set numdgt=17',
              'ac dec %d %s %s' % (request['points_per_decade'], n(request['frequency_start_hz']), n(request['frequency_stop_hz'])),
              'let zmag = mag(v(rail))', 'wrdata pdn-ac.txt zmag',
              # Request the two endpoints independently. ngspice-47 Windows
              # can return only the first row for a two-point linear sweep.
              'ac lin 1 %s %s' % (n(request['frequency_start_hz']), n(request['frequency_start_hz'])),
              'let zmag = mag(v(rail))', 'wrdata pdn-start.txt zmag',
              'ac lin 1 %s %s' % (n(request['frequency_stop_hz']), n(request['frequency_stop_hz'])),
              'let zmag = mag(v(rail))', 'wrdata pdn-stop.txt zmag', 'quit', '.endc', '.end']
    return '\n'.join(lines) + '\n'


def plan(request, root=None):
    """Validate model inputs and prepare a fixed recipe; run no external process."""
    try:
        project_root = Path(root if root is not None else Path.cwd()).resolve()
        source, target, samples = _validated(request, project_root)
        return {'status': 'SOLVER_PLAN_READY', 'scope': SCOPE, 'kind': 'pdn_rlc_ac',
                'external_solver_executed': False, 'production_authorized': False,
                'request_sha256': hashlib.sha256(_json(request)).hexdigest(),
                'board_sha256': request['board_sha256'].lower(),
                'board_binding': 'declared_input_hash; caller must verify against current board',
                'model_source': str(source), 'model_source_sha256': _digest(source),
                'target_impedance_ohm': target, 'maximum_expected_samples': samples,
                'requested_frequency_hz': [request['frequency_start_hz'], request['frequency_stop_hz']],
                'netlist': _netlist(request), 'assumptions': list(ASSUMPTIONS),
                'capabilities': {'geometry_extraction': False, 'full_board_pi': False,
                                 'si_eye': False, 'emc': False, 'lumped_passive_ac': True}}
    except (ValueError, OSError, TypeError, OverflowError) as exc:
        return {'status': 'BLOCKED_INPUT', 'scope': SCOPE, 'reason': str(exc),
                'external_solver_executed': False, 'production_authorized': False}


def parse_ac_data(path):
    """Read the fixed wr_singlescale/wr_vecnames frequency/zmag output."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_DATA_BYTES:
        raise ValueError('Expected bounded, nonempty AC output')
    rows = path.read_text(encoding='ascii').splitlines()
    rows = [row.strip() for row in rows if row.strip()]
    if not rows or rows[0].lower().split() != ['frequency', 'zmag']:
        raise ValueError('Expected frequency/zmag output header')
    if not 1 <= len(rows) - 1 <= MAX_SAMPLES + 2:
        raise ValueError('Unexpected number of AC data rows')
    values = []
    for row in rows[1:]:
        fields = row.split()
        if len(fields) != 2:
            raise ValueError('AC output must contain exactly two columns')
        frequency, magnitude = map(float, fields)
        _positive(frequency, 'output frequency')
        _positive(magnitude, 'output impedance', zero=True)
        if values and frequency <= values[-1][0]:
            raise ValueError('AC output frequency must be strictly increasing')
        values.append((frequency, magnitude))
    return values


def _evaluate(curve, endpoints, request, target, expected_samples):
    first, last = request['frequency_start_hz'], request['frequency_stop_hz']
    if len(curve) + len(endpoints) > expected_samples + 3:
        raise ValueError('Solver output exceeds the declared sample budget')
    if len(endpoints) != 2 or not math.isclose(endpoints[0][0], first, rel_tol=1e-8) or not math.isclose(endpoints[-1][0], last, rel_tol=1e-8):
        raise ValueError('Independent endpoint sweep does not match requested band')
    if not math.isclose(curve[0][0], first, rel_tol=1e-8) or curve[-1][0] > last * (1 + 1e-8):
        raise ValueError('AC sweep does not match requested band')
    # Reject a truncated or wrong-frequency sweep, not just an empty file.
    step = 10 ** (1 / request['points_per_decade'])
    for previous, current in zip(curve, curve[1:]):
        if not math.isclose(current[0] / previous[0], step, rel_tol=1e-6):
            raise ValueError('AC sweep has missing or unexpected frequency samples')
    if curve[-1][0] * step < last * (1 - 1e-7):
        raise ValueError('AC sweep was truncated before the requested stop frequency')
    points = sorted(curve + endpoints)
    worst = max(points, key=lambda point: point[1])
    within = worst[1] <= target
    return {'status': 'SAMPLED_MODEL_WITHIN_TARGET' if within else 'SAMPLED_MODEL_EXCEEDS_TARGET',
            'criterion': 'magnitude of declared lumped-model Z at sampled frequencies <= initial target',
            'sample_count': len(points), 'worst_frequency_hz': worst[0],
            'worst_impedance_ohm': worst[1], 'target_impedance_ohm': target,
            'sampled_only': True, 'continuous_band_convergence_verified': False,
            'result': 'WITHIN_TARGET_AT_SAMPLED_POINTS' if within else 'EXCEEDS_TARGET_AT_SAMPLED_POINTS'}


def reference_impedance(request, frequency):
    """Independent analytic magnitude of this exact lumped topology, in ohms."""
    omega = 2 * math.pi * frequency
    vrm = request['vrm']
    admittance = 1 / complex(vrm['r_ohm'], omega * vrm['l_h'])
    for cap in request['capacitors']:
        branch = complex(cap['esr_ohm'], omega * cap['esl_h'] - 1 / (omega * cap['c_f']))
        if branch == 0:
            return 0.0  # Exact ideal series resonance shorts the single rail node.
        admittance += 1 / branch
    value = abs(1 / admittance)
    _positive(value, 'analytic impedance', zero=True)
    return value


def run(request, executable, executable_sha256, output_dir, timeout_seconds=60, root=None):
    """Run only the generated recipe with an explicitly supplied, hash-bound ngspice."""
    prepared = plan(request, root=root)
    if prepared['status'] != 'SOLVER_PLAN_READY':
        return prepared
    result = {key: value for key, value in prepared.items() if key != 'netlist'}
    result['status'] = 'BLOCKED_CAPABILITY'
    out = None
    try:
        executable = Path(executable)
        if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
            result['reason'] = 'An explicitly selected external ngspice executable is unavailable; no solver was installed or run'
            return result
        if not isinstance(executable_sha256, str) or not HASH.fullmatch(executable_sha256) or _digest(executable) != executable_sha256.lower():
            result.update(status='BLOCKED_TOOL_IDENTITY', reason='Executable SHA-256 differs from the explicitly selected tool')
            return result
        timeout_seconds = _positive(timeout_seconds, 'timeout_seconds')
        if timeout_seconds > 60:
            raise ValueError('This adapter permits at most 60 seconds per process')
        destination = Path(output_dir)
        if not destination.is_absolute():
            raise ValueError('Explicit absolute new output directory required')
        for ancestor in (destination, *destination.parents):
            if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('Symlink or reparse-point output refused')
        if destination.exists():
            raise ValueError('Output directory already exists; no overwrite permitted')
        # No custom ngspice startup scripts: -n suppresses .spiceinit.
        version = subprocess.run([str(executable), '-n', '-v'], capture_output=True,
                                 text=True, encoding='utf-8', errors='replace',
                                 timeout=min(timeout_seconds, 10), shell=False,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        banner = (version.stdout + version.stderr).strip()
        match = re.search(r'(?i)ngspice[-\s]+([0-9][A-Za-z0-9.+_-]*)', banner)
        if version.returncode or not match:
            result.update(status='BLOCKED_TOOL_IDENTITY', reason='Selected executable did not identify as ngspice')
            return result
        result['tool'] = {'name': 'ngspice', 'version': match.group(1),
                          'executable': str(executable.resolve()), 'sha256': executable_sha256.lower()}
        candidate_output = destination.resolve()
        candidate_output.mkdir(parents=True, exist_ok=False)
        out = candidate_output
        (out / 'circuit.cir').write_text(prepared['netlist'], encoding='ascii')
        (out / 'request.json').write_bytes(_json(request))
        with (out / 'process.stdout').open('wb') as stdout, (out / 'process.stderr').open('wb') as stderr:
            process = subprocess.run([str(executable), '-n', '-b', '-o', 'ngspice.log', 'circuit.cir'],
                                     cwd=str(out), stdout=stdout, stderr=stderr,
                                     timeout=timeout_seconds, shell=False,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result['external_solver_executed'] = True
        if process.returncode:
            result.update(status='BLOCKED_SOLVER', reason='ngspice did not complete successfully', returncode=process.returncode)
        else:
            curve = parse_ac_data(out / 'pdn-ac.txt')
            first_point = parse_ac_data(out / 'pdn-start.txt')
            last_point = parse_ac_data(out / 'pdn-stop.txt')
            if len(first_point) != 1 or len(last_point) != 1:
                raise ValueError('Each independently requested endpoint must contain exactly one row')
            endpoints = first_point + last_point
            errors = []
            for frequency, magnitude in curve + endpoints:
                expected = reference_impedance(request, frequency)
                if not math.isclose(magnitude, expected, rel_tol=1e-4, abs_tol=1e-9):
                    raise ValueError('Solver output disagrees with the declared lumped-model analytic reference')
                errors.append(abs(magnitude - expected))
            result.update(_evaluate(curve, endpoints, request, prepared['target_impedance_ohm'], prepared['maximum_expected_samples']))
            result['analytic_reference_check'] = {'matched': True, 'maximum_absolute_error_ohm': max(errors),
                                                   'relative_tolerance': 1e-4, 'absolute_tolerance_ohm': 1e-9}
        if _digest(executable) != executable_sha256.lower() or _digest(prepared['model_source']) != prepared['model_source_sha256']:
            result.update(status='BLOCKED_INPUT_CHANGED', reason='Tool or model source changed during execution')
    except subprocess.TimeoutExpired:
        result.update(status='BLOCKED_TIMEOUT', reason='Solver process exceeded its time budget; no automatic retry', external_solver_executed=out is not None)
    except (ValueError, OSError, TypeError, ArithmeticError, UnicodeError) as exc:
        result.update(status='BLOCKED_RESULT' if out is not None else 'BLOCKED_INPUT', reason=str(exc))
    if out is not None:
        result['output_dir'] = str(out)
        try:
            result['artifacts_sha256'] = {p.name: _digest(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != 'result.json'}
            (out / 'result.json').write_bytes(_json(result))
        except OSError as exc:
            result.update(status='BLOCKED_REPORT', reason='Could not persist complete solver evidence: ' + str(exc))
    return result
