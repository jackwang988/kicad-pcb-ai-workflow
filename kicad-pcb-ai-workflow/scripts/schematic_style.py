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
    def risk(code,where,description,fix,level='\u963b\u65ad\u7ea7'):
        findings.append(dict(rule=code,level=level,location=where,description=description,reference='KiCad hierarchical label/sheet pin semantics; explicit project style policy',suggestion=fix))
    # No default page size, device count, distance or forced hierarchy.
    if 'require_sheet_pin_wire' in q and not isinstance(q['require_sheet_pin_wire'],bool):raise ValueError('Explicit boolean sheet-pin-wire setting required')
    declared=q.get('pages',{})
    if not isinstance(declared,dict) or set(declared)-set(trees):raise ValueError('Policy contains unreachable page')
    if declared or q.get('require_sheet_pin_wire') is True:
        src=q.get('source',{});f=local(root,src['file'])
        if not src.get('locator') or sha256(f)!=src.get('sha256'):raise ValueError('Explicit page constraints need current source and locator')
        inputs[str(f)]=sha256(f)
    archetype_contract = q.get('prototype_validation')
    if archetype_contract is not None:
        if not isinstance(archetype_contract, dict) or archetype_contract.get('required') is not True:
            raise ValueError('prototype_validation must explicitly request required=true')
        cases = archetype_contract.get('cases')
        if not isinstance(cases, list):
            raise ValueError('prototype_validation.cases must be a list')
        allowed = {'power_conversion','mcu_soc','multi_pin_interface','bus_storage',
                   'analog_audio','discrete_io','hierarchy_overview','debug'}
        declared_types = set()
        declared_pages = set()
        for case in cases:
            if not isinstance(case,dict) or case.get('archetype') not in allowed:
                risk('STYLE.PROTOTYPE_KIND',str(case),'Unknown or missing page archetype','Select a defined page archetype and provide actual evidence.')
                continue
            name = case.get('page')
            kind = case['archetype']
            if not isinstance(name,str) or name not in trees or name in declared_pages:
                risk('STYLE.PROTOTYPE_PAGE',str(name),'Archetype evidence sheet is missing, inaccessible or duplicated','Use distinct real pages from current project.')
                continue
            declared_pages.add(name)
            declared_types.add(kind)
            evidence = case.get('evidence')
            if not isinstance(evidence,dict) or not evidence.get('locator'):
                risk('STYLE.PROTOTYPE_EVIDENCE',name,'Actual visual review evidence locator missing','Provide evidence file, current SHA and specific locator.')
                continue
            try:
                file = local(root,evidence['file'])
                if file.is_symlink() or not file.is_file() or not file.stat().st_size:
                    raise ValueError('Missing evidence file')
                if sha256(file) != evidence.get('sha256'):
                    raise ValueError('Evidence has changed')
                inputs[str(file)] = sha256(file)
            except (KeyError,ValueError,OSError) as exc:
                risk('STYLE.PROTOTYPE_EVIDENCE',name,str(exc),'Use actual current project visual/PDF/human review evidence and rebind hashes.')
        if len(declared_pages) < 2 or len(declared_types) < 2:
            risk('STYLE.PROTOTYPE_DIVERSITY','prototype_validation',
                 'At least two distinct page archetypes require independent evidence before generalizing drawing strategy',
                 'Use two distinct archetypes, with full-page/200% detail, netlist, ERC and human checks.')
        if 'power_conversion' in declared_types and not ({'mcu_soc','multi_pin_interface'} & declared_types):
            risk('STYLE.PROTOTYPE_GENERALIZE','prototype_validation',
                 'Power-sheet strategy has not been validated on MCU or many-pin interface sheet',
                 'Add representative MCU/mult_pin interface verification; avoid fixed coordinate templates.')
        checks.append({'prototype_validation': 'declared_evidence_only',
                       'archetypes': sorted(declared_types), 'pages': sorted(declared_pages),
                       'scope': 'evidence identity and archetype diversity, not automatic visual proof'})
    for name,tree in trees.items():
        inputs[str(local(root,name))]=sha256(local(root,name));paper=child(tree,'paper',[])
        expected=declared.get(name,{})
        if expected.get('paper') and (len(paper)<2 or paper[1]!=expected['paper']):risk('STYLE.PAPER',name,'Paper size differs from explicit project requirement','Adjust page settings only; preserve electrical connectivity.')
        if 'portrait' in expected:
            if not isinstance(expected['portrait'],bool):raise ValueError('Portrait must be explicit boolean')
            if ('portrait' in paper)!=expected['portrait']:risk('STYLE.ORIENTATION',name,'Page orientation differs from requirements','Set specified page orientation.')
        electrical=children(tree,'symbol');seen={}
        for symbol in electrical:
            props={p[1]:p[2] for p in children(symbol,'property') if len(p)>2};ref=props.get('Reference','')
            # Across distinct pages/local instances is assessed natively; do not confuse repeated units with duplicate components.
            if ref.startswith(('#PWR','#FLG')):
                if ref in seen:risk('STYLE.POWER_REF',name+':'+ref,'Duplicate power-symbol reference on a page','Correct power reference annotations and native export; do not merge power nets.')
                seen[ref]=True
        for sheet in children(tree,'sheet'):
            props={p[1]:p[2] for p in children(sheet,'property') if len(p)>2};filename=props.get('Sheetfile') or props.get('Sheet file')
            sub=local(root,str((local(root,name).parent/filename).relative_to(root)));subname=sub.relative_to(root).as_posix()
            pins=[str(pin[1]) for pin in children(sheet,'pin')];labels=[str(x[1]) for x in children(trees[subname],'hierarchical_label')]
            if len(pins)!=len(set(pins)) or set(pins)!=set(labels):risk('STYLE.HIERARCHY',name+' -> '+subname,'Hierarchical sheet pins do not match child labels or are duplicated','Map pins to actual interfaces then verify native XML/ERC connectivity.')
            if q.get('require_sheet_pin_wire') is True:
                segments=[]
                for wire in children(tree,'wire'):
                    pts=[(float(v[1]),float(v[2])) for v in children(child(wire,'pts',[]),'xy')];segments+=list(zip(pts,pts[1:]))
                for pin in children(sheet,'pin'):
                    if not any(segment_distance(xy(pin),a,b)<1e-6 for a,b in segments):risk('STYLE.SHEET_WIRE',name+':'+str(pin[1]),'Hierarchical pin needing a real wire has no recognizable connected segment','Connect explicitly; verify buses/complex interfaces with native netlist.')
        checks.append({'page':name,'paper':paper[1:],'symbol_instances':len(electrical),'scope':'declared page constraints and immediate sheet mapping only'})
    return {'status':'BLOCKED' if findings else 'DECLARED_STRUCTURE_CHECKS_COMPLETE','scope':'schematic_structure_only','production_authorized':False,'findings':findings,'checks':checks,'inputs_sha256':inputs,
            'manual_remaining':['Actual readability, clusters, text overlap, power symbol scope, NC correctness and device recommendations', 'Prototype evidence identity does not prove its visual or ERC content; AI and engineer must review','Native ERC/XML and complete AI/engineer review; this is not electrical approval']}

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
            out.mkdir(parents=True);(out/'style-report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
        print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False,'findings':[blocking('INPUT.CONTRACT',e)]},ensure_ascii=False));return 2
if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__':raise SystemExit(main())
