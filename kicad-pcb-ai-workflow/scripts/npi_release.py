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
    if destination.exists(): raise ValueError('Target directory exists; overwriting is prohibited')
    if destination.is_relative_to(candidate) or candidate.is_relative_to(destination):
        raise ValueError('Candidate and release directories must not contain each other')
    report=evaluate(project,config,'mass_production','release',cli,False,candidate)
    if not report['release_allowed']:
        return {'released':False,'preview':not apply,'blocked':True,'counts':report['counts'],'findings':report['findings']}
    data=json.loads(Path(config).read_text(encoding='utf-8'))
    entries=sorted({f for files in data['delivery_manifest'].values() for f in files} | {'build-manifest.json'})
    # Include every validated log/review/freeze dependency in the final release.
    # Windows may report the same file through an 8.3 alias and its long name.
    # Compare canonical identities so validated nested evidence is not omitted.
    entries=sorted(set(entries) | {str(Path(file).resolve().relative_to(candidate)) for file in report['inputs_sha256'] if Path(file).resolve().is_relative_to(candidate)})
    if not apply: return {'released':False,'preview':True,'blocked':False,'files':entries}
    # Revalidate all engineering input and candidate hashes immediately before publication.
    for p,digest in report['inputs_sha256'].items():
        if not Path(p).is_file() or sha256(p)!=digest: raise ValueError('Input changed after review: '+p)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.npi-stage-',dir=destination.parent) as temp:
        stage=Path(temp)/'release'; stage.mkdir()
        for name in entries:
            source=candidate/name
            if any(p.is_symlink() for p in [source,*source.parents] if p!=candidate.parent):
                raise ValueError('Cannot release symlink: '+name)
            target=stage/name; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            if sha256(source)!=sha256(target): raise ValueError('Copy hash mismatch: '+name)
        for p,digest in report['inputs_sha256'].items():
            if sha256(p)!=digest: raise ValueError('Input changed during release preparation: '+p)
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
    except (OSError,ValueError,KeyError,TypeError) as e: p.exit(2,'Release prohibited: '+str(e)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result['blocked'] else 0

if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__': raise SystemExit(main())
