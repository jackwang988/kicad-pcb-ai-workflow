#!/usr/bin/env python3
"""Read-only topology-first schematic pre-placement, label-space and trial-route gate.

No KiCad modifications. An accepted plan is conditional on independently
supplied, source-bound geometry. It is not proof of rendered font precision,
manufacturer electrical correctness, or live Konnect execution.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

from schematic_geometry import bounded, evidence, sha, intersects, rect
from schematic_space_map import point, placements, reject_collision
from schematic_wire_planner import route, clear_segment


def load_bound(root, name, digest):
    p=bounded(root,name)
    if not isinstance(digest,str) or sha(p)!=digest:
        raise ValueError('Missing or changed source evidence: '+str(name))
    return json.loads(p.read_text(encoding='utf-8-sig'))


def number(v,lo,hi,name):
    if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or not lo<=v<=hi:
        raise ValueError(name+' must be a finite number in '+str((lo,hi)))
    return float(v)


def validate_topology(root,plan):
    topo=load_bound(root,plan.get('topology_file'),plan.get('topology_sha256'))
    if topo.get('schema_version')!=1 or not isinstance(topo.get('pins'),list) or not topo['pins']:
        raise ValueError('Independent expected pin-to-net design contract required')
    basis=topo.get('source',{})
    if not basis.get('locator') or not basis.get('file') or not basis.get('sha256'):
        raise ValueError('Expected topology needs independently authored design basis')
    if sha(bounded(root,basis['file']))!=basis['sha256']:
        raise ValueError('Original design basis changed')
    terms={}
    for item in topo['pins']:
        key=(item.get('ref'),str(item.get('pin')))
        if not all(key) or key in terms or not isinstance(item.get('net'),str) or not item['net']:
            raise ValueError('Missing or duplicate expected pin/net')
        terms[key]=item['net']
    return terms


def proposed_candidates(symbol,grid,dims,limit):
    candidates=[]
    rotations=symbol.get('rotations_deg',[0,90,180,270])
    if not isinstance(rotations,list) or not rotations or len(set(rotations))!=len(rotations) or any(r not in (0,90,180,270) for r in rotations):
        raise ValueError('Only unique orthogonal rotations supported')
    if symbol.get('candidate_positions_mm') is not None:
        anchors=symbol['candidate_positions_mm']
        if not isinstance(anchors,list) or not anchors or len(anchors)>limit:
            raise ValueError('Explicit anchor list must be nonempty and bounded')
        anchors=[point(p) for p in anchors]
        for at in anchors:
            if any(abs(round(x/grid)*grid-x)>1e-5 for x in at):
                raise ValueError('Requested anchor is off the declared KiCad schematic grid')
    else:
        zone=rect(symbol.get('zone_mm'))
        if not(0<=zone[0]<zone[2]<=dims[0] and 0<=zone[1]<zone[3]<=dims[1]):
            raise ValueError('Placement zone must be inside the current page')
        # Grid coordinates are KiCad schematic millimeters, not display pixels.
        x0=math.ceil(zone[0]/grid);x1=math.floor(zone[2]/grid)
        y0=math.ceil(zone[1]/grid);y1=math.floor(zone[3]/grid)
        anchors=itertools.product((round(i*grid,6) for i in range(x0,x1+1)),
                                  (round(i*grid,6) for i in range(y0,y1+1)))
    for a in anchors:
        for rot in rotations:
            candidates.append((a,rot))
            if len(candidates)>=limit:return candidates
    return candidates


def inspect_candidate(candidate, obstacles, clearance, dimensions, escape_width):
    objects=candidate['objects']
    # Symbol body and its own fields must not overlap; they are not paint-only estimates.
    for i,(name,b) in enumerate(objects):
        if reject_collision(b,obstacles,clearance,dimensions):return 'OCCUPIED_OR_KEEP_OUT'
        for _,other in objects[:i]:
            if intersects(b,other):return 'OWN_FIELD_COLLISION'
    for _,box,info in candidate['labels']:
        if reject_collision(box,obstacles,clearance,dimensions) or any(intersects(box,x,clearance) for _,x in objects):
            return 'LABEL_SPACE_BLOCKED'
    for i,(_,a,_) in enumerate(candidate['labels']):
        if any(intersects(a,b,clearance) for _,b,_ in candidate['labels'][:i]):
            return 'LABEL_OVERLAP'
    for pin,box in candidate['escapes'].items():
        if reject_collision(box,obstacles,0,dimensions):return 'PIN_ESCAPE_BLOCKED'
        # Outside the body, source pin escape must not intersect its own fields.
        if any(intersects(box,b) for name,b in objects if name!='body'):
            return 'PIN_ESCAPE_FIELD_COLLISION'
    return None


def layout(root, plan):
    """Return a bounded, explainable plan; no native EDA write is possible here."""
    if not isinstance(plan,dict) or plan.get('schema_version')!=1:
        raise ValueError('Expected pre-placement request schema_version=1')
    ev=evidence(root,plan)
    topo=validate_topology(root,plan)
    pg=ev['page'];dims=pg['dims']
    grid=number(plan.get('grid_mm'),0.5,10,'grid_mm')
    clearance=number(plan.get('clearance_mm'),0,20,'clearance_mm')
    pin_escape=number(plan.get('pin_escape_mm'),1,25,'pin_escape_mm')
    width=number(plan.get('wire_corridor_width_mm'),0.1,10,'wire_corridor_width_mm')
    limit=int(number(plan.get('max_candidate_positions',120),1,2000,'max_candidate_positions'))
    budget=int(number(plan.get('search_budget',1000),1,10000,'search_budget'))
    max_occupancy=number(plan.get('max_occupancy',0.75),0.2,0.9,'max_occupancy')
    max_wire_length=number(plan.get('max_trial_wire_length_mm',dims[0]+dims[1]),1,dims[0]+dims[1],'max_trial_wire_length_mm')
    max_bends=int(number(plan.get('max_trial_wire_bends',6),0,30,'max_trial_wire_bends'))
    syms=plan.get('symbols')
    if not isinstance(syms,list) or not syms or len(syms)>30:
        raise ValueError('Pre-placement batch requires 1..30 explicit symbols; split larger designs into modules')
    refs=[s.get('ref') if isinstance(s,dict) else None for s in syms]
    if len(set(refs))!=len(refs) or any(not isinstance(x,str) or not x for x in refs):
        raise ValueError('Unique component reference designators required')
    if any(s.get('ref') in pg['existing_uuids'] for s in syms):
        raise ValueError('Use incremental move contract, not new placement, for existing UUID')
    # Every candidate's exact pins must match independently authored expected net membership.
    all_new=set();labels_by_pin=set()
    for s in syms:
        g=s.get('geometry')
        if not isinstance(g,dict):raise ValueError('Every symbol needs real bounding and pin geometry')
        src=g.get('source',{})
        if not src.get('file') or not src.get('sha256') or not src.get('locator') or sha(bounded(root,src['file']))!=src['sha256']:
            raise ValueError('Symbol geometry must be bound to measured library/source evidence')
        rect(g.get('body_bbox_mm'))
        pins=g.get('pins')
        if not isinstance(pins,list) or not pins:raise ValueError('Symbol pin list required')
        for p in pins:
            key=(s['ref'],str(p['number']))
            if key not in topo or p.get('net')!=topo[key] or key in all_new:
                raise ValueError('Symbol pin/net differs from independent expected topology: '+str(key))
            all_new.add(key)
        for l in g.get('labels',[]):
            key=(s['ref'],str(l['pin']))
            if key in labels_by_pin:raise ValueError('Duplicate label target')
            if l.get('text')!=topo.get(key) and l.get('kind')!='power':
                raise ValueError('Label text must match actual named net; do not silently alias')
            if l.get('kind')=='power' and l.get('net')!=topo.get(key):
                raise ValueError('Power label must match current power net')
            labels_by_pin.add(key)
    if all_new != {k for k in topo if k[0] in set(refs)}:
        raise ValueError('Expected design contains missing or extraneous pins for new symbols')
    fixed={}
    for p in plan.get('fixed_ports',[]):
        ident=p.get('id')
        if not ident or ident in fixed or p.get('source_uuid') not in pg['existing_uuids']:
            raise ValueError('Fixed endpoint requires a current native object UUID')
        fixed[ident]={'at':point(p.get('at_mm')),'net':p.get('net'),'source_uuid':p['source_uuid']}
        if not isinstance(p.get('net'),str) or not p['net']:raise ValueError('Fixed endpoint net missing')
    linked=set();routes=plan.get('connections',[])
    if not isinstance(routes,list):raise ValueError('Connections must be a list')
    for r in routes:
        if not isinstance(r,dict) or not isinstance(r.get('net'),str):raise ValueError('Malformed explicit connection')
        for key in ('from','to'):
            node=r.get(key)
            if not isinstance(node,list) or len(node)!=2 or not all(isinstance(x,str) for x in node):
                raise ValueError('Connection endpoint must be [ref,pin] or ["@fixed",id]')
            t=tuple(node)
            net=topo.get(t) if t[0]!='@fixed' else fixed.get(t[1],{}).get('net')
            if not net or net != r['net'] or (t[0]!='@fixed' and t not in all_new):
                raise ValueError('Route endpoints do not match independent topology')
            if t[0]!='@fixed':linked.add(t)
    dangling=[x for x in all_new if topo[x]!='NC' and x not in linked and x not in labels_by_pin]
    if dangling:raise ValueError('No connection or label reservation for required pins: '+repr(dangling[:8]))
    rails=plan.get('power_rails',[])
    if not rails and any(x=='GND' for x in topo.values()):
        raise ValueError('GND requires explicit native power-symbol policy')
    if not isinstance(rails,list) or len(set(rails))!=len(rails) or any(not isinstance(x,str) or not x for x in rails):
        raise ValueError('Power rail names must be explicit and unique')
    for sym in syms:
        for label in sym['geometry'].get('labels',[]):
            if label['kind']=='power' and label['net'] not in rails:
                raise ValueError('Power-symbol reservation net must be in explicitly approved rails')
            if label['net'] in rails and label['kind']!='power':
                raise ValueError('Supply/GND rail requires a native power-symbol reservation, not a local label')
    obstacles=list(pg['obstacles'])
    # Source geometry symbols have fields and pin exit clearances; put constrained
    # symbols first. Search is bounded, deterministic and intentionally conservative.
    ordered=sorted(syms,key=lambda s:(len(proposed_candidates(s,grid,dims,limit)),
                                 -(rect(s['geometry']['body_bbox_mm'])[2]-rect(s['geometry']['body_bbox_mm'])[0])*(rect(s['geometry']['body_bbox_mm'])[3]-rect(s['geometry']['body_bbox_mm'])[1]),s['ref']))
    if not isinstance(ordered,list):raise ValueError('Invalid order')
    attempts=0;selected={};rejections={};selected_boxes={}
    # Tier 1: hard electrical/geometry constraints. Tier 2: advisory route and
    # layout quality. Search within bounded limits; never mislabel a heuristic
    # timeout as an electrically impossible design.
    best=None
    solutions=0
    max_solutions=int(number(plan.get('max_scored_solutions',12),1,100,'max_scored_solutions'))
    def evaluate():
        nonlocal best,solutions
        solutions+=1
        try:
            routes_result=check_routes(selected,obstacles,connections=routes,fixed=fixed,grid=grid,width=width,dims=dims,pin_escape=pin_escape,
                                       max_wire_length=max_wire_length,max_bends=max_bends)
        except ValueError as exc:
            # Routing-grid/resource limits are an inconclusive planning result.
            routes_result=None
            route_note='trial_route_resource_limit: '+str(exc)[:180]
        else:
            route_note='trial_route_failed_or_soft_limit' if routes_result is None else None
        rotations_cost=0
        for s in ordered:
            r=selected[s['ref']]['rotation']
            # Application-specific preferences win. For ordinary parts, evaluate
            # all legal orientations instead of assuming every symbol stays at 0.
            prefs=s.get('preferred_rotations_deg')
            if prefs is None:
                role=s.get('role','')
                prefs=([90,270,0,180] if role in ('decoupling','pullup','pulldown','vertical_branch')
                       else [0,180,90,270])
            if (not isinstance(prefs,list) or set(prefs)-{0,90,180,270}
                    or not prefs or len(prefs)!=len(set(prefs))):
                raise ValueError('Invalid preferred_rotations_deg for '+s['ref'])
            rotations_cost+=prefs.index(r) if r in prefs else 4
        wire_len=sum(r['estimated_length_mm'] for r in routes_result) if routes_result else 0
        bends=sum(r['bends'] for r in routes_result) if routes_result else 0
        coords=[c['origin'] for c in selected.values()]
        spread=(max(x for x,y in coords)-min(x for x,y in coords) + max(y for x,y in coords)-min(y for x,y in coords)) if len(coords)>1 else 0
        # Lower score is better, but a valid trial route outranks layout elegance.
        score=(0 if routes_result is not None else 1, round(wire_len+4*bends+2*rotations_cost+0.05*spread,5))
        if best is None or score<best['score']:
            best={'score':score,'selected':dict(selected),'routes':routes_result,'route_note':route_note}
    def build(index,filled):
        nonlocal attempts
        if attempts>=budget or solutions>=max_solutions:return
        if index==len(ordered):
            evaluate();return
        s=ordered[index]
        for at,angle in proposed_candidates(s,grid,dims,limit):
            if attempts>=budget or solutions>=max_solutions:break
            attempts+=1
            try:
                c=placements(s,at,angle,pin_escape,width)
                reason=inspect_candidate(c,filled,clearance,dims,width)
            except (TypeError,ValueError,KeyError) as exc:
                raise ValueError('Invalid symbol geometry for '+s['ref']+': '+str(exc)) from exc
            if reason:
                rejections[reason]=rejections.get(reason,0)+1
                continue
            added=[(s['ref']+':'+k,v) for k,v in c['objects']]
            added += [(s['ref']+':label:'+num,b) for num,b,_ in c['labels']]
            added += [(s['ref']+':escape:'+num,b) for num,b in c['escapes'].items()]
            selected[s['ref']]=c
            build(index+1,filled+added)
            del selected[s['ref']]
    build(0,obstacles)
    if best is None:
        return {'schema_version':1,'status':('REPLAN_REQUIRED' if attempts>=budget else 'BLOCKED'),
                'reason':'No geometry-feasible candidate found in the bounded search; this does not prove the page is full',
                'attempted':attempts,'search_budget':budget,'rejections':rejections,
                'scope':'current declared geometry only','production_authorized':False,'executed':False}
    selected=best['selected'];routes_result=best['routes']
    protected_area=sum((b[2]-b[0])*(b[3]-b[1]) for uid,b in pg['obstacles'] if uid.startswith('protected:'))
    free_area=dims[0]*dims[1]-protected_area
    def union_area(rectangles):
        # Do not count overlapping labels/escape reservations more than once.
        edges=sorted({v for b in rectangles for v in (b[0],b[2])})
        total=0.0
        for left,right in zip(edges,edges[1:]):
            intervals=sorted((b[1],b[3]) for b in rectangles if b[0]<right-1e-7 and b[2]>left+1e-7)
            if not intervals:continue
            low,high=intervals[0];height=0.0
            for y0,y1 in intervals[1:]:
                if y0<=high:high=max(high,y1)
                else:height+=high-low;low,high=y0,y1
            height+=high-low;total+=(right-left)*height
        return total
    all_boxes=[b for uid,b in pg['obstacles'] if not uid.startswith('protected:')]
    for c in selected.values():
        all_boxes.extend(b for name,b in c['objects'])
        all_boxes.extend(b for _,b,_ in c['labels'])
        all_boxes.extend(c['escapes'].values())
    occupied=union_area(all_boxes)
    occupancy=occupied/free_area if free_area>0 else float('inf')
    for ref,c in selected.items():
        selected_boxes[ref]={'position_mm':list(c['origin']),'rotation_deg':c['rotation'],
                             'object_bbox_mm':{name:list(box) for name,box in c['objects']},
                             'reserved_labels':[{'pin':n,'bbox_mm':list(box),'kind':d['kind']} for n,box,d in c['labels']],
                             'pin_escape_mm':{n:list(box) for n,box in c['escapes'].items()}}
    warnings=[]
    if occupancy>max_occupancy:warnings.append('DENSITY_ADVISORY: page occupancy exceeds soft target; check readability or repartition')
    if routes_result is None:warnings.append('TRIAL_ROUTE_INCONCLUSIVE: geometry is clear, but electrical wiring must be independently completed and verified')
    if attempts>=budget:warnings.append('SEARCH_BUDGET_REACHED: better candidate may exist; selected layout is not proven optimal')
    status=('PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY' if routes_result is not None
            else 'PREPLACEMENT_GEOMETRY_READY_ROUTE_REVIEW_REQUIRED')
    return {'schema_version':1,'status':status,
            'page':plan['page'],'schematic':plan['schematic'],'schematic_sha256':plan['schematic_sha256'],
            'geometry_sha256':plan['geometry_sha256'],'topology_sha256':plan['topology_sha256'],
            'bindings':{**ev['files_sha256'],**ev['all_sheet_sha256'],plan['topology_file']:plan['topology_sha256']},
            'placements':selected_boxes,'trial_routes':routes_result,'attempted':attempts,
            'scored_solutions':solutions,'selection_score':list(best['score']),
            'estimated_occupancy':round(occupancy,4),'threshold':max_occupancy,'warnings':warnings,
            'route_note':best['route_note'],
            'scope':'hard geometry checked; route/density are soft and require post-write verification',
            'limitations':['Geometry and current worksheet/text bounds are supplied and source-bound, not extracted or authenticated by this planner.',
                           'Trial routes are not actual KiCad wires; label anchors and native wire connectivity require readback.',
                           'Existing pins and net identity require independent native-netlist comparison after execution.',
                           'Konnect direct calls outside this wrapper cannot be prevented by this standalone script.'],
            'production_authorized':False,'executed':False}

def check_routes(selected, existing, connections, fixed, grid, width, dims, pin_escape, max_wire_length, max_bends):
    obstacles=list(existing)
    escape_areas=[]
    for ref,c in selected.items():
        obstacles += [(ref+':'+k,box) for k,box in c['objects']]
        obstacles += [(ref+':label:'+n,box) for n,box,_ in c['labels']]
        escape_areas += [(ref+':escape:'+n,box) for n,box in c['escapes'].items()]
    # Verify pin escape segments before testing route paths. Source pin attachment
    # itself is exempt from collision with its own symbol body only.
    for ref,c in selected.items():
        for num,point_info in c['pins'].items():
            if point_info['net'] in (None,'NC'):continue
            blockers=[(id,b) for id,b in obstacles if not id.startswith(ref+':body') and not id.startswith(ref+':label:'+num)]
            if not clear_segment(point_info['at'],point_info['end'],blockers,width,dims):return None
    result=[];wires=[]
    for r in connections:
        def endpoint(node):
            if node[0]=='@fixed':return fixed[node[1]]['at']
            return selected[node[0]]['pins'][node[1]]['end']
        start=endpoint(r['from']);end=endpoint(r['to'])
        ends={n[0]+':escape:'+n[1] for n in (r['from'],r['to']) if n[0]!='@fixed'}
        forbidden=[(uid,box) for uid,box in escape_areas if uid not in ends]
        path=route(start,end,obstacles+forbidden+wires,grid,width,dims)
        if path is None:return None
        length=sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(path,path[1:]))
        bends=max(0,len(path)-2)
        if length>max_wire_length+1e-6 or bends>max_bends:return None
        result.append({'net':r['net'],'from':r['from'],'to':r['to'],'path_mm':[list(v) for v in path],
                       'estimated_length_mm':round(length,3),'bends':bends})
        # Different nets and unrelated same-net paths may not accidentally cross
        # in this conservative v1 preflight, unless a deliberate junction is modeled.
        for a,b in zip(path,path[1:]):
            from schematic_space_map import corridor
            wires.append(('planned_wire:'+r['net'],corridor(a,b,width/2)))
    return result


def run_cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project',help='Existing project root; read-only')
    p.add_argument('--request',required=True,help='Project-relative JSON pre-placement request')
    p.add_argument('--output',help='NEW immutable JSON receipt; inside 03_REPORTS or outside project')
    args=p.parse_args()
    root=Path(args.project).resolve()
    try:
        if not root.is_dir():raise ValueError('Existing project root required')
        req=bounded(root,args.request)
        plan=json.loads(req.read_text(encoding='utf-8-sig'))
        result=layout(root,plan)
        result['request_sha256']=sha(req)
        result['production_authorized']=False
        if args.output:
            target=Path(args.output).resolve()
            allowed=not target.is_relative_to(root) or target.is_relative_to(root/'03_REPORTS')
            if target.exists() or not target.parent.is_dir() or not allowed:
                raise ValueError('Receipt must be a NEW file inside 03_REPORTS or outside the project')
            with target.open('x',encoding='utf-8') as fh:json.dump(result,fh,ensure_ascii=False,indent=2)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status'].startswith('PREPLACEMENT_') else 2
    except (ValueError,KeyError,TypeError,OSError,OverflowError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'executed':False,'production_authorized':False}))
        return 2


if __name__=='__main__':
    raise SystemExit(run_cli())
