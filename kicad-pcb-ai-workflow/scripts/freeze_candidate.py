#!/usr/bin/env python3
"""Konnect-only freeze handoff; never writes KiCad board geometry via pcbnew.

1. --apply copies the source to a new independent candidate and writes a request.
2. Konnect's separately fixture-accepted zone fill tool edits/saves that candidate.
3. --finalize checks an actual Konnect operation receipt, source immutability,
   saved zone geometry and native KiCad CLI reload+DRC.  No silent fallback.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from npi_common import sha256, write_json, parse_sexpr, children, cli_compatible, environment


def within(root, child):
    return child==root or child.is_relative_to(root)


def prepare(project, board_relative, destination, apply=False):
    project=Path(project).resolve(); dest=Path(destination).resolve()
    board=(project/board_relative).resolve()
    if not within(project,board) or board.suffix!='.kicad_pcb' or not board.is_file():
        raise ValueError('Existing project-local KiCad PCB file required')
    if dest.exists() or within(project,dest) or within(dest,project):
        raise ValueError('Destination must be a NEW independent directory')
    if any(p.is_symlink() for p in project.rglob('*')):
        raise ValueError('Symlinked projects are not accepted')
    result={'schema_version':2,'status':'PREVIEW','source_board':str(board),
            'source_board_sha256':sha256(board),'destination':str(dest),
            'required_operations':['copy','konnect_zone_fill','konnect_save_project','native_reload_and_drc'],
            'production_authorized':False}
    if not apply:return result
    shutil.copytree(project,dest,ignore=shutil.ignore_patterns('.git','__pycache__'))
    candidate=dest/board_relative
    try:
        if sha256(board)!=result['source_board_sha256'] or sha256(candidate)!=result['source_board_sha256']:
            raise ValueError('Original changed while staging candidate')
        handoff={**result,'status':'KONNECT_HANDOFF_PENDING','candidate_board':str(candidate),
                 'candidate_sha256_before':sha256(candidate),
                 'next_step':'Open candidate in KiCad, verify Konnect zone-fill capability on an isolated fixture, run accepted fill tool with --save-after, then finalize with its evidence report.'}
        write_json(dest/'freeze-handoff.json',handoff)
        return handoff
    except Exception:
        shutil.rmtree(dest)
        raise


def finalize(candidate_dir, board_relative, operation_report, cli='kicad-cli'):
    dest=Path(candidate_dir).resolve();board=(dest/board_relative).resolve()
    if not within(dest,board) or not board.is_file():
        raise ValueError('Candidate board missing or escapes directory')
    handoff=json.loads((dest/'freeze-handoff.json').read_text(encoding='utf-8'))
    if handoff.get('schema_version')!=2 or handoff.get('status')!='KONNECT_HANDOFF_PENDING':
        raise ValueError('No current Konnect freeze handoff')
    original=Path(handoff['source_board']).resolve()
    if (not original.is_file() or sha256(original)!=handoff['source_board_sha256']
            or handoff['candidate_board']!=str(board)
            or sha256(original)!=handoff['candidate_sha256_before']):
        raise ValueError('Source/candidate handoff identity changed')
    receipt_file=Path(operation_report).resolve()
    if not receipt_file.is_file() or within(dest,receipt_file):
        raise ValueError('Operation receipt must be a separate saved evidence file outside candidate')
    receipt=json.loads(receipt_file.read_text(encoding='utf-8'))
    if (receipt.get('schema_version')!=1 or receipt.get('status')!='OPERATION_EXECUTED_REQUIRES_PROJECT_REVIEW'
            or receipt.get('board')!=str(board) or receipt.get('original_board')!=str(original)
            or receipt.get('original_sha256')!=sha256(original)
            or receipt.get('board_before_sha256')!=handoff['candidate_sha256_before']
            or receipt.get('board_after_sha256')!=sha256(board)
            or receipt.get('save_completed') is not True
            or receipt.get('risk') not in ('L2','L3')
            or not re.search(r'(fill.*zone|zone.*fill)', receipt.get('tool',''),re.I)):
        raise ValueError('No exact matching Konnect zone-fill plus saved candidate evidence')
    tree=parse_sexpr(board.read_text(encoding='utf-8-sig'))
    if tree[0]!='kicad_pcb':raise ValueError('Candidate cannot be parsed as KiCad PCB')
    zones=children(tree,'zone')
    if zones and not any(children(z,'filled_polygon') for z in zones):
        raise ValueError('PCB contains zones, but saved file has no filled copper polygons')
    env=environment(cli)
    if not cli_compatible(env):
        raise ValueError('Real, supported KiCad CLI required for native reload/DRC; pcbnew is not needed')
    # Independently reloads saved PCB with KiCad CLI. Any violations block freeze.
    drc_file=dest/'freeze-native-drc.txt'
    if drc_file.exists():raise ValueError('Existing native DRC evidence would be overwritten')
    cmd=[str(env['kicad_cli']),'pcb','drc','--output',str(drc_file),str(board)]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
    if r.returncode!=0 or not drc_file.is_file():
        if drc_file.exists():drc_file.unlink()
        raise ValueError('KiCad CLI reload/DRC failed; candidate remains pending: '+r.stderr[-500:])
    if sha256(original)!=handoff['source_board_sha256'] or sha256(board)!=receipt['board_after_sha256']:
        raise ValueError('Source or candidate changed during native verification')
    result={'schema_version':2,'status':'FROZEN_NOT_VALIDATED',
            'operations':['copy','refill','save','reload'],
            'execution_backend':'Konnect MCP only','native_reload_method':'KiCad CLI pcb drc',
            'source_sha256':sha256(original),'candidate_sha256':sha256(board),
            'zone_count':len(zones),'operation_receipt_sha256':sha256(receipt_file),
            'native_drc_sha256':sha256(drc_file),'production_authorized':False,
            'remaining':['erc','netlist_parity','full_design_intent_review','engineer_review','CAM','EQ','production_authorization']}
    freeze_log=dest/'freeze-log.json'
    if freeze_log.exists():raise ValueError('Freeze log already exists; do not overwrite')
    write_json(freeze_log,result)
    return result



# Read-only compatibility for legacy R9.4 callers. The old pcbnew writer has
# deliberately not been restored: explicit --apply must use prepare()/Konnect.
def freeze(project, board_relative, destination, apply=False):
    if apply:
        raise ValueError('Legacy freeze write is disabled; use prepare() and approved Konnect handoff')
    return prepare(project, board_relative, destination, apply=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project',help='Original project for prepare; candidate directory for --finalize')
    p.add_argument('--board',required=True,help='Project-relative PCB path')
    p.add_argument('--destination',help='NEW independent candidate (prepare)')
    p.add_argument('--operation-report',help='Saved Konnect capability invoke report')
    p.add_argument('--kicad-cli',default='kicad-cli')
    g=p.add_mutually_exclusive_group()
    g.add_argument('--apply',action='store_true',help='Stage copy; never modifies board geometry')
    g.add_argument('--finalize',action='store_true',help='Validate prior Konnect fill+save evidence and native CLI DRC')
    args=p.parse_args()
    try:
        if args.finalize:
            if not args.operation_report:raise ValueError('--finalize requires --operation-report')
            result=finalize(args.project,args.board,args.operation_report,args.kicad_cli)
        else:
            if not args.destination:raise ValueError('--destination required for prepare')
            result=prepare(args.project,args.board,args.destination,args.apply)
    except Exception as exc:
        result={'status':'BLOCKED','reason':str(exc),'production_authorized':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result['status']=='BLOCKED' else 0

if __name__=='__main__':
    raise SystemExit(main())
