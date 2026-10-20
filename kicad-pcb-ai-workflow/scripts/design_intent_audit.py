#!/usr/bin/env python3
"""Verify declared intent, generated rules and actual PCB netclass state.

Static preview is never manufacturing authorization. Native loads use a throwaway
copy so project settings cannot be saved over engineering source files.
"""
import argparse
import json
import math
import shutil
import tempfile
from pathlib import Path
from design_intent import (compile_intent, local, digest, layout_digest, approval,
                           positive, native_profile)
from npi_common import (environment, run, sha256, parse_sexpr, children, child,
                        value, xy, distance, TARGET_VERSION)
from link_audit import arc_length

def native_effective(root, intent):
    import pcbnew
    if not environment().get('pcbnew_exact_target'):raise ValueError('KiCad10.0.7 pcbnew required')
    with tempfile.TemporaryDirectory(prefix='kicad-intent-native-') as temp:
        base=Path(temp);pro=local(root,intent['project_file']);board=local(root,intent['board_file'])
        for f in (pro,board,pro.with_suffix('.kicad_dru')):
            target=base/f.name
            if f.is_file():shutil.copyfile(f,target)
        manager=pcbnew.SETTINGS_MANAGER();project=None;b=None
        try:
            if not manager.LoadProject(str(base/pro.name)):raise ValueError('Native project load failed')
            project=manager.GetProject(str(base/pro.name));b=pcbnew.LoadBoard(str(base/board.name))
            if project is None or b is None:raise ValueError('Native board/project context unavailable')
            b.SetProject(project);b.SynchronizeNetsAndNetClasses(False)
            native_nets={str(k):v for k,v in b.GetNetsByName().items()};out={}
            for n in intent['nets']:
                if n['name'] not in native_nets:raise ValueError('PCB net missing: '+n['name'])
                nc=native_nets[n['name']].GetNetClass()
                out[n['name']]={'contains_expected':bool(nc.ContainsNetclassWithName(n['netclass'])),
                    'clearance_mm':float(pcbnew.ToMM(nc.GetClearance())),
                    'track_width_mm':float(pcbnew.ToMM(nc.GetTrackWidth())),
                    'diff_width_mm':float(pcbnew.ToMM(nc.GetDiffPairWidth())),
                    'diff_gap_mm':float(pcbnew.ToMM(nc.GetDiffPairGap())),
                    'tuning_profile':str(nc.GetTuningProfile())}
            return out
        finally:
            if b is not None:b.ClearProject()
            if project is not None:manager.UnloadProject(project,False)

