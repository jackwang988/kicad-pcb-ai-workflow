#!/usr/bin/env python3
"""Universal project intake/navigation and allowlisted tool entry, not approval.

init is preview unless --apply; check/plan are read-only. A completed contract
means declared inputs exist, never that hardware or a stage passed.
"""
import argparse
from schematic_io import blocking
import ast
import json
import subprocess
import sys
from pathlib import Path
from engineering_gate import local
from npi_common import finite_tree,sha256,runtime_inventory

STAGES=('environment','requirements','sources','reserve','schematic','schematic_review','footprints','stackup','placement','routing','pcb_review','npi','manufacturing','cam_release','prototype','eco')
TOOLS={
 'environment':['environment_start','doctor','kicad_ipc_probe','konnect_backend','konnect_capabilities'],'requirements':[],'sources':['device_knowledge'],'reserve':['reserve_review'],
 'schematic':['schematic_candidate','schematic_style','system_integration'],'schematic_review':['static_review','static_review_gate','system_integration'],
 'footprints':['pad_audit','resource_guard'],'stackup':['design_intent','design_intent_audit'],'placement':['placement_review'],
 'routing':['routing_policy','script_route_search','link_audit','freeze_candidate','freerouting_adapter'],'pcb_review':['static_review','static_review_gate'],
 'npi':['mass_production_review','validate_frozen_candidate'],'manufacturing':['manufacturing_export','build_manifest'],
 'cam_release':['npi_release'],'prototype':[],'eco':['netlist_guard']}
FEATURES=('power','differential','rf','high_speed','safety','thermal','testability','assembly_variants')
SKILL=Path(__file__).resolve().parents[1]

def template():
    return {'schema_version':1,'project_id':None,'revision':None,'inputs':{'schematic':None,'board':None,'project':None},'requirements':[],
            'features':{f:{'applicability':'undecided','reason':None,'source':None} for f in FEATURES},
            'stages':{s:{'executor':None,'method':None,'required_files':[],'verification_tools':TOOLS[s]} for s in STAGES},
            'scope_note':'Project-specific declared inputs only; no automatic engineering approval or unsupported capability promise'}

def registry():
    return runtime_inventory(SKILL)

