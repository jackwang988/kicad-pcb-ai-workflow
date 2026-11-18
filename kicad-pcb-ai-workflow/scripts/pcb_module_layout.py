#!/usr/bin/env python3
"""Rules-first, read-only two-level PCB placement planner for an existing KiCad board.

Preflight delegates the native effective rule audit to design_intent_audit; this
planner never changes .kicad_pcb, supplies no fabricated manufacturing values,
and does not replace G3, native DRC or the authorized Konnect writer.
"""
import argparse
import hashlib
import itertools
import json
import math
import re
from pathlib import Path

from design_intent_audit import audit as audit_design_rules
from engineering_gate import local
from npi_common import parse_sexpr, children, child, value, sha256
from netlist_guard import read_netlist
from placement_review import metadata
from pcb_fab_approval import validate_for_layout
from pcb_placement_geometry import (shift as shift_poly, bbox as poly_bbox, intersects as poly_intersects,
    in_rectangle as poly_fits, footprint_keepouts, locked as footprint_locked,
    npth_holes, hits_holes, pad_anchor)

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
             'layers':child(board,'layers',[]),'stackup':child(child(board,'setup',[]),'stackup',[]),'outline':_outline(board),
             'mechanical_keepouts':children(board,'zone'),
             'fixed_board_vias':children(board,'via')}
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



def _effective_courtyard_screen(project, declared_clearance, pro):
    """Conservative screen against explicit KiCad custom courtyard DRC minima.

    All recognized courtyard rules contribute a max minimum, regardless of
    condition; this can be stricter than a conditional KiCad DRC, but never
    silently loosens a project-specific courtyard rule. Unsupported syntax
    blocks planning; native DRC remains authoritative.
    """
    severities=pro.get('board',{}).get('design_settings',{}).get('rule_severities',{})
    for key,level in severities.items():
        if ('courtyard' in key.lower() and ('overlap' in key.lower() or 'clearance' in key.lower())
                and str(level).lower()=='ignore'):
            raise ValueError('Courtyard DRC severity must not be ignored: '+key)
    dru=project.with_suffix('.kicad_dru')
    if not dru.exists():return declared_clearance
    source=dru.read_text(encoding='utf-8-sig')
    if 'courtyard_clearance' not in source:return declared_clearance
    # KiCad 10 custom rule: (constraint courtyard_clearance (min 0.4mm))
    values=[]
    for item in re.finditer(r'\(constraint\s+courtyard_clearance\b',source):
        tail=source[item.end():]
        minimum=re.match(r'\s*\(min\s+(-?(?:\d+(?:\.\d*)?|\.\d+))\s*(mm|mil|in)\s*\)\s*\)',tail)
        if not minimum:
            raise ValueError('Unknown custom courtyard_clearance expression; require native DRC review')
        distance=float(minimum.group(1))*{'mm':1.,'mil':0.0254,'in':25.4}[minimum.group(2)]
        if not math.isfinite(distance):raise ValueError('Invalid custom courtyard minimum')
        values.append(distance)
    if not values:
        raise ValueError('Unrecognized courtyard_clearance token in custom rules')
    return max(declared_clearance,0.,*values)


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
    for (ref,pin),net in actual.items():
        if ref in graph['components'] and net and (ref,pin) not in expected:
            raise ValueError('PCB electrical pad is not in current schematic netlist: '+repr((ref,pin,net)))
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
    courtyard=_effective_courtyard_screen(project,courtyard,pro)
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
    """Bounded ring generation, not a million-point Cartesian product/sort."""
    x0=int(math.ceil(zone[0]/grid));x1=int(math.floor(zone[2]/grid))
    y0=int(math.ceil(zone[1]/grid));y1=int(math.floor(zone[3]/grid))
    if x0>x1 or y0>y1:return
    cx=max(x0,min(x1,round(target[0]/grid)))
    cy=max(y0,min(y1,round(target[1]/grid)))
    emitted=0
    max_radius=max(abs(cx-x0),abs(cx-x1))+max(abs(cy-y0),abs(cy-y1))
    for radius in range(max_radius+1):
        lo=max(x0,cx-radius);hi=min(x1,cx+radius)
        for x in range(lo,hi+1):
            dy=radius-abs(x-cx)
            for y in ((cy-dy,) if dy==0 else (cy-dy,cy+dy)):
                if y0<=y<=y1:
                    yield (round(x*grid,6),round(y*grid,6))
                    emitted+=1
                    if emitted>=limit:return


