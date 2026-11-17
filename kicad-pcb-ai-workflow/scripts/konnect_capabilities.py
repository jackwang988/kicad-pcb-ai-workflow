#!/usr/bin/env python3
"""Konnect MCP capability discovery, risk gates and isolated fixture acceptance.

No published tool count or predefined functional allowlist is assumed.  Only
Konnect may write a live board; this module never edits a KiCad file itself.
A tool being discoverable does NOT grant write permission or project approval.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from konnect_backend import McpSession, McpError, body, backend_profile, require_live_board

READ_HINTS = ('get_', 'list_', 'inspect_', 'read_', 'query_', 'find_', 'search_', 'check_', 'validate_', 'analyze_')
EDIT_HINTS = re.compile(r'(move|rotat|place|edit|update|set_|rename|change|modify|assign|text|silk)', re.I)
DESIGN_HINTS = re.compile(r'(route|track|via|zone|fill|net|connect|wire|pin|schematic|symbol|footprint|pad|import|export|save|reload|open_project)', re.I)
DESTRUCTIVE_HINTS = re.compile(r'(delete|remove|erase|clear|reset|replace|bulk|batch|autorout|optimiz|run_script|execute|shell)', re.I)
DANGEROUS = re.compile(r'(delete|remove|erase|clear|reset|replace|bulk|batch|autorout|optimiz|run_script|execute|shell)', re.I)
LEVELS = ('L0','L1','L2','L3')
SCHEMA = 1


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',', ':'),allow_nan=False)


def sha(path):
    return digest_bytes(Path(path).read_bytes())


def risk(tool):
    """Conservative name-only floor; unknown capabilities are high risk."""
    name = tool['name']
    if DANGEROUS.search(name):return 'L3'
    if DESIGN_HINTS.search(name):return 'L2'
    if name.startswith(READ_HINTS):return 'L0'
    if EDIT_HINTS.search(name):return 'L1'
    return 'L3'


def tool_schema_hash(tool):
    return digest_bytes(canonical({'name':tool['name'],'inputSchema':tool.get('inputSchema',{})}).encode())


def _toolboxes(raw):
    if isinstance(raw,list): rows=raw
    elif isinstance(raw,dict):
        rows=next((raw[k] for k in ('toolboxes','toolsets','items') if isinstance(raw.get(k),list)), [])
    else: rows=[]
    out=[]
    for row in rows:
        if isinstance(row,str): name=row
        elif isinstance(row,dict): name=next((row[k] for k in ('name','id','toolbox') if isinstance(row.get(k),str)),None)
        else:name=None
        if name and name not in out:out.append(name)
    return out


def discover(session, toolsets=(), all_toolsets=False):
    """Read only. Load advertised tool sets to discover tools; never call edit tools."""
    toolboxes=body(session.call('list_toolboxes'))
    available=_toolboxes(toolboxes)
    if all_toolsets and not available:
        raise ValueError('Cannot enumerate advertised toolboxes; do not claim full discovery')
    selected=available if all_toolsets else list(toolsets)
    if any(not isinstance(n,str) or n not in available for n in selected):
        raise ValueError('Requested toolset is not advertised by current Konnect server')
    load_results=[]
    for name in selected:
        load_results.append({'name':name,'result':body(session.call('load_toolset',{'name':[name]}))})
    tools=session.tools()
    names=[t.get('name') for t in tools]
    if not all(isinstance(n,str) and n for n in names) or len(names)!=len(set(names)):
        raise ValueError('Duplicate or unnamed discovered tools')
    rows=[{'name':t['name'],'input_schema_sha256':tool_schema_hash(t),'risk_floor':risk(t),
           'description':str(t.get('description',''))[:600], 'inputSchema':t.get('inputSchema',{})}
          for t in tools]
    return {'schema_version':SCHEMA,'status':'DISCOVERED_NOT_ACCEPTED','toolboxes_advertised':available,
            'toolsets_loaded':selected,'tools_count':len(rows),'tools':rows,
            'complete_discovery_claim':bool(all_toolsets),'production_authorized':False}


def pin_binary_before_launch(executable, local_enrollment=None):
    """Block unpinned binaries before subprocess startup, not after MCP handshake."""
    binary_sha=sha(executable)
    try:
        profile=backend_profile(binary_sha)
    except ValueError:
        if local_enrollment is None:raise ValueError('Unknown Konnect binary; explicit local enrollment required (never auto-trust an update)')
        cfg=json.loads(Path(local_enrollment).read_text(encoding='utf-8'))
        if cfg.get('schema_version')!=1 or cfg.get('approved_for_local_use') is not True or cfg.get('executable_sha256')!=binary_sha:
            raise ValueError('Invalid or mismatching local enrollment')
        profile={'server_name':'konnect','version':cfg['version'],'build_commit':cfg['build_commit'],
                 'id':cfg.get('id','local-explicit-pin'),'license':'operator verified independently',
                 'eligible_kicad_versions':cfg.get('eligible_kicad_versions',[])}
    return binary_sha,profile


def check_identity(session, executable, local_enrollment=None):
    binary_sha,profile=pin_binary_before_launch(executable,local_enrollment)
    info=body(session.call('get_installation_info'))
    server=session.server.get('serverInfo',{})
    if server.get('name')!=profile['server_name'] or server.get('version')!=profile['version']:
        raise ValueError('Serving MCP identity differs from pinned executable identity')
    build=info.get('build',{})
    if build.get('version')!=profile['version'] or build.get('commit')!=profile['build_commit']:
        raise ValueError('Konnect executable build and returned server build do not match')
    return {'server_name':server['name'],'version':profile['version'],'build_commit':profile['build_commit'],
            'executable_sha256':binary_sha,'profile':profile['id'],'eligible_kicad_versions':profile.get('eligible_kicad_versions',[]), 'toolchain_verified':True}


def empty_registry():
    return {'schema_version':1,'kind':'konnect_capability_acceptance','records':[]}


def load_registry(path):
    if path is None:return empty_registry()
    path=Path(path)
    if not path.is_file():return empty_registry()
    o=json.loads(path.read_text(encoding='utf-8'))
    if o.get('schema_version')!=1 or o.get('kind')!='konnect_capability_acceptance' or not isinstance(o.get('records'),list):
        raise ValueError('Invalid capability registry')
    return o


def assessment(registry, identity, tool, kicad_version, scope):
    """Exact binary+schema+KiCad+scope binding. No wildcard generalizations."""
    floor=risk(tool)
    toolhash=tool_schema_hash(tool)
    matched=[]
    for rec in registry['records']:
        if (rec.get('status')=='FIXTURE_PASSED_ACCEPTANCE_RECORDED' and rec.get('backend')==identity
            and rec.get('tool')==tool['name'] and rec.get('tool_schema_sha256')==toolhash
            and rec.get('kicad_version')==kicad_version and rec.get('scope')==scope
            and rec.get('risk')==floor and rec.get('production_authorized') is False):
            native=rec.get('native_drc')
            if (not isinstance(native,dict) or native.get('returncode')!=0
                    or not re.fullmatch(r'[a-f0-9]{64}',str(native.get('report_sha256','')))):
                continue
            evidence_path=Path(str(native.get('report_path','')))
            if not evidence_path.is_file() or sha(evidence_path)!=native['report_sha256']:
                continue
            if not (re.fullmatch(r'[a-f0-9]{64}',str(rec.get('source_sha256','')))
                    and re.fullmatch(r'[a-f0-9]{64}',str(rec.get('fixture_before_sha256','')))
                    and re.fullmatch(r'[a-f0-9]{64}',str(rec.get('fixture_after_sha256','')))
                    and rec.get('fixture') and rec.get('fixture_before_sha256')!=rec.get('fixture_after_sha256')):
                continue
            matched.append(rec)
    return {'tool':tool['name'],'risk':floor,'scope':scope,'tool_schema_sha256':toolhash,
            'status':'ACCEPTED_WITHIN_RECORDED_SCOPE' if matched else ('DISCOVERED_READ_ONLY' if floor=='L0' else 'FIXTURE_REQUIRED'),
            'matching_acceptance_count':len(matched),'production_authorized':False}


def inspect_saved_board(path):
    """Parse saved footprint positions/lock flags without pcbnew (read-only)."""
    from npi_common import parse_sexpr, children, child, value
    root=parse_sexpr(Path(path).read_text(encoding='utf-8-sig'))
    if not root or root[0]!='kicad_pcb':raise ValueError('Not a KiCad board')
    out={}
    for fp in children(root,'footprint'):
        refs=[p[2] for p in children(fp,'property') if len(p)>2 and p[1]=='Reference']
        if not refs:
            refs=[p[2] for p in children(fp,'fp_text') if len(p)>2 and p[1]=='reference']
        if len(refs)!=1 or refs[0] in out:raise ValueError('Missing/duplicate saved footprint reference')
        ref=refs[0]
        at=child(fp,'at',[])
        if len(at)<3:raise ValueError('Footprint has no saved position')
        # KiCad forms include standalone `locked`, or `(locked yes)` in some revisions.
        lock=any(v=='locked' or (isinstance(v,list) and v and v[0]=='locked' and len(v)>1 and v[1] not in ('no','false')) for v in fp[2:])
        out[ref]={'x':float(at[1]),'y':float(at[2]),'rotation':float(at[3]) if len(at)>3 else 0.,
                  'layer':value(fp,'layer'), 'locked':lock}
    return out


def validate_board_argument_paths(arguments, board, original_board):
    """Reject source-project paths in mutation arguments, including nested data."""
    board=Path(board).resolve();original_board=Path(original_board).resolve()
    original_root=original_board.parent
    def scan(node):
        if isinstance(node,dict):
            for key,value in node.items():
                if isinstance(value,str) and (value.lower().endswith(('.kicad_pcb','.kicad_sch','.kicad_pro','.kicad_dru'))
                                                or key.lower() in ('board','board_file','board_path','pcb_file')):
                    p=Path(value)
                    if p.is_absolute():
                        actual=p.resolve()
                        if actual.is_relative_to(original_root):raise ValueError('MCP arguments reference protected source project')
                        if actual.suffix.lower()=='.kicad_pcb' and actual!=board:
                            raise ValueError('MCP PCB argument points to a different candidate')
                scan(value)
        elif isinstance(node,list):
            for child in node:scan(child)
    scan(arguments)


def verify_fixture_change(before, after, expected):
    """Require explicit expected placement changes and protect all other refs.

    Other classes of modification need dedicated native parity validators and
    cannot earn automated acceptance from this minimal footprint verifier.
    """
    if set(before)!=set(after):raise ValueError('Fixture footprints were added or removed unexpectedly')
    if expected.get('kind')!='placement' or not isinstance(expected.get('placements'),dict) or not expected['placements']:
        raise ValueError('Only placement fixture is currently auto-verifiable; other tool families need a dedicated validator')
    target=expected['placements']
    if not set(target).issubset(before):raise ValueError('Expected footprint absent')
    for ref in before:
        b,a=before[ref],after[ref]
        if b['locked']!=a['locked'] or b['layer']!=a['layer']:
            raise ValueError('Fixture lock/layer changed unexpectedly: '+ref)
        if ref not in target:
            if any(abs(a[k]-b[k])>1e-5 for k in ('x','y','rotation')):
                raise ValueError('Unlisted fixture footprint moved: '+ref)
        else:
            for k in ('x','y','rotation'):
                if k not in target[ref] or abs(a[k]-float(target[ref][k]))>1e-4:
                    raise ValueError('Expected fixture placement not reached: '+ref+'.'+k)
    return {'checked_references':len(before),'expected_moved':sorted(target),
            'scope':'placement_positions_lock_and_layer_only; not all geometries or electrical proof'}


def verify_zone_fill_change(before_board_text, after_path, expected):
    from npi_common import parse_sexpr, children
    a=parse_sexpr(before_board_text);b=parse_sexpr(Path(after_path).read_text(encoding='utf-8-sig'))
    if a[0]!='kicad_pcb' or b[0]!='kicad_pcb':raise ValueError('Invalid fixture board')
    def remove_fills(obj):
        if not isinstance(obj,list):return obj
        return [remove_fills(x) for x in obj if not (isinstance(x,list) and x and x[0] in ('filled_polygon','fill_segments'))]
    if remove_fills(a)!=remove_fills(b):
        raise ValueError('Non-fill board structure changed; zone-fill test failed')
    def counts(root):
        return sum(len(children(z,'filled_polygon')) for z in children(root,'zone'))
    before_count,after_count=counts(a),counts(b)
    minimum=expected.get('min_filled_polygons',1)
    if not isinstance(minimum,int) or minimum<=0 or after_count<minimum or after_count<=before_count:
        raise ValueError('No verified filled-zone polygon growth')
    return {'kind':'zone_fill','polygons_before':before_count,'polygons_after':after_count,
            'unfilled_board_tree_unchanged':True,
            'limitations':'KiCad DRC and specific return-path assessment remain required'}


def _native_drc(executable, board, report):
    cmd=[str(executable),'pcb','drc','--output',str(report),str(board)]
    completed=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
    # Zero = no violations; unknown codes and violations cannot grant acceptance.
    if completed.returncode!=0 or not report.is_file():
        raise ValueError('Native KiCad DRC not clean; output='+completed.stderr[-500:])
    return {'command':cmd,'returncode':completed.returncode,'report_sha256':sha(report),'report_path':str(report.resolve())}


def record_fixture(registry_path, registry, record):
    if registry_path is None:raise ValueError('Explicit external --registry is required to save acceptance')
    p=Path(registry_path).resolve()
    if p.exists():
        old=load_registry(p)
        if old!=registry:raise ValueError('Registry changed during testing; do not overwrite')
    else:
        p.parent.mkdir(parents=True,exist_ok=True)
    registry['records'].append(record)
    tmp=p.with_name(p.name+'.new')
    if tmp.exists():raise ValueError('Concurrent registry write in progress')
    tmp.write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(p)


def fixture(session, tool, arguments, identity, board, source_board, expected, registry_path, registry,
            scope, cli, output_dir):
    """One explicit test in an independent candidate already open in KiCad.

    Never performs a generic 'auto-test' on a user's current source project.
    A write timeout leaves result UNKNOWN and does not auto-retry.
    """
    board=Path(board).resolve();source_board=Path(source_board).resolve()
    if board==source_board or not board.is_file() or not source_board.is_file() or board.suffix!='.kicad_pcb':
        raise ValueError('Fixture needs separate existing original and candidate .kicad_pcb files')
    if board.parent==source_board.parent or source_board.is_relative_to(board.parent):
        raise ValueError('Fixture and source must live in separate projects')
    if sha(board)!=sha(source_board):
        raise ValueError('Fixture board was not cloned exactly from original')
    if risk(tool) not in ('L1','L2','L3'):
        raise ValueError('Read-only tools do not require a mutating fixture')
    validate_board_argument_paths(arguments,board,source_board)
    original_before=sha(source_board)
    live=require_live_board(session,board,identity['eligible_kicad_versions'])
    kicad_version=live['editor_state']['kicad_version']['full_version']
    before=inspect_saved_board(board)
    before_content=board.read_text(encoding='utf-8-sig')
    start=sha(board)
    response=session.call(tool['name'],arguments)
    # No blind retry if timeout, error or session interruption.
    live_after=require_live_board(session,board,identity['eligible_kicad_versions'])
    # Save must be explicit and confirmed; calling unknown tools is forbidden.
    saves=[t for t in session.tools() if t.get('name')=='save_project']
    if len(saves)!=1:raise ValueError('Current Konnect toolset must expose explicit save_project')
    session.call('save_project')
    after=inspect_saved_board(board)
    if sha(source_board)!=original_before:raise ValueError('Protected test source changed during fixture')
    if sha(board)==start:raise ValueError('Fixture did not change saved board; cannot accept an editing capability')
    if expected.get('kind')=='zone_fill':
        verified=verify_zone_fill_change(before_content,board,expected)
    else:
        verified=verify_fixture_change(before,after,expected)
    report=output_dir/'fixture-drc.txt'
    drc=_native_drc(cli,board,report)
    result={'status':'FIXTURE_PASSED_ACCEPTANCE_RECORDED','backend':identity,'tool':tool['name'],
            'tool_schema_sha256':tool_schema_hash(tool),'kicad_version':kicad_version,'risk':risk(tool),
            'scope':scope,'tested_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'source_sha256':sha(source_board),'fixture_before_sha256':start,'fixture_after_sha256':sha(board),
            'fixture':verified,'native_drc':drc,'production_authorized':False}
    record_fixture(registry_path,registry,result)
    return {'status':'FIXTURE_ACCEPTED_SCOPE_LIMITED','record':result,'mcp_response_sha256':digest_bytes(canonical(body(response)).encode()),
            'note':'Fixture validation does not replace current-project ERC/DRC, SI/PI or engineer review.'}


def invoke(session, tool, arguments, identity, board, original_board, scope, registry, save_after=False):
    """Call exactly one discovered tool. Mutation requires fixture acceptance.

    This runs only on an independent working copy of the original project.
    The operation receipt is NOT a design, DRC, or manufacturing acceptance.
    """
    board=Path(board).resolve();original_board=Path(original_board).resolve()
    if not board.is_file() or not original_board.is_file() or board==original_board:
        raise ValueError('Use an existing separate original and candidate board')
    if board.parent==original_board.parent or board.is_relative_to(original_board.parent):
        raise ValueError('Refusing a write in the original project directory')
    validate_board_argument_paths(arguments,board,original_board)
    live=require_live_board(session,board,identity['eligible_kicad_versions'])
    kicad_version=live['editor_state']['kicad_version']['full_version']
    allow=assessment(registry,identity,tool,kicad_version,scope)
    if allow['risk']!='L0' and allow['status']!='ACCEPTED_WITHIN_RECORDED_SCOPE':
        raise ValueError('Operation not fixture-accepted in this binary/board/schema/scope: '+allow['status'])
    before=sha(board)
    original_before=sha(original_board)
    # Unknown state after a timed-out write: do not auto-retry.
    response=session.call(tool['name'],arguments)
    after_live=require_live_board(session,board,identity['eligible_kicad_versions'])
    save_response=None
    if save_after and allow['risk']!='L0':
        tools={t['name']:t for t in session.tools()}
        if 'save_project' not in tools:raise ValueError('Cannot save: Konnect save_project not loaded')
        save_response=session.call('save_project')
        require_live_board(session,board,identity['eligible_kicad_versions'])
    if sha(original_board)!=original_before:
        raise ValueError('Original board unexpectedly changed during operation')
    if allow['risk']=='L0' and sha(board)!=before:
        raise ValueError('Read-only tool unexpectedly changed the saved candidate')
    return {'schema_version':1,'status':'OPERATION_EXECUTED_REQUIRES_PROJECT_REVIEW',
            'tool':tool['name'],'tool_schema_sha256':tool_schema_hash(tool),
            'risk':allow['risk'],'scope':scope,'backend':identity,
            'kicad_version':kicad_version,'board':str(board),
            'original_board':str(original_board),'original_sha256':original_before,
            'board_before_sha256':before,'board_after_sha256':sha(board),
            'save_requested':bool(save_after),'save_completed':save_response is not None,
            'mcp_response_sha256':digest_bytes(canonical(body(response)).encode()),'production_authorized':False,
            'limitations':['MCP success is not KiCad DRC pass','Tool outcome must be compared with actual expected geometry/network changes',
                           'No CAM/EQ/manufacturing signoff']}


def _parse_config(args):
    exe=Path(args.executable).resolve();cfg=Path(args.config).resolve()
    if not exe.is_file() or not cfg.is_file():raise ValueError('Konnect executable/config files are required')
    settings=json.loads(cfg.read_text(encoding='utf-8-sig'))
    if settings.get('transport')!='stdio':raise ValueError('Only local stdio Konnect configuration supported')
    if settings.get('ipc_address') and not settings['ipc_address'].startswith('ipc://'):
        raise ValueError('Remote IPC address refused')
    return exe,cfg


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('discover','assess','fixture','invoke'))
    p.add_argument('--executable',required=True)
    p.add_argument('--config',required=True)
    p.add_argument('--enrollment',help='Explicit local binary SHA/build pin for future Konnect releases; never auto-enroll')
    p.add_argument('--registry',help='Persistent acceptance records stored outside Skill and project tree')
    p.add_argument('--output-dir',required=True,help='Fresh independent report directory')
    p.add_argument('--toolset',action='append',default=[])
    p.add_argument('--all-toolsets',action='store_true')
    p.add_argument('--tool')
    p.add_argument('--scope',default='')
    p.add_argument('--board')
    p.add_argument('--source-board')
    p.add_argument('--arguments',help='Existing UTF-8 JSON object for one actual MCP tool invocation')
    p.add_argument('--expected',help='Existing JSON expected placement/allowed footprint changes')
    p.add_argument('--kicad-cli',default='kicad-cli')
    p.add_argument('--apply',action='store_true',help='Required for fixture/invoke; explicit candidate write authorization')
    p.add_argument('--save-after',action='store_true',help='After one accepted mutating tool call, explicitly call Konnect save_project')
    args=p.parse_args()
    out=Path(args.output_dir).resolve()
    if out.exists():p.error('New output directory required')
    report={'status':'BLOCKED','production_authorized':False}
    try:
        if args.command in ('fixture','invoke') and not args.apply:
            raise ValueError('Explicit --apply required before a Konnect mutation')
        exe,cfg=_parse_config(args)
        pin_binary_before_launch(exe,args.enrollment)
        registry=load_registry(args.registry)
        with McpSession(exe,cfg) as session:
            identity=check_identity(session,exe,args.enrollment)
            found=discover(session,args.toolset,args.all_toolsets)
            if args.command=='discover':
                report={**found,'backend':identity}
            else:
                rows={t['name']:t for t in session.tools()}
                if not args.tool or args.tool not in rows:raise ValueError('Requested tool is not discovered; load its toolset first')
                tool=rows[args.tool]
                if not args.scope:raise ValueError('Explicit operation/geometry scope required')
                if args.command=='assess':
                    if not args.board:raise ValueError('Board required for version-scoped assessment')
                    live=require_live_board(session,args.board,identity['eligible_kicad_versions'])
                    report={**assessment(registry,identity,tool,live['editor_state']['kicad_version']['full_version'],args.scope),
                            'backend':identity,'board':str(Path(args.board).resolve())}
                else:
                    if not all((args.board,args.source_board,args.arguments,args.registry)):
                        raise ValueError('Fixture/invoke needs separate source/candidate, tool arguments and registry')
                    arguments=json.loads(Path(args.arguments).read_text(encoding='utf-8'))
                    if not isinstance(arguments,dict):raise ValueError('Tool arguments must be a JSON object')
                    # API drift is not silently tolerated.
                    try:
                        from jsonschema import validate as validate_json
                    except ImportError as exc:
                        raise ValueError('jsonschema package required for mutation validation') from exc
                    validate_json(instance=arguments,schema=tool.get('inputSchema',{}))
                    out.mkdir(parents=True,exist_ok=False)
                    if args.command=='fixture':
                        if not args.expected:raise ValueError('Fixture requires explicit expected geometry')
                        expected=json.loads(Path(args.expected).read_text(encoding='utf-8'))
                        if not isinstance(expected,dict):raise ValueError('Fixture expected must be a JSON object')
                        report=fixture(session,tool,arguments,identity,args.board,args.source_board,expected,args.registry,
                                       registry,args.scope,args.kicad_cli,out)
                    else:
                        report=invoke(session,tool,arguments,identity,args.board,args.source_board,args.scope,
                                      registry,save_after=args.save_after)
    except Exception as exc:
        report={'status':'BLOCKED','reason':str(exc),'production_authorized':False,
                'note':'No automatic backend fallback. If a write timed out, inspect candidate before retry.'}
    out.mkdir(parents=True,exist_ok=True)
    (out/'konnect-capabilities.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('tools','mcp_response')},ensure_ascii=False,indent=2))
    return 2 if report['status']=='BLOCKED' else 0

if __name__=='__main__':
    raise SystemExit(main())