def check(root,contract,through=None):
    root=Path(root).resolve();p=local(root,contract);q=finite_tree(json.loads(p.read_text(encoding='utf-8-sig')));findings=[];inputs={str(p):sha256(p)};stages=[];allowed=registry()
    def risk(code,where,desc,fix):findings.append({'rule':code,'level':'\u963b\u65ad\u7ea7','location':where,'description':desc,'reference':'Project specifications, manufacturer/factory constraints and R9 project contract','suggestion':fix})
    def source(src):
        if not isinstance(src,dict) or not src.get('locator'):raise ValueError('Actual source file/hash/locator required')
        f=local(root,src['file'])
        if not f.is_file() or not f.stat().st_size or sha256(f)!=src.get('sha256'):raise ValueError('Source absent or changed')
        inputs[str(f)]=sha256(f)
    if q.get('schema_version')!=1:raise ValueError('Unknown project contract')
    if not all(isinstance(q.get(k),str) and q[k].strip() for k in ('project_id','revision')):risk('FLOW.IDENTITY','project','Project identity/revision is undefined','Enter actual project ID and revision.')
    for k,suffix in [('schematic','.kicad_sch'),('board','.kicad_pcb'),('project','.kicad_pro')]:
        name=q.get('inputs',{}).get(k)
        try:
            if not isinstance(name,str) or Path(name).suffix!=suffix:raise ValueError('Explicit path required')
            f=local(root,name)
            if not f.is_file() or not f.stat().st_size:raise ValueError('Missing project artifact')
            inputs[str(f)]=sha256(f)
        except Exception as e:risk('FLOW.INPUT',k,str(e),'Create actual stage artifacts first; do not use empty placeholder files.')
    requirements=q.get('requirements',[]);ids=[]
    if not isinstance(requirements,list) or not requirements:risk('FLOW.REQUIREMENTS','requirements','No quantitative requirement traceability','Record each requirement, acceptance criteria, source and verification stage.');requirements=[]
    for req in requirements:
        try:
            if not all(isinstance(req.get(k),str) and req[k].strip() for k in ('id','requirement','acceptance')):raise ValueError('Requirement/acceptance missing')
            ids.append(req['id']);source(req['source'])
            if not req.get('stages') or not set(req['stages']).issubset(STAGES):raise ValueError('Requirement needs actual verification stage mapping')
            verification=req.get('verification')
            if not isinstance(verification,list) or not verification:raise ValueError('Requirement needs actual rule task or external test plan mapping')
            for v in verification:
                if v.get('kind')=='static_task':
                    f=local(root,v['config']);cfg=json.loads(f.read_text(encoding='utf-8-sig'));inputs[str(f)]=sha256(f)
                    tasks=cfg['stages'][v['stage']]['tasks'];matches=[t for t in tasks if t['id']==v['task_id'] and t.get('requirement_id')==req['id']]
                    if len(matches)!=1:raise ValueError('Unknown task or requirement_id binding')
                elif v.get('kind')=='external_test_plan':source(v['source'])
                else:raise ValueError('Unsupported requirement verification method')
        except Exception as e:risk('FLOW.REQUIREMENT',str(req.get('id','unknown')),str(e),'Provide measurable acceptance and real sources; do not derive expected values from the output.')
    if len(ids)!=len(set(ids)):risk('FLOW.REQUIREMENT.ID','requirements','Duplicate requirement ID','Use a unique ID.')
    for feature in FEATURES:
        item=q.get('features',{}).get(feature,{})
        try:
            if item.get('applicability') not in ('required','not_applicable') or not item.get('reason'):raise ValueError('Applicability undecided or reason missing')
            source(item['source'])
        except Exception as e:risk('FLOW.APPLICABILITY',feature,str(e),'Decide applicability using real project conditions; required is not proof of implementation, and N/A requires rationale.')
    if set(q.get('stages',{}))!=set(STAGES):risk('FLOW.STAGES','stages','Stage set incomplete or contains unknown entries','Preserve all 16 nodes; future stages stay pending, never silently skipped.')
    for stage in STAGES:
        spec=q.get('stages',{}).get(stage,{});missing=[]
        if spec.get('executor') not in ('agent','native','engineer','external','combined') or not isinstance(spec.get('method'),str) or not spec['method'].strip():missing.append('explicit executor/method')
        names=spec.get('required_files');tools=spec.get('verification_tools')
        if not isinstance(names,list) or not isinstance(tools,list):missing.append('file/tool inventory');names=[];tools=[]
        for name in names:
            try:
                f=local(root,name)
                if not f.is_file() or not f.stat().st_size:raise ValueError('Absent stage input')
                inputs[str(f)]=sha256(f)
            except Exception:missing.append(str(name))
        if any(t not in allowed for t in tools):missing.append('unsupported/legacy tool')
        if missing and (through is None or STAGES.index(stage)<=STAGES.index(through)):risk('FLOW.STAGE',stage,'Missing: '+', '.join(missing),'Supply actual stage inputs/adapter; declared inputs alone are not engineering approval.')
        stages.append({'stage':stage,'status':'NEEDS_INPUT_OR_ADAPTER' if missing else 'DECLARED_INPUTS_READY_NOT_APPROVED','executor':spec.get('executor'),'method':spec.get('method'),'verification_tools':tools,'missing':missing})
    return {'status':'BLOCKED' if findings else 'DECLARED_CONTRACT_READY_NOT_APPROVED','scope':'workflow_intake_only','production_authorized':False,'findings':findings,'stages':stages,'inputs_sha256':inputs,'remaining':['Run actual native/AI/engineer checks for each applicable stage','SI/PI/safety/manufacturing and prototype validation are product-specific; no universal success claim']}

def dispatch(tool,args):
    tools=registry()
    if tool not in tools or tool=='project_flow':raise ValueError('Only active, nonrecursive tool entrypoints accepted; legacy scripts excluded')
    path=tools[tool];tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    if not any(isinstance(n,ast.If) and '__name__' in ast.unparse(n.test) for n in tree.body):raise ValueError('Module-only tool; use its documented owning command')
    # Explicit argv, no shell, no arbitrary executable or project-supplied code.
    return subprocess.run([sys.executable,'-B',str(path),*args],check=False).returncode

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('init');a.add_argument('--destination',required=True);a.add_argument('--apply',action='store_true')
    for cmd in ('check','plan'):
        a=sub.add_parser(cmd);a.add_argument('project');a.add_argument('--contract',default='project-flow.json');a.add_argument('--output-dir')
    a=sub.add_parser('run');a.add_argument('tool');a.add_argument('args',nargs=argparse.REMAINDER)
    a=p.parse_args()
    try:
        if a.cmd=='run':return dispatch(a.tool,a.args[1:] if a.args[:1]==['--'] else a.args)
        if a.cmd=='init':
            out=Path(a.destination)
            if out.exists():raise ValueError('New control directory required')
            r={'status':'PREVIEW','destination':str(out),'files':['project-flow.json'],'production_authorized':False}
            if a.apply:out.mkdir(parents=True,exist_ok=False);(out/'project-flow.json').write_text(json.dumps(template(),ensure_ascii=False,indent=2)+'\n', encoding='utf-8');r['status']='UNCONFIGURED_TEMPLATE_CREATED'
        else:
            r=check(a.project,a.contract)
            if a.output_dir:
                out=Path(a.output_dir)
                if out.exists():raise ValueError('New report directory required')
                out.mkdir(parents=True,exist_ok=False);(out/'flow-report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
        print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False,'findings':[blocking('INPUT.CONTRACT',e)]},ensure_ascii=False));return 2
if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__':raise SystemExit(main())