def _critical_constraint_ok(constraints, selected, pads, vias, native_pad_offsets=None):
    """Evaluate mandatory pin-specific constraints when all endpoints are placed.

    Return bool; raise on unsupported hard constraints instead of silently
    ignoring them. Exact copper return paths still require G3/native review.
    """
    def point(spec):
        if spec.get('kind','pad')=='via':
            key=str(spec.get('uuid',''))
            if key not in vias:raise ValueError('Unverified return via: '+key)
            pos,net=vias[key]
            if spec['net']!=net:raise ValueError('Return via net mismatch: '+key)
            return pos
        if spec.get('kind','pad')!='pad':raise ValueError('Unsupported hard placement anchor kind')
        ref=str(spec['ref'])
        if ref not in selected:return None
        if ref not in pads:raise ValueError('Hard constraint references absent footprint '+ref)
        return pad_anchor(pads[ref],selected[ref],spec['pad'],spec['net'],(native_pad_offsets or {}).get(ref))
    for c in constraints:
        kind=c.get('kind');level=c.get('level')
        if level not in ('阻断级','高风险'):continue
        if kind=='pad_proximity':
            a,b=point(c['a']),point(c['b'])
            if a is None or b is None:continue
            if math.dist(a,b)>_finite(c['max_mm'],'pad proximity maximum',False)+1e-8:return False
            if c.get('same_side') is True:
                if any(value(pads[e['ref']],'layer') != 'F.Cu' for e in (c['a'],c['b']) if e.get('kind','pad')=='pad'):
                    return False
        elif kind=='decoupling':
            if c.get('same_side') not in (True,False):raise ValueError('Decoupling needs explicit same_side rule')
            a,b,g,r=(point(c[k]) for k in ('ic_power','cap_power','cap_ground','return_anchor'))
            if any(p is None for p in (a,b,g,r)):continue
            if (math.dist(a,b)>_finite(c['max_power_mm'],'decoupling power maximum',False)+1e-8 or
                math.dist(g,r)>_finite(c['max_return_mm'],'decoupling return maximum',False)+1e-8):return False
            if c['same_side'] and any(value(pads[e['ref']],'layer')!='F.Cu' for e in (c['ic_power'],c['cap_power'],c['cap_ground']) if e.get('kind','pad')=='pad'):return False
        elif kind in ('alignment','uniform_spacing','orientation'):
            raise ValueError('Visual preference must not be a mandatory electrical placement blocker')
        elif kind in ('fixed','corridor'):
            # Fixed/corridor are enforced as native geometric constraints.
            pass
        else:
            raise ValueError('Unsupported mandatory placement constraint kind: '+str(kind))
    return True


def _plan_constraint_geometry(constraints, current, angles, fixed_refs, board):
    """Convert native fixed/corridor declarations; reject ambiguous hard rules."""
    corridors=[]
    for c in constraints:
        kind=c.get('kind');level=c.get('level')
        if kind=='fixed' and level in ('阻断级','高风险'):
            ref=c['ref']
            if ref not in current:raise ValueError('Fixed constraint names unknown footprint: '+str(ref))
            if math.dist(current[ref],c['position_mm'])>_finite(c['position_tolerance_mm'],'position tolerance',False)+1e-8:
                raise ValueError('Fixed footprint already violates declared position: '+str(ref))
            a=angles[ref];target=_finite(c['angle_deg'],'fixed angle',False)
            if abs((a-target+180)%360-180)>_finite(c['angle_tolerance_deg'],'angle tolerance',False)+1e-8:
                raise ValueError('Fixed footprint already violates declared angle: '+str(ref))
            fixed_refs.add(ref)
        elif kind=='corridor' and level in ('阻断级','高风险'):
            margin=_finite(c.get('margin_mm',0),'corridor margin',False)
            b=_rect(c['bounds_mm']);region=[b[0]-margin,b[1]-margin,b[2]+margin,b[3]+margin]
            corridors.append((region,set(c.get('allowed_refs',[]))))
    for region,allowed in corridors:
        if not allowed.issubset(current):raise ValueError('Unknown allowed ref in corridor')
    return corridors


