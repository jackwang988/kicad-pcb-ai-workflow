#!/usr/bin/env python3
"""Read-only utilities for the additive KiCad 10.0.7 NPI workflow."""
from __future__ import annotations
import hashlib
import json
import math
import re
import shutil
import subprocess
import os
from pathlib import Path

TARGET_VERSION = '10.0.7'  # Recommended and previously validated baseline, not a universal hard lock.
def kicad10_patch_version(value):
    """Recognize stable 10.0.x build identity; this is eligibility, NOT native approval."""
    if value is None:
        return None
    raw = str(value).strip()
    m = re.search(r'(?<![0-9.])(10\.0\.\d+)(?![0-9.])', raw)
    if not m or re.search(r'(?:^|[-_+ ])(?:rc|dev|nightly|alpha|beta|testing)(?:\b|\d)', raw[m.end():], re.I):
        return None
    return m.group(1)

def stable_kicad_version(value):
    """Return stable KiCad version identity >=10 for CLI capability probing.
    A newer major is a *candidate*, never proof of pcbnew/IPC compatibility.
    """
    if value is None:
        return None
    raw = str(value).strip()
    match = re.search(r'(?<![0-9.])(\d+)\.(\d+)\.(\d+)(?![0-9.])', raw)
    if not match or int(match.group(1)) < 10:
        return None
    # Development and pre-release binaries require explicit engineering evaluation.
    if re.search(r'(?:rc\d*|alpha\d*|beta\d*|dev|nightly|testing|snapshot|dirty)', raw, re.I):
        return None
    return match.group(0)

def cli_major_version(env):
    version = stable_kicad_version(env.get('cli_version'))
    return int(version.split('.')[0]) if version else None

def cli_native_ready(env, cli=None):
    """Future major releases need a current CLI-only smoke record before signed-off native review."""
    if not cli_compatible(env):
        return False
    major = cli_major_version(env)
    if major is None or major == 10:
        return True  # Old software test fixtures + v10; native reports still validated on each operation.
    state = os.getenv('KICAD_CLI_STARTUP_STATE')
    if not state:
        return False
    try:
        from environment_start import check
        return check(state, cli=cli or env.get('kicad_cli'))['status'] == 'ENVIRONMENT_CLI_READY'
    except (ValueError, OSError, KeyError, TypeError):
        return False

def cli_compatible(env):
    # Fallback permits existing test fixtures to exercise the historical baseline contract.
    return bool(env['cli_compatible']) if 'cli_compatible' in env else bool(env.get('cli_exact_target'))

def pcbnew_compatible(env):
    return bool(env['pcbnew_compatible']) if 'pcbnew_compatible' in env else bool(env.get('pcbnew_exact_target'))

def pair_compatible(env):
    if 'version_pair_compatible' in env:
        return bool(env['version_pair_compatible'])
    return cli_compatible(env) and pcbnew_compatible(env)

LEVELS = ['阻断级', '高风险', '中风险', '优化建议']

