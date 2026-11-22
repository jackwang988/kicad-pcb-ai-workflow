#!/usr/bin/env python3
"""Prepare the exact AGPL Konnect field extension in a NEW directory.

Source preparation is not installation or capability acceptance. No host/MCP
configuration or KiCad project is modified. Commercial Konnect is not patched.
"""
import argparse,hashlib,json,os,shutil,subprocess,urllib.request,zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def prepare(destination,archive=None,build=False,cargo='cargo'):
    manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    dest=Path(destination).resolve()
    if dest.exists():raise ValueError('Use a NEW source/build directory')
    if sha(HERE/'pcb_fields.rs')!=manifest['extension_module_sha256']:raise ValueError('Extension source hash mismatch')
    dest.mkdir(parents=True)
    package=dest/'upstream.zip'
    if archive:shutil.copyfile(archive,package)
    else:
        with urllib.request.urlopen(manifest['source_url'],timeout=90) as response,package.open('wb') as output:
            shutil.copyfileobj(response,output)
    if sha(package)!=manifest['source_archive_sha256']:raise ValueError('Pinned upstream archive hash mismatch')
    root=dest/'source';root.mkdir()
    with zipfile.ZipFile(package) as z:
        prefix=z.namelist()[0].split('/')[0]
        for member in z.infolist():
            parts=Path(member.filename.replace('\\','/')).parts
            if not parts or parts[0]!=prefix or '..' in parts or any(':' in p for p in parts):raise ValueError('Unsafe upstream archive path')
            if (member.external_attr>>16)&0o170000==0o120000:raise ValueError('Symlinked archive member')
            if len(parts)==1:continue
            target=root.joinpath(*parts[1:])
            if not target.is_relative_to(root):raise ValueError('Archive escaped source root')
            if member.is_dir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(member) as stream,target.open('wb') as output:shutil.copyfileobj(stream,output)
    for rel,digest in manifest['base_file_sha256'].items():
        if sha(root/rel)!=digest:raise ValueError('Unexpected upstream source: '+rel)
    tools=root/'crates/konnect-core/src/tools'
    for path,needle,replacement in [
        (tools/'mod.rs','pub mod pcb_components;','pub mod pcb_components;\npub mod pcb_fields;'),
        (tools/'pcb_components.rs','    let mut tools = vec![','    let mut tools = vec![\n        super::pcb_fields::tool(),')]:
        text=path.read_text(encoding='utf-8')
        if text.count(needle)!=1:raise ValueError('Ambiguous source patch anchor')
        path.write_text(text.replace(needle,replacement,1),encoding='utf-8',newline='\n')
    shutil.copyfile(HERE/'pcb_fields.rs',tools/'pcb_fields.rs')
    cargo_manifest=root/'Cargo.toml';text=cargo_manifest.read_text(encoding='utf-8')
    text=text.replace('version = "0.13.0"','version = "'+manifest['server_version']+'"',1)
    cargo_manifest.write_text(text,encoding='utf-8',newline='\n')
    lock=root/'Cargo.lock';text=lock.read_text(encoding='utf-8')
    for name in ['konnect','konnect-core','konnect-ipc','konnect-render','konnect-schematic-editor','konnect-sexp','konnect-vcs']:
        needle='name = "'+name+'"\nversion = "0.13.0"'
        if text.count(needle)!=1:raise ValueError('Unexpected package identity: '+name)
        text=text.replace(needle,needle.replace('"0.13.0"','"'+manifest['server_version']+'"'))
    lock.write_text(text,encoding='utf-8',newline='\n')
    report={'status':'SOURCE_PREPARED_NOT_INSTALLED','base_commit':manifest['source_commit'],
            'extension_module_sha256':sha(tools/'pcb_fields.rs'),'source':str(root),
            'host_configuration_changed':False,'native_capability_accepted':False,'production_authorized':False}
    if build:
        env=dict(os.environ,KONNECT_BUILD_COMMIT=manifest['source_commit'])
        for command in [[cargo,'test','--locked','-p','konnect-core','--lib','pcb_fields::tests'],
                        [cargo,'build','--locked','--release','-p','konnect','--bin','konnect']]:
            subprocess.run(command,cwd=root,env=env,check=True,timeout=1800)
        executable=root/'target/release'/('konnect.exe' if os.name=='nt' else 'konnect')
        report.update(status='BUILT_NOT_INSTALLED',executable=str(executable),executable_sha256=sha(executable))
        enrollment={'schema_version':1,'id':'local-open-konnect-fields','approved_for_local_use':False,
                    'executable_sha256':sha(executable),'version':manifest['server_version'],
                    'build_commit':manifest['source_commit'],'eligible_kicad_versions':['10.0.8']}
        (dest/'local-enrollment.review.json').write_text(json.dumps(enrollment,indent=2)+'\n',encoding='utf-8')
    (dest/'prepare-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--destination',required=True);p.add_argument('--archive');p.add_argument('--build',action='store_true');p.add_argument('--cargo',default='cargo');a=p.parse_args()
    try:print(json.dumps(prepare(a.destination,a.archive,a.build,a.cargo),indent=2))
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'host_configuration_changed':False}));raise SystemExit(2)
