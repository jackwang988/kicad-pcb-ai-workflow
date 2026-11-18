#!/usr/bin/env python3
"""Read-only JLCPCB profile proposal, explicit human confirmation and scoped approval verifier.

The approval records USER authorization to attempt applying a rule set. They do
not write KiCad, certify a board, or substitute native rule readback / DRC.
"""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from npi_common import parse_sexpr, children, child, value, sha256
from engineering_gate import local

CATALOG = Path(__file__).resolve().parents[1]/'references/jlcpcb-rigid-fr4-presets.json'
KEYS = ('min_clearance_mm','min_track_width_mm','min_via_diameter_mm','min_via_drill_mm',
        'min_annular_width_mm','min_copper_edge_clearance_mm','min_hole_to_hole_mm')


def load_catalog():
    data=json.loads(CATALOG.read_text(encoding='utf-8'))
    if data.get('schema_version')!=1 or set(data.get('profiles',{}))!={'2','4','6','8'}:
        raise ValueError('Invalid bundled JLCPCB capability catalog')
    return data


def _selected_board(root,name):
    root=Path(root).resolve()
    if not isinstance(name,str) or not name or '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Existing project-relative PCB path required')
    p=local(root,name)
    if not p.is_file() or p.is_symlink() or p.suffix!='.kicad_pcb':raise ValueError('Current KiCad PCB required')
    project=p.with_suffix('.kicad_pro')
    if not project.is_file():raise ValueError('Matching current KiCad project required')
    board=parse_sexpr(p.read_text(encoding='utf-8-sig'))
    if board[0]!='kicad_pcb':raise ValueError('Invalid native PCB file')
    count=sum(1 for item in child(board,'layers',[])[1:] if isinstance(item,list) and len(item)>2 and (item[2] in ('signal','power','jumper') or str(item[1]).endswith('.Cu')))
    if count not in (2,4,6,8):raise ValueError('Unsupported actual KiCad copper layer count '+str(count))
    return p,project,board,count


def propose(root,board,layer_count):
    root=Path(root).resolve();p,project,tree,actual_count=_selected_board(root,board)
    if actual_count!=layer_count:raise ValueError('Selected layer count conflicts with actual KiCad copper layers')
    catalog=load_catalog();selected=catalog['profiles'][str(layer_count)]
    general=child(tree,'general',[])
    actual_thickness=value(general,'thickness',None)
    if actual_thickness is None or not math.isclose(float(actual_thickness),selected['board_thickness_mm'],abs_tol=0.01):
        raise ValueError('Current board thickness differs from selected nominal JLCPCB profile; first select/verify a compatible profile')
    return {'schema_version':1,'status':'FAB_USER_CONFIRMATION_REQUIRED','vendor':'JLCPCB',
            'catalog_id':catalog['catalog_id'],'catalog_sha256':sha256(CATALOG),
            'snapshot_date':catalog['snapshot_date'],'official_sources':catalog['sources'],
            'board':p.relative_to(root).as_posix(),'project':project.relative_to(root).as_posix(),
            'copper_layers':actual_count,'selection':selected,
            'fabrication_caps_mm':catalog['general_fabrication_caps_mm'],
            'limitations':catalog['notes']+[
                'Approval does not confirm the actual selected ordering stackup/dielectric materials or impedance.',
                'The design rule defaults are a conservative Skill suggestion, NOT official factory default settings.',
                'Approval does not apply KiCad Board Setup; verify effective rules after authorized Konnect changes.'],
            'next_action':'SHOW EXACT PROPOSAL TO USER; obtain explicit approval or modifications; do not invoke confirm automatically',
            'executed':False,'production_authorized':False}


def _safe_report(root,name):
    root=Path(root).resolve();p=Path(name)
    if not p.is_absolute():p=root/p
    p=p.resolve()
    if not p.is_relative_to(root/'03_REPORTS') or p.is_symlink():
        raise ValueError('Output/receipt must be inside existing 03_REPORTS')
    if not p.parent.is_dir():raise ValueError('Create report folder once before proposal/approval')
    return p


def _load_report(root,name):
    p=_safe_report(root,name)
    if not p.is_file():raise ValueError('Missing proposal or approval receipt')
    return p,json.loads(p.read_text(encoding='utf-8-sig'))