def audit(root, intent_file, native=True, effective_provider=None, phase='final'):
    root=Path(root).resolve();intent_file=Path(intent_file).resolve()
    findings=[];checks=[];inputs={str(intent_file):sha256(intent_file)};d={}
    if phase not in ('pre_route','final'):raise ValueError('Unknown intent audit phase')
    def risk(code,description,location='工程级（无坐标）',fix='修复设计意图/生成规则并重新同步、评审；不得降低门禁。'):
        findings.append({'rule':code,'level':'阻断级','gate':'design_intent','location':location,
                         'description':description,'reference':'原厂设计指南、批准叠层/工艺；KiCad10.0.7规则',
                         'fix':fix,'method':'设计意图静态核对/原生API/人工证据'})
    try:
        d=json.loads(intent_file.read_text());plan=compile_intent(root,d,verify=True);inputs.update(plan['inputs_sha256'])
        for name,expected in plan['proposed'].items():
            p=local(root,name)
            same=p.is_file() and (json.loads(p.read_text())==json.loads(expected) if p.suffix=='.kicad_pro' else p.read_text(encoding='utf-8-sig')==expected)
            if not same:risk('INTENT.NOT_APPLIED','设计意图尚未完整写入候选：'+name,name)
            if p.is_file():inputs[str(p)]=sha256(p)
        pro=json.loads(local(root,d['project_file']).read_text());board=parse_sexpr(local(root,d['board_file']).read_text())
        if d.get('demonstration_only'):risk('INTENT.DEMO','演示参数禁止用于生产')
        classes={c['name']:c for c in d['classes']};nets={n['name']:n for n in d['nets']}
        netnames={int(n[1]):n[2] for n in children(board,'net')}
        for fp in children(board,'footprint'):
            for p in children(fp,'pad'):
                net=child(p,'net',[])
                if len(net)>2:netnames[int(net[1])]=net[2]
        declared=set(nets)
        if not declared.issubset(set(netnames.values())):risk('INTENT.NETS','声明网络未同步到PCB：'+str(sorted(declared-set(netnames.values()))))
        # Naming heuristic is a warning against omissions, never a proof of total coverage.
        candidates={s for s in netnames.values() if s.endswith(('_P','_N'))}
        if candidates-declared:risk('INTENT.COVERAGE','发现未声明的P/N候选网络：'+str(sorted(candidates-declared)))
        effective=None
        if native:
            try:effective=(effective_provider or native_effective)(root,d)
            except Exception as e:risk('INTENT.NATIVE',str(e))
        else:risk('INTENT.STATIC','静态预览不能证明实际生效网络类，不允许生产放行')
        if effective is not None:
            for name,n in nets.items():
                actual=effective.get(name,{})
                c=classes[n['netclass']];g=c['geometry'][0]
                expected={'clearance_mm':c['clearance_mm'],'track_width_mm':g['width_mm']}
                if n['kind']=='differential':expected.update(diff_width_mm=g['width_mm'],diff_gap_mm=g['gap_mm'])
                if not actual.get('contains_expected') or any(not isinstance(actual.get(k),(int,float)) or not math.isclose(actual[k],v,rel_tol=0,abs_tol=1e-6) for k,v in expected.items()):
                    risk('INTENT.EFFECTIVE','实际生效网络类/参数与批准值不符：'+str(actual),name)
                tuning='DI_'+c['name'] if c['kind']!='power' else ''
                if actual.get('tuning_profile')!=tuning:risk('INTENT.TUNING','实际Tuning Profile不符',name)
        primitives={name:[] for name in nets}
        for tag in ('segment','arc'):
            for t in children(board,tag):
                name=netnames.get(int(value(t,'net',0)))
                if name not in nets:continue
                a,b=xy(t,'start'),xy(t,'end')
                length=distance(a,b) if tag=='segment' else arc_length(a,xy(t,'mid'),b)
                width=float(value(t,'width'));layer=value(t,'layer');pos=str(a)
                c=classes[nets[name]['netclass']];g=next((g for g in c['geometry'] if g['layer']==layer),None)
                if not g:risk('INTENT.LAYER','走线使用了未批准的层',name+' '+pos)
                elif not g['min_width_mm']-1e-9<=width<=g['max_width_mm']+1e-9:risk('INTENT.WIDTH','实际线宽不在批准范围内',name+' '+pos)
                primitives[name].append({'length_mm':length,'layer':layer,'width_mm':width})
        layout=layout_digest(board)
        for name,n in nets.items():
            if phase=='final' and not primitives[name]:risk('INTENT.UNROUTED','关键网络无已布线路径；不能用类分配代替布线完成',name)
            total=sum(e['length_mm'] for e in primitives[name])
            if n['kind']=='power':
                p=n['power']
                if total>p['max_path_length_mm']:risk('POWER.LENGTH','保守累计路径超过压降预算使用的最大长度',name)
                checks.append({'net':name,'power_budgets':plan['power_budgets'][name]})
                if phase=='pre_route':continue
                review=p.get('layout_review',{})
                try:
                    approval(review,root,inputs)
                    if review.get('layout_sha256')!=layout:raise ValueError('Power layout evidence stale')
                    required={'via_ampacity','pad_necks','copper_necks','return_path','contacts','fault_protection','transient_thermal'}
                    if any(review.get('checks',{}).get(k)!='PASS' for k in required):raise ValueError('Power via/neck/return/fault/transient checks incomplete')
                except Exception as e:risk('POWER.LAYOUT',str(e),name)
            if n['kind']=='rf':
                rf=n['rf']
                if total>rf['max_path_length_mm']:risk('RF.LENGTH','射频累计路径超过批准长度',name)
                if rf['reference_net'] not in netnames.values():risk('RF.REFERENCE','声明参考地未出现在PCB',name)
                for key in (() if phase=='pre_route' else ('return_review','matching_review')):
                    if rf[key].get('layout_sha256')!=layout:risk('RF.REVIEW','射频参考/匹配评审未绑定当前布局：'+key,name)
        footprints={}
        for f in children(board,'footprint'):
            props={p[1]:p[2] for p in children(f,'property') if len(p)>2};footprints[props.get('Reference')]=f
        for region in d.get('regions',[]):
            matches=[z for z in children(board,'zone') if value(z,'name')=='DI_'+region['id']]
            if len(matches)!=1:risk('RF.KEEPOUT','缺少唯一的原生天线禁布区',region['id']);continue
            z=matches[0];k=child(z,'keepout',[]);pts=children(child(child(z,'polygon',[]),'pts',[]),'xy')
            actual_points=[[float(v) for v in p[1:3]] for p in pts]
            layer_values=child(z,'layers',[])[1:] or [value(z,'layer')]
            if set(layer_values)!=set(region['layers']) or actual_points!=region['polygon_mm'] or any(value(k,name)!='not_allowed' for name in ('tracks','vias','pads','copperpour','footprints')):
                risk('RF.KEEPOUT','禁布范围/层/限制与批准值不符',region['id'])
            anchor=region['anchor'];f=footprints.get(anchor['ref']);at=child(f or [],'at',[])
            if not f or len(at)<3 or list(map(float,at[1:3]))!=anchor.get('position_mm') or (float(at[3]) if len(at)>3 else 0)!=anchor.get('rotation_deg'):
                risk('RF.ANCHOR','天线位置或方向已变化，必须重新定位净空区域',anchor['ref'])
        for loop in d.get('loops',[]):
            if phase=='pre_route':continue
            review=loop['review']
            if review.get('layout_sha256')!=layout or not review.get('method'):
                risk('LOOP.REVIEW','实际回路面积缺少当前布局的测量/求解证据',loop.get('id','?'));continue
            try:
                measured=positive(review.get('measured_area_mm2'),'measured loop area',zero=True)
                if measured>loop['max_area_mm2']:risk('LOOP.AREA','实际回路面积超过批准上限',loop['id'])
            except Exception as e:risk('LOOP.REVIEW',str(e),loop.get('id','?'))
        # Capture potentially changing dependencies again in the enclosing release gate.
        checks.append({'declared_nets':len(nets),'declared_pairs':len(d.get('pairs',[])),
                       'layout_sha256':layout,'scope':'Native class + generated geometry; RF fields and thermal physics remain evidence-backed reviews'})
    except Exception as e:risk('INTENT.CONFIG',str(e))
    return {'status':'BLOCKED' if findings else 'PASS','production_authorized':False,
            'native_requested':native,'phase':phase,'deferred':['routed completeness','final power/RF/loop layout evidence'] if phase=='pre_route' else [],
            'inputs_sha256':inputs,'findings':findings,'checks':checks}

def integrate(r,root,config):
    entry=config.get('design_intent')
    if not entry:
        r.risk('INTENT.MISSING','schematic','阻断级','缺少差分/电源/射频设计意图配置',fix='设置design_intent，声明完整关键网络、原厂依据与批准几何；不能由网络类存在推断正确。');return
    try:
        path=local(root,entry);d=json.loads(path.read_text())
        if d.get('project_file')!=config.get('inputs',{}).get('project') or d.get('board_file')!=config.get('inputs',{}).get('board'):
            raise ValueError('Intent refers to another project/PCB')
        result=audit(root,path,True);r.inputs.update(result['inputs_sha256']);r.evidence.append({'design_intent':result})
        for item in result['findings']:
            r.risk(item['rule'],'routing',item['level'],item['description'],item['location'],item['reference'],item['fix'],item['method'])
    except Exception as e:r.risk('INTENT.CONFIG','routing','阻断级',str(e))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--intent',required=True);p.add_argument('--static-preview',action='store_true');p.add_argument('--phase',choices=['pre_route','final'],default='final');a=p.parse_args()
    try:r=audit(a.project,a.intent,not a.static_preview,phase=a.phase)
    except Exception as e:r={'status':'BLOCKED','reason':str(e)}
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
