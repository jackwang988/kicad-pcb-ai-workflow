#!/usr/bin/env python3
"""Typed KiCad manufacturing candidate export after current native design gates.

Preview by default. --apply creates only a fresh independent candidate, never
publishes or executes arbitrary jobsets. CAM/EQ/authorization follow separately.
"""
import argparse
from schematic_io import blocking
import json
import shutil
from pathlib import Path
from engineering_gate import local
from npi_common import environment,sha256,run,finite_tree,load_board
from mass_production_review import evaluate

def commands(root,cfg,out,exe):
    root=Path(root).resolve();out=Path(out).resolve();e=cfg['delivery_export'];board=local(root,cfg['inputs']['board']);sch=local(root,cfg['inputs']['schematic'])
    if e.get('schema_version')!=1 or e.get('origin') not in ('absolute','drill'):raise ValueError('Explicit export schema/origin required')
    b=load_board(board,False);layers=e['gerber_layers'];assembly=e['assembly_layers'];fields=e['bom_fields']
    if not isinstance(layers,list) or not layers or len(layers)!=len(set(layers)) or not set(b['copper_layers']).union({'F.Mask','B.Mask','Edge.Cuts'}).issubset(layers):raise ValueError('All actual copper, masks and edge layers required')
    available=set(b['copper_layers'])|{'F.Mask','B.Mask','F.Paste','B.Paste','F.Silkscreen','B.Silkscreen','Edge.Cuts','F.Fab','B.Fab','Dwgs.User','Cmts.User'}
    if not set(layers).issubset(available) or not isinstance(assembly,list) or not assembly or not set(assembly).issubset(available):raise ValueError('Unsupported or empty explicit layer list')
    if not isinstance(fields,list) or not fields or len(fields)!=len(set(fields)) or any(not isinstance(f,str) or not f or ',' in f or f.startswith('-') for f in fields):raise ValueError('Explicit unique BOM fields required')
    required={'Reference',*cfg.get('bom_fields',{}).values()}
    if not required.issubset(fields):raise ValueError('BOM fields miss configured identity columns')
    names={k:e[k] for k in ('gerber_dir','drill_dir','position_file','bom_file','assembly_file')};paths={k:local(out,v) for k,v in names.items()}
    if any(not isinstance(v,str) or not v or Path(v).is_absolute() or any(c in v for c in '*?[') for v in names.values()):raise ValueError('Explicit relative candidate output paths required')
    for a,p in paths.items():
        for c,q in paths.items():
            if a!=c and (p==q or p.is_relative_to(q) or q.is_relative_to(p)):raise ValueError('Export targets must not overlap or contain each other')
    variants=cfg.get('variants',[]);variant=e.get('variant')
    if not isinstance(variants,list) or len(variants)!=1 or variant!=variants[0]:raise ValueError('Export one explicitly reviewed variant per candidate')
    variant_args=[] if variant=='default' else ['--variant',variant]
    cmds=[
      [exe,'pcb','export','gerbers','--output',str(paths['gerber_dir'])+'/', '--layers',','.join(layers),'--check-zones',*variant_args],
      [exe,'pcb','export','drill','--output',str(paths['drill_dir'])+'/', '--format','excellon','--excellon-units','mm','--excellon-separate-th'],
      [exe,'pcb','export','pos','--output',str(paths['position_file']),'--format','csv','--units','mm','--side','both','--exclude-dnp',*variant_args],
      [exe,'sch','export','bom','--output',str(paths['bom_file']),'--fields',','.join(fields),'--group-by','Reference','--exclude-dnp',*variant_args],
      [exe,'pcb','export','pdf','--output',str(paths['assembly_file']),'--layers',','.join(assembly),'--mode-multipage','--check-zones',*variant_args]]
    if e['origin']=='drill':cmds[0]+=['--use-drill-file-origin'];cmds[1]+=['--drill-origin','plot'];cmds[2]+=['--use-drill-file-origin']
    else:cmds[1]+=['--drill-origin','absolute']
    for i,c in enumerate(cmds):c.append(str(sch if i==3 else board))
    return cmds

