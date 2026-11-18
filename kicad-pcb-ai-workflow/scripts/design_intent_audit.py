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
                        value, xy, distance, TARGET_VERSION, pair_compatible, patch_native_ready)
from link_audit import arc_length

def native_effective(root, intent):
    import pcbnew
    if not patch_native_ready(environment()):raise ValueError('Matching KiCad 10.0.x CLI/pcbnew and current patch setup evidence required for native effective-rule audit')
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
                # The raw pointer from GetNetClass() is opaque in KiCad's SWIG binding.
                nc=native_nets[n['name']].GetNetClassSlow()
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
    def risk(code,description,location='project-wide (no coordinate)',fix='Repair design intent/native rules, resynchronize and review; never weaken the gate.'):
        findings.append({'rule':code,'level':'\u963b\u65ad\u7ea7','gate':'design_intent','location':location,
                         'description':description,'reference':'Manufacturer design guide, approved stack-up/process and actual KiCad rules',
                         'fix':fix,'method':'design-intent audit / native reader / human evidence'})
    try:
        d=json.loads(intent_file.read_text(encoding='utf-8-sig'));plan=compile_intent(root,d,verify=True);inputs.update(plan['inputs_sha256'])
        for name,expected in plan['proposed'].items():
            p=local(root,name)
            same=p.is_file() and (json.loads(p.read_text(encoding='utf-8-sig'))==json.loads(expected) if p.suffix=='.kicad_pro' else p.read_text(encoding='utf-8-sig')==expected)
            if not same:risk('INTENT.NOT_APPLIED','Design intent not fully applied to candidate: '+name,name)
            if p.is_file():inputs[str(p)]=sha256(p)
        pro=json.loads(local(root,d['project_file']).read_text(encoding='utf-8-sig'));board=parse_sexpr(local(root,d['board_file']).read_text(encoding='utf-8-sig'))
        if d.get('demonstration_only'):risk('INTENT.DEMO','Demonstration-only parameters must not be used for production')
        classes={c['name']:c for c in d['classes']};nets={n['name']:n for n in d['nets']}
        netnames={int(n[1]):n[2] for n in children(board,'net')}
        for fp in children(board,'footprint'):
            for p in children(fp,'pad'):
                net=child(p,'net',[])
                if len(net)>2:netnames[int(net[1])]=net[2]
        declared=set(nets)
        if not declared.issubset(set(netnames.values())):risk('INTENT.NETS','Declared nets not synchronized to PCB: '+str(sorted(declared-set(netnames.values()))))
        # Naming heuristic is a warning against omissions, never a proof of total coverage.
        candidates={s for s in netnames.values() if s.endswith(('_P','_N'))}
        if candidates-declared:risk('INTENT.COVERAGE','Undeclared differential P/N candidate nets detected: '+str(sorted(candidates-declared)))
        effective=None
        if native:
            try:effective=(effective_provider or native_effective)(root,d)
            except Exception as e:risk('INTENT.NATIVE',str(e))
        else:risk('INTENT.STATIC','Static preview cannot prove effective NetClasses or authorize production')
        if effective is not None:
            for name,n in nets.items():
                actual=effective.get(name,{})
                c=classes[n['netclass']];g=c['geometry'][0]
                expected={'clearance_mm':c['clearance_mm'],'track_width_mm':g['width_mm']}
                if n['kind']=='differential':expected.update(diff_width_mm=g['width_mm'],diff_gap_mm=g['gap_mm'])
                if not actual.get('contains_expected') or any(not isinstance(actual.get(k),(int,float)) or not math.isclose(actual[k],v,rel_tol=0,abs_tol=1e-6) for k,v in expected.items()):
                    risk('INTENT.EFFECTIVE','Effective NetClasses/parameters differ from approved values: '+str(actual),name)
                tuning='DI_'+c['name'] if c['kind']!='power' else ''
                if actual.get('tuning_profile')!=tuning:risk('INTENT.TUNING','Actual tuning profile mismatch',name)
        primitives={name:[] for name in nets}
        for tag in ('segment','arc'):
            for t in children(board,tag):
                name=netnames.get(int(value(t,'net',0)))
                if name not in nets:continue
                a,b=xy(t,'start'),xy(t,'end')
                length=distance(a,b) if tag=='segment' else arc_length(a,xy(t,'mid'),b)
                width=float(value(t,'width'));layer=value(t,'layer');pos=str(a)
                c=classes[nets[name]['netclass']];g=next((g for g in c['geometry'] if g['layer']==layer),None)
                if not g:risk('INTENT.LAYER','Track uses a layer that is not approved',name+' '+pos)
                elif not g['min_width_mm']-1e-9<=width<=g['max_width_mm']+1e-9:risk('INTENT.WIDTH','Actual track width is outside the approved range',name+' '+pos)
                primitives[name].append({'length_mm':length,'layer':layer,'width_mm':width})
        layout=layout_digest(board)
        for name,n in nets.items():
            if phase=='final' and not primitives[name]:risk('INTENT.UNROUTED','Critical net has no actual routed path; a class assignment is not finished copper',name)
            total=sum(e['length_mm'] for e in primitives[name])
            if n['kind']=='power':
                p=n['power']
                if total>p['max_path_length_mm']:risk('POWER.LENGTH','Conservative path sum exceeds the maximum length used for voltage-drop budget',name)
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
                if total>rf['max_path_length_mm']:risk('RF.LENGTH','Accumulated RF path exceeds approved length',name)
                if rf['reference_net'] not in netnames.values():risk('RF.REFERENCE','Declared reference-ground net not found in current PCB',name)
                for key in (() if phase=='pre_route' else ('return_review','matching_review')):
                    if rf[key].get('layout_sha256')!=layout:risk('RF.REVIEW','RF reference/matching review is not bound to current placement: '+key,name)
        footprints={}
        for f in children(board,'footprint'):
            props={p[1]:p[2] for p in children(f,'property') if len(p)>2};footprints[props.get('Reference')]=f
        for region in d.get('regions',[]):
            matches=[z for z in children(board,'zone') if value(z,'name')=='DI_'+region['id']]
            if len(matches)!=1:risk('RF.KEEPOUT','No unique native antenna keepout found',region['id']);continue
            z=matches[0];k=child(z,'keepout',[]);pts=children(child(child(z,'polygon',[]),'pts',[]),'xy')
            actual_points=[[float(v) for v in p[1:3]] for p in pts]
            layer_values=child(z,'layers',[])[1:] or [value(z,'layer')]
            if set(layer_values)!=set(region['layers']) or actual_points!=region['polygon_mm'] or any(value(k,name)!='not_allowed' for name in ('tracks','vias','pads','copperpour','footprints')):
                risk('RF.KEEPOUT','Keepout region/layers/restrictions differ from approved conditions',region['id'])
            anchor=region['anchor'];f=footprints.get(anchor['ref']);at=child(f or [],'at',[])
            if not f or len(at)<3 or list(map(float,at[1:3]))!=anchor.get('position_mm') or (float(at[3]) if len(at)>3 else 0)!=anchor.get('rotation_deg'):
                risk('RF.ANCHOR','Antenna position/orientation changed; rebind and inspect keepout geometry',anchor['ref'])
        for loop in d.get('loops',[]):
            if phase=='pre_route':continue
            review=loop['review']
            if review.get('layout_sha256')!=layout or not review.get('method'):
                risk('LOOP.REVIEW','Actual loop area lacks current-placement measurements/solver evidence',loop.get('id','?'));continue
            try:
                measured=positive(review.get('measured_area_mm2'),'measured loop area',zero=True)
                if measured>loop['max_area_mm2']:risk('LOOP.AREA','Actual loop area exceeds approved limit',loop['id'])
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
        r.risk('INTENT.MISSING','schematic','\u963b\u65ad\u7ea7','Differential/power/RF design-intent profile missing',fix='Populate design_intent with exact critical nets, manufacturer basis and approved geometry; a class name alone is not proof.');return
    try:
        path=local(root,entry);d=json.loads(path.read_text(encoding='utf-8-sig'))
        if d.get('project_file')!=config.get('inputs',{}).get('project') or d.get('board_file')!=config.get('inputs',{}).get('board'):
            raise ValueError('Intent refers to another project/PCB')
        result=audit(root,path,True);r.inputs.update(result['inputs_sha256']);r.evidence.append({'design_intent':result})
        for item in result['findings']:
            r.risk(item['rule'],'routing',item['level'],item['description'],item['location'],item['reference'],item['fix'],item['method'])
    except Exception as e:r.risk('INTENT.CONFIG','routing','\u963b\u65ad\u7ea7',str(e))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--intent',required=True);p.add_argument('--static-preview',action='store_true');p.add_argument('--phase',choices=['pre_route','final'],default='final');a=p.parse_args()
    try:r=audit(a.project,a.intent,not a.static_preview,phase=a.phase)
    except Exception as e:r={'status':'BLOCKED','reason':str(e)}
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status']=='PASS' else 2

if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__':raise SystemExit(main())
