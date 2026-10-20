#!/usr/bin/env python3
"""Read-only modular placement, pin-level proximity and visual preference review.

Never moves parts. Supported geometry checks are distinct from grounded manual
pre-route/final review. All results remain non-authorizing for production.
"""
import argparse
import datetime as dt
import html
import json
import math
from pathlib import Path
from npi_common import sha256,finite_tree,parse_sexpr,children,child,value,xy,transform,distance,environment
from design_intent import local,digest
from link_audit import primitives
from netlist_guard import read_netlist

ROLES={'controller','decoupling','clock','power','connector','protection','termination','filter','feedback','rf','analog','passive','test','mechanical','reserve','other'}
TYPES={'decoupling','power_loop','crystal','termination','protection','filter','feedback','rf','reserve','other'}
BEAUTY={'alignment','uniform_spacing','orientation'}
KINDS=BEAUTY|{'fixed','pad_proximity','decoupling','corridor'}
TOPICS={'routability','return_paths','source_layouts','mechanical'}

def read(p):return finite_tree(json.loads(Path(p).read_text()))
def text(row,*keys):
    if any(not isinstance(row.get(k),str) or not row[k].strip() for k in keys):raise ValueError('Missing nonempty fields '+','.join(keys))
def num(n):
    if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<0:raise ValueError('Explicit nonnegative finite limit required')
    return n

def rect(values):
    if not isinstance(values,list) or len(values)!=4 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in values) or values[0]>=values[2] or values[1]>=values[3]:raise ValueError('Explicit ordered rectangular bounds required')
    return values

def metadata(board_file,board=None):
    tree=parse_sexpr(Path(board_file).read_text());result={}
    for fp in children(tree,'footprint'):
        props={x[1]:x[2] for x in children(fp,'property') if len(x)>2}
        for t in children(fp,'fp_text'):
            if t[1]=='reference':props.setdefault('Reference',t[2])
        ref=props.get('Reference');at=child(fp,'at',[]);angle=float(at[3]) if len(at)>3 else 0
        if not ref or ref in result:raise ValueError('Missing/duplicate board reference')
        edges=[];unsupported=False
        for node in fp:
            if not isinstance(node,list) or not value(node,'layer').endswith('.CrtYd'):continue
            if node[0]=='fp_line':edges.append((xy(node,'start'),xy(node,'end')))
            elif node[0]=='fp_rect':
                a,b=xy(node,'start'),xy(node,'end');p=[a,(b[0],a[1]),b,(a[0],b[1])];edges+=list(zip(p,p[1:]+p[:1]))
            else:unsupported=True
        # Only one closed, straight top-side polygon; unsupported geometry needs explicit current-board review.
        polygon=[]
        if edges and not unsupported and value(fp,'layer')=='F.Cu':
            pending=edges[:];a,b=pending.pop(0);polygon=[a,b]
            while pending:
                matches=[(i,q if distance(polygon[-1],p)<1e-6 else p) for i,(p,q) in enumerate(pending) if min(distance(polygon[-1],p),distance(polygon[-1],q))<1e-6]
                if len(matches)!=1:break
                i,p=matches[0];pending.pop(i);polygon.append(p)
            if pending or len(polygon)<4 or distance(polygon[0],polygon[-1])>1e-6:polygon=[]
            else:
                rotate=angle;can_rotate=True
                if angle%360:
                    can_rotate=False
                    if board and board.get('engine')!='static_preview':
                        actual=next(f for f in board['footprints'] if f['ref']==ref)
                        native_pads={p['number']:p['pos'] for p in actual['pads']}
                        local_pads=[(str(p[1]),xy(p)) for p in children(fp,'pad')]
                        candidates=[a for a in (angle,-angle) if local_pads and all(n in native_pads and distance(transform(pos,xy(fp),a),native_pads[n])<1e-5 for n,pos in local_pads)]
                        if candidates and (len(candidates)==1 or all(distance(transform(p,xy(fp),candidates[0]),transform(p,xy(fp),candidates[-1]))<1e-6 for p in polygon)):
                            rotate=candidates[0];can_rotate=True
                polygon=[transform(p,xy(fp),rotate) for p in polygon[:-1]] if can_rotate else []
        result[ref]={'angle_deg':angle%360,'courtyard':polygon,'courtyard_mode':'straight_top_polygon' if polygon else 'manual_required'}
    return result

