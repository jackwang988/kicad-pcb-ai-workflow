#!/usr/bin/env python3
"""R22: refill/save/reload ONLY a fresh project copy. Never edits the source.

Final ERC/DRC/parity/spec review must follow on the resulting candidate.
The generated freeze log never claims those follow-on checks passed.
"""
import argparse
import json
import shutil
from pathlib import Path
from npi_common import environment,sha256,write_json

def freeze(project,board_relative,destination,apply=False):
    project=Path(project).resolve();dest=Path(destination).resolve();board=(project/board_relative).resolve()
    if not board.is_relative_to(project) or not board.is_file():raise ValueError('Invalid board path')
    if dest.exists() or dest.is_relative_to(project) or project.is_relative_to(dest):raise ValueError('Destination must be a new independent directory')
    if any(x.is_symlink() for x in project.rglob('*')):raise ValueError('Symlinks in project are not accepted')
    if not apply:return {'status':'PREVIEW','source_sha256':sha256(board),'destination':str(dest),'operations':['copy','refill','save','reload']}
    env=environment()
    if not env.get('pcbnew_exact_target'):raise ValueError('KiCad 10.0.7 pcbnew required')
    import pcbnew
    before=sha256(board)
    shutil.copytree(project,dest,ignore=shutil.ignore_patterns('.git','__pycache__'))
    try:
        target=dest/board_relative;b=pcbnew.LoadBoard(str(target))
        if b is None:raise RuntimeError('LoadBoard returned None')
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        if pcbnew.SaveBoard(str(target),b) is False:raise RuntimeError('SaveBoard failed')
        loaded=pcbnew.LoadBoard(str(target))
        if loaded is None:raise RuntimeError('Reload failed')
        if sha256(board)!=before:raise RuntimeError('Source changed during preparation')
        result={'status':'FROZEN_NOT_VALIDATED','operations':['copy','refill','save','reload'],
                'source_sha256':before,'candidate_sha256':sha256(target),'environment':env,
                'remaining':['erc','drc','schematic_parity','spec_review','CAM','EQ','production_authorization']}
        write_json(dest/'freeze-log.json',result);return result
    except Exception:
        shutil.rmtree(dest);raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--board',required=True);p.add_argument('--destination',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:r=freeze(a.project,a.board,a.destination,a.apply)
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
