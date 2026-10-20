#!/usr/bin/env python3
"""Six-group navigation and shared configuration compiler; never an approval engine.

Keep every existing checker and release gate. Generated configs are immutable
snapshots in a NEW project sidecar directory. No cache substitutes for a gate.
"""
import argparse
import copy
import json
import shutil
import sys
from pathlib import Path

from engineering_gate import local
from npi_common import finite_tree, sha256
import project_flow as flow

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'environment': ('environment',),
    'architecture': ('requirements', 'sources', 'reserve'),
    'schematic': ('schematic', 'schematic_review', 'footprints'),
    'pcb': ('stackup', 'placement', 'routing', 'pcb_review'),
    'manufacturing': ('npi', 'manufacturing', 'cam_release'),
    'lifecycle': ('prototype', 'eco'),
}
TASKS = {
    'environment.doctor': 'doctor', 'environment.setup': 'environment_start',
    'environment.check': 'environment_start', 'architecture.check': 'project_flow',
    'schematic.prepare': 'static_review', 'schematic.gate': 'static_review_gate',
    'pcb.prepare': 'static_review', 'pcb.gate': 'static_review_gate',
    'pcb.placement_pre': 'placement_review', 'pcb.placement_final': 'placement_review',
    'pcb.rules_pre': 'design_intent_audit', 'pcb.rules_final': 'design_intent_audit',
    'manufacturing.precheck': 'mass_production_review',
    'manufacturing.export': 'manufacturing_export', 'manufacturing.release': 'npi_release',
    'lifecycle.check': 'project_flow',
}
WRITING = {'environment.setup', 'manufacturing.export', 'manufacturing.release'}
FLAGS = ('require_device_knowledge', 'require_reserve_review', 'require_placement_review',
         'require_schematic_style', 'require_system_integration')
METHODS = {
    'environment': 'Run real target CLI/pcbnew setup or current environment check.',
    'requirements': 'Agent and owner establish quantitative requirements and verification mappings.',
    'sources': 'Read actual manufacturer documents and verify project-specific source cards.',
    'reserve': 'Review default assembly, alternatives, risk and no-reserve rationale.',
    'schematic': 'Design actual schematic, architecture overview and interface contract.',
    'schematic_review': 'Run current ERC/static checks; actual AI and engineer review at G1.',
    'footprints': 'Compare actual MPN pinout and land pattern; engineer confirms G2.',
    'stackup': 'Obtain approved factory stackup and validate actual rule/netclass bindings.',
    'placement': 'Place actual components and review module/local geometry at G3.',
    'routing': 'Route with supported tools; refill, save, reload and inspect current PCB.',
    'pcb_review': 'Review actual layers/critical paths; AI and engineer confirm G4.',
    'npi': 'Run actual DFX/NPI pre-export checks; unresolved blockers forbid export.',
    'manufacturing': 'Freeze source and export a new isolated candidate, not a released package.',
    'cam_release': 'Actual CAM/factory EQ/assembly review and authorized G5 release.',
    'prototype': 'Record real project-specific EVT/DVT/PVT results.',
    'eco': 'Assess changes, invalidate impacted evidence and confirm G6 archive.',
}


