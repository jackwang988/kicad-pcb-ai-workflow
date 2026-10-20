#!/usr/bin/env python3
"""Collect real sources/outputs/log hashes. Default preview, never invent approval.

Does not generate Gerber/BOM or contact a factory. D2 requires a passing design
review plus supplied factory/CAM/authorization records; release rechecks them.
"""
import argparse
import json
from pathlib import Path
from npi_common import sha256,finite_tree
from mass_production_review import evaluate
from engineering_gate import local

def collect(project,config,candidate,records,level='D0',apply=False,cli=None):
    project=Path(project).resolve();config=Path(config).resolve();candidate=Path(candidate).resolve()
    cfg=finite_tree(json.loads(config.read_text()));approved=finite_tree(json.loads(Path(records).read_text()))
    output=candidate/'build-manifest.json'
    if output.exists():raise ValueError('Build manifest exists; overwrite forbidden')
    if not candidate.is_dir():raise ValueError('Existing isolated candidate directory required')
    design=evaluate(project,config,'mass_production','pre_export',cli,False,None)
    if level=='D2' and design['blocked']:raise ValueError('Design gates have unresolved blocking findings')
    sources={str(Path(p).relative_to(project)):h for p,h in design['inputs_sha256'].items() if Path(p).is_relative_to(project)}
    if cfg.get('engineering_profile'):
        profile=json.loads(local(project,cfg['engineering_profile']).read_text())
        # Include CAM/EQ review evidence deferred by pre_export, for subsequent release matching.
        for item in profile.get('reviews',{}).values():
            for rec in item.get('evidence',[]):
                f=local(project,rec['file'])
                if sha256(f)!=rec['sha256']:raise ValueError('Review evidence changed')
                sources[str(f.relative_to(project))]=sha256(f)
    outputs={}
    for names in cfg.get('delivery_manifest',{}).values():
        for name in names:
            if name=='build-manifest.json':continue
            f=local(candidate,name)
            if not f.is_file() or not f.stat().st_size:raise ValueError('Missing/empty candidate file '+name)
            outputs[name]=sha256(f)
    data={'level':level,'source_sha256':sources,'output_sha256':outputs,
          'tools':approved.get('tools',[]),'commands':approved.get('commands',[]),
          'production_authorization':approved.get('production_authorization',{}),'logs':[]}
    for key in ('cam_review','factory_eq','final_state_validation'):
        name=approved.get(key)
        if not name:
            if level=='D2':raise ValueError('Missing approved record path '+key)
            data[key]=None;continue
        f=local(candidate,name)
        if not f.is_file() or not f.stat().st_size:raise ValueError('Missing evidence file '+name)
        data[key]={'file':name,'sha256':sha256(f)}
    for name in approved.get('logs',[]):
        f=local(candidate,name)
        if not f.is_file() or not f.stat().st_size:raise ValueError('Missing actual log '+name)
        data['logs'].append({'file':name,'sha256':sha256(f)})
    if level=='D2' and (not data['tools'] or not data['commands'] or not data['logs'] or not all(data['production_authorization'].get(x) for x in ('reviewer','date','factory','order_scope'))):
        raise ValueError('D2 requires actual tool/command/log and production authorization records')
    if apply:
        with output.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
    return {'status':'MANIFEST_WRITTEN' if apply else 'PREVIEW','level':level,'source_count':len(sources),'output_count':len(outputs),
            'production_authorized':False,'note':'Manifest creation never grants release; run npi_release for fresh full checks.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--config',required=True);p.add_argument('--candidate-dir',required=True);p.add_argument('--records',required=True);p.add_argument('--level',choices=['D0','D1','D2'],default='D0');p.add_argument('--apply',action='store_true');p.add_argument('--kicad-cli');a=p.parse_args()
    try:r=collect(a.project,a.config,a.candidate_dir,a.records,a.level,a.apply,a.kicad_cli)
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