def confirm(root,proposal_file,confirmed_by,decision,approval_output,fab_output):
    """Called only AFTER an explicit user decision, not by preview or autopilot."""
    root=Path(root).resolve();proposal_path,q=_load_report(root,proposal_file)
    if decision!='CONFIRM' or not isinstance(confirmed_by,str) or not confirmed_by.strip():
        raise ValueError('Explicit human CONFIRM decision and identified reviewer required')
    if q.get('status')!='FAB_USER_CONFIRMATION_REQUIRED' or q.get('catalog_sha256')!=sha256(CATALOG):
        raise ValueError('Stale factory profile proposal; preview again')
    p,project,_,layer_count=_selected_board(root,q['board'])
    if q['project']!=project.relative_to(root).as_posix() or layer_count!=q['copper_layers']:
        raise ValueError('Board layers/identity changed; obtain a new user decision')
    canonical=propose(root,q['board'],layer_count)
    if canonical!=q:raise ValueError('Proposal changed since preview; request human confirmation again')
    approval_path=_safe_report(root,approval_output);fab_path=_safe_report(root,fab_output)
    if approval_path==fab_path or any(t.exists() for t in (approval_path,fab_path)):
        raise ValueError('Approval and rule output paths must be distinct NEW files')
    profile=q['selection']
    fab={'schema_version':1,'vendor':'JLCPCB','source':{
            'file':proposal_path.relative_to(root).as_posix(),'sha256':sha256(proposal_path),
            'locator':q['catalog_id']+'; official URLs and capability-vs-recommendation distinction in proposal'},
         'minimums_mm':profile['user_reviewed_design_rules_mm'],
         'courtyard_clearance_mm':profile['courtyard_clearance_mm'],
         'approved_layers':layer_count,'approved_thickness_mm':profile['board_thickness_mm'],
         'approved_outer_copper_oz':profile['outer_copper_oz'],
         'approved_inner_copper_oz':profile['inner_copper_oz'],
         'user_approval_file':approval_path.relative_to(root).as_posix()}
    fab_text=json.dumps(fab,ensure_ascii=False,indent=2)+'\n'
    a={'schema_version':1,'status':'FAB_PROFILE_USER_CONFIRMED',
       'decision':'CONFIRM','confirmed_by':confirmed_by.strip(),
       'confirmed_utc':datetime.now(timezone.utc).isoformat(),
       'scope':'authorization to APPLY approved values via accepted KiCad writer, not manufacturing certification',
       'proposal_file':proposal_path.relative_to(root).as_posix(),'proposal_sha256':sha256(proposal_path),
       'catalog_sha256':sha256(CATALOG), 'board':q['board'],'copper_layers':layer_count,
       'fab_rules_file':fab_path.relative_to(root).as_posix(),
       'fab_rules_sha256':hashlib.sha256(fab_text.encode('utf-8')).hexdigest(),
       'next_action':'Apply through authorized Konnect then verify REAL active project Board Setup and native preflight',
       'executed':False,'production_authorized':False}
    # Exclusive creations: approval cannot exist without its corresponding immutable fab.
    with fab_path.open('x',encoding='utf-8') as out:out.write(fab_text)
    try:
        with approval_path.open('x',encoding='utf-8') as out:out.write(json.dumps(a,ensure_ascii=False,indent=2)+'\n')
    except Exception:
        fab_path.unlink()
        raise
    return a