def export(root,config_file,destination,apply=False,cli=None):
    root=Path(root).resolve();config_file=Path(config_file).resolve();out=Path(destination).resolve()
    if not config_file.is_relative_to(root):raise ValueError('In-project config required')
    if out.exists() or out.is_relative_to(root) or root.is_relative_to(out):raise ValueError('Fresh independent candidate directory required')
    cfg=finite_tree(json.loads(config_file.read_text(encoding='utf-8-sig')));env=environment(cli)
    plan=commands(root,cfg,out,env.get('kicad_cli') or 'kicad-cli')
    result={'status':'PREVIEW','production_authorized':False,'scope':'isolated_manufacturing_candidate_only','commands':plan,'remaining':['native current design gates before export','actual CAM, factory EQ, assembly review and authorized release']}
    if not apply:return result
    if not cfg.get('workflow_contract') or not cfg.get('schematic_style',{}).get('policy'):raise ValueError('R9 export requires project workflow contract and schematic style policy; legacy config is diagnostic only')
    if not env.get('cli_exact_target') or not env.get('pcbnew_exact_target'):raise ValueError('Exact KiCad10.0.7 CLI and pcbnew required')
    report=evaluate(root,config_file,'mass_production','pre_export',cli,False,None)
    if report['blocked']:return {**result,'status':'BLOCKED','reason':'Current pre-export gates failed','findings':report['findings'],'commands_executed':[]}
    board=local(root,cfg['inputs']['board']);freeze=local(root,'freeze-log.json')
    fr=json.loads(freeze.read_text(encoding='utf-8-sig'))
    if fr.get('operations')!=['copy','refill','save','reload'] or fr.get('candidate_sha256')!=sha256(board):raise ValueError('Export requires current frozen refill/save/reload candidate')
    # Bind all source files, including external library configuration explicitly copied into project.
    if any(p.is_symlink() for p in root.rglob('*')):raise ValueError('Symlinked project refused')
    before={str(p.relative_to(root)):sha256(p) for p in root.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts}
    out.mkdir(parents=True,exist_ok=False);logs=[]
    try:
        for argv in plan:
            output=Path(argv[argv.index('--output')+1]);output.parent.mkdir(parents=True,exist_ok=True)
            r=run(argv);logs.append(r)
            if r['returncode']!=0:raise ValueError('Native export failed')
        after={str(p.relative_to(root)):sha256(p) for p in root.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts}
        if before!=after:raise ValueError('Project changed during export')
        for p,h in report['inputs_sha256'].items():
            if not Path(p).is_file() or sha256(p)!=h:raise ValueError('Reviewed dependency changed')
        required={n for names in cfg['delivery_manifest'].values() for n in names if n!='build-manifest.json'}
        if not required:raise ValueError('Nonempty exact delivery manifest required')
        for name in required:
            f=local(out,name)
            if not f.is_file() or not f.stat().st_size:raise ValueError('Missing declared native output: '+name)
        result.update(status='EXPORTED_NOT_RELEASED',source_sha256=before,output_sha256={str(p.relative_to(out)):sha256(p) for p in out.rglob('*') if p.is_file()},commands_executed=logs)
    except Exception as e:
        # Leave the failure record, never a partial package that looks ready for a factory.
        for p in out.iterdir():
            if p.is_dir():shutil.rmtree(p)
            else:p.unlink()
        result.update(status='BLOCKED',reason=str(e),findings=[blocking('EXPORT.CANDIDATE',e)],commands_executed=logs)
    (out/'export-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--config',required=True);p.add_argument('--destination',required=True);p.add_argument('--kicad-cli');p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:r=export(a.project,a.config,a.destination,a.apply,a.kicad_cli);print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False,'findings':[blocking('INPUT.CONTRACT',e)]},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