def read(path):
    return finite_tree(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def ref(pointer):
    return {'$ref': pointer}


def template():
    """Share repeated fields; leave every engineering value/decision unresolved."""
    review = read(ROOT / 'assets/static-review.template.json')
    npi = read(ROOT / 'assets/review-config.template.json')
    contract = flow.template()
    shared = {'inputs': npi['inputs'], 'documents': review['documents'], 'variant': None,
              'design_intent': npi['design_intent'], 'engineering_profile': npi['engineering_profile']}
    for key in ('device_knowledge', 'reserve_review', 'placement_review', 'schematic_style', 'system_integration'):
        shared[key] = copy.deepcopy(review[key])
        review[key] = ref('/shared/' + key)
        if key in npi:
            npi[key] = ref('/shared/' + key)
    shared['reserve_review']['variant'] = ref('/shared/variant')
    for key in ('project_id', 'revision'):
        contract[key] = ref('/' + key)
    contract['inputs'] = ref('/shared/inputs')
    for stage, spec in contract['stages'].items():
        spec.update(executor='combined', method=METHODS[stage])
    review['documents'] = npi['documents'] = ref('/shared/documents')
    npi['inputs'] = ref('/shared/inputs')
    for stage in review['stages'].values():
        for key in ('schematic', 'board', 'project'):
            stage['inputs'][key] = ref('/shared/inputs/' + key)
    npi['workflow_contract'] = {'$config': 'flow'}
    npi['variants'] = [ref('/shared/variant')]
    npi['delivery_export']['variant'] = ref('/shared/variant')
    for key in ('design_intent', 'engineering_profile'):
        npi[key] = ref('/shared/' + key)
    return {'schema_version': 1, 'project_id': None, 'revision': None, 'shared': shared,
            'configs': {'flow': contract, 'static': review, 'npi': npi}}


def expand(value, master, bundle_rel, trail=()):
    """Local JSON pointers only. No eval, remote refs or shell substitutions."""
    if isinstance(value, dict):
        special = set(value) & {'$ref', '$config'}
        if special:
            if len(value) != 1 or len(special) != 1:
                raise ValueError('Reference object must contain exactly one token')
            if '$config' in value:
                if value['$config'] not in ('flow', 'static', 'npi'):
                    raise ValueError('Unknown generated config')
                return (bundle_rel / (value['$config'] + '.json')).as_posix()
            pointer = value['$ref']
            if not isinstance(pointer, str) or not pointer.startswith('/') or pointer in trail or len(trail) > 64:
                raise ValueError('Invalid/cyclic shared reference')
            target = master
            for token in pointer[1:].split('/'):
                token = token.replace('~1', '/').replace('~0', '~')
                if isinstance(target, list):
                    if not token.isdigit():
                        raise ValueError('Invalid list pointer')
                    target = target[int(token)]
                else:
                    target = target[token]
            return expand(target, master, bundle_rel, trail + (pointer,))
        return {k: expand(v, master, bundle_rel, trail) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, master, bundle_rel, trail) for v in value]
    return value


def render(master, bundle_rel):
    if master.get('schema_version') != 1 or set(master.get('configs', {})) != {'flow', 'static', 'npi'}:
        raise ValueError('Expected workflow schema 1 with flow/static/npi configs')
    configs = expand(master['configs'], master, bundle_rel)
    c, s, n = (configs[k] for k in ('flow', 'static', 'npi'))
    shared = expand(master['shared'], master, bundle_rel)
    if set(c.get('stages', {})) != set(flow.STAGES):
        raise ValueError('All 16 workflow nodes must remain')
    if c.get('schema_version') != 1 or s.get('schema_version') != 1:
        raise ValueError('Unsupported compiled schema')
    if any(s.get(k) is not True for k in FLAGS) or n.get('require_system_integration') is not True:
        raise ValueError('Mandatory R9.1 review gates cannot be disabled')
    if c.get('inputs') != shared['inputs'] or n.get('inputs') != shared['inputs']:
        raise ValueError('Conflicting canonical inputs')
    if any(c.get(k) != master.get(k) for k in ('project_id', 'revision')):
        raise ValueError('Conflicting project identity/revision')
    for stage in ('schematic', 'pcb'):
        for key in ('schematic', 'board', 'project'):
            if s['stages'][stage]['inputs'].get(key) != shared['inputs'].get(key):
                raise ValueError('Conflicting static-review input')
    for key in ('reserve_review', 'placement_review', 'schematic_style', 'system_integration', 'documents'):
        if n.get(key) != s.get(key) or s.get(key) != shared.get(key):
            raise ValueError('Conflicting shared policy/source: ' + key)
    if s.get('device_knowledge') != shared.get('device_knowledge'):
        raise ValueError('Conflicting device source bundle')
    if n.get('workflow_contract') != (bundle_rel / 'flow.json').as_posix():
        raise ValueError('NPI must bind current generated workflow contract')
    if n.get('variants') != [shared['variant']] or n['delivery_export'].get('variant') != shared['variant']:
        raise ValueError('Conflicting production variant')
    for key in ('design_intent', 'engineering_profile'):
        if n.get(key) != shared.get(key):
            raise ValueError('Conflicting shared configuration: ' + key)
    if set(s.get('stages', {})) != {'schematic', 'pcb'}:
        raise ValueError('Both independent schematic and PCB reviews are required')
    from static_review import CATEGORIES
    for stage, categories in CATEGORIES.items():
        if not set(categories).issubset({t.get('category') for t in s['stages'][stage]['tasks']}):
            raise ValueError('Mandatory review category removed: ' + stage)
    return configs


