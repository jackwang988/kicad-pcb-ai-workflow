#!/usr/bin/env python3
"""Read-only project-specific schematic structure checks, not electrical proof."""
import argparse
from schematic_io import blocking
import json
from pathlib import Path
from schematic_io import sheets
from engineering_gate import local
from npi_common import children,child,value,xy,segment_distance,sha256,finite_tree

def audit(root,top,policy_file):
    root=Path(root).resolve();p=local(root,policy_file);q=finite_tree(json.loads(p.read_text(encoding='utf-8-sig')))
    if q.get('schema_version')!=1:raise ValueError('Unknown style policy')
    trees=sheets(root,top);inputs={str(p):sha256(p)};findings=[];checks=[]
    def risk(code,where,description,fix,level='阻断级'):
        findings.append(dict(rule=code,level=level,location=where,description=description,reference='KiCad hierarchical label/sheet pin semantics; explicit project style policy',suggestion=fix))
    # No default page size, device count, distance or forced hierarchy.
    if 'require_sheet_pin_wire' in q and not isinstance(q['require_sheet_pin_wire'],bool):raise ValueError('Explicit boolean sheet-pin-wire setting required')
    declared=q.get('pages',{})
    if not isinstance(declared,dict) or set(declared)-set(trees):raise ValueError('Policy contains unreachable page')
    if declared or q.get('require_sheet_pin_wire') is True:
        src=q.get('source',{});f=local(root,src['file'])
        if not src.get('locator') or sha256(f)!=src.get('sha256'):raise ValueError('Explicit page constraints need current source and locator')
        inputs[str(f)]=sha256(f)
    for name,tree in trees.items():
        inputs[str(local(root,name))]=sha256(local(root,name));paper=child(tree,'paper',[])
        expected=declared.get(name,{})
        if expected.get('paper') and (len(paper)<2 or paper[1]!=expected['paper']):risk('STYLE.PAPER',name,'纸张与项目明确要求不符','按项目要求改图面；不得改动连接。')
        if 'portrait' in expected:
            if not isinstance(expected['portrait'],bool):raise ValueError('Portrait must be explicit boolean')
            if ('portrait' in paper)!=expected['portrait']:risk('STYLE.ORIENTATION',name,'页面方向与项目要求不符','按实际约定设置方向。')
        electrical=children(tree,'symbol');seen={}
        for symbol in electrical:
            props={p[1]:p[2] for p in children(symbol,'property') if len(p)>2};ref=props.get('Reference','')
            # Across distinct pages/local instances is assessed natively; do not confuse repeated units with duplicate components.
            if ref.startswith(('#PWR','#FLG')):
                if ref in seen:risk('STYLE.POWER_REF',name+':'+ref,'同页电源符号位号重复','重新注释电源位号并核对原生导出；不合并电源网络。')
                seen[ref]=True
        for sheet in children(tree,'sheet'):
            props={p[1]:p[2] for p in children(sheet,'property') if len(p)>2};filename=props.get('Sheetfile') or props.get('Sheet file')
            sub=local(root,str((local(root,name).parent/filename).relative_to(root)));subname=sub.relative_to(root).as_posix()
            pins=[str(pin[1]) for pin in children(sheet,'pin')];labels=[str(x[1]) for x in children(trees[subname],'hierarchical_label')]
            if len(pins)!=len(set(pins)) or set(pins)!=set(labels):risk('STYLE.HIERARCHY',name+' -> '+subname,'层次图框引脚与子页标签不一致或图框引脚重复','按实际接口逐项配对；再以原生XML/ERC核对电气连接。')
            if q.get('require_sheet_pin_wire') is True:
                segments=[]
                for wire in children(tree,'wire'):
                    pts=[(float(v[1]),float(v[2])) for v in children(child(wire,'pts',[]),'xy')];segments+=list(zip(pts,pts[1:]))
                for pin in children(sheet,'pin'):
                    if not any(segment_distance(xy(pin),a,b)<1e-6 for a,b in segments):risk('STYLE.SHEET_WIRE',name+':'+str(pin[1]),'明确要求实体互联的层次引脚未接到可识别导线','显式接线；总线入口和复杂接口需另用原生网表验证。')
        checks.append({'page':name,'paper':paper[1:],'symbol_instances':len(electrical),'scope':'declared page constraints and immediate sheet mapping only'})
    return {'status':'BLOCKED' if findings else 'DECLARED_STRUCTURE_CHECKS_COMPLETE','scope':'schematic_structure_only','production_authorized':False,'findings':findings,'checks':checks,'inputs_sha256':inputs,
            'manual_remaining':['Actual readability, clusters, text overlap, power symbol scope, NC correctness and device recommendations','Native ERC/XML and complete AI/engineer review; this is not electrical approval']}

def validate_binding(root,config):
    entry=config['schematic_style'];q=json.loads(local(Path(root).resolve(),entry['policy']).read_text(encoding='utf-8-sig'))
    tasks=[t for t in config['stages']['schematic']['tasks'] if t.get('category')=='schematic_style' and t.get('check',{}).get('kind')=='semantic']
    if not tasks:raise ValueError('Schematic style requires an actual semantic review task')
    src=q.get('source')
    if src:
        docs={d['id']:d for d in config['documents']}
        if not any(docs[s['document_id']]['file']==src['file'] and docs[s['document_id']]['sha256']==src['sha256'] and s['locator']==src['locator'] for t in tasks for s in t['source_refs']):raise ValueError('Style source/locator missing from AI review')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--schematic',required=True);p.add_argument('--policy',required=True);p.add_argument('--output-dir');a=p.parse_args()
    try:
        r=audit(a.project,a.schematic,a.policy)
        if a.output_dir:
            out=Path(a.output_dir)
            if out.exists():raise ValueError('New report directory required')
            out.mkdir(parents=True);(out/'style-report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False,'findings':[blocking('INPUT.CONTRACT',e)]},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