def _return_vias(board):
    names={int(n[1]):str(n[2]) for n in children(board,'net') if len(n)>2}
    result={}
    for v in children(board,'via'):
        uid=value(v,'uuid',None);at=child(v,'at',[])
        if uid and len(at)>2:
            result[str(uid)]=((float(at[1]),float(at[2])),names.get(int(value(v,'net',0)),''))
    return result


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
    clearance=_effective_courtyard_screen(project,clearance,pro)
    if rule_values!=ready['active_fabrication_rules'] or clearance!=ready['courtyard_clearance_mm']:
        raise ValueError('Active fabrication rules differ from verified preflight')
    graph,_=_parity(board,netlist)
    policy_data=json.loads(policy.read_text(encoding='utf-8-sig'))
    modules=policy_data.get('modules',[])
    # Where available, native pcbnew readback verifies rotated courtyard
    # transforms and supplies exact pad offsets; no native writer is used.
    native_geometry=None
    try:
        from link_audit import primitives as read_native_primitives
        native_geometry,_=read_native_primitives(board_file,True)
    except (ImportError,OSError,RuntimeError,ValueError,AttributeError):
        native_geometry=None
    info=metadata(board_file,native_geometry)
    native_pad_offsets={}
    if native_geometry and native_geometry.get('engine')!='static_preview':
        for fp in native_geometry['footprints']:
            ref=fp['ref'];old=fp['pos']
            if ref not in native_pad_offsets:
                native_pad_offsets[ref]={str(pad['number']):((pad['pos'][0]-old[0],pad['pos'][1]-old[1]),pad['net']) for pad in fp['pads']}
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
    # Connector and mechanical positions are mechanical interfaces, not
    # optimizable aesthetic suggestions. Native locked and RF anchors are fixed.
    for m in modules:
        fixed_refs.update(r for r in m['refs'] if m.get('roles',{}).get(r) in ('connector','mechanical'))
    fixed_refs.update(_sensitive_anchors(board,intent_data))
    for f in children(board,'footprint'):
        props={p[1]:p[2] for p in children(f,'property') if len(p)>2}
        if footprint_locked(f) and props.get('Reference'):fixed_refs.add(props['Reference'])
    if not fixed_refs.issubset(all_refs):raise ValueError('Fixed ref is not a current footprint')
    local_rects={};local_polygons={};current={};angles={};fp_nodes={}
    for f in children(board,'footprint'):
        ref=next(p[2] for p in children(f,'property') if len(p)>2 and p[1]=='Reference')
        fp_nodes[ref]=f
        at=child(f,'at',[])
        if len(at)<3:raise ValueError('Footprint has no position: '+ref)
        pos=(float(at[1]),float(at[2]));current[ref]=pos
        angles[ref]=float(at[3]) if len(at)>3 else 0
        polygon=info[ref]['courtyard']
        if not polygon:raise ValueError('No verified top-side Courtyard polygon for '+ref+'; native/manual geometry required')
        xs=[p[0] for p in polygon];ys=[p[1] for p in polygon]
        local_rects[ref]=[min(xs)-pos[0],min(ys)-pos[1],max(xs)-pos[0],max(ys)-pos[1]]
        local_polygons[ref]=[(x-pos[0],y-pos[1]) for x,y in polygon]
    keepouts=footprint_keepouts(board)
    holes=npth_holes(board,fixed_refs)
    hard_constraints=policy_data.get('constraints',[])
    if not isinstance(hard_constraints,list):raise ValueError('Invalid hard layout constraint inventory')
    critical=policy_data.get('critical_subcircuits',[])
    if not isinstance(critical,list):raise ValueError('Invalid critical subcircuit inventory')
    by_id={c.get('id'):c for c in hard_constraints}
    for sub in critical:
        if sub.get('type')=='decoupling' and not any(by_id.get(cid,{}).get('kind')=='decoupling' for cid in sub.get('check_ids',[])):
            raise ValueError('Critical decoupling subcircuit lacks explicit pin-level layout constraint: '+str(sub.get('id')))
    corridors=_plan_constraint_geometry(hard_constraints,current,angles,fixed_refs,board)
    return_vias=_return_vias(board)
    def shape(ref,pos):return shift_poly(local_polygons[ref],pos[0],pos[1])
    def accepts(ref,pos,occupied,region):
        polygon=shape(ref,pos)
        if not poly_fits(polygon,region) or not poly_fits(polygon,outline):return False
        if any(poly_intersects(polygon,shape(other,point),clearance) for other,point in occupied.items() if other!=ref):return False
        if any(poly_intersects(polygon,k['polygon'],0) for k in keepouts):return False
        if hits_holes(polygon,holes,clearance,own_ref=ref):return False
        if any(poly_intersects(polygon,[(b[0],b[1]),(b[2],b[1]),(b[2],b[3]),(b[0],b[3])],0)
               for b,allowed in corridors if ref not in allowed):return False
        return _critical_constraint_ok(hard_constraints,{**occupied,ref:pos},fp_nodes,return_vias,native_pad_offsets)
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
            # Fixed geometry is never moved. It must not violate mandatory
            # Courtyard/keepout/hole/corridor or pin-level hard constraints.
            if not accepts(ref,p,selected,region):
                raise ValueError('Fixed footprint intersects a protected region or violates declared hard rule: '+ref)
            selected[ref]=p
        ordered=sorted((r for r in refs if r not in fixed),key=lambda r:(0 if r==m['anchor'] else priorities.get(roles[r],3),-len(neighbors[r]),r))
        for ref in ordered:
            peers=[selected[r] for r in neighbors[ref] if r in selected]
            # Preserve a currently legal position before moving a passive for
            # visual reasons. For connected parts prefer already-placed peers.
            focus=(sum(p[0] for p in peers)/len(peers),sum(p[1] for p in peers)) if peers else current[ref]
            chosen=None
            for p in itertools.chain((current[ref],),_candidates(focus,region,grid,limit)):
                if not accepts(ref,p,selected,region):continue
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
                    if not accepts(ref,p,{r:selected[r] for r in selected if r not in movable},region):return None
                    for other in neighbors[ref]:
                        if other not in movable:
                            q=selected[other];score+=abs(p[0]-q[0])+abs(p[1]-q[1])
                hypothetical={**selected,**{ref:(selected[ref][0]+shift_x,selected[ref][1]+shift_y) for ref in refs}}
                if not _critical_constraint_ok(hard_constraints,hypothetical,fp_nodes,return_vias,native_pad_offsets):return None
                return score
            options=[]
            for dx in (-grid,0,grid):
                for dy in (-grid,0,grid):
                    c=cost(dx,dy)
                    if c is not None:options.append((round(c,6),abs(dx)+abs(dy),dx,dy))
            if options:
                _,_,dx,dy=min(options)
                for ref in refs:selected[ref]=(round(selected[ref][0]+dx,6),round(selected[ref][1]+dy,6))
    if not _critical_constraint_ok(hard_constraints,selected,fp_nodes,return_vias,native_pad_offsets):
        return {'schema_version':1,'status':'REPLAN_REQUIRED',
                'reason':'Final pin-specific hard electrical placement constraints are not met; no KiCad write allowed',
                'executed':False,'production_authorized':False}
    for ref,point in selected.items():
        assigned_module=next(m for m in modules if ref in m['refs'])
        if not accepts(ref,point,{r:p for r,p in selected.items() if r!=ref},_rect(assigned_module['bounds_mm'])):
            return {'schema_version':1,'status':'REPLAN_REQUIRED','reason':'Final Courtyard/keepout/mechanical constraints are not met: '+ref,
                    'executed':False,'production_authorized':False}
    return {'schema_version':1,'status':'BOUNDED_MODULAR_PLACEMENT_PROPOSAL','geometry_precheck':'NATIVE_COURTYARD_POLYGONS_AND_FOOTPRINT_KEEPOUTS',
            'hard_constraint_precheck':'SOURCE_BOUND_PIN_ENDPOINTS_WHERE_SUPPORTED',
            'critical_subcircuits_pending_full_G3':[sub.get('id') for sub in critical if sub.get('type')!='decoupling'],

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