# Release contract: removing a required checker from a manifest cannot disable
# its inventory gate. Historical project scripts are not runtime dependencies.
RUNTIME_TOOLS = frozenset('''assembly_guard build_manifest doctor engineering_gate
freeze_candidate link_audit mass_production_review native_report netlist_guard
npi_common npi_geometry npi_release pad_audit production_contract spice_precheck
validate_frozen_candidate design_intent design_intent_audit static_review
static_review_gate device_knowledge environment_start reserve_review placement_review
schematic_io schematic_style schematic_candidate project_flow manufacturing_export
system_integration workflow freerouting_adapter'''.split())

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def runtime_inventory(root):
    """Validate the complete standalone core, without requiring any archive."""
    root = Path(root).resolve()
    manifest = root/'references/tool-manifest.json'
    if manifest.is_symlink() or manifest.parent.is_symlink() or (root/'scripts').is_symlink():
        raise ValueError('Symlinked runtime inventory refused')
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if data.get('schema_version') != 1 or data.get('package_kind') != 'universal_runtime':
        raise ValueError('Unsupported runtime package contract')
    rows = data.get('active')
    if not isinstance(rows, list):
        raise ValueError('Missing active tool inventory')
    expected = {'scripts/'+name+'.py' for name in RUNTIME_TOOLS}
    names = [row.get('file') for row in rows if isinstance(row, dict)]
    if len(names) != len(rows) or len(names) != len(set(names)) or set(names) != expected:
        raise ValueError('Required runtime tool set missing, duplicated or changed')
    actual = {'scripts/'+p.relative_to(root/'scripts').as_posix() for p in (root/'scripts').rglob('*.py')}
    if actual != expected:
        raise ValueError('Unexpected/missing runtime script; project scripts belong outside the Skill')
    result = {}
    for row in rows:
        p = root/row['file']
        if p.is_symlink() or not p.is_file() or not re.fullmatch('[0-9a-f]{64}', str(row.get('sha256', ''))) or sha256(p) != row['sha256']:
            raise ValueError('Missing/changed active tool: '+row['file'])
        if not all(row.get(k) for k in ('version','command','input','output','exit_codes')):
            raise ValueError('Incomplete active tool contract: '+row['file'])
        result[p.stem] = p
    return result

def run(command, timeout=120):
    try:
        p = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=timeout)
        return {'command': list(map(str, command)), 'returncode': p.returncode,
                'stdout': p.stdout, 'stderr': p.stderr}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'command': list(map(str, command)), 'returncode': -1, 'error': str(e)}