def validate_for_layout(root,req):
    root=Path(root).resolve()
    approval_rel=req.get('fab_approval')
    if not approval_rel:raise ValueError('FAB_USER_CONFIRMATION_REQUIRED: preview JLCPCB profile, obtain user choice, then confirm')
    try:approval_file,a=_load_report(root,approval_rel)
    except ValueError as exc:raise ValueError('FAB_USER_CONFIRMATION_REQUIRED: user approval receipt missing or invalid') from exc
    if a.get('status')!='FAB_PROFILE_USER_CONFIRMED' or a.get('decision')!='CONFIRM' or not a.get('confirmed_by'):
        raise ValueError('No explicit user-confirmed manufacturing rule profile')
    proposal_file,q=_load_report(root,a['proposal_file'])
    if sha256(proposal_file)!=a.get('proposal_sha256') or a.get('catalog_sha256')!=sha256(CATALOG):
        raise ValueError('Confirmed preset/source changed; obtain fresh approval')
    p,project,board,layers=_selected_board(root,req['board'])
    if q.get('copper_layers')!=layers or a.get('copper_layers')!=layers:
        raise ValueError('Actual copper layer count changed since user confirmation; re-confirm profile')
    # The rule profile is not enough: physical copper layer count and copper
    # weights must match the actual KiCad Board Setup stackup before placement.
    actual_layers=[str(item[1]) for item in child(board,'layers',[])[1:]
                   if isinstance(item,list) and len(item)>2 and str(item[1]).endswith('.Cu')]
    stack=child(child(board,'setup',[]),'stackup',[])
    stack_layers={}
    for item in children(stack,'layer'):
        if value(item,'type')=='copper':
            name=str(item[1]);thick=value(item,'thickness',None)
            if name in stack_layers or thick is None:raise ValueError('Incomplete/duplicate KiCad copper stackup')
            stack_layers[name]=float(thick)
    if set(stack_layers)!=set(actual_layers) or len(stack_layers)!=layers:
        raise ValueError('Actual KiCad per-layer copper stackup missing or does not match approved layer count')
    selected=q['selection']
    for name,thickness in stack_layers.items():
        expected_oz=selected['outer_copper_oz'] if name in ('F.Cu','B.Cu') else selected['inner_copper_oz']
        expected_mm=0.035 if expected_oz==1 else 0.0175 if expected_oz==0.5 else None
        if expected_mm is None or abs(thickness-expected_mm)>0.005:
            raise ValueError('Actual '+name+' finished copper thickness differs from selected factory profile')
    if (a['board']!=req['board'] or q['board']!=req['board'] or q['project']!=req['project']
            or q['copper_layers']!=layers or a['copper_layers']!=layers):
        raise ValueError('Actual PCB or layer count differs from user-confirmed profile')
    selected=propose(root,q['board'],layers)
    if selected!=q:raise ValueError('Current JLCPCB proposal no longer matches approval; re-confirm')
    fabpath=local(root,req['fab_rules'])
    if fabpath.relative_to(root).as_posix()!=a['fab_rules_file'] or sha256(fabpath)!=a['fab_rules_sha256']:
        raise ValueError('Fabrication rules differ from exactly user-approved values')
    fab=json.loads(fabpath.read_text(encoding='utf-8-sig'))
    if (fab.get('source',{}).get('sha256')!=a['proposal_sha256'] or
            fab.get('minimums_mm')!=q['selection']['user_reviewed_design_rules_mm'] or
            fab.get('approved_layers')!=layers or
            fab.get('courtyard_clearance_mm')!=q['selection']['courtyard_clearance_mm']):
        raise ValueError('Approval/fab values diverged')
    return {'approval_sha256':sha256(approval_file),'proposal_sha256':sha256(proposal_file),
            'approval_path':str(approval_file.relative_to(root)),
            'proposal_path':str(proposal_file.relative_to(root)),
            'status':'FAB_PROFILE_APPROVAL_CURRENT', 'layers':layers,
            'scope':'authorization + exact proposal binding; actual active native rules must still independently pass'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('preview','confirm'))
    parser.add_argument('project_root')
    parser.add_argument('--board')
    parser.add_argument('--layers',type=int,choices=(2,4,6,8))
    parser.add_argument('--proposal')
    parser.add_argument('--confirmed-by')
    parser.add_argument('--decision')
    parser.add_argument('--output')
    parser.add_argument('--fab-output')
    parser.add_argument('--apply',action='store_true',help='Explicit user confirmation authorization, never for preview')
    args=parser.parse_args()
    try:
        root=Path(args.project_root).resolve()
        if args.command=='preview':
            if args.apply:raise ValueError('Preview may not --apply')
            if not args.board or not args.layers:raise ValueError('Explicit board and 2/4/6/8 layer selection required')
            result=propose(root,args.board,args.layers)
            if args.output:
                path=_safe_report(root,args.output)
                with path.open('x',encoding='utf-8') as f:f.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        else:
            if not args.apply:raise ValueError('User confirmation requires explicit --apply')
            if not all((args.proposal,args.output,args.fab_output)):
                raise ValueError('Explicit proposal, approval receipt and fab-output required')
            result=confirm(root,args.proposal,args.confirmed_by,args.decision,args.output,args.fab_output)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError,KeyError,TypeError,ValueError,IndexError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'executed':False,'production_authorized':False}))
        return 2

if __name__=='__main__':raise SystemExit(main())
