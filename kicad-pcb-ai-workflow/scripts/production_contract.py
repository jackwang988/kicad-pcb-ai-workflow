"""Structural contracts for real manufacturing provenance and approvals.

These records improve traceability; this is not cryptographic authentication
of an engineer/factory, nor a complete Gerber/CAM interpreter.
"""
from pathlib import Path
import re
import datetime as dt
from npi_common import TARGET_VERSION

CAM_CHECKS={'all_copper_layers','mask_silk_paste','outline_cutouts','drills_slots_plating_spans',
            'units_origin_mirror','assembly_variant_polarity','fabrication_requirements'}

def basis(config,profile,sources):
    names={x for x in config.get('inputs',{}).values() if x} | set(profile.get('source_files',[]))
    if not names or any(name not in sources for name in names):raise ValueError('Incomplete design-source basis')
    return {name:sources[name] for name in sorted(names)}

def outputs(config,build):
    names={f for category in ('gerber','drill','cpl','bom','assembly','paste','fabrication') for f in config.get('delivery_manifest',{}).get(category,[])}
    mapping=build.get('output_sha256',{})
    if not names or any(name not in mapping for name in names):raise ValueError('Incomplete manufacturing-output binding')
    return {name:mapping[name] for name in sorted(names)}

def generating_operation(command, tool, config, produced):
    """Fail closed on unsupported tools/jobsets; paths bind actual argv to records.

    Absolute roots are execution-time provenance, not paths we execute or trust
    as current filesystem locations. Hash checks are performed by the caller.
    """
    argv=command['argv']
    if tool['name']!='kicad-cli' or tool['version']!=TARGET_VERSION:
        raise ValueError('Generating tool requires a supported KiCad export contract')
    operations={('pcb','export','gerbers'):({'gerber','paste'},'board',True),
                ('pcb','export','drill'):({'drill'},'board',True),
                ('pcb','export','pos'):({'cpl'},'board',False),
                ('sch','export','bom'):({'bom'},'schematic',False),
                ('pcb','export','pdf'):({'assembly','fabrication'},'board',False)}
    spec=operations.get(tuple(argv[1:4]))
    if spec is None or '--help' in argv or '--version' in argv:
        raise ValueError('Command is not a supported generating export; jobsets require verified per-export records')
    categories,input_key,directory=spec
    inputs=config.get('inputs',{})
    source=inputs.get(input_key) or (inputs.get('sch') if input_key=='schematic' else None)
    if not source:raise ValueError('Export source is not declared')
    roots={k:command.get(k) for k in ('cwd','source_root','output_root')}
    if not all(isinstance(v,str) and Path(v).is_absolute() for v in roots.values()):
        raise ValueError('Absolute execution cwd/source_root/output_root required')
    def resolve(value):
        p=Path(value)
        return (p if p.is_absolute() else Path(roots['cwd'])/p).resolve()
    expected_source=(Path(roots['source_root'])/source).resolve()
    if resolve(argv[-1])!=expected_source:raise ValueError('Export input does not match frozen design source')
    output_args=[]
    for i,arg in enumerate(argv[4:-1],4):
        if arg in ('--output','-o'):
            if i+1>=len(argv)-1:raise ValueError('Missing export output argument')
            output_args.append(argv[i+1])
        elif arg.startswith('--output='):output_args.append(arg.split('=',1)[1])
    if len(output_args)!=1:raise ValueError('Exactly one explicit export output required')
    target=resolve(output_args[0]);root=Path(roots['output_root']).resolve()
    for name in produced:
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe output path')
        matches={cat for cat,files in config.get('delivery_manifest',{}).items() if name in files}
        if not matches or not matches.issubset(categories):raise ValueError('Export operation/output category mismatch')
        actual=(root/relative).resolve()
        if (directory and target not in actual.parents) or (not directory and actual!=target):
            raise ValueError('Claimed output not generated at recorded output argument')

def records(build,config,profile):
    sources=basis(config,profile,build.get('source_sha256',{}));manufacturing=outputs(config,build)
    tools=build.get('tools');commands=build.get('commands');logs=build.get('logs')
    if not isinstance(tools,list) or not tools or not isinstance(commands,list) or not commands or not isinstance(logs,list) or not logs:raise ValueError('Tool/command/log arrays required')
    registry={}
    for tool in tools:
        if not isinstance(tool,dict) or not all(tool.get(k) for k in ('id','name','version','executable_sha256')):raise ValueError('Incomplete tool record')
        if not re.fullmatch('[0-9a-f]{64}',tool['executable_sha256']) or tool['id'] in registry:raise ValueError('Invalid tool hash/identity')
        registry[tool['id']]=tool
    if not any(t['name']=='kicad-cli' and t['version']==TARGET_VERSION for t in tools):raise ValueError('Required KiCad CLI version not recorded')
    log_names={r.get('file') for r in logs if isinstance(r,dict)};covered=set()
    for command in commands:
        if not isinstance(command,dict) or command.get('tool_id') not in registry:raise ValueError('Unknown command tool')
        argv=command.get('argv')
        if not isinstance(argv,list) or len(argv)<2 or not all(isinstance(a,str) and a for a in argv):raise ValueError('Actual command arguments missing')
        if Path(argv[0]).name.lower().removesuffix('.exe')!=registry[command['tool_id']]['name'].lower():raise ValueError('Command executable/tool identity mismatch')
        if type(command.get('returncode')) is not int or command['returncode']!=0 or command.get('log') not in log_names:raise ValueError('Successful bound command/log record required')
        if command.get('source_basis_sha256')!=sources:raise ValueError('Command not bound to current design sources')
        produced=command.get('output_sha256')
        if not isinstance(produced,dict) or not produced or any(k not in manufacturing or v!=manufacturing[k] for k,v in produced.items()):raise ValueError('Command output hashes missing/inconsistent')
        generating_operation(command,registry[command['tool_id']],config,produced)
        covered.update(produced)
    if covered!=set(manufacturing):raise ValueError('Manufacturing outputs lack generating-command evidence')
    auth=build.get('production_authorization',{})
    if not isinstance(auth,dict) or not all(auth.get(k) for k in ('reviewer','date','factory','order_scope')):raise ValueError('Production authorization incomplete')
    dt.date.fromisoformat(auth['date'])
    if auth.get('source_basis_sha256')!=sources or auth.get('output_sha256')!=manufacturing:raise ValueError('Production authorization applies to another design/package')
    return sources,manufacturing

def cam_checks(cam):
    checks=cam.get('checks',{})
    if not isinstance(checks,dict) or not CAM_CHECKS.issubset(checks):raise ValueError('CAM required checks missing')
    for name in CAM_CHECKS:
        record=checks[name]
        if record=='PASS':continue
        if isinstance(record,dict) and record.get('status')=='N/A' and record.get('reason'):continue
        raise ValueError('CAM check not passed: '+name)
    dt.date.fromisoformat(cam['date'])
