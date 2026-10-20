#!/usr/bin/env python3
"""Materialize an explicit Agent-authored draft into a NEW native-checked candidate.

This is a generic file writer/acceptance adapter, not an electrical designer.
The draft contains exact file text and an independently reviewed expected XML
inventory/connection contract. Never derives the expected circuit from its output.
"""
import argparse
from schematic_io import blocking
import json
from pathlib import Path
from npi_common import environment,run,sha256,finite_tree
from engineering_gate import local
from schematic_io import parse,sheets,hashes
from netlist_guard import read_netlist
from native_report import extract

def expected_contract(q,graph):
    expected=q.get('expected',{});components=expected.get('components');nets=expected.get('nets')
    if not isinstance(components,dict) or not components or not isinstance(nets,dict) or not nets:raise ValueError('Explicit nonempty expected component and named-net contract required')
    if set(components)!=set(graph['components']):raise ValueError('Native component inventory differs from expected circuit')
    for ref,props in components.items():
        if not isinstance(props,dict) or not props or set(props)-{'value','footprint','fields'}:raise ValueError('Expected component needs explicit supported identity fields')
        for key,val in props.items():
            if key in ('value','footprint') and (not isinstance(val,str) or not val.strip()):raise ValueError('Nonempty expected identity required')
            if key=='fields' and (not isinstance(val,dict) or not val or any(not isinstance(v,str) or not v for v in val.values())):raise ValueError('Explicit nonempty identity fields required')
            if graph['components'][ref].get(key)!=val:raise ValueError('Native component identity mismatch: '+ref+'.'+key)
    def canon(data):
        seen=set();result={}
        for net,pins in data.items():
            if not isinstance(net,str) or not net or not isinstance(pins,list) or not pins:raise ValueError('Explicit net/pin list required')
            nodes=[]
            for pin in pins:
                if not isinstance(pin,(list,tuple)) or len(pin)!=2 or pin[0] not in components or not isinstance(pin[1],str) or not pin[1]:raise ValueError('Invalid expected endpoint')
                node=tuple(pin)
                if node in seen:raise ValueError('Pin repeated across expected/native nets')
                seen.add(node);nodes.append(node)
            result[net]=sorted(nodes)
        return result
    if canon(nets)!=canon(graph['nets']):raise ValueError('Native nets/pin partitions differ from expected circuit')

def materialize(draft_file,destination,apply=False,cli=None):
    draft_file=Path(draft_file).resolve();dest=Path(destination).resolve();q=finite_tree(json.loads(draft_file.read_text(encoding='utf-8-sig')))
    if q.get('schema_version')!=1 or not isinstance(q.get('design_basis'),dict):raise ValueError('Explicit draft schema and design basis required')
    basis=q['design_basis'];basis_file=local(draft_file.parent,basis['file'])
    if not basis.get('locator') or not basis_file.is_file() or not basis_file.stat().st_size or sha256(basis_file)!=basis.get('sha256'):raise ValueError('Actual current design basis file/hash/locator required')
    if dest.exists() or dest==draft_file.parent or dest.is_relative_to(draft_file.parent):raise ValueError('Destination must be new and outside draft directory')
    files=q.get('files',{})
    if not isinstance(files,dict) or not files:raise ValueError('Exact generated file contents required')
    normalized=[Path(n).as_posix().casefold() for n in files]
    if len(normalized)!=len(set(normalized)):raise ValueError('Case-ambiguous output filenames')
    for name,content in files.items():
        if Path(name).is_absolute():raise ValueError('Relative generated file paths required')
        p=local(dest,name)
        if not isinstance(content,str) or not content.strip() or p.suffix not in ('.kicad_sch','.kicad_pro','.kicad_sym','.kicad_mod','.kicad_dru'):
            raise ValueError('Only explicit KiCad design text files accepted')
        if p.suffix in ('.kicad_sch','.kicad_sym','.kicad_mod'):parse(content)
        elif p.suffix=='.kicad_pro':finite_tree(json.loads(content))
    if q.get('top') not in files or q.get('project') not in files or Path(q['top']).suffix!='.kicad_sch' or Path(q['project']).suffix!='.kicad_pro':raise ValueError('Top schematic/project must be supplied')
    # Validate expected schema before any write, without pretending expected data proves itself.
    dummy={'components':q.get('expected',{}).get('components',{}),'nets':q.get('expected',{}).get('nets',{})};expected_contract(q,dummy)
    record={'status':'PREVIEW','scope':'schematic_candidate_only','production_authorized':False,'draft_sha256':sha256(draft_file),'basis_sha256':sha256(basis_file),'files':sorted(files),'destination':str(dest),'remaining':['native export/ERC and exact expected circuit comparison','AI visual/device/application review','hardware engineer confirmation']}
    if not apply:return record
    env=environment(cli)
    if not env.get('cli_exact_target'):raise ValueError('KiCad10.0.7 CLI required before candidate writing')
    before=sha256(draft_file);dest.mkdir(parents=True,exist_ok=False)
    try:
        for name,text in files.items():p=local(dest,name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
        pages=sheets(dest,q['top']);initial=hashes(dest,files);proof=dest/'candidate-evidence';proof.mkdir();commands=[]
        schematic=local(dest,q['top']);xml=proof/'netlist.xml';pdf=proof/'schematic.pdf';erc=proof/'erc.json'
        for argv,target,acceptable in [([env['kicad_cli'],'sch','export','netlist','--format','kicadxml','--output',str(xml),str(schematic)],xml,(0,)),([env['kicad_cli'],'sch','export','pdf','--output',str(pdf),str(schematic)],pdf,(0,)),([env['kicad_cli'],'sch','erc','--format','json','--units','mm','--severity-all','--exit-code-violations','--output',str(erc),str(schematic)],erc,(0,5))]:
            result=run(argv);commands.append(result)
            if result['returncode'] not in acceptable or not target.is_file() or not target.stat().st_size:raise ValueError('Native candidate operation failed: '+str(argv[1:4]))
        expected_contract(q,read_netlist(xml));violations=extract('erc',json.loads(erc.read_text(encoding='utf-8-sig')),schematic)
        if violations:raise ValueError('Native ERC has unresolved findings; candidate remains unapproved')
        if sha256(draft_file)!=before or sha256(basis_file)!=basis['sha256'] or hashes(dest,files)!=initial:raise ValueError('Draft/candidate changed during validation')
        record.update(status='NATIVE_CANDIDATE_CHECKED_NOT_APPROVED',environment=env,inputs_sha256=initial,pages=list(pages),evidence_sha256=hashes(dest,[str(p.relative_to(dest)) for p in (xml,pdf,erc)]))
    except Exception as e:
        record.update(status='BLOCKED',reason=str(e),findings=[blocking('SCH.CANDIDATE',e)],commands=locals().get('commands',[]));(dest/'candidate-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');return record
    record['commands']=commands;(dest/'candidate-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');return record

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--draft',required=True);p.add_argument('--destination',required=True);p.add_argument('--kicad-cli');p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:r=materialize(a.draft,a.destination,a.apply,a.kicad_cli);print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False,'findings':[blocking('INPUT.CONTRACT',e)]},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