def placement_digest(board,meta):
    return digest({'footprints':board['footprints'],'placement_metadata':meta,'stackup':board.get('stackup')})

def audit(root,policy_file,graph,board,edges,board_file,phase='pre_route'):
    root=Path(root).resolve();policy_file=Path(policy_file).resolve();board_file=Path(board_file).resolve();findings=[];inputs={};checks=[];meta={};q={}
    def risk(code,desc,location='工程级',level='阻断级',fix='按实际原厂/结构/工艺依据修复或补齐当前版本评审；不得以美观覆盖电气约束。'):
        findings.append(dict(rule=code,level=level,location=location,description=desc,reference='具体器件原厂布局、项目结构/制造约束及布局评审契约',suggestion=fix))
    def evidence(ev):
        text(ev,'file','sha256');p=local(root,ev['file'])
        if not p.is_file() or not p.stat().st_size or sha256(p)!=ev['sha256']:raise ValueError('Missing/changed placement evidence '+ev['file'])
        inputs[str(p)]=ev['sha256']
    def source(s):text(s,'locator');evidence(s)
    try:
        if phase not in ('pre_route','final') or not policy_file.is_relative_to(root) or not board_file.is_relative_to(root):raise ValueError('Explicit phase and in-project policy/board required')
        inputs[str(policy_file)]=sha256(policy_file);inputs[str(board_file)]=sha256(board_file);q=read(policy_file)
        if q.get('schema_version')!=1:raise ValueError('Unknown placement schema')
        text(q,'scope_reason');meta=metadata(board_file,board)
        if q.get('demonstration_only'):risk('PLACE.DEMO','TEST布局资料禁止用于真实项目或生产确认')
        fs={f['ref']:f for f in board['footprints']}
        if len(fs)!=len(board['footprints']) or set(fs)!=set(meta):raise ValueError('Duplicate/inconsistent footprint inventory')
        missing=set(graph['components'])-set(fs);exclusions=q.get('schematic_only',[])
        if {e['ref'] for e in exclusions}!=missing or len(exclusions)!=len(missing):raise ValueError('Schematic component missing from PCB or exclusions inconsistent')
        for ex in exclusions:
            text(ex,'ref','reason')
            if not ex.get('evidence'):raise ValueError('Schematic-only exclusion requires actual evidence')
            for ev in ex['evidence']:evidence(ev)
        pinmap={}
        for net,nodes in graph['nets'].items():
            for ref,pin in nodes:pinmap[(ref,str(pin))]=net
        def endpoint(spec):
            text(spec,'net')
            if spec.get('kind','pad')=='via':
                candidates=[e for e in edges if e['kind']=='via' and e['id']==spec['uuid'] and e['net']==spec['net']]
                if len(candidates)!=1:raise ValueError('Missing/ambiguous return via or wrong net')
                return candidates[0]['a'][:2],set(candidates[0]['a'][2:]+candidates[0]['b'][2:])
            ref=spec['ref'];pad=str(spec['pad'])
            if pinmap.get((ref,pad))!=spec['net']:raise ValueError('Declared pad/net differs from actual schematic')
            if board.get('engine')=='static_preview' and (fs[ref]['layer']=='B.Cu' or meta[ref]['angle_deg']%360):raise ValueError('Bottom/rotated pad positions require native geometry')
            p=[p for p in fs[ref]['pads'] if p['number']==pad and p['net']==spec['net']]
            if len(p)!=1:raise ValueError('Missing/ambiguous actual pad/net')
            return p[0]['pos'],{fs[ref]['layer']}
        assigned=[];module_ids=[]
        modules=q.get('modules')
        if not isinstance(modules,list) or not modules:raise ValueError('Explicit complete module inventory required')
        for m in modules:
            text(m,'id','anchor');source(m['source']);module_ids.append(m['id']);refs=m['refs']
            if not refs or len(refs)!=len(set(refs)) or not set(refs).issubset(fs) or m['anchor'] not in refs:raise ValueError('Invalid module members/anchor')
            if set(m.get('roles',{}))!=set(refs) or not set(m['roles'].values()).issubset(ROLES):raise ValueError('Every module member requires explicit electrical/physical role')
            assigned+=refs;bounds=rect(m['bounds_mm'])
            for ref in refs:
                polygon=meta[ref]['courtyard']
                if polygon:
                    if not all(bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3] for x,y in polygon):risk('PLACE.MODULE.BOUNDS','真实支持的courtyard超出模块允许区域',ref)
                else:
                    manual=q.get('manual_geometry',{}).get(ref,{})
                    if manual.get('board_sha256')!=sha256(board_file) or not manual.get('reason') or not manual.get('evidence'):risk('PLACE.GEOMETRY','缺少/不支持courtyard（含底面/曲线），不能用器件中心冒充完整边界检查',ref)
                    for ev in manual.get('evidence',[]):evidence(ev)
                    checks.append({'ref':ref,'scope':'manual_geometry_evidence_only','reason':manual.get('reason')})
        if len(module_ids)!=len(set(module_ids)) or len(assigned)!=len(set(assigned)) or set(assigned)!=set(fs):raise ValueError('Every PCB component must belong to exactly one module')
        # Conservative same-side courtyard envelopes; candidates require native DRC/manual confirmation.
        for i,a in enumerate(board['footprints']):
            pa=meta[a['ref']]['courtyard']
            if not pa:continue
            for b in board['footprints'][i+1:]:
                pb=meta[b['ref']]['courtyard']
                if not pb or a['layer']!=b['layer']:continue
                overlap=[min(max(p[k] for p in pa),max(p[k] for p in pb))-max(min(p[k] for p in pa),min(p[k] for p in pb)) for k in (0,1)]
                if min(overlap)>1e-6:risk('PLACE.COURTYARD.CANDIDATE','同面courtyard包围框重叠候选 '+json.dumps({'overlap_mm':overlap})+'；非实体碰撞结论，需原生DRC/结构复核',a['ref']+'/'+b['ref'],'高风险')
        sub=q.get('critical_subcircuits',[]);subids=[s['id'] for s in sub]
        if len(subids)!=len(set(subids)):raise ValueError('Duplicate local subcircuit ID')
        critical_roles={'decoupling','clock','power','termination','filter','feedback','rf','protection','reserve'}
        required={r for m in modules for r,role in m['roles'].items() if role in critical_roles}
        covered=set()
        for s in sub:
            text(s,'id','type','reason');source(s['source'])
            if s['type'] not in TYPES or not s['refs'] or not set(s['refs']).issubset(fs):raise ValueError('Invalid local circuit inventory')
            covered.update(s['refs'])
        if not required.issubset(covered):raise ValueError('Critical-role component missing from local layout review')
        constraints=q.get('constraints',[]);cids=[c['id'] for c in constraints]
        if len(cids)!=len(set(cids)):raise ValueError('Duplicate placement constraint IDs')
        decoupled=set()
        for c in constraints:
            text(c,'id','kind');source(c['source']);kind=c['kind'];level=c.get('level')
            if kind not in KINDS or level not in ('阻断级','高风险','中风险','优化建议'):raise ValueError('Invalid placement constraint')
            if kind in BEAUTY and level!='优化建议':raise ValueError('Aesthetic preferences cannot become electrical blockers')
            for s in sub:
                if c['id'] in s.get('check_ids',[]) and kind=='decoupling':decoupled.add(c['cap_power']['ref'])
            loc=c['id'];ok=True;actual={}
            if kind=='fixed':
                ref=c['ref'];pos=c['position_mm'];num(c['position_tolerance_mm']);num(c['angle_tolerance_deg'])
                if len(pos)!=2 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in pos):raise ValueError('Invalid fixed position')
                a=meta[ref]['angle_deg'];target=float(c['angle_deg']);delta=abs((a-target+180)%360-180)
                if not math.isfinite(target):raise ValueError('Invalid angle')
                ok=distance(fs[ref]['pos'],pos)<=c['position_tolerance_mm'] and delta<=c['angle_tolerance_deg'];loc=ref;actual={'position_mm':fs[ref]['pos'],'angle_deg':a}
            elif kind=='pad_proximity':
                a,sa=endpoint(c['a']);b,sb=endpoint(c['b']);num(c['max_mm']);ok=distance(a,b)<=c['max_mm']
                if c.get('same_side') is True:ok=ok and bool(sa&sb)
                actual={'pad_center_distance_mm':distance(a,b),'max_mm':c['max_mm'],'endpoints':[dict(spec=c['a'],position_mm=a),dict(spec=c['b'],position_mm=b)],'scope':'Named endpoints only, not actual routed loop'}
            elif kind=='decoupling':
                if not isinstance(c.get('same_side'),bool):raise ValueError('Explicit same_side boolean required for decoupling')
                a,sa=endpoint(c['ic_power']);b,sb=endpoint(c['cap_power']);g,sg=endpoint(c['cap_ground']);ret,sr=endpoint(c['return_anchor'])
                if c['cap_power']['ref']!=c['cap_ground']['ref'] or str(c['cap_power']['pad'])==str(c['cap_ground']['pad']):raise ValueError('Explicit distinct terminals on the same capacitor required')
                if c['ic_power']['net']!=c['cap_power']['net'] or c['cap_ground']['net']!=c['return_anchor']['net'] or c['cap_ground']['net']==c['cap_power']['net']:raise ValueError('Decoupling power/return net roles inconsistent')
                p=distance(a,b);r=distance(g,ret);num(c['max_power_mm']);num(c['max_return_mm'])
                ok=p<=c['max_power_mm'] and r<=c['max_return_mm']
                if c.get('same_side') is True:ok=ok and bool(sa&sb)
                loc=c['cap_power']['ref']+'/'+c['ic_power']['ref'];actual={'power_terminal_distance_mm':p,'max_power_mm':c['max_power_mm'],'ground_terminal_to_anchor_mm':r,'max_return_mm':c['max_return_mm'],'endpoints':[dict(spec=c[k],position_mm=v) for k,v in [('ic_power',a),('cap_power',b),('cap_ground',g),('return_anchor',ret)]],'scope':'Pin-specific geometric screen only; actual current/plane path still requires review'}
            elif kind=='corridor':
                bounds=rect(c['bounds_mm']);allowed=set(c.get('allowed_refs',[]));num(c.get('margin_mm',0));unknown=[];blocked=[]
                for ref in fs:
                    if ref in allowed:continue
                    polygon=meta[ref]['courtyard']
                    if not polygon:unknown.append(ref);continue
                    xs=[p[0] for p in polygon];ys=[p[1] for p in polygon];m=c.get('margin_mm',0)
                    if max(xs)+m>=bounds[0] and min(xs)-m<=bounds[2] and max(ys)+m>=bounds[1] and min(ys)-m<=bounds[3]:blocked.append(ref)
                if unknown:raise ValueError('Corridor geometry unsupported for '+','.join(unknown))
                ok=not blocked;actual={'conservative_AABB_obstacles':blocked,'scope':'Placement corridor only; no guarantee routing capacity/return-plane continuity'}
            else:
                refs=c['refs']
                if len(refs)<(3 if kind=='uniform_spacing' else 2) or len(refs)!=len(set(refs)) or not set(refs).issubset(fs):raise ValueError('Explicit unique visual group required')
                num(c['tolerance'])
                if kind=='orientation':
                    angles=c['allowed_angles_deg']
                    if not angles or any(isinstance(a,bool) or not isinstance(a,(int,float)) or not math.isfinite(a) for a in angles):raise ValueError('Invalid visual angles')
                    actual={ref:meta[ref]['angle_deg'] for ref in refs};ok=all(min(abs((a-t+180)%360-180) for t in angles)<=c['tolerance'] for a in actual.values())
                else:
                    if c['axis'] not in ('x','y'):raise ValueError('Visual axis must be x/y')
                    values=sorted(fs[r]['pos'][0 if c['axis']=='x' else 1] for r in refs)
                    measure=values[-1]-values[0] if kind=='alignment' else (max(b-a for a,b in zip(values,values[1:]))-min(b-a for a,b in zip(values,values[1:])))
                    ok=measure<=c['tolerance'];actual={'center_spread_or_gap_variation_mm':measure}
                exception=c.get('exception')
                if not ok and exception:
                    text(exception,'reason');evidence(exception['evidence']);actual['visual_exception']=exception['reason'];ok=True
            checks.append({'id':c['id'],'status':'PASS' if ok else 'FAIL','kind':kind,'actual':actual,'level':level,'source':c['source'],'limits':{k:v for k,v in c.items() if k.startswith('max_') or 'tolerance' in k}})
            if not ok:
                risk('PLACE.'+kind.upper(),'声明布局约束未满足：'+json.dumps(actual,ensure_ascii=False),loc,level)
                findings[-1]['reference']=json.dumps(c['source'],ensure_ascii=False)
                findings[-1]['limits']={k:v for k,v in c.items() if k.startswith('max_') or 'tolerance' in k}
        for s in sub:
            if not set(s.get('check_ids',[])).issubset(cids):raise ValueError('Local circuit references unknown constraint')
        dec_caps={r for m in modules for r,role in m['roles'].items() if role=='decoupling'}
        if not dec_caps.issubset(decoupled):raise ValueError('Every declared decoupling capacitor needs a pin-specific rule linked to its local circuit')
        # Review snapshots bind all placement, pin/network facts and rule/source requirements.
        pd=placement_digest(board,meta);gd=digest(graph);rd=digest({k:v for k,v in q.items() if k!='reviews'})
        reviews=q.get('reviews',{});required_phases=['pre_route'] if phase=='pre_route' else ['pre_route','final']
        for name in required_phases:
            try:
                review=reviews.get(name,{})
                text(review,'reviewer','date','reason');dt.date.fromisoformat(review['date'])
                if dt.date.fromisoformat(review['date'])>dt.date.today():raise ValueError('Future placement review date')
                if review.get('placement_sha256')!=pd or review.get('netlist_sha256')!=gd or review.get('policy_sha256')!=rd:raise ValueError('Placement/rule/netlist review snapshot stale: '+name)
                if name=='final' and review.get('board_sha256')!=sha256(board_file):raise ValueError('Final board changed after placement/beauty review')
                topics=TOPICS|({'visual','moves_rechecked'} if name=='final' else set())
                if any(review.get('topics',{}).get(t) is not True for t in topics) or set(review.get('subcircuits',[]))!=set(subids):raise ValueError('Incomplete routing/return/mechanical/local/visual review checklist')
                if not review.get('evidence'):raise ValueError('Actual pre-route/final placement review evidence required')
                for ev in review['evidence']:evidence(ev)
            except Exception as e:risk('PLACE.REVIEW.'+name.upper(),str(e),name)
    except Exception as e:risk('PLACE.CONTRACT',str(e))
    snapshots={'placement_sha256':placement_digest(board,meta) if meta else None,'netlist_sha256':digest(graph),'policy_sha256':digest({k:v for k,v in q.items() if k!='reviews'}) if q else None,'board_sha256':sha256(board_file)}
    return {'status':'BLOCKED' if any(f['level']=='阻断级' for f in findings) else 'DECLARED_LAYOUT_CHECKS_COMPLETE','phase':phase,'scope':'static_placement_only','production_authorized':False,'native_geometry_verified':board.get('engine')!='static_preview','findings':findings,'checks':checks,'inputs_sha256':inputs,'snapshots':snapshots,'placement_metadata':meta,'modules':q.get('modules',[]),'critical_subcircuits':q.get('critical_subcircuits',[]),'limits':['No automatic placement, full DFM/3D/return-current/SI/thermal proof or reviewer authentication','Visual preferences never override hard electrical constraints']}

