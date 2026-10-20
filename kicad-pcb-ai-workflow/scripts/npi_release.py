#!/usr/bin/env python3
"""Review and publish an existing candidate package (including jobset outputs).

Default: preview only. --apply creates a NEW directory after every gate passes.
This does not intercept native GUI/CLI exports and does not execute arbitrary jobsets.
"""
import argparse
import json
import shutil
import tempfile
from pathlib import Path
from mass_production_review import evaluate
from npi_common import sha256

def release(project, config, candidate, destination, apply=False, cli=None):
    destination=Path(destination).resolve(); candidate=Path(candidate).resolve()
    if destination.exists(): raise ValueError('目标目录已存在，禁止覆盖')
    if destination.is_relative_to(candidate) or candidate.is_relative_to(destination):
        raise ValueError('候选目录与发布目录不得相互包含')
    report=evaluate(project,config,'mass_production','release',cli,False,candidate)
    if not report['release_allowed']:
        return {'released':False,'preview':not apply,'blocked':True,'counts':report['counts'],'findings':report['findings']}
    data=json.loads(Path(config).read_text(encoding='utf-8'))
    entries=sorted({f for files in data['delivery_manifest'].values() for f in files} | {'build-manifest.json'})
    # Include every validated log/review/freeze dependency in the final release.
    entries=sorted(set(entries) | {str(Path(file).relative_to(candidate)) for file in report['inputs_sha256'] if Path(file).is_relative_to(candidate)})
    if not apply: return {'released':False,'preview':True,'blocked':False,'files':entries}
    # Revalidate all engineering input and candidate hashes immediately before publication.
    for p,digest in report['inputs_sha256'].items():
        if not Path(p).is_file() or sha256(p)!=digest: raise ValueError('评审后输入发生变化：'+p)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.npi-stage-',dir=destination.parent) as temp:
        stage=Path(temp)/'release'; stage.mkdir()
        for name in entries:
            source=candidate/name
            if any(p.is_symlink() for p in [source,*source.parents] if p!=candidate.parent):
                raise ValueError('禁止发布符号链接：'+name)
            target=stage/name; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            if sha256(source)!=sha256(target): raise ValueError('复制哈希不一致：'+name)
        for p,digest in report['inputs_sha256'].items():
            if sha256(p)!=digest: raise ValueError('发布准备期间输入发生变化：'+p)
        # A new destination is reserved exclusively; no pre-existing directory is overwritten.
        destination.mkdir(exist_ok=False)
        try:
            for item in stage.iterdir(): shutil.move(str(item),str(destination/item.name))
        except Exception:
            shutil.rmtree(destination); raise
    return {'released':True,'preview':False,'blocked':False,'destination':str(destination),'files':entries}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project',type=Path); p.add_argument('--config',required=True,type=Path)
    p.add_argument('--candidate-dir',required=True,type=Path); p.add_argument('--destination',required=True,type=Path)
    p.add_argument('--kicad-cli'); p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try: result=release(a.project,a.config,a.candidate_dir,a.destination,a.apply,a.kicad_cli)
    except (OSError,ValueError,KeyError,TypeError) as e: p.exit(2,'禁止发布：'+str(e)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result['blocked'] else 0

if __name__=='__main__': raise SystemExit(main())