def windows_cli_version_resource(executable):
    """Read real PE metadata when this Windows build loses piped version text.

    This does not manufacture CLI output or infer its version from pcbnew.
    The caller must also require a successful, error-free CLI version command.
    """
    if os.name != 'nt':return None
    import ctypes
    from ctypes import wintypes
    path=Path(shutil.which(str(executable)) or executable).resolve()
    if not path.is_file() or path.suffix.lower()!='.exe':return None
    api=ctypes.WinDLL('version',use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype=wintypes.DWORD
    api.GetFileVersionInfoW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]
    api.GetFileVersionInfoW.restype=wintypes.BOOL
    api.VerQueryValueW.argtypes=[wintypes.LPCVOID,wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.UINT)]
    api.VerQueryValueW.restype=wintypes.BOOL
    handle=wintypes.DWORD();size=api.GetFileVersionInfoSizeW(str(path),ctypes.byref(handle))
    if not size:return None
    blob=ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path),0,size,blob):return None
    pointer=ctypes.c_void_p();length=wintypes.UINT()
    if not api.VerQueryValueW(blob,'\\VarFileInfo\\Translation',ctypes.byref(pointer),ctypes.byref(length)) or length.value<4:return None
    translations=ctypes.cast(pointer,ctypes.POINTER(wintypes.WORD))
    for i in range(length.value//4):
        prefix=f'\\StringFileInfo\\{translations[2*i]:04x}{translations[2*i+1]:04x}\\'
        values={}
        for field in ('ProductVersion','FileVersion'):
            if api.VerQueryValueW(blob,prefix+field,ctypes.byref(pointer),ctypes.byref(length)) and length.value:
                values[field]=ctypes.wstring_at(pointer.value,length.value).rstrip('\x00').strip()
        if re.fullmatch(r'\d+\.\d+\.\d+',values.get('ProductVersion','')):
            return {'product_version':values['ProductVersion'],'file_version':values.get('FileVersion'),
                    'executable':str(path),'executable_sha256':sha256(path)}
    return None

def environment(cli=None):
    executable = cli or shutil.which('kicad-cli')
    result = {'target': TARGET_VERSION, 'kicad_cli': executable, 'cli_version': None,
              'pcbnew': False, 'pcbnew_version': None, 'ngspice': shutil.which('ngspice')}
    if executable:
        probe = run([str(executable), 'version'])
        result['cli_probe'] = probe
        m = re.search(r'\b(\d+\.\d+\.\d+)\b', probe.get('stdout', ''))
        result['cli_version'] = m.group(1) if m else None
        result['cli_exact_target'] = probe.get('returncode')==0 and probe.get('stdout','').strip()==TARGET_VERSION
        result['cli_version_source']='stdout' if m else None
        if (os.name=='nt' and probe.get('returncode')==0 and not probe.get('error')
                and not probe.get('stdout','').strip() and not probe.get('stderr','').strip()):
            try:
                resource=windows_cli_version_resource(executable)
                if resource:
                    result['cli_version_resource']=resource
                    result['cli_version']=resource['product_version']
                    result['cli_version_source']='windows_executable_version_resource'
                    result['cli_exact_target']=resource['product_version']==TARGET_VERSION
            except (OSError,ValueError,AttributeError) as e:
                result['cli_version_resource_error']=str(e)
    try:
        import pcbnew
        result['pcbnew'] = True
        result['pcbnew_version'] = str(pcbnew.GetBuildVersion())
        result['pcbnew_exact_target'] = bool(re.search(r'(?<![\d.])'+re.escape(TARGET_VERSION)+r'(?![\w.\-])',result['pcbnew_version']))
    except (ImportError, AttributeError, RuntimeError) as e:
        result['pcbnew_error'] = str(e)
    normalized = stable_kicad_version(result.get('pcbnew_version'))
    result['pcbnew_normalized_version'] = normalized
    # A patch version is only a candidate. Every native operation and production
    # gate still performs its actual checks and fails closed on unsupported behavior.
    cli_observed = (result.get('cli_version_source') == 'stdout' and
                    result.get('cli_probe', {}).get('returncode') == 0 and
                    result.get('cli_probe', {}).get('stdout', '').strip() == result.get('cli_version'))
    resource_observed = (result.get('cli_version_source') == 'windows_executable_version_resource'
                         and result.get('cli_probe', {}).get('returncode') == 0
                         and not result.get('cli_probe', {}).get('stderr', '').strip()
                         and result.get('cli_version_resource', {}).get('product_version') == result.get('cli_version'))
    result['cli_compatible'] = bool(stable_kicad_version(result.get('cli_version')) and
                                    (cli_observed or resource_observed))
    result['pcbnew_compatible'] = bool(normalized and int(normalized.split('.')[0]) == 10)
    result['version_pair_compatible'] = (result['cli_compatible'] and result['pcbnew_compatible']
                                         and result['cli_version'] == normalized)
    result['compatibility_tier'] = ('RECOMMENDED_BASELINE' if result['version_pair_compatible'] and
                                    result['cli_version'] == TARGET_VERSION else
                                    'PATCH_CANDIDATE_NATIVE_SMOKE_REQUIRED' if result['version_pair_compatible'] else
                                    'FUTURE_CLI_CANDIDATE_SMOKE_REQUIRED' if result['cli_compatible'] and
                                    int(result['cli_version'].split('.')[0]) >= 11 else
                                    'OFFLINE_ONLY_OR_UNVERIFIED')
    result['kicad9_native_status'] = 'UNVERIFIED_NOT_ENABLED'
    # These states express feature eligibility, not a completed engineering review.
    result['capabilities'] = {
        'offline_requirements_and_document_review': 'AVAILABLE_WITH_REQUIRED_INPUTS',
        'offline_static_preview': 'AVAILABLE_WITH_REQUIRED_INPUTS_NOT_NATIVE_EVIDENCE',
        'schematic_cli': ('CLI_ONLY_SMOKE_REQUIRED' if result['cli_compatible'] and
                          int(result['cli_version'].split('.')[0]) >= 11 else
                          'NATIVE_SMOKE_REQUIRED' if result['cli_compatible'] else 'UNVERIFIED_OR_UNAVAILABLE'),
        'pcb_native': 'NATIVE_SMOKE_REQUIRED' if result['version_pair_compatible'] else
                     'IPC_ADAPTER_REQUIRED' if result['cli_compatible'] and int(result['cli_version'].split('.')[0]) >= 11 else
                     'UNVERIFIED_OR_UNAVAILABLE',
        'manufacturing': 'FULL_PROJECT_GATES_REQUIRED' if result['version_pair_compatible'] else 'BLOCKED',
    }
    return result

def patch_native_ready(env, cli=None):
    """Non-baseline KiCad patches require a CURRENT, genuine setup --apply record.
    This is an additional environment gate, never a production authorization.
    """
    if not pair_compatible(env):
        return False
    if env.get('cli_version', TARGET_VERSION) == TARGET_VERSION:
        return True  # Preserve established baseline workflow; project gates still run.
    state = os.getenv('KICAD_PATCH_STARTUP_STATE')
    if not state:
        return False
    try:
        from environment_start import check
        return check(state, cli=cli or env.get('kicad_cli'))['status'] == 'ENVIRONMENT_READY'
    except (ValueError, OSError, KeyError, TypeError):
        return False

def parse_sexpr(text):
    """Parse lists and quoted strings; do not evaluate code or change any bytes."""
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text)
    root, stack = [], []
    current = root
    for t in tokens:
        if t == '(':
            child = []; current.append(child); stack.append(current); current = child
        elif t == ')':
            if not stack: raise ValueError('Unbalanced S-expression')
            current = stack.pop()
        elif t.startswith('"'):
            current.append(t[1:-1].replace('\\"', '"').replace('\\\\', '\\'))
        else:
            current.append(t)
    if stack or len(root) != 1 or not isinstance(root[0], list):
        raise ValueError('Invalid S-expression root')
    return root[0]

