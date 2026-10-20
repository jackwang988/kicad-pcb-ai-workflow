#!/usr/bin/env python3
"""Validate grounded AI static review, then require a hardware engineer signoff.

This validates evidence structure/freshness and deterministic results. It cannot
authenticate a person or prove semantic reasoning correct. Never forge a signoff.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
from npi_common import sha256,LEVELS,finite_tree
from design_intent import local,digest
from static_review import validate_config,current_record,evaluate_rule,DYNAMIC
from netlist_guard import read_netlist

def folded(s):return ' '.join(s.split())

def pointer(data,path):
    if not isinstance(path,str) or not path.startswith('/'):raise ValueError('Fact requires JSON pointer')
    for key in path[1:].split('/'):
        key=key.replace('~1','/').replace('~0','~')
        data=data[int(key)] if isinstance(data,list) else data[key]
    return data

def observations(items,facts,packet):
    if not isinstance(items,list) or not items:raise ValueError('Actual design observations required')
    graph=facts['netlist'];refs=graph['components'];nets=graph['nets'];board=facts.get('board') or {};layers=board.get('copper_layers',[])
    views={r['file'] for r in packet['views']}
    for ob in items:
        if not isinstance(ob,dict):raise ValueError('Invalid observation')
        if not set(ob).intersection(('fact','ref','net','layer','view','footprint')):raise ValueError('Observation lacks actual design identity')
        if 'fact' in ob:
            if 'actual' not in ob or pointer(facts,ob['fact'])!=ob['actual']:raise ValueError('Observation contradicts captured fact')
        if 'ref' in ob:
            if ob['ref'] not in refs:raise ValueError('Observation references unknown component')
            if 'pin' in ob:
                matches=[net for net,nodes in nets.items() if [ob['ref'],str(ob['pin'])] in nodes]
                if len(matches)!=1 or ob.get('net')!=matches[0]:raise ValueError('Observed pin/net is not actual connection')
        if 'footprint' in ob:
            if ob['footprint'] not in {f['ref'] for f in board.get('footprints',[])} or not ob.get('detail'):raise ValueError('Unknown/unexplained board footprint observation')
        if 'net' in ob:
            if ob['net'] not in nets:raise ValueError('Observation references unknown network')
        if 'layer' in ob:
            if ob['layer'] not in layers:raise ValueError('Observation references unknown copper layer')
        if 'view' in ob:
            if ob['view'] not in views or not ob.get('detail'):raise ValueError('Unknown/unexplained visual evidence')
            expected=next(v.get('layer') for v in packet['views'] if v['file']==ob['view'])
            if expected and ob.get('layer')!=expected:raise ValueError('Visual evidence layer mismatch')

def citations(items,allowed,packet,folder):
    if not isinstance(items,list) or not items:raise ValueError('Source citations required')
    docs={d['id']:d for d in packet['documents']};seen=set()
    for c in items:
        key=(c.get('document_id'),c.get('locator'))
        if key not in allowed:raise ValueError('Citation does not match approved task source/location')
        d=docs[key[0]];text=local(folder,d['text_file']).read_text();quote=c.get('quote')
        if not isinstance(quote,str) or not 8<=len(quote)<=500 or folded(quote) not in folded(text):raise ValueError('Citation text absent in actual source')
        seen.add(key)
    if not allowed.issubset(seen):raise ValueError('Task source coverage incomplete')

def validate(root,packet_dir,ai_file=None,engineer_file=None):
    root=Path(root).resolve();folder=Path(packet_dir).resolve();inputs={};findings=[];result_status='BLOCKED'
    def risk(code,desc,location='工程级（无坐标）',level='阻断级',fix='补齐真实来源、静态证据和工程师确认；修复后重新生成评审，不得补写假通过。'):
        findings.append({'rule':code,'level':level,'location':location,'description':desc,
                         'reference':'产品规格、适用器件/原厂指南及静态评审契约','suggestion':fix})
    try:
        packet_path=local(folder,'packet.json');packet=finite_tree(json.loads(packet_path.read_text()));inputs[str(packet_path)]=sha256(packet_path)
        if packet.get('schema_version')!=1 or packet.get('scope')!='static_only':raise ValueError('Unsupported packet/scope')
        stage=packet['stage'];spec=validate_config(packet['config'],stage)
        if packet['config'].get('device_knowledge'):
            from device_knowledge import validate_bundle
            required=validate_bundle(root,packet['config']['device_knowledge'])
            if not set(required).issubset(packet['baseline']):raise ValueError('Device evidence missing from review baseline')
        mandatory={packet['facts_file'],packet['checks_file'],'commands.json','netlist.xml'}
        if packet['config'].get('require_system_integration') is True:mandatory.add('system-integration.json')
        mandatory.update((Path('inputs')/n).as_posix() for n in packet['baseline'])
        mandatory.update(d['text_file'] for d in packet['documents'])
        mandatory.update(v['file'] for v in packet['views'])
        if not mandatory.issubset(packet['artifacts_sha256']):raise ValueError('Packet hash inventory missing required artifacts')
        for name,record in packet['baseline'].items():
            p=local(root,name);inputs[str(p)]=sha256(p)
            if current_record(root,name,stage,record['kind']=='project_projection')!=record:raise ValueError('Review baseline stale: '+name)
        for name,h in packet['artifacts_sha256'].items():
            p=local(folder,name)
            if not p.is_file() or sha256(p)!=h:raise ValueError('Packet artifact missing/changed: '+name)
            inputs[str(p)]=h
        if packet.get('demonstration_only'):risk('STATIC.DEMO','TEST演示资料不得用于真实工程签核')
        if packet.get('native_ready') is not True or packet.get('preparation_issues'):risk('STATIC.INPUTS','原生来源/视图/数据覆盖尚未验证：'+str(packet.get('preparation_issues')))
        provenance=packet.get('native_provenance',{});env=provenance.get('environment',{})
        if provenance.get('xml_origin')!='native_export' or env.get('cli_exact_target') is not True or (stage=='pcb' and env.get('pcbnew_exact_target') is not True):
            risk('STATIC.PROVENANCE','缺少目标版本原生导出来源；导入XML仅可作预评审')
        if provenance.get('xml_sha256')!=sha256(local(folder,'netlist.xml')):raise ValueError('XML origin hash mismatch')
        facts=json.loads(local(folder,packet['facts_file']).read_text())
        if packet['config'].get('device_knowledge'):
            from device_knowledge import validate_project_binding
            validate_project_binding(root,packet['config'],stage,facts['netlist'])
        if digest(read_netlist(local(folder,'netlist.xml')))!=digest(facts['netlist']):raise ValueError('Captured netlist facts differ from XML')
        if packet['config'].get('reserve_review',{}).get('policy'):
            from reserve_review import audit as reserve_audit,validate_review_binding
            validate_review_binding(root,packet['config'],stage)
            rr=reserve_audit(root,local(root,packet['config']['reserve_review']['policy']),facts['netlist'],stage,facts['board'],local(root,spec['inputs']['board']) if stage=='pcb' else None)
            if not set(Path(n).relative_to(root).as_posix() for n in rr['inputs_sha256']).issubset(packet['baseline']):raise ValueError('Reserve evidence missing from baseline')
            for f in rr['findings']:risk(f['rule'],f['description'],f['location'],f['level'],f['suggestion'])
        if stage=='pcb' and packet['config'].get('placement_review',{}).get('policy'):
            from placement_review import audit as placement_audit,validate_review_binding as bind_placement
            bind_placement(root,packet['config'])
            layout=placement_audit(root,local(root,packet['config']['placement_review']['policy']),facts['netlist'],facts['board'],facts['edges'],local(root,spec['inputs']['board']),'final')
            if not set(Path(n).relative_to(root).as_posix() for n in layout['inputs_sha256']).issubset(packet['baseline']):raise ValueError('Placement evidence missing from baseline')
            for f in layout['findings']:risk(f['rule'],f['description'],f['location'],f['level'],f['suggestion'])
        if stage=='schematic' and packet['config'].get('schematic_style',{}).get('policy'):
            from schematic_style import audit as style_audit,validate_binding as bind_style
            bind_style(root,packet['config']);style=style_audit(root,spec['inputs']['schematic'],packet['config']['schematic_style']['policy'])
            if not set(Path(n).relative_to(root).as_posix() for n in style['inputs_sha256']).issubset(packet['baseline']):raise ValueError('Style dependencies missing from baseline')
            for f in style['findings']:risk(f['rule'],f['description'],f['location'],f['level'],f['suggestion'])
        if stage=='schematic' and packet['config'].get('require_system_integration') is True:
            from system_integration import audit as system_audit
            system=system_audit(root,packet['config']['system_integration']['contract'],spec['inputs']['schematic'],facts['netlist'],packet['config']['documents'])
            captured=json.loads(local(folder,'system-integration.json').read_text())
            if captured!=system:raise ValueError('System architecture/interface audit differs from captured packet')
            if not set(Path(n).relative_to(root).as_posix() for n in system['inputs_sha256']).issubset(packet['baseline']):raise ValueError('System architecture/interface inputs missing from review baseline')
            for f in system['findings']:risk(f['rule'],f['description'],f['location'],f['level'],f['fix'])
        checks=[evaluate_rule(t,facts) for t in spec['tasks']]
        saved=json.loads(local(folder,packet['checks_file']).read_text())
        if checks!=saved:raise ValueError('Deterministic results do not match captured facts/config')
        tasks={t['id']:t for t in spec['tasks']};issues=[];bycheck={c['task_id']:c for c in checks}
        for c in checks:
            if c['status']=='BLOCKED':risk('STATIC.CHECK.INPUT',str(c['detail']),c['task_id'])
            elif c['status']=='FAIL':
                t=tasks[c['task_id']];risk('STATIC.CHECK.FAIL',str(c['detail']),c['task_id'],t['level'])
        if ai_file is None or not Path(ai_file).is_file():
            preexisting=any(f['level']=='阻断级' for f in findings)
            risk('STATIC.AI.PENDING','尚未完成AI逐项静态工程评审');return {'status':'BLOCKED' if preexisting else 'AI_REVIEW_PENDING','review_state':'ai_pending','stage':stage,'production_authorized':False,'findings':findings,'inputs_sha256':inputs}
        ai_path=Path(ai_file).resolve();ai=finite_tree(json.loads(ai_path.read_text()));inputs[str(ai_path)]=sha256(ai_path)
        if ai.get('schema_version')!=1 or ai.get('scope')!='static_only' or ai.get('stage')!=stage or ai.get('packet_sha256')!=sha256(packet_path):raise ValueError('AI report stage/packet binding invalid')
        who=ai.get('reviewer',{})
        if who.get('type')!='ai' or not who.get('model'):raise ValueError('Actual AI model/reviewer identity required')
        dt.date.fromisoformat(who['date'])
        if set(ai.get('deferred_dynamic_tests',[]))!=set(DYNAMIC):raise ValueError('Dynamic tests must remain explicitly unverified')
        coverage=ai.get('coverage',{});graph=facts['netlist'];board=facts.get('board') or {}
        for key,expected in [('components',set(graph['components'])),('critical_nets',set(spec['critical_nets'])),('layers',set(board.get('copper_layers',[])))]:
            actual=coverage.get(key)
            if not isinstance(actual,list) or len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('AI review coverage incomplete/unknown: '+key)
        rows=ai.get('items',[]);ids=[r.get('task_id') for r in rows]
        if len(ids)!=len(set(ids)) or set(ids)!=set(tasks):raise ValueError('AI tasks missing/duplicated/unknown')
        for row in rows:
            t=tasks[row['task_id']]
            if row.get('status') not in ('PASS','FAIL','NEEDS_EVIDENCE','NOT_APPLICABLE') or row.get('level')!=t['level']:raise ValueError('AI changed severity or invalid status')
            if not row.get('applicability') or not row.get('reasoning') or not row.get('verification'):raise ValueError('AI conclusion needs applicability, reasoning and verification method')
            observations(row.get('observations'),facts,packet)
            for kind,key in [('refs','ref'),('nets','net'),('layers','layer'),('footprints','footprint')]:
                seen={o[key] for o in row['observations'] if key in o}
                if not set(t['targets'].get(kind,[])).issubset(seen):raise ValueError('Task targets were not actually identified in observations')
            if t.get('category')=='system_integration':
                report=json.loads(local(folder,'system-integration.json').read_text())
                seen_refs={o['ref'] for o in row['observations'] if 'ref' in o};seen_nets={o['net'] for o in row['observations'] if 'net' in o};seen_views={o['view'] for o in row['observations'] if 'view' in o}
                needed_refs={ref for refs in report['module_components'].values() for ref in refs}
                needed_nets={net['net'] for net in report['checked_nets']}
                overview_views={v['file'] for v in packet['views'] if v.get('kind')=='system_architecture_overview'}
                schematic_views={v['file'] for v in packet['views'] if v.get('kind')=='schematic'} if packet.get('native_ready') else set()
                if not needed_refs.issubset(seen_refs) or not needed_nets.issubset(seen_nets) or not overview_views.issubset(seen_views) or not schematic_views.issubset(seen_views):
                    raise ValueError('System integration AI task must observe every module component, declared interface net, top-level architecture page and native schematic PDF')
            allowed={(s['document_id'],s['locator']) for s in t['source_refs']}
            citations(row.get('source_citations'),allowed,packet,folder)
            if bycheck[t['id']]['status']=='FAIL' and row['status']!='FAIL':raise ValueError('AI cannot override deterministic failure')
            if bycheck[t['id']]['status']=='PASS' and row['status']=='NOT_APPLICABLE':raise ValueError('Measured applicable predicate cannot become N/A')
            if row['status']=='NEEDS_EVIDENCE':risk('STATIC.AI.UNRESOLVED','静态要求证据不足，不得当通过',t['id'])
            if row['status']=='FAIL':
                if not row.get('fix'):raise ValueError('Failed item needs actionable fix')
                risk('STATIC.AI.FAIL',row['reasoning'],t['id'],row['level']);issues.append(row)
            if row['status']=='NOT_APPLICABLE':issues.append(row)
        observed_refs={o['ref'] for row in rows for o in row['observations'] if 'ref' in o}
        observed_nets={o['net'] for row in rows for o in row['observations'] if 'net' in o}
        if not set(graph['components']).issubset(observed_refs) or not set(spec['critical_nets']).issubset(observed_nets):
            raise ValueError('Claimed component/critical-net coverage lacks actual observations')
        for ref in graph['components']:
            linked=set(spec['component_sources'].get(ref,[]))
            read_sources={c['document_id'] for row in rows if any(o.get('ref')==ref for o in row['observations']) for c in row['source_citations']}
            if not linked.intersection(read_sources):raise ValueError('Component has no observed review against its applicable source: '+ref)
        if packet.get('native_ready'):
            observed={o['view'] for row in rows for o in row['observations'] if 'view' in o}
            required_views={v['file'] for v in packet['views']}
            if not required_views or not required_views.issubset(observed):raise ValueError('AI visual review of schematic/all copper layers incomplete')
        additional=ai.get('additional_findings')
        if not isinstance(additional,list):raise ValueError('Additional findings array required, even if empty')
        extra_ids=set()
        for row in additional:
            rid=row.get('id')
            if not rid or rid in extra_ids or rid in tasks or row.get('level') not in LEVELS:raise ValueError('Invalid additional finding ID/severity')
            extra_ids.add(rid)
            if not all(row.get(k) for k in ('reasoning','fix','verification')):raise ValueError('Additional issue details incomplete')
            observations(row.get('observations'),facts,packet)
            refs={(s['document_id'],s['locator']) for t in spec['tasks'] for s in t['source_refs']}
            citations(row.get('source_citations'),{(x['document_id'],x['locator']) for x in row.get('source_citations',[])},packet,folder)
            if any((x['document_id'],x['locator']) not in refs for x in row['source_citations']):raise ValueError('Additional finding cites unapproved source/location')
            row={**row,'task_id':rid,'status':'FAIL'};issues.append(row);risk('STATIC.AI.EXTRA',row['reasoning'],rid,row['level'])
        if engineer_file is None or not Path(engineer_file).is_file():
            preexisting=any(f['level']=='阻断级' for f in findings)
            risk('STATIC.ENGINEER.PENDING','AI评审已提交，尚无硬件工程师对本版报告的最终确认')
            result_status='BLOCKED' if preexisting else 'ENGINEER_REVIEW_PENDING'
        else:
            eng_path=Path(engineer_file).resolve();eng=finite_tree(json.loads(eng_path.read_text()));inputs[str(eng_path)]=sha256(eng_path)
            if eng.get('schema_version')!=1 or eng.get('role')!='hardware_engineer' or eng.get('scope')!='static_only' or eng.get('decision')!='approve' or not eng.get('name') or not eng.get('reason'):
                raise ValueError('Real hardware engineer approval record required')
            dt.date.fromisoformat(eng['date'])
            if eng.get('packet_sha256')!=sha256(packet_path) or eng.get('ai_review_sha256')!=sha256(ai_path):raise ValueError('Engineer approved another packet/report')
            if set(eng.get('dynamic_tests_not_approved',[]))!=set(DYNAMIC):raise ValueError('Engineer signoff cannot silently approve dynamic testing')
            for item in issues:
                disposition=eng.get('dispositions',{}).get(item['task_id'],{})
                required='not_applicable' if item['status']=='NOT_APPLICABLE' else 'accept_deviation'
                if disposition.get('action')!=required or disposition.get('item_sha256')!=digest(item) or not disposition.get('reason'):
                    risk('STATIC.DISPOSITION','缺少针对当前问题/不适用项的逐项工程判断',item['task_id'])
                if item['status']=='FAIL' and item['level']=='阻断级':risk('STATIC.NONWAIVABLE','当前阻断问题必须修复并重审，不能以签字豁免',item['task_id'])
            evidence=eng.get('evidence')
            if not isinstance(evidence,list) or not evidence:raise ValueError('Actual engineer review evidence file/hash required')
            for rec in evidence:
                p=local(root,rec['file'])
                if not p.is_file() or not p.stat().st_size or sha256(p)!=rec['sha256']:raise ValueError('Engineer evidence missing/changed')
                inputs[str(p)]=sha256(p)
            result_status='APPROVED_STATIC' if not any(f['level']=='阻断级' for f in findings) else 'BLOCKED'
        return {'status':result_status,'stage':stage,'scope':'static_only','production_authorized':False,
                'review_state':'engineer_pending' if engineer_file is None else 'changes_required' if result_status=='BLOCKED' else 'engineer_confirmed',
                'issue_fingerprints':{item['task_id']:digest(item) for item in issues},
                'findings':findings,'inputs_sha256':inputs,'note':'Static review only. Human identity/authenticity and dynamic validation remain outside this script.'}
    except Exception as e:risk('STATIC.CONTRACT',str(e))
    return {'status':'BLOCKED','production_authorized':False,'findings':findings,'inputs_sha256':inputs}

def integrate(r,root,config):
    for stage in CATEGORIES_NAMES:
        item=config.get('static_ai_reviews',{}).get(stage,{})
        try:
            if not all(item.get(k) for k in ('packet','ai_review','engineer_review')):raise ValueError('Missing AI/hardware review paths')
            result=validate(root,local(root,item['packet']),local(root,item['ai_review']),local(root,item['engineer_review']))
            if result.get('stage')!=stage:raise ValueError('Wrong review stage')
            r.inputs.update(result['inputs_sha256']);r.evidence.append({'static_ai_review':result})
            if result['status']!='APPROVED_STATIC':r.risk('STATIC.'+stage.upper(),'schematic' if stage=='schematic' else 'routing','阻断级','AI静态评审/工程师确认未完成：'+result['status'],fix='按static-ai-review.md完成真实逐项评审并由硬件工程师确认；不允许AI自签。')
            for f in result['findings']:
                r.risk(f['rule'],stage,f['level'],f['description'],f['location'],f['reference'],f['suggestion'],'静态AI评审与工程师签核')
        except Exception as e:r.risk('STATIC.'+stage.upper(),'npi','阻断级',str(e),fix='准备该阶段静态资料包、AI评审报告与当前版本工程师签核。')

CATEGORIES_NAMES=('schematic','pcb')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--packet',required=True);p.add_argument('--ai-review');p.add_argument('--engineer-review');a=p.parse_args()
    r=validate(a.project,a.packet,a.ai_review,a.engineer_review);print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status']=='APPROVED_STATIC' else 2

if __name__=='__main__':raise SystemExit(main())