def write_artifacts(result,board,out):
    out=Path(out)
    if out.exists():raise ValueError('Report directory must be new')
    out.mkdir(parents=True,exist_ok=False)
    (out/'placement-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    lines=['# 布局专项报告',f"状态：{result['status']}；相位：{result['phase']}；仅静态布局，不授予生产许可。",'', '输入版本：`'+json.dumps(result['inputs_sha256'],ensure_ascii=False)+'`','']
    for f in result['findings']:lines.append(f"- 【{f['level']}】{f['location']}：{f['description']}；依据：{f['reference']}；建议：{f['suggestion']}")
    lines+=['','检查明细：']+[f"- {c.get('id',c.get('ref',''))}：{json.dumps(c,ensure_ascii=False)}" for c in result['checks']]
    (out/'placement-report.md').write_text('\n'.join(lines)+'\n')
    fs={f['ref']:f for f in board['footprints']};meta=result['placement_metadata']
    def drawing(refs,name,check_ids=None):
        selected=[c for c in result['checks'] if c.get('id') in (check_ids or [])]
        endpoints=[e for c in selected for e in c.get('actual',{}).get('endpoints',[])]
        points=[p for r in refs for p in meta.get(r,{}).get('courtyard',[])] or [fs[r]['pos'] for r in refs]
        if name=='module-map.svg':points += [(m['bounds_mm'][i],m['bounds_mm'][i+1]) for m in result['modules'] for i in (0,2)]
        points += [e['position_mm'] for e in endpoints]
        if not points:return
        x0=min(p[0] for p in points)-2;y0=min(p[1] for p in points)-2;w=max(p[0] for p in points)-x0+2;h=max(p[1] for p in points)-y0+2
        geometry_width=w;w+=16;h=max(h,2+len(refs)*0.7+len(endpoints)*0.7+sum(len({k:v for k,v in c.get('actual',{}).items() if k not in ('endpoints','scope')})+1 for c in selected)*0.5)
        parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {w} {h}" width="1000" height="700"><title>Placement geometry only; not copper/CAM proof</title><rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="white"/>']
        if name=='module-map.svg':
            for m in result['modules']:
                b=m['bounds_mm'];parts.append(f'<rect x="{b[0]}" y="{b[1]}" width="{b[2]-b[0]}" height="{b[3]-b[1]}" fill="none" stroke="#aaa" stroke-width="0.08"/><text x="{b[0]}" y="{b[1]+0.6}" font-size="0.5" fill="#467">{html.escape(m["id"])}</text>')
        for idx,r in enumerate(refs):
            f=fs[r];p=meta.get(r,{}).get('courtyard',[])
            if p:parts.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in p)+'" fill="#dceeff" stroke="#135" stroke-width="0.08"/>')
            for pad in f['pads']:
                x,y=pad['pos'];parts.append(f'<circle cx="{x}" cy="{y}" r="0.12" fill="#c44"/>')
            x,y=f['pos'];lx=x0+geometry_width+0.5;ly=y0+0.7+idx*0.7
            parts.append(f'<path d="M {x} {y} L {lx} {ly}" stroke="#789" stroke-width="0.025"/><text x="{lx}" y="{ly}" font-size="0.45" fill="#123">{html.escape(r)} ({x:g},{y:g})</text>')
        for idx,e in enumerate(endpoints):
            x,y=e['position_mm'];spec=e['spec'];label=(spec.get('ref','via')+'.'+str(spec.get('pad',spec.get('uuid','')))+' '+spec['net']);lx=x0+geometry_width+0.5;ly=y0+0.7+(len(refs)+idx)*0.7
            parts.append(f'<circle cx="{x}" cy="{y}" r="0.16" fill="none" stroke="#080" stroke-width="0.05"/><path d="M {x} {y} L {lx} {ly}" stroke="#080" stroke-width="0.025"/><text x="{lx}" y="{ly}" font-size="0.35">{html.escape(label)} ({x:g},{y:g})</text>')
        cursor=y0+0.7+(len(refs)+len(endpoints))*0.7
        for c in selected:
            actual={k:v for k,v in c.get('actual',{}).items() if k not in ('endpoints','scope')};lx=x0+geometry_width+0.5
            for label in [c['id']]+[k+': '+(f'{v:.4g}' if isinstance(v,(int,float)) else str(v)) for k,v in actual.items()]:
                parts.append(f'<text x="{lx}" y="{cursor}" font-size="0.3">{html.escape(label)}</text>');cursor+=0.5
        parts.append(f'<text x="{x0+0.2}" y="{y0+h-0.3}" font-size="0.3">Geometry only. Grey = module bounds, not board edge. No copper/CAM proof.</text>')
        parts.append('</svg>');(out/name).write_text(''.join(parts))
    drawing(list(fs),'module-map.svg')
    for i,s in enumerate(result['critical_subcircuits']):drawing([r for r in s['refs'] if r in fs],f'local-{i+1}.svg',s.get('check_ids',[]))
    (out/'visual-review.md').write_text('# 视觉整理与例外待评审\n\n检查对齐/方向/间距、重复通道、丝印可读/极性/引脚1、测试与返修可达性。电气/结构约束优先。模块图仅几何示意，必须结合真实铜层、装配/结构图审查。任何移动后重跑电气约束并重新确认，禁止自动填通过。\n')