def master_path(root, name):
    p = local(root, name)
    if not p.is_file():
        raise ValueError('Master config missing; run init and fill actual project data')
    return p


def compile_bundle(root, name, destination, apply=False):
    root = Path(root).resolve()
    source = master_path(root, name)
    out = local(root, destination)
    if out.exists() or not out.parent.is_dir():
        raise ValueError('Use a NEW bundle directory under an existing project directory')
    source_hash = sha256(source)
    configs = render(read(source), out.relative_to(root))
    # Validate inventory even for preview; never execute stale or legacy tools.
    flow.registry()
    result = {'status': 'PREVIEW', 'scope': 'configuration_only', 'production_authorized': False,
              'bundle': str(out), 'files': [k + '.json' for k in configs],
              'note': 'Unfilled engineering values remain unresolved; building configs is not stage approval.'}
    if not apply:
        return result
    if sha256(source) != source_hash:
        raise ValueError('Master changed while compiling')
    out.mkdir(exist_ok=False)
    try:
        for key, value in configs.items():
            (out / (key + '.json')).write_text(encoded(value), encoding='utf-8')
        manifest = {'schema_version': 1, 'source': source.relative_to(root).as_posix(),
                    'source_sha256': source_hash,
                    'tool_manifest_sha256': sha256(ROOT / 'references/tool-manifest.json'),
                    'files': {p.name: sha256(p) for p in out.iterdir()}}
        (out / 'bundle.json').write_text(encoded(manifest), encoding='utf-8')
        if sha256(source) != source_hash:
            raise ValueError('Master changed while compiling')
    except Exception:
        shutil.rmtree(out)
        raise
    return {**result, 'status': 'CONFIG_BUNDLE_CREATED_NOT_APPROVED'}


def load_bundle(root, name, bundle):
    root = Path(root).resolve()
    source = master_path(root, name)
    out = local(root, bundle)
    manifest = read(local(root, out.relative_to(root) / 'bundle.json'))
    if manifest.get('schema_version') != 1 or manifest.get('source') != source.relative_to(root).as_posix():
        raise ValueError('Wrong bundle/master binding')
    if manifest.get('source_sha256') != sha256(source):
        raise ValueError('Master changed: build a NEW bundle and refresh affected reviews')
    if manifest.get('tool_manifest_sha256') != sha256(ROOT / 'references/tool-manifest.json'):
        raise ValueError('Toolchain changed: rebuild configuration snapshot')
    configs = render(read(source), out.relative_to(root))
    expected = {k + '.json' for k in configs}
    if set(manifest.get('files', {})) != expected:
        raise ValueError('Incomplete configuration inventory')
    for key, value in configs.items():
        p = local(root, out.relative_to(root) / (key + '.json'))
        if sha256(p) != manifest['files'][p.name] or p.read_text(encoding='utf-8') != encoded(value):
            raise ValueError('Generated config changed: ' + key)
    flow.registry()
    return configs


