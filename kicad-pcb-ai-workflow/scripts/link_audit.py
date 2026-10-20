#!/usr/bin/env python3
"""Conservative endpoint-path audit. Missing/ambiguous geometry blocks.

Tracks, circular arcs and vias are distinct. Straight/arc branches and cycles
are not silently summed. Centerline topology is deliberately conservative;
DRC/native connectivity and reference-plane/SI review remain required.
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from npi_common import parse_sexpr,children,child,value,xy,distance,load_board,sha256

def arc_length(a,m,b):
    ax,ay=a;mx,my=m;bx,by=b
    d=2*(ax*(my-by)+mx*(by-ay)+bx*(ay-my))
    if abs(d)<1e-12: raise ValueError('Degenerate arc')
    u=((ax*ax+ay*ay)*(my-by)+(mx*mx+my*my)*(by-ay)+(bx*bx+by*by)*(ay-my))/d
    v=((ax*ax+ay*ay)*(bx-mx)+(mx*mx+my*my)*(ax-bx)+(bx*bx+by*by)*(mx-ax))/d
    aa,mm,bb=[math.atan2(y-v,x-u)%(2*math.pi) for x,y in (a,m,b)]
    ccw=(bb-aa)%(2*math.pi)
    sweep=ccw if (mm-aa)%(2*math.pi)<=ccw+1e-10 else 2*math.pi-ccw
    return math.hypot(ax-u,ay-v)*sweep

def primitives(path, native=True):
    board=load_board(path,require_native=native)
    tree=parse_sexpr(Path(path).read_text(encoding='utf-8-sig'))
    nets={int(n[1]):n[2] for n in children(tree,'net')}
    edges=[]
    for kind in ('segment','arc'):
        for i,t in enumerate(children(tree,kind)):
            a,b=xy(t,'start'),xy(t,'end');layer=value(t,'layer')
            length=arc_length(a,xy(t,'mid'),b) if kind=='arc' else distance(a,b)
            if length<=0:raise ValueError('Zero length copper primitive')
            edges.append({'id':value(t,'uuid',kind+str(i)),'kind':kind,'net':nets.get(int(value(t,'net',0)),''),
                          'a':(*a,layer),'b':(*b,layer),'length_mm':length,'layer':layer})
    for i,v in enumerate(children(tree,'via')):
        layers=child(v,'layers',[])[1:];pos=xy(v)
        if len(layers)!=2:raise ValueError('Via start/end layers absent')
        edges.append({'id':value(v,'uuid','via'+str(i)),'kind':'via','net':nets.get(int(value(v,'net',0)),''),
                      'a':(*pos,layers[0]),'b':(*pos,layers[1]),'length_mm':None,'layer':None})
    return board,edges

def key(point):return (round(point[0],6),round(point[1],6),point[2])

def resolve_endpoint(board,entry,net):
    matches=[p for f in board['footprints'] if f['ref']==entry['ref'] for p in f['pads'] if p['number']==str(entry['pad'])]
    if len(matches)!=1 or matches[0]['net']!=net:raise ValueError('Endpoint missing/ambiguous or wrong net: '+str(entry))
    return key((*matches[0]['pos'],entry['layer']))

def audit_path(board,edges,spec):
    if not all(spec.get(k) for k in ('id','net','start','end','source','allowed_layers','reference_planes')):
        raise ValueError('Missing endpoint/profile/source/reference specification')
    if not isinstance(spec['source'],dict) or not all(spec['source'].get(k) for k in ('document','revision','section')):raise ValueError('Incomplete source version/section')
    for limit in ('max_length_mm','max_delay_ps','max_vias'):
        n=spec.get(limit)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<0:raise ValueError('Invalid limit '+limit)
    net_edges=[e for e in edges if e['net']==spec['net']]
    if not net_edges:raise ValueError('Requested net has no tracks/arcs/vias: '+spec['net'])
    adjacency=defaultdict(list);seen=set()
    for e in net_edges:
        a,b=key(e['a']),key(e['b']);signature=(e['kind'],tuple(sorted((a,b))),round(e['length_mm'] or 0,8))
        if signature in seen:raise ValueError('Duplicate copper primitive')
        seen.add(signature);adjacency[a].append((b,e));adjacency[b].append((a,e))
    start=resolve_endpoint(board,spec['start'],spec['net']);end=resolve_endpoint(board,spec['end'],spec['net'])
    if start==end or start not in adjacency or end not in adjacency:raise ValueError('Endpoint not connected to supported centerline geometry')
    # A branch or loop requires a richer, explicitly modeled electrical topology.
    if any(len(v)>2 for v in adjacency.values()):raise ValueError('Branch topology requires separate stub/path model')
    route=[];visited={start};current=start
    while current!=end:
        candidates=[(p,e) for p,e in adjacency[current] if p not in visited]
        if len(candidates)!=1:raise ValueError('Missing/ambiguous path or cycle')
        following,e=candidates[0];route.append(e);visited.add(following);current=following
    if len(route)!=len(net_edges):raise ValueError('Disconnected copper, unused branch or cycle on requested net')
    length=0;delay=0;transitions=[]
    for e in route:
        if e['kind']=='via':
            z=spec.get('layer_z_mm',{});a,b=e['a'][2],e['b'][2]
            if a not in spec['allowed_layers'] or b not in spec['allowed_layers']:raise ValueError('Unauthorized via span')
            if a not in z or b not in z or not spec.get('via_delay_ps_per_mm'):raise ValueError('Missing actual via span/propagation model')
            if not all(isinstance(n,(int,float)) and math.isfinite(n) for n in (z[a],z[b],spec['via_delay_ps_per_mm'])) or spec['via_delay_ps_per_mm']<=0:raise ValueError('Invalid via delay model')
            l=abs(z[a]-z[b]);delay+=l*spec['via_delay_ps_per_mm'];length+=l
            transitions.append({'position_mm':e['a'][:2],'layers':sorted([a,b]),'id':e['id']})
        else:
            if e['layer'] not in spec['allowed_layers']:raise ValueError('Unauthorized routing layer: '+e['layer'])
            factor=spec.get('delay_ps_per_mm',{}).get(e['layer'])
            if not isinstance(factor,(int,float)) or not math.isfinite(factor) or factor<=0:raise ValueError('Missing per-layer delay model')
            length+=e['length_mm'];delay+=e['length_mm']*factor
    failures=[]
    for name,actual in [('max_length_mm',length),('max_delay_ps',delay),('max_vias',len(transitions))]:
        if name not in spec:raise ValueError('Missing explicit limit: '+name)
        if actual>spec[name]:failures.append(name)
    return {'id':spec['id'],'status':'FAIL' if failures else 'PASS','length_mm':length,'delay_ps':delay,
            'failures':failures,'transitions':transitions,'primitives':[{'id':e['id'],'kind':e['kind']} for e in route],
            'scope':'Geometric centerline/delay model only; impedance, coupling and actual return continuity are not proven.'}

def audit(board,edges,profile):
    paths=[];results={}
    specs=profile.get('paths',[])
    if not specs:return {'status':'BLOCKED','reason':'No applicable path declarations; use explicit non-applicability evidence instead of an empty PASS','paths':[]}
    if len({s['id'] for s in specs})!=len(specs):raise ValueError('Duplicate path id')
    for spec in specs:
        try: result=audit_path(board,edges,spec)
        except (ValueError,KeyError,TypeError) as e:result={'id':spec.get('id'),'status':'BLOCKED','reason':str(e)}
        paths.append(result);results[result['id']]=result
    pairs=[]
    for pair in profile.get('pairs',[]):
        a,b=results.get(pair['positive_path']),results.get(pair['negative_path'])
        if not a or not b or a['status']!='PASS' or b['status']!='PASS':
            pairs.append({'id':pair['id'],'status':'BLOCKED','reason':'Pair path incomplete'});continue
        for field in ('max_skew_ps','max_transition_offset_mm'):
            n=pair.get(field)
            if not isinstance(n,(int,float)) or not math.isfinite(n) or n<0:raise ValueError('Missing/invalid pair limit '+field)
        skew=abs(a['delay_ps']-b['delay_ps']);fails=[]
        if skew>pair['max_skew_ps']:fails.append('skew_ps')
        ta,tb=a['transitions'],b['transitions']
        if len(ta)!=len(tb):fails.append('transition_count')
        else:
            for x,y in zip(ta,tb):
                if x['layers']!=y['layers'] or distance(x['position_mm'],y['position_mm'])>pair['max_transition_offset_mm']:
                    fails.append('transition_span_or_position')
        pairs.append({'id':pair['id'],'status':'FAIL' if fails else 'PASS','skew_ps':skew,'failures':fails})
    statuses=[x['status'] for x in paths+pairs]
    return {'status':'BLOCKED' if 'BLOCKED' in statuses else 'FAIL' if 'FAIL' in statuses else 'PASS','paths':paths,'pairs':pairs}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('board');p.add_argument('--profile',type=Path,required=True);p.add_argument('--static-preview',action='store_true')
    a=p.parse_args()
    try:
        board,edges=primitives(a.board,not a.static_preview);result=audit(board,edges,json.loads(a.profile.read_text()))
        result['board_sha256']=sha256(a.board);result['static_preview']=a.static_preview
        if a.static_preview:result['production_authorized']=False
    except (OSError,ValueError,KeyError,TypeError,ImportError) as e:result={'status':'BLOCKED','reason':str(e)}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return {'PASS':0,'FAIL':1,'BLOCKED':2}[result['status']]

if __name__=='__main__':raise SystemExit(main())