def children(node, tag):
    return [x for x in node if isinstance(x, list) and x and x[0] == tag]

def child(node, tag, default=None):
    return next(iter(children(node, tag)), default)

def value(node, tag, default=''):
    x = child(node, tag)
    return x[1] if x and len(x) > 1 else default

def number(node, tag, default=0.0):
    return float(value(node, tag, default))

def xy(node, tag='at'):
    p = child(node, tag, [tag, 0, 0])
    return (float(p[1]), float(p[2]))

def transform(p, origin, angle):
    a = math.radians(angle)
    return (origin[0] + p[0]*math.cos(a) - p[1]*math.sin(a),
            origin[1] + p[0]*math.sin(a) + p[1]*math.cos(a))

def distance(a, b): return math.hypot(a[0]-b[0], a[1]-b[1])

def segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return distance(p, (a[0]+t*dx, a[1]+t*dy))

def polygon_area(points):
    if len(points) < 3: return 0
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points, points[1:]+points[:1])))/2

def load_board(path, require_native=True):
    """Use pcbnew.LoadBoard, retaining a read-only text view for stackup/custom fields.

    No SaveBoard/Save method is called. Static fallback is for preview/testing only.
    """
    tree = parse_sexpr(Path(path).read_text(encoding='utf-8-sig'))
    if tree[0] != 'kicad_pcb': raise ValueError('Not a KiCad PCB')
    board = {'engine': 'static_preview', 'footprints': [], 'tracks': [], 'vias': [],
             'edges': [], 'zones': [], 'netclasses': [], 'thickness': number(child(tree,'general',[]),'thickness',1.6)}
    nets = {int(x[1]):x[2] for x in children(tree,'net') if len(x)>2}
    board['copper_layers']=[x[1] for x in child(tree,'layers',[])[1:] if isinstance(x,list) and len(x)>1 and x[1].endswith('.Cu')]
    for fp in children(tree, 'footprint'):
        props = {x[1]: x[2] for x in children(fp, 'property') if len(x)>2}
        for text in children(fp,'fp_text'):
            if text[1] == 'reference': props.setdefault('Reference',text[2])
            if text[1] == 'value': props.setdefault('Value',text[2])
        origin = xy(fp); at = child(fp,'at',[]); angle=float(at[3]) if len(at)>3 else 0
        pads=[]
        for p in children(fp,'pad'):
            size=xy(p,'size'); n=child(p,'net',[])
            pads.append({'number':str(p[1]), 'pos':transform(xy(p),origin,angle), 'size':size,
                         'net':n[2] if len(n)>2 else nets.get(int(n[1]),'') if len(n)>1 else '',
                         'drill':number(p,'drill',0), 'type':p[2]})
        board['footprints'].append({'ref':props.get('Reference','?'), 'value':props.get('Value',''),
            'footprint':fp[1], 'pos':origin, 'layer':value(fp,'layer','F.Cu'), 'pads':pads, 'properties':props})
    for t in children(tree,'segment'):
        board['tracks'].append({'start':xy(t,'start'),'end':xy(t,'end'),'width':number(t,'width'),
                                'layer':value(t,'layer'), 'net':nets.get(int(value(t,'net',0)),'')})
    for v in children(tree,'via'):
        board['vias'].append({'pos':xy(v), 'diameter':number(v,'size'), 'drill':number(v,'drill'),
                             'net':nets.get(int(value(v,'net',0)),''), 'layers':child(v,'layers',[])[1:]})
    for e in children(tree,'gr_line'):
        if value(e,'layer') == 'Edge.Cuts': board['edges'].append((xy(e,'start'),xy(e,'end')))
    for e in children(tree,'gr_rect'):
        if value(e,'layer') == 'Edge.Cuts':
            a,b=xy(e,'start'),xy(e,'end'); pts=[a,(b[0],a[1]),b,(a[0],b[1])]
            board['edges'].extend(zip(pts,pts[1:]+pts[:1]))
    board['curved_outline'] = any(value(e,'layer')=='Edge.Cuts' for tag in ('gr_arc','gr_circle','gr_poly') for e in children(tree,tag))
    for z in children(tree,'zone'):
        polygons=[]
        for p in children(z,'filled_polygon'):
            pts=child(p,'pts',[])
            polygons.append([xy(q,'xy') if False else (float(q[1]),float(q[2])) for q in children(pts,'xy')])
        board['zones'].append({'net':value(z,'net_name'), 'layer':value(z,'layer'), 'filled_polygons':polygons})
    board['stackup'] = child(child(tree,'setup',[]),'stackup',[])
    if require_native:
        import pcbnew
        native = pcbnew.LoadBoard(str(Path(path).resolve()))
        if native is None: raise RuntimeError('pcbnew.LoadBoard returned None')
        mm = lambda n: float(pcbnew.ToMM(n))
        parsed={f['ref']:f for f in board['footprints']}
        # Public documented methods; no invented netclass filtering API.
        for fp in native.GetFootprints():
            ref=fp.GetReference()
            if ref not in parsed: continue
            f=parsed[ref]; f['pos']=(mm(fp.GetPosition().x),mm(fp.GetPosition().y))
            f['pads']=[{'number':p.GetNumber(), 'pos':(mm(p.GetPosition().x),mm(p.GetPosition().y)),
                       'size':(mm(p.GetSize().x),mm(p.GetSize().y)), 'net':p.GetNetname(),
                       'drill':mm(p.GetDrillSize().x), 'type':str(p.GetAttribute())} for p in fp.Pads()]
        try: board['netclasses']=[str(k) for k in native.GetNetClasses().keys()]
        except (AttributeError, TypeError): board['netclass_api_unavailable']=True
        board['engine']='pcbnew.LoadBoard'
    return board

def write_json(path, data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def finite_tree(data):
    """Reject nonstandard NaN/Infinity inputs instead of letting comparisons pass."""
    if isinstance(data,float) and not math.isfinite(data):raise ValueError('Nonfinite numeric configuration')
    if isinstance(data,dict):
        for value_ in data.values():finite_tree(value_)
    if isinstance(data,list):
        for value_ in data:finite_tree(value_)
    return data
