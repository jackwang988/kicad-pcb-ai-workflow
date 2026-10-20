#!/usr/bin/env python3
"""First-run environment smoke test and read-only daily startup check.

No installation, global PATH changes, engineering writes or production approval.
Setup writes a new report only with --apply; check always probes current tools.
"""
import argparse
import datetime as dt
import importlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from npi_common import environment,run,sha256,runtime_inventory
from design_intent import local,digest
from netlist_guard import read_netlist

ROOT=Path(__file__).resolve().parents[1]

def inventory(project):
    result={}
    for p in project.rglob('*'):
        if set(p.relative_to(project).parts)&{'.git','__pycache__'}:continue
        if p.is_symlink():raise ValueError('Project smoke copy cannot contain symlinks')
        if p.is_file():result[str(p.relative_to(project))]=sha256(p)
    if not result:raise ValueError('Empty project')
    return result

def signature(cli=None):
    env=environment(cli);files={str(Path(sys.executable).resolve()):sha256(sys.executable)}
    if env.get('kicad_cli'):
        p=Path(shutil.which(str(env['kicad_cli'])) or env['kicad_cli']).resolve()
        if p.is_file():files[str(p)]=sha256(p)
    for name in ('pcbnew','_pcbnew'):
        try:
            module=importlib.import_module(name);p=Path(module.__file__).resolve();files[str(p)]=sha256(p)
        except (ImportError,AttributeError,TypeError):pass
    for p in runtime_inventory(ROOT).values():files[str(p.resolve())]=sha256(p)
    files[str((ROOT/'references/tool-manifest.json').resolve())]=sha256(ROOT/'references/tool-manifest.json')
    return {'os':platform.platform(),'python':str(Path(sys.executable).resolve()),
            'cli':str(Path(shutil.which(str(env['kicad_cli'])) or env['kicad_cli']).resolve()) if env.get('kicad_cli') else None,
            'configuration_sha256':digest({k:os.getenv(k) for k in ('PATH','PYTHONPATH','PYTHONHOME','KICAD_CONFIG_HOME','KICAD10_SYMBOL_DIR','KICAD10_FOOTPRINT_DIR')}),
            'files_sha256':files,'cli_version':env.get('cli_version'),'pcbnew_version':env.get('pcbnew_version')},env