def pending(value, prefix=''):
    found = []
    if value is None or value == 'undecided':
        return [prefix]
    if isinstance(value, dict):
        for k, v in value.items():
            found.extend(pending(v, prefix + '/' + k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(pending(v, prefix + '/' + str(i)))
    return found


def status(root, name, bundle):
    root = Path(root).resolve()
    cfg = load_bundle(root, name, bundle)
    contract = (Path(bundle) / 'flow.json').as_posix()
    report = flow.check(root, contract)
    return {'status': 'NEEDS_INPUT' if report['findings'] else 'DECLARED_INPUTS_READY_NOT_APPROVED',
            'scope': 'navigation_only', 'production_authorized': False,
            'groups': [{'group': group, 'nodes': list(nodes),
                        'tasks': [t for t in TASKS if t.startswith(group + '.')],
                        'gate_status': 'NOT_EVALUATED_BY_NAVIGATION'} for group, nodes in GROUPS.items()],
            'unfilled_config_fields': pending(cfg), 'findings': report['findings'],
            'note': 'Future missing files are pending work, not permission to skip gates. Feature N/A never disables a gate.'}


def command(root, name, bundle, task, options):
    root = Path(root).resolve()
    if task not in TASKS:
        raise ValueError('Unknown task')
    if options.get('apply') and task not in WRITING:
        raise ValueError('--apply is only valid for explicit candidate/setup writes')
    if task == 'environment.doctor' and not bundle:
        flow.registry()
        args = ['--kicad-cli', options['kicad_cli']] if options.get('kicad_cli') else []
        return 'doctor', args
    if not bundle:
        raise ValueError('This task needs --bundle; build a configuration snapshot first')
    cfg = load_bundle(root, name, bundle)
    inputs = cfg['flow']['inputs']

    def required(key):
        value = options.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Task needs --' + key.replace('_', '-'))
        return value

    def input_file(key):
        value = inputs.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Fill shared.inputs.' + key)
        return str(local(root, value))

    def config_file(key):
        return str(local(root, Path(bundle) / (key + '.json')))

    stage = task.split('.')[0]
    args = [str(root)]
    if task == 'environment.doctor':
        args = []
    elif task == 'environment.check':
        args = ['check', '--state', required('state')]
    elif task == 'environment.setup':
        args = ['setup', '--project', str(root), '--schematic', input_file('schematic'),
                '--board', input_file('board'), '--project-file', input_file('project'),
                '--report-dir', required('output_dir')]
    elif task in ('architecture.check', 'lifecycle.check'):
        args += ['--contract', str(Path(bundle) / 'flow.json')]
        args.insert(0, 'check')
    elif task.endswith('.prepare'):
        args += ['--config', config_file('static'), '--stage', stage, '--output-dir', required('output_dir')]
    elif task.endswith('.gate'):
        packet, ai, engineer = required('packet'), required('ai_review'), required('engineer_review')
        if read(Path(packet).resolve() / 'packet.json').get('stage') != stage:
            raise ValueError('Review packet belongs to a different stage')
        args += ['--packet', packet, '--ai-review', ai, '--engineer-review', engineer]
    elif '.placement_' in task:
        policy = cfg['static']['placement_review'].get('policy')
        if not isinstance(policy, str) or not policy.strip():
            raise ValueError('Fill shared.placement_review.policy')
        args += ['--policy', str(local(root, policy)), '--netlist', required('netlist'),
                 '--board', input_file('board'), '--phase', 'pre_route' if task.endswith('_pre') else 'final',
                 '--output-dir', required('output_dir')]
    elif '.rules_' in task:
        intent = cfg['npi'].get('design_intent')
        if not isinstance(intent, str) or not intent.strip():
            raise ValueError('Fill shared.design_intent')
        args += ['--intent', str(local(root, intent)), '--phase', 'pre_route' if task.endswith('_pre') else 'final']
    elif task == 'manufacturing.precheck':
        args += ['--config', config_file('npi'), '--mode', options.get('mode', 'mass_production'),
                 '--phase', 'pre_export', '--output-dir', required('output_dir')]
    elif task in ('manufacturing.export', 'manufacturing.release'):
        if options.get('mode', 'mass_production') != 'mass_production':
            raise ValueError('Prototype mode cannot export or release production files')
        args += ['--config', config_file('npi'), '--destination', required('destination')]
        if task.endswith('.release'):
            args += ['--candidate-dir', required('candidate_dir')]
    if options.get('apply'):
        args.append('--apply')
    if options.get('kicad_cli'):
        if TASKS[task] not in ('doctor', 'environment_start', 'static_review', 'mass_production_review', 'manufacturing_export', 'npi_release'):
            raise ValueError('Selected task does not accept --kicad-cli')
        args += ['--kicad-cli', options['kicad_cli']]
    return TASKS[task], args


def summary(report):
    lines = ['工作流待办（仅导航；不表示任何门禁已通过）']
    labels = ('环境', '需求/架构/资料', '原理图/封装', 'PCB规则/布局/布线', 'DFX/NPI/制造', '试产/ECO')
    for group, label in zip(report['groups'], labels):
        lines.append(f"- {label} [{group['group']}]: " + ', '.join(group['tasks']))
    lines.append(f"项目契约缺项：{len(report['findings'])}；配置未填字段：{len(report['unfilled_config_fields'])}（含可能合法留空的可选项）。")
    for item in report['findings'][:8]:
        lines.append(f"  {item['location']}: {item['description']}")
    lines.append('工程尚未生成的PCB等文件属于后续待办；环境/需求工作可先开始。')
    lines.append('详细缺项用 status --format json；实际检查、AI和工程师签核必须分别执行。')
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    for cmd in ('init', 'build', 'status', 'plan', 'run'):
        a = sub.add_parser(cmd)
        a.add_argument('project')
        a.add_argument('--config', default='workflow.json')
        if cmd == 'init':
            a.add_argument('--apply', action='store_true')
        elif cmd == 'build':
            a.add_argument('--bundle', required=True)
            a.add_argument('--apply', action='store_true')
        else:
            a.add_argument('--bundle', required=cmd == 'status')
        if cmd == 'status':
            a.add_argument('--format', choices=('text', 'json'), default='text')
        if cmd in ('plan', 'run'):
            a.add_argument('--task', choices=TASKS, required=True)
            for key in ('output-dir', 'state', 'packet', 'ai-review', 'engineer-review', 'netlist', 'destination', 'candidate-dir', 'kicad-cli'):
                a.add_argument('--' + key)
            a.add_argument('--mode', choices=('prototype', 'mass_production'), default='mass_production')
            a.add_argument('--apply', action='store_true')
    a = p.parse_args()
    try:
        root = Path(a.project).resolve()
        if not root.is_dir():
            raise ValueError('Existing project directory required')
        if a.cmd == 'init':
            out = local(root, a.config)
            if out.exists():
                raise ValueError('Master already exists; never overwrite')
            r = {'status': 'PREVIEW', 'file': str(out), 'scope': 'configuration_only', 'production_authorized': False}
            if a.apply:
                with out.open('x', encoding='utf-8') as f:
                    f.write(encoded(template()))
                r['status'] = 'UNCONFIGURED_MASTER_CREATED'
        elif a.cmd == 'build':
            r = compile_bundle(root, a.config, a.bundle, a.apply)
        elif a.cmd == 'status':
            r = status(root, a.config, a.bundle)
        else:
            tool, args = command(root, a.config, a.bundle, a.task, vars(a))
            if a.cmd == 'run':
                # project_flow.dispatch intentionally excludes itself; use the same
                # checked subprocess path here for its read-only check subcommand.
                if tool == 'project_flow':
                    import subprocess
                    return subprocess.run([sys.executable, '-B', str(flow.registry()[tool]), *args], check=False).returncode
                return flow.dispatch(tool, args)
            r = {'status': 'PREVIEW', 'scope': 'task_plan_only', 'production_authorized': False,
                 'command': [sys.executable, '-B', str(flow.registry()[tool]), *args]}
        if a.cmd == 'status' and a.format == 'text':
            print(summary(r))
        else:
            print(encoded(r), end='')
        return 2 if r['status'] in ('BLOCKED', 'NEEDS_INPUT') else 0
    except Exception as e:
        from schematic_io import blocking
        print(encoded({'status': 'BLOCKED', 'production_authorized': False,
                       'findings': [blocking('WORKFLOW.INPUT', e)]}), end='')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