def validate_review_binding(root,config):
    entry=config['placement_review'];q=read(local(Path(root).resolve(),entry['policy']));tasks=[t for t in config['stages']['pcb']['tasks'] if t.get('category')=='placement_quality' and t.get('check',{}).get('kind')=='semantic']
    if not tasks:raise ValueError('Explicit placement_quality semantic AI review required')
    refs={r for m in q['modules'] for r in m['refs']}
    if not refs.issubset({r for t in tasks for r in t['targets'].get('footprints',[])}):raise ValueError('Placement AI task misses physical module members in targets.footprints')
    nets={e['net'] for c in q.get('constraints',[]) for k,e in c.items() if k in ('a','b','ic_power','cap_power','cap_ground','return_anchor') and isinstance(e,dict) and e.get('net')}
    if not nets.issubset({n for t in tasks for n in t['targets'].get('nets',[])}):raise ValueError('Placement AI task misses named endpoint nets')
    docs={d['id']:d for d in config['documents']}
    for src in [m['source'] for m in q['modules']]+[s['source'] for s in q.get('critical_subcircuits',[])]+[c['source'] for c in q.get('constraints',[])]:
        if not any(docs[s['document_id']]['file']==src['file'] and docs[s['document_id']]['sha256']==src['sha256'] and s['locator']==src['locator'] for t in tasks for s in t['source_refs']):raise ValueError('Placement source/location absent from AI review')

