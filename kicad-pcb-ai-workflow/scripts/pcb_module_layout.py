#!/usr/bin/env python3
"""Rules-first, read-only two-level PCB placement planner for an existing KiCad board.

Preflight delegates the native effective rule audit to design_intent_audit; this
planner never changes .kicad_pcb, supplies no fabricated manufacturing values,
and does not replace G3, native DRC or the authorized Konnect writer.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from design_intent_audit import audit as audit_design_rules
from engineering_gate import local
from npi_common import parse_sexpr, children, child, value, sha256
from netlist_guard import read_netlist
from placement_review import metadata
from pcb_fab_approval import validate_for_layout

# Actual KiCad .kicad_pro keys, saved as millimeter floating point values.
REQUIRED_RULES = {
    'min_clearance_mm': 'min_clearance',
    'min_track_width_mm': 'min_track_width',
    'min_via_diameter_mm': 'min_via_diameter',
    'min_via_drill_mm': 'min_through_hole_diameter',
    'min_annular_width_mm': 'min_via_annular_width',
    'min_copper_edge_clearance_mm': 'min_copper_edge_clearance',
    'min_hole_to_hole_mm': 'min_hole_to_hole',
}


def _checked(root, name, extension):
    if not isinstance(name, str) or not name or '..' in Path(name).parts or Path(name).is_absolute():
        raise ValueError('A current project-relative path is required')
    p = local(root, name)
    if p.suffix != extension or p.is_symlink() or not p.is_file():
        raise ValueError('Missing or invalid current engineering input: '+str(name))
    return p


def _finite(value_, name, positive=True):
    if isinstance(value_, bool) or not isinstance(value_, (int, float)) or not math.isfinite(value_):
        raise ValueError('Finite numeric '+name+' required')
    if positive and value_ <= 0:
        raise ValueError('Positive '+name+' required')
    return float(value_)


def _rect(box):
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError('Expected module bounds [x0,y0,x1,y1]')
    a = [_finite(x,'bounds',False) for x in box]
    if a[2] <= a[0] or a[3] <= a[1]:
        raise ValueError('Invalid module bounds')
    return a


def _outline(board):
    """One strictly supported rectangular Edge.Cuts loop; others need native evidence."""
    shapes = [x for x in board if isinstance(x,list) and x and x[0] in ('gr_rect','gr_line','gr_arc','gr_poly','gr_curve') and value(x,'layer')=='Edge.Cuts']
    if len(shapes)==1 and shapes[0][0]=='gr_rect':
        a,b = child(shapes[0],'start',[]),child(shapes[0],'end',[])
        if len(a)<3 or len(b)<3:raise ValueError('Invalid Edge.Cuts rectangle')
        return _rect([min(float(a[1]),float(b[1])),min(float(a[2]),float(b[2])),max(float(a[1]),float(b[1])),max(float(a[2]),float(b[2]))])
    if len(shapes)==4 and all(x[0]=='gr_line' for x in shapes):
        segments=[]
        for x in shapes:
            a,b=child(x,'start',[]),child(x,'end',[])
            if len(a)<3 or len(b)<3:raise ValueError('Invalid Edge.Cuts segment')
            p,q=(float(a[1]),float(a[2])),(float(b[1]),float(b[2]))
            if p==q or (p[0]!=q[0] and p[1]!=q[1]):break
            segments.append((p,q))
        if len(segments)==4:
            pts=set(p for pair in segments for p in pair)
            if len(pts)==4 and all(sum(p in seg for seg in segments)==2 for p in pts):
                r=_rect([min(p[0] for p in pts),min(p[1] for p in pts),max(p[0] for p in pts),max(p[1] for p in pts)])
                if pts==set(((r[0],r[1]),(r[0],r[3]),(r[2],r[1]),(r[2],r[3]))):return r
    raise ValueError('Unsupported/missing closed Edge.Cuts outline; inspect native arcs/polygons, do not guess a rectangular board')


def _board_electrical(board):
    """Fingerprint insensitive to footprint moves but sensitive to pads/net/stackup."""
    footprint=[]
    for f in children(board,'footprint'):
        refs=[p[2] for p in children(f,'property') if len(p)>2 and p[1]=='Reference']
        if len(refs)!=1:raise ValueError('Missing/duplicate PCB reference property')
        pads=[]
        for p in children(f,'pad'):
            net=child(p,'net',[])
            pads.append((str(p[1]),str(net[2]) if len(net)>2 else '',json.dumps(child(p,'size',[])),json.dumps(child(p,'drill',[]))))
        footprint.append((refs[0],str(f[1]),value(f,'layer'),sorted(pads)))
    payload={'footprints':sorted(footprint),'nets':sorted(tuple(n[1:3]) for n in children(board,'net')),
             'layers':child(board,'layers',[]),'stackup':child(child(board,'setup',[]),'stackup',[]),'outline':_outline(board)}
    data=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(data.encode()).hexdigest(),footprint


def _sources(root, req):
    project=_checked(root,req['project'],'.kicad_pro')
    board_file=_checked(root,req['board'],'.kicad_pcb')
    if project.parent!=board_file.parent or project.stem!=board_file.stem:
        raise ValueError('PCB/project must be the same authoritative KiCad project')
    netlist=_checked(root,req['netlist'],'.xml')
    intent=_checked(root,req['design_intent'],'.json')
    policy=_checked(root,req['placement_policy'],'.json')
    fab=_checked(root,req['fab_rules'],'.json')
    configuration=json.loads(project.read_text(encoding='utf-8-sig'))
    board=parse_sexpr(board_file.read_text(encoding='utf-8-sig'))
    if board[0]!='kicad_pcb':raise ValueError('Not a native KiCad PCB')
    intent_data=json.loads(intent.read_text(encoding='utf-8-sig'))
    if (intent_data.get('project_file')!=str(project.relative_to(root)) or
        intent_data.get('board_file')!=str(board_file.relative_to(root))):
        raise ValueError('Design intent refers to another PCB/project')
    return project,board_file,netlist,intent,policy,fab,configuration,board


def _validate_fab(root, fab, pro):
    profile=json.loads(fab.read_text(encoding='utf-8-sig'))
    if profile.get('schema_version')!=1 or not isinstance(profile.get('source'),dict):
        raise ValueError('Source-backed fabricator profile required')
    source=profile['source'];src=local(root,source.get('file',''))
    if not source.get('locator') or not src.is_file() or sha256(src)!=source.get('sha256'):
        raise ValueError('Manufacturer/fabricator source evidence missing or changed')
    limits=profile.get('minimums_mm')
    if not isinstance(limits,dict) or set(limits)!=set(REQUIRED_RULES):
        raise ValueError('All seven required fabrication minima must be explicit and sourced')
    current=pro.get('board',{}).get('design_settings',{}).get('rules',{})
    if not isinstance(current,dict):raise ValueError('Missing active KiCad Board Setup rules')
    checked={}
    for name,key in REQUIRED_RULES.items():
        target=_finite(limits[name],name)
        actual=current.get(key)
        if isinstance(actual,bool) or not isinstance(actual,(int,float)):
            raise ValueError('Current KiCad project lacks verified rule '+key)
        measured=_finite(actual,key,False)
        if measured+1e-9<target:raise ValueError('Active KiCad rule '+key+' below approved fabricator minimum')
        checked[key]={'active_mm':round(measured,6),'approved_min_mm':target}
    courtyard=_finite(profile.get('courtyard_clearance_mm'),'courtyard_clearance_mm',False)
    return checked,courtyard


def _sensitive_anchors(board, intent):
    """Movement of an RF/keepout anchor invalidates the original rule audit."""
    refs={z['anchor']['ref'] for z in intent.get('regions',[]) if isinstance(z,dict) and isinstance(z.get('anchor'),dict) and z['anchor'].get('ref')}
    actual={}
    for f in children(board,'footprint'):
        props={p[1]:p[2] for p in children(f,'property') if len(p)>2}
        ref=props.get('Reference')
        if ref not in refs:continue
        at=child(f,'at',[])
        if len(at)<3:raise ValueError('Sensitive anchor has no native position '+str(ref))
        actual[ref]=[float(at[1]),float(at[2]),float(at[3]) if len(at)>3 else 0.0]
    if set(actual)!=refs:raise ValueError('Native RF/keepout anchor missing: '+str(sorted(refs-set(actual))))
    return actual


def _parity(board, xml):
    graph=read_netlist(xml)
    expected={(ref,str(pin)):net for net,nodes in graph['nets'].items() for ref,pin in nodes}
    present=set();actual={}
    for f in children(board,'footprint'):
        refs=[p[2] for p in children(f,'property') if len(p)>2 and p[1]=='Reference']
        if len(refs)!=1:raise ValueError('Cannot identify PCB footprint')
        ref=refs[0]
        if ref in present:raise ValueError('Duplicate footprint reference')
        present.add(ref)
        for p in children(f,'pad'):
            key=(ref,str(p[1]));net=child(p,'net',[]);name=str(net[2]) if len(net)>2 else ''
            if key in actual and actual[key]!=name:raise ValueError('Duplicate pad number with conflicting nets: '+repr(key))
            actual[key]=name
    for key,net in expected.items():
        if key[0] in present and actual.get(key)!=net:
            raise ValueError('Schematic-to-PCB pad/net mismatch '+repr(key))
    if not set(graph['components']).issubset(present):
        raise ValueError('Schematic footprints have not been synchronized to PCB; run F8 and verify G2')
    return graph,actual


def preflight(root, request, native_audit=None):
    root=Path(root).resolve()
    req=json.loads(_checked(root,request,'.json').read_text(encoding='utf-8-sig'))
    if req.get('schema_version')!=1:raise ValueError('Expected schema_version=1')
    # Human decision is checked before requiring profile sidecars or running
    # costly native rule audits; preview without consent remains actionable.
    approval=validate_for_layout(root,req)
    project,board_file,netlist,intent,policy,fab,pro,board=_sources(root,req)
    rule_values,courtyard=_validate_fab(root,fab,pro)
    graph,_=_parity(board,netlist)
    fingerprint,_=_board_electrical(board)
    intent_data=json.loads(intent.read_text(encoding='utf-8-sig'))
    anchors=_sensitive_anchors(board,intent_data)
    checks=(native_audit or audit_design_rules)(root,intent,native=True,phase='pre_route')
    if checks.get('status')!='PASS' or checks.get('native_requested') is not True:
        raise ValueError('Current KiCad effective rules not verified: '+repr(checks.get('findings',checks.get('status'))))
    file_hashes={str(p.relative_to(root)):sha256(p) for p in (project,netlist,intent,policy,fab)}
    file_hashes[approval["approval_path"]]=approval["approval_sha256"]
    file_hashes[approval["proposal_path"]]=approval["proposal_sha256"]
    dru=project.with_suffix('.kicad_dru')
    if dru.exists():file_hashes[str(dru.relative_to(root))]=sha256(dru)
    return {'schema_version':1,'status':'RULES_VERIFIED_FOR_LAYOUT_PLANNING',
            'input_hashes':file_hashes,'board_electrical_fingerprint':fingerprint,
            'board_hash_at_preflight':sha256(board_file),'board':str(board_file.relative_to(root)),
            'sensitive_anchor_poses':anchors,'fab_user_confirmation':approval,
            'board_outline_mm':_outline(board),'active_fabrication_rules':rule_values,
            'courtyard_clearance_mm':courtyard,'netlist_components':len(graph['components']),
            'scope':'Current native Board Setup minima + design-intent native effective-netclass subset, not full manufacturing, geometry or DRC approval',
            'executed':False,'production_authorized':False}


def _fits(box,region):
    return all((region[0]-1e-7<=box[0],region[1]-1e-7<=box[1],box[2]<=region[2]+1e-7,box[3]<=region[3]+1e-7))


def _overlap(a,b,clear):
    return a[0]<b[2]+clear-1e-7 and a[2]>b[0]-clear+1e-7 and a[1]<b[3]+clear-1e-7 and a[3]>b[1]-clear+1e-7


def _shift(box,dx,dy):return [box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy]


def _candidates(target, zone, grid, limit):
    x0=int(math.ceil(zone[0]/grid));x1=int(math.floor(zone[2]/grid))
    y0=int(math.ceil(zone[1]/grid));y1=int(math.floor(zone[3]/grid))
    pts=[(round(x*grid,6),round(y*grid,6)) for x in range(x0,x1+1) for y in range(y0,y1+1)]
    pts.sort(key=lambda p:(abs(p[0]-target[0])+abs(p[1]-target[1]),p))
    return pts[:limit]


def plan(root, request, receipt):
    root=Path(root).resolve()
    req=json.loads(_checked(root,request,'.json').read_text(encoding='utf-8-sig'))
    saved=Path(receipt).resolve()
    if not saved.is_file() or saved.is_symlink() or (saved.is_relative_to(root) and not saved.is_relative_to(root/'03_REPORTS')):
        raise ValueError('Preflight receipt must be immutable and outside work files')
    ready=json.loads(saved.read_text(encoding='utf-8-sig'))
    if ready.get('status')!='RULES_VERIFIED_FOR_LAYOUT_PLANNING':raise ValueError('No verified rules-first preflight')
    current_approval=validate_for_layout(root,req)
    if current_approval!=ready.get('fab_user_confirmation'):
        raise ValueError('User-approved fabrication profile differs from preflight; obtain fresh confirmation')
    project,board_file,netlist,intent,policy,fab,pro,board=_sources(root,req)
    for name,digest in ready['input_hashes'].items():
        if sha256(local(root,name))!=digest:raise ValueError('Rules/electrical/layout policy changed; repeat native preflight')
    fingerprint,_=_board_electrical(board)
    if fingerprint!=ready.get('board_electrical_fingerprint'):
        raise ValueError('Board electrical/stackup/pad/outline changed; repeat native rule preflight and F8 checks')
    intent_data=json.loads(intent.read_text(encoding='utf-8-sig'))
    if _sensitive_anchors(board,intent_data)!=ready.get('sensitive_anchor_poses'):
        raise ValueError('Sensitive fixed RF/keepout anchor changed; rerun native design intent preflight')
    rule_values,clearance=_validate_fab(root,fab,pro)
    if rule_values!=ready['active_fabrication_rules'] or clearance!=ready['courtyard_clearance_mm']:
        raise ValueError('Active fabrication rules differ from verified preflight')
    graph,_=_parity(board,netlist)
    policy_data=json.loads(policy.read_text(encoding='utf-8-sig'))
    modules=policy_data.get('modules',[])
    info=metadata(board_file)
    footprints={ref:box for ref,box in info.items()}
    all_refs=set(footprints)
    if not modules or any(not isinstance(m,dict) for m in modules):raise ValueError('Explicit existing module grouping required')
    ownership=[ref for m in modules for ref in m['refs']]
    if len(set(ownership))!=len(ownership) or set(ownership)!=all_refs:
        raise ValueError('Every real PCB footprint must belong to exactly one module')
    outline=ready['board_outline_mm'];grid=_finite(req.get('grid_mm'),'grid_mm')
    limit=int(_finite(req.get('max_candidates_per_ref',120),'max_candidates_per_ref'))
    if grid<0.1 or grid>10 or limit>2000:raise ValueError('Placement search grid/budget outside bounded range')
    fixed_refs=set(req.get('fixed_refs',[]))
    for f in children(board,'footprint'):
        props={p[1]:p[2] for p in children(f,'property') if len(p)>2}
        if child(f,'locked') and props.get('Reference'):fixed_refs.add(props['Reference'])
    if not fixed_refs.issubset(all_refs):raise ValueError('Fixed ref is not a current footprint')
    local_rects={};current={};angles={}
    for f in children(board,'footprint'):
        ref=next(p[2] for p in children(f,'property') if len(p)>2 and p[1]=='Reference')
        at=child(f,'at',[])
        if len(at)<3:raise ValueError('Footprint has no position: '+ref)
        pos=(float(at[1]),float(at[2]));current[ref]=pos
        angles[ref]=float(at[3]) if len(at)>3 else 0
        polygon=info[ref]['courtyard']
        if not polygon:raise ValueError('No verified top-side Courtyard polygon for '+ref+'; native/manual geometry required')
        xs=[p[0] for p in polygon];ys=[p[1] for p in polygon]
        local_rects[ref]=[min(xs)-pos[0],min(ys)-pos[1],max(xs)-pos[0],max(ys)-pos[1]]
    neighbors={ref:set() for ref in all_refs}
    for net,nodes in graph['nets'].items():
        refs={ref for ref,_ in nodes if ref in all_refs}
        if len(refs)>1:
            for ref in refs:neighbors[ref].update(refs-{ref})
    selected={};modules_output=[]
    # Global page/connector anchors constrain each local module search before the
    # module as a unit can be repositioned. No speculative changes to orientation.
    priorities={'connector':0,'mechanical':0,'rf':1,'power':1,'controller':1,
                'decoupling':2,'clock':2,'protection':2,'feedback':2,'termination':2}
    for m in sorted(modules,key=lambda a:(not bool(set(a['refs'])&fixed_refs),a['id'])):
        refs=m['refs'];region=_rect(m['bounds_mm'])
        if not _fits(region,outline):raise ValueError('Module zone outside verified Edge.Cuts: '+m['id'])
        roles=m.get('roles',{})
        if set(roles)!=set(refs) or m.get('anchor') not in refs:
            raise ValueError('Module roles/anchor must cover current footprints: '+m['id'])
        fixed=[r for r in refs if r in fixed_refs]
        for ref in fixed:
            p=current[ref];b=_shift(local_rects[ref],*p)
            if not _fits(b,region) or not _fits(b,outline):raise ValueError('Locked/connector footprint outside module bounds: '+ref)
            if any(_overlap(b,_shift(local_rects[r],*selected[r]),clearance) for r in selected):
                raise ValueError('Existing fixed footprint courtyard collision: '+ref)
            selected[ref]=p
        ordered=sorted((r for r in refs if r not in fixed),key=lambda r:(0 if r==m['anchor'] else priorities.get(roles[r],3),-len(neighbors[r]),r))
        for ref in ordered:
            peers=[selected[r] for r in neighbors[ref] if r in selected]
            focus=(sum(p[0] for p in peers)/len(peers),sum(p[1] for p in peers)/len(peers)) if peers else ((region[0]+region[2])/2,(region[1]+region[3])/2)
            chosen=None
            for p in _candidates(focus,region,grid,limit):
                b=_shift(local_rects[ref],*p)
                if not _fits(b,region) or not _fits(b,outline):continue
                if any(_overlap(b,_shift(local_rects[r],*selected[r]),clearance) for r in selected):continue
                chosen=p;break
            if chosen is None:
                return {'schema_version':1,'status':'REPLAN_REQUIRED','reason':'No room for '+ref+' within tested region/grid; do not infer that the board is impossible',
                        'module':m['id'],'placed':sorted(selected),'executed':False,'production_authorized':False}
            selected[ref]=chosen
        modules_output.append({'id':m['id'],'refs':refs,'region_mm':region,'fixed':fixed,
                               'scope':'local courtyard/neighbor proximity heuristic only'})
    # Whole-board coordination: small legal translations of movable modules,
    # while retaining local geometry and preserving all fixed connectors/holes.
    for _ in range(2):
        for m in modules_output:
            if m['fixed']:continue
            refs=m['refs'];movable=set(refs);region=m['region_mm']
            def cost(shift_x,shift_y):
                score=0
                for ref in refs:
                    a=selected[ref];p=(a[0]+shift_x,a[1]+shift_y);b=_shift(local_rects[ref],*p)
                    if not _fits(b,region) or not _fits(b,outline):return None
                    for r in selected:
                        if r not in movable and _overlap(b,_shift(local_rects[r],*selected[r]),clearance):return None
                    for other in neighbors[ref]:
                        if other not in movable:
                            q=selected[other];score+=abs(p[0]-q[0])+abs(p[1]-q[1])
                return score
            options=[]
            for dx in (-grid,0,grid):
                for dy in (-grid,0,grid):
                    c=cost(dx,dy)
                    if c is not None:options.append((round(c,6),abs(dx)+abs(dy),dx,dy))
            if options:
                _,_,dx,dy=min(options)
                for ref in refs:selected[ref]=(round(selected[ref][0]+dx,6),round(selected[ref][1]+dy,6))
    return {'schema_version':1,'status':'BOUNDED_MODULAR_PLACEMENT_PROPOSAL',
            'board':req['board'],'board_sha256':sha256(board_file),
            'preflight_receipt_sha256':sha256(saved),'rules_source_hashes':ready['input_hashes'],
            'placements':{ref:{'position_mm':list(selected[ref]),'angle_deg':angles[ref],
                               'fixed':ref in fixed_refs} for ref in sorted(selected)},
            'modules':modules_output,'grid_mm':grid,
            'limitations':['Source-owned fabrication/netclass rules are checked before layout; native DRC and G3 are separate.',
                           'Planner uses verified rectilinear top courtyards; no B.Cu/curved/3D support.',
                           'Only board-level module translations, not rotations; no high-speed/RF/thermal route proof.',
                           'Plan does not modify KiCad; Konnect exact-position execution and saved-state verification remain necessary.'],
            'executed':False,'production_authorized':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('preflight','plan'))
    parser.add_argument('project_root')
    parser.add_argument('--request',required=True)
    parser.add_argument('--receipt',help='preflight: new output JSON; plan: existing receipt JSON')
    args=parser.parse_args()
    try:
        root=Path(args.project_root).resolve()
        if not root.is_dir():raise ValueError('Existing project root required')
        if args.command=='preflight':
            result=preflight(root,args.request)
            if args.receipt:
                target=Path(args.receipt).resolve()
                if target.exists() or not target.parent.is_dir() or not (target.is_relative_to(root/'03_REPORTS') or not target.is_relative_to(root)):
                    raise ValueError('Preflight receipt must be a NEW immutable report file')
                with target.open('x',encoding='utf-8') as fh:json.dump(result,fh,indent=2)
        else:
            if not args.receipt:raise ValueError('Plan needs current preflight receipt')
            result=plan(root,args.request,args.receipt)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status'] in ('RULES_VERIFIED_FOR_LAYOUT_PLANNING','BOUNDED_MODULAR_PLACEMENT_PROPOSAL') else 2
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'executed':False,'production_authorized':False}))
        return 2

if __name__=='__main__':raise SystemExit(main())