def setup(project,schematic,board,project_file,output,cli=None,apply=False):
    project=Path(project).resolve();out=Path(output).resolve();sig,env=signature(cli)
    plan={'status':'PREVIEW','production_authorized':False,'environment':env,
          'project':str(project),'report_dir':str(out),'inputs':{'schematic':schematic,'board':board,'project_file':project_file},
          'plan':['Copy project into NEW report directory','Export schematic PDF/XML and PCB PDF','Run ERC/DRC and load board via pcbnew','Persist environment-only startup evidence']}
    if not env.get('cli_exact_target') or not env.get('pcbnew_exact_target'):
        return {**plan,'status':'BLOCKED','reason':'Required target CLI/pcbnew unavailable; configure the selected Python/CLI first'}
    if out.exists() or out==project or out.is_relative_to(project) or project.is_relative_to(out):raise ValueError('Use a NEW report directory outside project')
    if len({Path(n).stem for n in (schematic,board,project_file)})!=1:raise ValueError('Smoke project top schematic/PCB/project basenames must match')
    before=inventory(project)
    for name,suffix in ((schematic,'.kicad_sch'),(board,'.kicad_pcb'),(project_file,'.kicad_pro')):
        if not local(project,name).is_file() or Path(name).suffix!=suffix:raise ValueError('Missing/wrong project input '+name)
    if not apply:return plan
    out.mkdir(parents=True,exist_ok=False);copy=out/'project-copy';copy.mkdir();commands=[];design_issues={};design_ignored={}
    try:
        for n in before:
            dest=local(copy,n);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(local(project,n),dest)
        exe=env['kicad_cli'];sch=local(copy,schematic);pcb=local(copy,board)
        def invoke(args,target,violations=False):
            r=run(args);commands.append(r)
            if r['returncode'] not in ((0,5) if violations else (0,)) or not target.is_file() or not target.stat().st_size:raise ValueError('Native command failed: '+str(args))
            return r
        pdf=out/'schematic.pdf';invoke([exe,'sch','export','pdf','--output',str(pdf),str(sch)],pdf)
        if not pdf.read_bytes().startswith(b'%PDF-'):raise ValueError('Invalid schematic PDF')
        xml=out/'netlist.xml';invoke([exe,'sch','export','netlist','--format','kicadxml','--output',str(xml),str(sch)],xml);read_netlist(xml)
        pdf=out/'pcb.pdf';invoke([exe,'pcb','export','pdf','--layers','F.Cu,B.Cu','--output',str(pdf),str(pcb)],pdf)
        if not pdf.read_bytes().startswith(b'%PDF-'):raise ValueError('Invalid PCB PDF')
        from native_report import extract
        for sub,kind,src in (('sch','erc',sch),('pcb','drc',pcb)):
            target=out/(kind+'.json');args=[exe,sub,kind,'--format','json','--severity-all','--exit-code-violations','--output',str(target)]
            if kind=='drc':args+=['--schematic-parity']
            invoke(args+[str(src)],target,True)
            report=json.loads(target.read_text())
            # Startup validates tool/report compatibility, not project acceptance.
            # Production calls keep extract's default fail-closed ignored policy.
            design_issues[kind]=len(extract(kind,report,str(src),allow_ignored=True))
            design_ignored[kind]=report.get('ignored_checks',[])
        module=importlib.import_module('pcbnew');loaded=module.LoadBoard(str(pcb))
        if loaded is None:raise ValueError('pcbnew.LoadBoard failed')
        if inventory(project)!=before:raise ValueError('Original project changed during smoke test')
        artifacts={str(p.relative_to(out)):sha256(p) for p in out.rglob('*') if p.is_file()}
        state={'schema_version':1,'scope':'environment_only','status':'ENVIRONMENT_READY',
               'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'signature':sig,
               'source_project':str(project),'source_sha256':before,'artifacts_sha256':artifacts,
               'design_issue_counts':design_issues,'design_ignored_checks':design_ignored,
               'design_checks_complete':False,'commands':commands,'production_authorized':False,
               'manual_checks_remaining':['Agent can actually read PDF/figures','GUI symbol/footprint libraries and external dependencies','Project-specific rules and production checks']}
        (out/'startup-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
        return state
    except Exception as e:
        r={'status':'BLOCKED','scope':'environment_only','reason':str(e),'commands':commands,'production_authorized':False}
        (out/'failed-setup.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');return r

def check(state_file,cli=None,max_age_days=7):
    if not isinstance(max_age_days,int) or not 0<=max_age_days<=365:raise ValueError('max-age-days must be 0..365')
    sig,env=signature(cli)
    result={'status':'FULL_SETUP_REQUIRED','scope':'environment_only','production_authorized':False,'environment':env}
    if not env.get('cli_exact_target') or not env.get('pcbnew_exact_target'):return {**result,'status':'BLOCKED','reason':'Current required tools/version unavailable'}
    p=Path(state_file).resolve()
    if not p.is_file():return {**result,'reason':'No successful first-run record'}
    s=json.loads(p.read_text())
    if s.get('schema_version')!=1 or s.get('scope')!='environment_only' or s.get('status')!='ENVIRONMENT_READY' or s.get('signature')!=sig:return {**result,'reason':'Tool/interpreter/script signature changed or invalid state'}
    checked=dt.datetime.fromisoformat(s['checked_at'])
    if checked.tzinfo is None:raise ValueError('Startup timestamp requires timezone')
    age=(dt.datetime.now(dt.timezone.utc)-checked).total_seconds()
    if age<0 or age>max_age_days*86400:return {**result,'reason':'First-run record expired; repeat full setup smoke test'}
    if not {'schematic.pdf','pcb.pdf','netlist.xml','erc.json','drc.json'}.issubset(s.get('artifacts_sha256',{})):return {**result,'reason':'Incomplete first-run evidence'}
    for n,h in s.get('artifacts_sha256',{}).items():
        file=local(p.parent,n)
        if not file.is_file() or sha256(file)!=h:return {**result,'reason':'Stored smoke evidence missing/changed'}
    if not s.get('artifacts_sha256'):return {**result,'reason':'No smoke evidence inventory'}
    return {**result,'status':'ENVIRONMENT_READY','next':'Proceed to current project inputs; no reinstall needed. Current project/GUI/AI/production checks still required.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('setup');a.add_argument('--project',required=True);a.add_argument('--schematic',required=True);a.add_argument('--board',required=True);a.add_argument('--project-file',required=True);a.add_argument('--report-dir',required=True);a.add_argument('--apply',action='store_true');a.add_argument('--kicad-cli')
    a=sub.add_parser('check');a.add_argument('--state',required=True);a.add_argument('--kicad-cli');a.add_argument('--max-age-days',type=int,default=7)
    a=p.parse_args()
    try:
        if a.cmd=='setup':r=setup(a.project,a.schematic,a.board,a.project_file,a.report_dir,a.kicad_cli,a.apply)
        else:r=check(a.state,a.kicad_cli,a.max_age_days)
        print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status'] in ('PREVIEW','ENVIRONMENT_READY') else 2
    except Exception as e:print(json.dumps({'status':'BLOCKED','scope':'environment_only','reason':str(e),'production_authorized':False},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
