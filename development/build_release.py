#!/usr/bin/env python3
"""Validate and package the standalone Skill, legacy source and development files.

Preview unless --apply. Never installs, publishes, runs legacy code or replaces
an existing output directory. No project or manufacturing defaults are inferred.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def files(root):
    result = []
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('Symlink refused: ' + str(p))
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            result.append(p)
    return result


def validate(core):
    core = Path(core).resolve()
    spec = importlib.util.spec_from_file_location('release_npi_common', core/'scripts/npi_common.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tools = module.runtime_inventory(core)
    actual = files(core)
    if {p.name for p in core.iterdir()} != {'SKILL.md', 'scripts', 'references', 'assets'}:
        raise ValueError('Runtime must contain only SKILL.md/scripts/references/assets')
    md = (core/'SKILL.md').read_text(encoding='utf-8')
    header = re.match(r'^---\n(.*?)\n---\n', md, re.S)
    if not header or set(re.findall(r'^([\w-]+):', header[1], re.M)) != {'name','description'}:
        raise ValueError('Skill metadata must have name and description only')
    if 'name: kicad-pcb-ai-workflow' not in header[1] or len(md.splitlines()) >= 500:
        raise ValueError('Invalid Skill name or oversized entry')
    for p in actual:
        relative = p.relative_to(core)
        if p.name != 'SKILL.md' and relative.parts[0] == 'scripts' and (len(relative.parts) != 2 or p.suffix != '.py'):
            raise ValueError('Unexpected runtime script payload')
        if relative.parts[0] == 'assets' and (len(relative.parts) != 2 or not p.name.endswith('.template.json')):
            raise ValueError('Only generic templates belong in runtime assets')
        if relative.parts[0] == 'references' and (len(relative.parts) != 2 or p.suffix not in ('.md','.json')):
            raise ValueError('Historical/build data in runtime references')
        if p.suffix == '.py':
            tree = ast.parse(p.read_bytes(), filename=str(p))
            for node in ast.walk(tree):
                names = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) else [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module else []
                for name in names:
                    if name in sys.stdlib_module_names or name in ('pcbnew','_pcbnew','ctypes'):
                        continue
                    if name not in tools:
                        raise ValueError('Unbundled runtime import: ' + name)
        if p.suffix == '.md':
            text = p.read_text(encoding='utf-8')
            for link in re.findall(r'\]\(([^)]+)\)', text):
                if '://' in link or link.startswith(('#','mailto:')):
                    continue
                target = (p.parent/link.split('#')[0]).resolve()
                if not target.is_relative_to(core) or not target.is_file():
                    raise ValueError('Broken/external local document link: ' + str(relative) + ' -> ' + link)
        if p.suffix == '.json':
            json.loads(p.read_text(encoding='utf-8'))
        if p.suffix in ('.py','.md','.json'):
            if re.search(r'PROJECT_SPECIFIC_BOARD|[A-Za-z]:[/\\]Users[/\\](?!Public(?:[/\\]|$))', p.read_text(encoding='utf-8')):
                raise ValueError('Project/machine-specific payload: ' + str(relative))
    return {'files': len(actual), 'bytes': sum(p.stat().st_size for p in actual),
            'runtime_tools': len(tools), 'scope': 'software_package_integrity_only',
            'production_authorized': False}


def validate_archive(repo):
    archive = Path(repo)/'archive/legacy-project'
    manifest = json.loads((archive/'original-script-sha256.json').read_text())
    if len(manifest) != 70 or set(manifest) != {'scripts/'+p.name for p in (archive/'scripts').glob('*.py')}:
        raise ValueError('Incomplete original source archive')
    for name, digest in manifest.items():
        p = (archive/name).resolve()
        if not p.is_relative_to(archive.resolve()) or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError('Original source changed: ' + name)
    return len(manifest)


def build(destination, apply=False, repo=REPO):
    repo = Path(repo).resolve()
    out = Path(destination).resolve()
    if out.exists() or out.is_relative_to(repo) or repo.is_relative_to(out) or not out.parent.is_dir():
        raise ValueError('Fresh output directory outside source repository required')
    result = {'status': 'PREVIEW', 'runtime': validate(repo/'kicad-pcb-ai-workflow'),
              'archived_original_scripts': validate_archive(repo) if (repo/'archive/legacy-project').is_dir() else 0, 'production_authorized': False}
    sets = {'kicad-pcb-ai-workflow.zip': files(repo/'kicad-pcb-ai-workflow'),
            'kicad-pcb-ai-workflow-development.zip': files(repo/'development')}
    if (repo/'archive').is_dir():
        sets['kicad-pcb-ai-workflow-archive.zip'] = files(repo/'archive')
    result['packages'] = {n: {'files': len(ps), 'bytes': sum(p.stat().st_size for p in ps)} for n, ps in sets.items()}
    if not apply:
        return result
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for ps in sets.values() for p in ps}
    out.mkdir(exist_ok=False)
    try:
        for name, paths in sets.items():
            with zipfile.ZipFile(out/name, 'x', zipfile.ZIP_DEFLATED) as z:
                for p in paths:
                    z.write(p, p.relative_to(repo).as_posix())
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != h for p, h in before.items()):
            raise ValueError('Source changed during packaging')
        result['status'] = 'PACKAGED_NOT_ENGINEERING_APPROVED'
        result['zip_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}
        (out/'package-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    except Exception:
        shutil.rmtree(out)
        raise
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    try:
        print(json.dumps(build(args.output_dir, args.apply), ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({'status':'BLOCKED', 'reason':str(e), 'production_authorized':False}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
