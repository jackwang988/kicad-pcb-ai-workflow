#!/usr/bin/env python3
"""Read-only risk-based reserve/DNP checks. No automatic component insertion."""
import argparse
import datetime as dt
import json
import math
import re
from pathlib import Path
from npi_common import sha256,finite_tree,LEVELS,load_board
from design_intent import local
from netlist_guard import read_netlist
from assembly_guard import read_bom,check_cpl

CONTEXTS={'low_speed','high_speed','rf','power','clock','analog'}
ROLES={'selection_link','series_tuning','shunt_tuning','power_link','architecture_option','diagnostic'}

def read(p):return finite_tree(json.loads(Path(p).read_text(encoding='utf-8-sig')))
def need(row,keys):
    if any(not isinstance(row.get(k),str) or not row[k].strip() for k in keys):raise ValueError('Missing nonempty fields: '+','.join(keys))
def number(n):
    if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<0:raise ValueError('Explicit nonnegative finite number required')
    return n

def audit(root,policy,graph,stage='schematic',board=None,board_file=None,bom=None,cpl=None,variant=None):
    root=Path(root).resolve();policy=Path(policy).resolve();inputs={str(policy):sha256(policy)};findings=[];checks=[]
    def risk(code,desc,loc='project-wide',level='\u963b\u65ad\u7ea7',fix='Repair policy/assembly state or supply real current-revision evidence; do not invent approval.'):
        findings.append(dict(rule=code,level=level,location=loc,description=desc,reference='Exact manufacturer constraints, product requirements and reserve/assembly/manufacturing contract',suggestion=fix))
    def evidence(record):
        need(record,('file','sha256'));p=local(root,record['file'])
        if not p.is_file() or not p.stat().st_size or sha256(p)!=record['sha256']:raise ValueError('Missing/changed reserve evidence '+record['file'])
        inputs[str(p)]=record['sha256'];return p
    try:
        if not policy.is_relative_to(root) or stage not in ('schematic','pcb','npi'):raise ValueError('Policy must be in project; explicit known stage required')
        q=read(policy)
        if q.get('schema_version')!=1:raise ValueError('Unknown reserve schema')
        need(q,('default_variant','scope_reason'))
        items=q.get('decisions');variants=q.get('variants');parts=graph['components']
        if not isinstance(items,list) or not items or not isinstance(variants,list) or not variants:raise ValueError('Explicit critical-block decisions and variants required, even when no reserves are needed')
        names=[v['name'] for v in variants]
        if len(names)!=len(set(names)) or q['default_variant'] not in names:raise ValueError('Duplicate/missing default variant')
        default=next(v['parts'] for v in variants if v['name']==q['default_variant']);refs=set();ids=[];dependencies=[]
        for row in items:
            need(row,('id','block','uncertainty','decision','reason','verification_plan'))
            if not isinstance(row.get('required'),bool):raise ValueError('Explicit required boolean needed')
            if row['decision'] not in ('reserve','no_reserve'):raise ValueError('Decision must reserve/no_reserve')
            ids.append(row['id'])
            source=row.get('source',{});need(source,('file','sha256','locator'));evidence(source)
            cost=row.get('cost',{});number(cost.get('area_mm2'));number(cost.get('material_delta'));need(cost,('currency','assembly_risk','signal_risk','benefit_reason'))
            if row['decision']=='no_reserve':
                absent=row.get('absent_refs',[])
                if not isinstance(absent,list) or len(absent)!=len(set(absent)):raise ValueError('Explicit unique removed-reference list required')
                for ref in absent:
                    if ref in parts or (board is not None and ref in {f['ref'] for f in board['footprints']}):risk('RESERVE.ABSENT','Declared removed reserve reference still exists in schematic/PCB',ref)
                if stage=='npi' and bom:
                    if set(absent).intersection(r['Reference'] for r in read_bom(bom) if r['Variant']==variant):risk('RESERVE.ABSENT','Removed reserve reference still appears in selected production BOM',row['id'])
                if row.get('refs'):raise ValueError('no_reserve has active refs; archive removed options through ECO')
                if row['required']:risk('RESERVE.REQUIRED','Required reserve option is not implemented',row['id'])
                else:checks.append({'id':row['id'],'status':'NO_RESERVE_DECLARED','reason':row['reason']})
                continue
            if row.get('context') not in CONTEXTS or row.get('role') not in ROLES:raise ValueError('Explicit supported context/role required')
            selected=row.get('refs')
            if not isinstance(selected,list) or not selected or len(selected)!=len(set(selected)) or refs.intersection(selected):raise ValueError('Missing/duplicate option reference inventory')
            refs.update(selected)
            if not row.get('nets') or not set(row['nets']).issubset(graph['nets']):raise ValueError('Unknown/empty reserve network inventory')
            for ref in selected:
                if ref not in parts or ref not in default:raise ValueError('Reserve part absent from default schematic/matrix: '+ref)
                actual=parts[ref];state=default[ref]
                if actual['value']!=state['value'] or actual.get('fields',{}).get('DNP','').lower()!=('no' if state['fitted'] else 'yes'):risk('RESERVE.DEFAULT','Default value or DNP field differs from actual schematic',ref)
                if state['fitted'] and actual.get('fields',{}).get('MPN')!=state['mpn']:risk('RESERVE.MPN','Fitted default MPN differs from schematic field',ref)
            if not row.get('safety_evidence'):risk('RESERVE.SAFETY','No verified default safe state, switch conditions or DNP-state review',row['id'])
            for ev in row.get('safety_evidence',[]):evidence(ev)
            for v in variants:
                for ref in selected:
                    state=v['parts'][ref];need(state,('value',))
                    if not isinstance(state.get('fitted'),bool):raise ValueError('fitted must be boolean, not NC or text')
                    if state['fitted']:
                        need(state,('mpn',))
                        if re.fullmatch(r'0+(?:\.0+)?(?:[rkm]0*|ω|ohms?)?',re.sub(r'\s+','',state['value']).lower()):
                            zero=row.get('zero_ohm',{});need(zero,('reason',))
                            if zero.get('allowed') is not True or not zero.get('evidence'):risk('RESERVE.ZERO',f"Variant {v['name']} zero-ohm option lacks support; cannot replace feedback/current-limit/matching parameters implicitly",ref)
                            for ev in zero.get('evidence',[]):evidence(ev)
                            if row['context']=='power':
                                if number(zero.get('approved_current_a'))<number(zero.get('required_current_a')):risk('RESERVE.CURRENT',f"Variant {v['name']} zero-ohm approved ampacity is below the requirement",ref)
            if stage in ('pcb','npi'):
                if board is None or board_file is None:raise ValueError('PCB-stage requires actual board and hash')
                available={f['ref'] for f in board['footprints']}
                if not set(selected).issubset(available):risk('RESERVE.FOOTPRINT','DNP reserve footprint or pads missing from actual PCB',row['id'])
                layout=row.get('layout_review',{});need(layout,('reason','reviewer','date','board_sha256'))
                dt.date.fromisoformat(layout['date'])
                if layout['board_sha256']!=sha256(board_file):risk('RESERVE.LAYOUT.STALE','Reserve layout review is not bound to current PCB',row['id'])
                if not layout.get('evidence'):risk('RESERVE.LAYOUT','No stub/impedance/return/current/assembly/mechanical applicability evidence',row['id'])
                for ev in layout.get('evidence',[]):evidence(ev)
                inputs[str(Path(board_file).resolve())]=sha256(board_file)
                if row['context'] in ('high_speed','rf','clock') and layout.get('sensitive_path_checked') is not True:risk('RESERVE.SENSITIVE','High-speed/RF/clock option lacks actual stub and parasitic-effect review',row['id'])
            if stage=='npi':
                disposition=row.get('production',{});need(disposition,('action','reason'))
                if disposition['action'] not in ('retain','dnp_only'):risk('RESERVE.PRODUCTION','Production reserve disposition unresolved; removal requires ECO in real design and BOM',row['id'])
                if not disposition.get('evidence'):risk('RESERVE.PRODUCTION','No actual evidence for production retain/DNP decision',row['id'])
                for ev in disposition.get('evidence',[]):evidence(ev)
                if disposition['action']=='dnp_only' and any(v['parts'][r]['fitted'] for v in variants for r in selected):risk('RESERVE.PRODUCTION','Declared all DNP but at least one variant still fits the part',row['id'])
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate block decision IDs')
        for v in variants:
            if set(v['parts'])!=refs:raise ValueError('Each declared variant must contain every reserved ref exactly once')
        for group in q.get('groups',[]):
            need(group,('id','reason'));members=group['members']
            if not members or len(members)!=len(set(members)) or not set(members).issubset(refs):raise ValueError('Invalid mutual exclusion group')
            lo,hi=group['min_fitted'],group['max_fitted']
            if any(isinstance(n,bool) or not isinstance(n,int) for n in (lo,hi)) or not 0<=lo<=hi<=len(members):raise ValueError('Invalid group bounds')
            for v in variants:
                count=sum(v['parts'][r]['fitted'] for r in members)
                if not lo<=count<=hi:risk('RESERVE.MUTEX',f"Variant {v['name']} fitted-count {count} violates mutual-exclusion/required range {lo}..{hi}",group['id'])
        # Every selection/architecture alternative needs explicit grouping; physical electrical conflicts still need AI/human review.
        grouped={r for g in q.get('groups',[]) for r in g['members']}
        for row in items:
            if row['decision']=='reserve' and row['role'] in ('selection_link','architecture_option') and not set(row['refs']).issubset(grouped):risk('RESERVE.MUTEX.MISSING','Selector/architecture alternatives lack explicit mutex fit constraints',row['id'])
        if stage=='npi':
            if not bom or not cpl or variant not in names:raise ValueError('NPI requires actual selected-variant production BOM/CPL')
            rows=read_bom(bom);check_cpl(rows,cpl,variant);actual={r['Reference']:r for r in rows if r['Variant']==variant}
            expected=next(v['parts'] for v in variants if v['name']==variant)
            for ref,state in expected.items():
                row=actual.get(ref)
                if not row or row['DNP'].lower()!=('no' if state['fitted'] else 'yes') or row['Specification']!=state['value'] or (state['fitted'] and row['MPN']!=state['mpn']):risk('RESERVE.BOM','Production BOM DNP/value/MPN differs from selected assembly matrix',ref)
            inputs[str(Path(bom).resolve())]=sha256(bom);inputs[str(Path(cpl).resolve())]=sha256(cpl)
        checks.append({'status':'DECLARED_SCOPE_CHECKED','decisions':len(items),'reserved_refs':sorted(refs),'variants':names})
    except Exception as e:risk('RESERVE.CONTRACT',str(e))
    return {'status':'BLOCKED' if any(f['level']=='\u963b\u65ad\u7ea7' for f in findings) else 'STATIC_CHECKS_COMPLETE','scope':'declared_reserve_options_only','stage':stage,'production_authorized':False,'findings':findings,'checks':checks,'inputs_sha256':inputs,'limits':['No automatic reserve insertion or complete IC/risk discovery','No electrical simulation, true SI/stub solving or authentication of evidence/reviewer']}