def integrate(r,root,config,board_file):
    try:
        entry=config.get('placement_review')
        if not entry or not entry.get('policy'):raise ValueError('Missing modular/pin-level placement review policy')
        from static_review_gate import validate
        review=config['static_ai_reviews']['pcb'];folder=local(root,review['packet']);approved=validate(root,folder,local(root,review['ai_review']),local(root,review['engineer_review']))
        if approved['status']!='APPROVED_STATIC':raise ValueError('Current PCB AI/hardware confirmation required')
        packet=read(folder/'packet.json');pcfg=packet['config'];spec=pcfg['stages']['pcb']
        if pcfg.get('placement_review',{}).get('policy')!=entry['policy'] or local(root,spec['inputs']['board'])!=Path(board_file).resolve():raise ValueError('NPI placement policy/board differs from reviewed version')
        facts=read(folder/'facts.json');result=audit(root,local(root,entry['policy']),facts['netlist'],facts['board'],facts['edges'],board_file,'final')
        r.inputs.update(result['inputs_sha256']);r.evidence.append({'placement_review':result})
        for f in result['findings']:r.risk(f['rule'],'layout',f['level'],f['description'],f['location'],f['reference'],f['suggestion'])
    except Exception as e:r.risk('PLACE.NPI','layout','阻断级',str(e),fix='完成模块/引脚级/布线前/最终视觉复验及当前PCB的AI和工程师确认。')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--policy',required=True);p.add_argument('--netlist',required=True);p.add_argument('--board',required=True);p.add_argument('--phase',choices=['pre_route','final'],default='pre_route');p.add_argument('--static-preview',action='store_true');p.add_argument('--output-dir');a=p.parse_args()
    try:
        root=Path(a.project).resolve();board_file=local(root,a.board);xml=local(root,a.netlist)
        if not a.static_preview and not environment().get('pcbnew_exact_target'):raise ValueError('Target KiCad10.0.7 pcbnew required; static-preview cannot prove native/production success')
        board,edges=primitives(board_file,not a.static_preview);result=audit(root,local(root,a.policy),read_netlist(xml),board,edges,board_file,a.phase);result['inputs_sha256'][str(xml)]=sha256(xml)
        if a.output_dir:write_artifacts(result,board,a.output_dir)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
