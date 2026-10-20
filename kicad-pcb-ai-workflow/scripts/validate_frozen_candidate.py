#!/usr/bin/env python3
"""R22: run final checks on a refilled/saved/reloaded independent candidate.

Only creates a new evidence directory. No production files are generated.
"""
import argparse
import json
import shutil
from pathlib import Path
from npi_common import sha256,write_json
from mass_production_review import evaluate,write_report

def validate(project,config,output,cli=None):
    project=Path(project).resolve();config=Path(config).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Evidence output directory must be new')
    cfg=json.loads(config.read_text());board=(project/cfg['inputs']['board']).resolve()
    if not board.is_relative_to(project):raise ValueError('Unsafe board input')
    frozen=json.loads((project/'freeze-log.json').read_text())
    if frozen.get('operations')!=['copy','refill','save','reload'] or frozen.get('candidate_sha256')!=sha256(board):
        raise ValueError('Candidate changed since refill/save/reload; freeze again')
    result=evaluate(project,config,'mass_production','pre_export',cli,False,None)
    write_report(result,output)
    checked={e.get('kind') for e in result['evidence'] if isinstance(e,dict)}
    ok=not result['blocked'] and {'erc','drc'}.issubset(checked)
    final={'status':'PASS' if ok else 'BLOCKED','board_sha256':sha256(board),
           'operations':['refill','save','reload','erc','drc','schematic_parity','spec_review'],
           'freeze_log_sha256':sha256(project/'freeze-log.json'),
           'full_review_sha256':sha256(output/'npi-report.json'),'full_review_file':'npi-report.json',
           'counts':result['counts'],'scope':'Final design state checks only; CAM/EQ/D2 authorization remain separate.'}
    final['freeze_log_file']='freeze-log.json'
    shutil.copyfile(project/'freeze-log.json',output/'freeze-log.json')
    write_json(output/'final-state.json',final);return final

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--config',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--kicad-cli');a=p.parse_args()
    try:r=validate(a.project,a.config,a.output_dir,a.kicad_cli)
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