def validate_review_binding(root,config,stage):
    policy=read(local(Path(root).resolve(),config['reserve_review']['policy']))
    tasks=[t for t in config['stages'][stage]['tasks'] if t.get('category')=='reserve_options' and t.get('check',{}).get('kind')=='semantic']
    if not tasks:raise ValueError('Explicit AI reserve decision review task required')
    refs={r for row in policy['decisions'] for r in row.get('refs',[])}
    nets={n for row in policy['decisions'] if row['decision']=='reserve' for n in row.get('nets',[])}
    if not refs.issubset({r for t in tasks for r in t['targets'].get('refs',[])}) or not nets.issubset({n for t in tasks for n in t['targets'].get('nets',[])}):raise ValueError('Reserve AI task misses actual option refs/nets')
    docs={d['id']:d for d in config['documents']}
    for row in policy['decisions']:
        src=row['source']
        if not any(docs[s['document_id']]['file']==src['file'] and docs[s['document_id']]['sha256']==src['sha256'] and s['locator']==src['locator'] for t in tasks for s in t['source_refs']):raise ValueError('Reserve decision source/location absent from AI review documents/tasks')

def integrate(r,root,config,candidate=None,board_file=None):
    try:
        entry=config.get('reserve_review')
        if not isinstance(entry,dict) or not entry.get('policy'):raise ValueError('Missing risk-based reserve decision inventory; explicit no_reserve is allowed')
        from static_review_gate import validate
        review=config['static_ai_reviews']['pcb'];folder=local(root,review['packet'])
        verified=validate(root,folder,local(root,review['ai_review']),local(root,review['engineer_review']))
        if verified['status']!='APPROVED_STATIC':raise ValueError('Current PCB AI/hardware review required before NPI reserve acceptance')
        packet=read(folder/'packet.json');reviewed=packet['config']
        if reviewed.get('reserve_review',{}).get('policy')!=entry['policy']:raise ValueError('NPI policy differs from AI/hardware-reviewed reserve policy')
        if board_file is None or local(root,reviewed['stages']['pcb']['inputs']['board'])!=Path(board_file).resolve():raise ValueError('NPI board differs from AI/hardware-reviewed board')
        if entry.get('variant')!=reviewed['stages']['pcb'].get('variant','default') or read(local(root,entry['policy']))['default_variant']!=entry.get('variant'):raise ValueError('Selected variant must match current reviewed native variant/default matrix')
        facts=read(folder/'facts.json');stage='npi' if r.phase=='release' else 'pcb';bom=cpl=None;variant=entry.get('variant')
        if stage=='npi':
            manifest=config.get('delivery_manifest',{});bn=manifest.get('bom',[]);cn=manifest.get('cpl',[])
            if not candidate or len(bn)!=1 or len(cn)!=1:raise ValueError('Selected actual manufacturing BOM/CPL required')
            bom=local(Path(candidate).resolve(),bn[0]);cpl=local(Path(candidate).resolve(),cn[0])
            profile=read(local(root,config['engineering_profile']))
            if variant!=profile.get('assembly_variant'):raise ValueError('Reserve and manufacturing assembly variants differ')
        result=audit(root,local(root,entry['policy']),facts['netlist'],stage,facts['board'],board_file,bom,cpl,variant)
        r.inputs.update(result['inputs_sha256']);r.evidence.append({'reserve_review':result})
        for f in result['findings']:r.risk(f['rule'],'npi',f['level'],f['description'],f['location'],f['reference'],f['suggestion'])
    except Exception as e:r.risk('RESERVE.NPI','npi','\u963b\u65ad\u7ea7',str(e),fix='Document risk-backed reserve/omit rationale and review current PCB and selected production BOM/CPL.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--policy',required=True);p.add_argument('--netlist',required=True);p.add_argument('--stage',choices=['schematic','pcb','npi'],default='schematic');p.add_argument('--board');p.add_argument('--bom');p.add_argument('--cpl');p.add_argument('--variant');p.add_argument('--static-preview',action='store_true');a=p.parse_args()
    try:
        root=Path(a.project).resolve();net=local(root,a.netlist);board_path=local(root,a.board) if a.board else None
        result=audit(root,local(root,a.policy),read_netlist(net),a.stage,load_board(board_path,not a.static_preview) if board_path else None,board_path,local(root,a.bom) if a.bom else None,local(root,a.cpl) if a.cpl else None,a.variant)
        result['inputs_sha256'][str(net)]=sha256(net)
        if a.static_preview:result['native_geometry_verified']=False
        print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False}));return 2
if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__':raise SystemExit(main())
