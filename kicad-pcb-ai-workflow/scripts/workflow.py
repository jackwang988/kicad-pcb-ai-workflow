#!/usr/bin/env python3
"""Six-group navigation and shared configuration compiler; never an approval engine.

Keep every existing checker and release gate. Generated configs are immutable
snapshots in a NEW project sidecar directory. No cache substitutes for a gate.
"""
import argparse
import copy
from datetime import date
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
    'architecture.sources_resolve': 'device_knowledge', 'architecture.sources_register': 'device_knowledge',
    'environment.ipc_probe': 'kicad_ipc_probe', 'environment.ipc_snapshot': 'kicad_ipc_probe',
    'environment.konnect_check': 'konnect_backend',
    'environment.konnect_discover': 'konnect_capabilities',
    'environment.konnect_assess': 'konnect_capabilities',
    'environment.konnect_fixture': 'konnect_capabilities',
    'environment.konnect_invoke': 'konnect_capabilities',
    'environment.bridge_plugin': 'kicad_bridge', 'pcb.edit': 'kicad_bridge',
    'environment.open_editor': 'kicad_bridge',
    'pcb.edit_drc': 'kicad_bridge',
    'schematic.resources_lock': 'resource_guard', 'schematic.resources_check': 'resource_guard',
    'schematic.prepare': 'static_review', 'schematic.gate': 'static_review_gate',
    'pcb.prepare': 'static_review', 'pcb.gate': 'static_review_gate',
    'pcb.placement_pre': 'placement_review', 'pcb.placement_final': 'placement_review',
    'pcb.rules_pre': 'design_intent_audit', 'pcb.rules_final': 'design_intent_audit',
    'pcb.routing_preflight': 'routing_policy', 'pcb.routing_plan': 'routing_policy',
    'pcb.route_search': 'script_route_search',
    'pcb.high_speed_audit': 'high_speed',
    'manufacturing.precheck': 'mass_production_review',
    'manufacturing.export': 'manufacturing_export', 'manufacturing.release': 'npi_release',
    'lifecycle.check': 'project_flow',
}
WRITING = {'environment.konnect_fixture', 'environment.konnect_invoke', 'architecture.sources_resolve', 'architecture.sources_register', 'environment.setup', 'environment.bridge_plugin', 'environment.open_editor', 'pcb.edit', 'schematic.resources_lock', 'manufacturing.export', 'manufacturing.release'}
FLAGS = ('require_device_knowledge', 'require_reserve_review', 'require_placement_review',
         'require_schematic_style', 'require_system_integration')
METHODS = {
    'environment': 'Run KiCad CLI smoke and Konnect dynamic MCP discovery; legacy pcbnew optional.',
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


GROUP_ORDER = tuple(GROUPS)
CONFIRMATION_MODES = ('dialogue', 'formal_engineering')
APPROVAL_FOLDER = 'stage-approvals'


def confirmation_mode(configs):
    mode = configs['flow'].get('confirmation_mode', 'dialogue')
    if mode not in CONFIRMATION_MODES:
        raise ValueError('Unknown confirmation mode')
    return mode


def _approval_area(root, bundle, group):
    if group not in GROUPS:
        raise ValueError('Unknown workflow group')
    return local(root, Path(bundle) / APPROVAL_FOLDER / group)


def _latest_packet(root, bundle, group):
    area = _approval_area(root, bundle, group)
    versions = sorted((p for p in area.glob('r*') if p.is_dir()
                       and p.name[1:].isdigit()), key=lambda p: int(p.name[1:])) if area.is_dir() else []
    if not versions:
        raise ValueError('Stage engineer review pending for ' + group)
    return versions[-1] / 'packet.json'


def _stage_inputs(root, name, bundle, group, evidence):
    """Freeze existing stage files, configuration, and explicitly supplied outputs.

    No uncreated later-stage files are needed, and no approval can be its own evidence.
    """
    root = Path(root).resolve()
    configs = load_bundle(root, name, bundle)
    stage = GROUP_ORDER.index(group)
    tracked = {master_path(root, name), local(root, Path(bundle) / 'flow.json')}
    if stage >= 2:
        tracked.add(local(root, Path(bundle) / 'static.json'))
    if stage >= 3:
        tracked.add(local(root, Path(bundle) / 'npi.json'))
    suffixes = ('.kicad_sch', '.kicad_sym', '.kicad_pro', '.kicad_pcb', '.kicad_dru', '.kicad_mod')
    if stage >= 2:
        # Schematic stage binds schematic and library files. PCB stage adds board/pro config.
        stage_suffixes = suffixes[:2] if stage == 2 else suffixes
        tracked.update(p for p in root.rglob('*') if p.is_file() and p.suffix in stage_suffixes)
    outputs = set()
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('At least one actual stage output evidence is required')
    approvals = local(root, Path(bundle) / APPROVAL_FOLDER)
    for item in evidence:
        item_path = local(root, item)
        if item_path == approvals or approvals in item_path.parents:
            raise ValueError('Stage approval cannot reference approval files as evidence')
        if item_path.is_dir():
            outputs.update(p for p in item_path.rglob('*') if p.is_file())
        else:
            outputs.add(item_path)
    if not outputs or outputs.issubset(tracked):
        raise ValueError('Stage needs independent actual outputs, not only configuration files')
    tracked.update(outputs)
    digest = {}
    for item in sorted(tracked):
        # resolve also rejects traversal and symlink escape; explicit symlinks disallowed.
        if item.is_symlink() or not item.is_file() or not item.stat().st_size:
            raise ValueError('Missing, symlinked or empty stage evidence: ' + str(item))
        resolved = item.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError('Stage evidence escapes project root')
        if approvals in item.parents or item == approvals:
            raise ValueError('Approval artifacts cannot be review evidence')
        digest[resolved.relative_to(root).as_posix()] = sha256(resolved)
    return digest


def validate_stage(root, name, bundle, group, visited=()):
    root = local(Path(root), '.')
    if group in visited:
        raise ValueError('Cyclic approval chain')
    packet_path = _latest_packet(root, bundle, group)
    packet = read(packet_path)
    if (packet.get('schema_version') != 1 or packet.get('group') != group
            or packet.get('bundle') != bundle or packet.get('kind') != 'human_review'):
        raise ValueError('Invalid stage packet or automatic approval')
    actual = _stage_inputs(root, name, bundle, group, packet.get('evidence', []))
    if actual != packet.get('files_sha256'):
        raise ValueError('Stage evidence changed; new engineering review required')
    approval_path = packet_path.parent / 'approval.json'
    if not approval_path.is_file():
        raise ValueError('Engineering review has not been confirmed')
    confirmation = read(approval_path)
    review_path = local(root, confirmation.get('engineer_review', ''))
    if not review_path.is_file() or sha256(review_path) != confirmation.get('engineer_sha256'):
        raise ValueError('Engineer record missing or altered')
    review = read(review_path)
    if (review.get('role') != 'hardware_engineer' or review.get('decision') != 'approve'
            or review.get('group') != group or review.get('packet_sha256') != sha256(packet_path)
            or not isinstance(review.get('name'), str) or not review['name'].strip()
            or not isinstance(review.get('reason'), str) or not review['reason'].strip()):
        raise ValueError('Engineer record is not an explicit valid approval')
    date.fromisoformat(review['date'])
    index = GROUP_ORDER.index(group)
    if index:
        previous = GROUP_ORDER[index - 1]
        validate_stage(root, name, bundle, previous, visited + (group,))
        if packet.get('previous_packet_sha256') != sha256(_latest_packet(root, bundle, previous)):
            raise ValueError('Previous stage confirmation changed')
    return {'status': 'ENGINEER_APPROVED_CURRENT', 'group': group, 'packet': str(packet_path),
            'production_authorized': False}


def stage_prepare(root, name, bundle, group, evidence):
    root = local(Path(root), '.')
    cfg = load_bundle(root, name, bundle)
    if confirmation_mode(cfg) != 'formal_engineering':
        raise ValueError('Stage packet is only used in formal_engineering mode')
    index = GROUP_ORDER.index(group)
    previous_digest = None
    if index:
        previous = GROUP_ORDER[index - 1]
        validate_stage(root, name, bundle, previous)
        previous_digest = sha256(_latest_packet(root, bundle, previous))
    paths = _stage_inputs(root, name, bundle, group, evidence)
    area = _approval_area(root, bundle, group)
    area.mkdir(parents=True, exist_ok=True)
    numbers = [int(p.name[1:]) for p in area.glob('r*') if p.is_dir() and p.name[1:].isdigit()]
    dest = area / ('r' + str(max(numbers, default=0) + 1))
    dest.mkdir(exist_ok=False)
    packet = {'schema_version': 1, 'kind': 'human_review', 'group': group,
              'bundle': bundle, 'evidence': evidence, 'files_sha256': paths,
              'previous_packet_sha256': previous_digest}
    packet_path = dest / 'packet.json'
    packet_path.write_text(encoded(packet), encoding='utf-8')
    return {'status': 'ENGINEER_REVIEW_PENDING', 'group': group,
            'packet_sha256': sha256(packet_path), 'packet': str(packet_path),
            'production_authorized': False}


def stage_confirm(root, name, bundle, group, engineer_review):
    root = local(Path(root), '.')
    cfg = load_bundle(root, name, bundle)
    if confirmation_mode(cfg) != 'formal_engineering':
        raise ValueError('Formal stage approval must be explicitly configured')
    packet_path = _latest_packet(root, bundle, group)
    if (packet_path.parent / 'approval.json').exists():
        raise ValueError('Review already confirmed; create a fresh packet for changes')
    review_path = local(root, engineer_review)
    if not review_path.is_file() or not review_path.stat().st_size:
        raise ValueError('Existing engineer review JSON required')
    rec = read(review_path)
    if (rec.get('role') != 'hardware_engineer' or rec.get('decision') != 'approve'
            or rec.get('group') != group or rec.get('packet_sha256') != sha256(packet_path)
            or not str(rec.get('name') or '').strip() or not str(rec.get('reason') or '').strip()):
        raise ValueError('Engineer review is incomplete or not bound to this packet')
    date.fromisoformat(rec['date'])
    approval = packet_path.parent / 'approval.json'
    approval.write_text(encoded({'engineer_review': review_path.relative_to(root).as_posix(),
                                 'engineer_sha256': sha256(review_path)}), encoding='utf-8')
    try:
        return validate_stage(root, name, bundle, group)
    except Exception:
        approval.unlink()
        raise


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
    contract['confirmation_mode'] = 'dialogue'
    shared = {'inputs': npi['inputs'], 'documents': review['documents'], 'variant': None,
              'design_intent': npi['design_intent'], 'engineering_profile': npi['engineering_profile'],
              'resource_lock': None}
    review['resource_lock'] = npi['resource_lock'] = ref('/shared/resource_lock')
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
    confirmation_mode({'flow': c})
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
    for key in ('reserve_review', 'placement_review', 'schematic_style', 'system_integration', 'documents', 'resource_lock'):
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
    from skill_modules import registry as component_registry, fingerprint as component_fingerprint
    component_registry(ROOT)
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
                    'component_manifest_sha256': sha256(ROOT / 'references/component-manifest.json'),
                    'component_files_sha256': component_fingerprint(ROOT),
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
    if manifest.get('component_manifest_sha256') != sha256(ROOT / 'references/component-manifest.json'):
        raise ValueError('Components changed: rebuild configuration snapshot')
    from skill_modules import fingerprint as component_fingerprint
    if manifest.get('component_files_sha256') != component_fingerprint(ROOT):
        raise ValueError('Component instructions changed: rebuild configuration snapshot')
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
    mode = confirmation_mode(cfg)
    groups = []
    for group, nodes in GROUPS.items():
        if mode == 'dialogue':
            approval_status = 'DIALOGUE_CHECKPOINT'
        else:
            try:
                approval_status = validate_stage(root, name, bundle, group)['status']
            except (ValueError, KeyError, OSError):
                approval_status = 'ENGINEER_REVIEW_PENDING'
        groups.append({'group': group, 'nodes': list(nodes),
                       'tasks': [t for t in TASKS if t.startswith(group + '.')],
                       'gate_status': 'NOT_EVALUATED_BY_NAVIGATION',
                       'confirmation_status': approval_status})
    return {'status': 'NEEDS_INPUT' if report['findings'] else 'DECLARED_INPUTS_READY_NOT_APPROVED',
            'scope': 'navigation_only', 'production_authorized': False,
            'component_version': read(ROOT / 'references/component-manifest.json')['version'],
            'confirmation_mode': mode, 'groups': groups,
            'unfilled_config_fields': pending(cfg), 'findings': report['findings'],
            'note': 'Future missing files are pending work, not permission to skip gates. Feature N/A never disables a gate.'}


def command(root, name, bundle, task, options):
    root = Path(root).resolve()
    if task not in TASKS:
        raise ValueError('Unknown task')
    if options.get('apply') and task not in WRITING:
        raise ValueError('--apply is only valid for explicit candidate/setup writes')
    if options.get('cli_only') and task != 'environment.setup':
        raise ValueError('--cli-only only applies to environment.setup')
    if options.get('require_ipc') and not task.startswith('environment.ipc_'):
        raise ValueError('--require-ipc only applies to IPC discovery tasks')
    if task in ('environment.bridge_plugin','environment.open_editor','pcb.edit'):
        raise ValueError('LEGACY_WRITE_DISABLED: use Konnect MCP as the sole EDA writer; no silent kicad_bridge fallback')
    if task == 'pcb.high_speed_audit':
        flow.registry()
        if not options.get('high_speed_policy'):
            raise ValueError('High-speed audit requires --high-speed-policy; it is never an automatic connection check')
        policy = local(root, options['high_speed_policy'])
        if not policy.is_file():
            raise ValueError('Existing high-speed policy required')
        args = ['audit', str(root), '--policy', str(policy.relative_to(root))]
        if options.get('output_dir'):
            args += ['--output-dir', str(Path(options['output_dir']).absolute())]
        return 'high_speed', args
    if task.startswith('environment.konnect_') and task != 'environment.konnect_check':
        flow.registry()
        mode=task.removeprefix('environment.konnect_')
        if mode in ('fixture', 'invoke') and not options.get('apply'):
            raise ValueError('Konnect EDA mutation requires explicit --apply')
        args=[mode,'--executable',options.get('konnect_executable') or '',
              '--config',options.get('konnect_config') or '',
              '--output-dir',options.get('output_dir') or '']
        if not all(args[i] for i in (2,4,6)):
            raise ValueError('Konnect capability task needs --konnect-executable, --konnect-config, --output-dir')
        for opt,flag in (('konnect_enrollment','--enrollment'),('konnect_registry','--registry'),
                         ('konnect_tool','--tool'),('konnect_scope','--scope'),
                         ('arguments_json','--arguments'),('expected_json','--expected'),
                         ('source_board','--source-board')):
            if options.get(opt):args += [flag,options[opt]]
        if options.get('konnect_toolset'):
            for t in options['konnect_toolset'].split(','):
                args+=['--toolset',t.strip()]
        if options.get('konnect_all_toolsets'):args.append('--all-toolsets')
        if options.get('save_after'):args.append('--save-after')
        if mode in ('fixture', 'invoke'):args.append('--apply')
        if options.get('board'):args+=['--board',str(local(root,options['board']))]
        if options.get('kicad_cli'):args+=['--kicad-cli',options['kicad_cli']]
        return 'konnect_capabilities',args
    if task == 'environment.konnect_check':
        flow.registry()
        if not isinstance(options.get('output_dir'), str) or not options['output_dir'].strip():
            raise ValueError('Konnect check needs explicit --output-dir')
        args = ['--output-dir', str(Path(options['output_dir']).resolve())]
        if options.get('installation'):
            args += ['--installation', str(Path(options['installation']).resolve())]
        if options.get('board'):
            board = local(root, options['board'])
            if not board.is_file() or board.suffix != '.kicad_pcb':
                raise ValueError('Existing target PCB required')
            args += ['--expected-board', str(board)]
        return 'konnect_backend', args
    if task in ('architecture.sources_resolve', 'architecture.sources_register'):
        # Shared library intentionally lives outside the project/Skill repository.
        # The project inventory/selected requirements must still be project-scoped.
        flow.registry()  # enforce actual tool-manifest hash before dispatch
        cache_option = options.get('device_cache')
        inventory_option = options.get('device_inventory')
        if not isinstance(cache_option, str) or not cache_option.strip():
            raise ValueError('Knowledge lookup requires explicit --device-cache')
        cache = Path(cache_option).resolve()
        if not cache.is_dir():
            raise ValueError('Existing shared device-cache directory required')
        if not isinstance(inventory_option, str) or not inventory_option.strip():
            raise ValueError('Knowledge lookup requires project-relative --device-inventory')
        inventory = local(root, inventory_option)
        if not inventory.is_file():
            raise ValueError('Existing project inventory/verified requirements required')
        operation = 'resolve' if task.endswith('resolve') else 'register'
        args = ['--cache', str(cache), operation, '--requirements', str(inventory)]
        if options.get('apply'):
            if operation == 'resolve':
                dest = options.get('device_output')
                if not isinstance(dest, str) or not dest.strip():
                    raise ValueError('Use --device-output for a NEW project-local file')
                path = local(root, dest)
                if path.exists():
                    raise ValueError('Cannot overwrite existing resolved requirements')
                args += ['--output', str(path)]
            args.append('--apply')
        return 'device_knowledge', args
    if task == 'environment.bridge_plugin':
        flow.registry()
        if not options.get('destination') or not options.get('sessions_root'):
            raise ValueError('Bridge plugin needs --destination and --sessions-root')
        args = ['plugin', '--destination', options['destination'], '--sessions-root', options['sessions_root']]
        if options.get('python_executable'):
            args += ['--python-executable', options['python_executable']]
        if options.get('apply'):
            args.append('--apply')
        return 'kicad_bridge', args
    if task == 'environment.open_editor':
        flow.registry()
        if not all(options.get(k) for k in ('board','pcb_editor','runtime_dir')):
            raise ValueError('Editor launch needs --board, --pcb-editor and --runtime-dir')
        target = local(root,options['board'])
        args = ['open-editor','--board',str(target),'--pcb-editor',options['pcb_editor'],
                '--runtime-dir',options['runtime_dir']]
        if options.get('apply'):
            args.append('--apply')
        return 'kicad_bridge',args
    if task.startswith('environment.ipc_'):
        flow.registry()
        board = options.get('board')
        if not isinstance(board, str) or not board.strip():
            raise ValueError('IPC task needs explicit --board under the selected project')
        target = local(root, board)
        if target.suffix != '.kicad_pcb' or not target.is_file():
            raise ValueError('Existing target PCB required')
        args = ['snapshot' if task.endswith('snapshot') else 'probe', '--board', str(target)]
        output = options.get('output_dir')
        if task.endswith('snapshot') and not output:
            raise ValueError('IPC snapshot needs --output-dir')
        if output:
            args += ['--output-dir', output]
        if options.get('require_ipc'):
            args.append('--require-ipc')
        return 'kicad_ipc_probe', args
    if task == 'environment.doctor' and not bundle:
        flow.registry()
        args = ['--kicad-cli', options['kicad_cli']] if options.get('kicad_cli') else []
        return 'doctor', args
    if not bundle:
        raise ValueError('This task needs --bundle; build a configuration snapshot first')
    cfg = load_bundle(root, name, bundle)
    inputs = cfg['flow']['inputs']
    group = task.split('.')[0]
    if confirmation_mode(cfg) == 'formal_engineering' and GROUP_ORDER.index(group):
        validate_stage(root, name, bundle, GROUP_ORDER[GROUP_ORDER.index(group) - 1])

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
    if task == 'pcb.edit':
        request = local(root, required('bridge_request'))
        if not request.is_file():
            raise ValueError('Existing project-local bridge request required')
        args = ['request', '--session-dir', required('session_dir'), '--request', str(request)]
        if options.get('apply'):
            args.append('--apply')
    elif task == 'pcb.edit_drc':
        args = ['drc', '--board', input_file('board'),
                '--candidate-manifest', str(local(root, required('candidate_manifest'))),
                '--kicad-cli', required('kicad_cli'), '--output-dir', required('output_dir')]
    elif task == 'environment.doctor':
        args = []
    elif task == 'environment.check':
        args = ['check', '--state', required('state')]
    elif task == 'environment.setup':
        args = ['setup', '--project', str(root), '--schematic', input_file('schematic'),
                '--board', input_file('board'), '--project-file', input_file('project'),
                '--report-dir', required('output_dir')]
        if options.get('cli_only'):
            args.append('--cli-only')
    elif task in ('architecture.check', 'lifecycle.check'):
        args += ['--contract', str(Path(bundle) / 'flow.json')]
        args.insert(0, 'check')
    elif task == 'schematic.resources_lock':
        args = ['lock', str(root), '--manifest', required('resource_manifest'),
                '--output', required('resource_lock')]
    elif task == 'schematic.resources_check':
        args = ['check', str(root), '--lock', required('resource_lock'), '--review-config', config_file('static')]
    elif task in ('pcb.routing_preflight', 'pcb.routing_plan'):
        args = ['preflight' if task.endswith('preflight') else 'plan', str(root),
                '--request', required('routing_request')]
        if options.get('output_dir'):
            args += ['--output-dir', options['output_dir']]
        if options.get('after_attempt'):
            if task != 'pcb.routing_plan':
                raise ValueError('--after-attempt only applies to routing plan')
            args += ['--after-attempt', options['after_attempt']]
    elif task == 'pcb.route_search':
        args = [str(root), '--problem', required('route_problem')]
        if options.get('output_dir'):
            args += ['--output-dir', options['output_dir']]
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
                 '--output-dir', required('output_dir'), '--review-config', config_file('static')]
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



# R10: workspace index is navigation, not a KiCad writer or approval.
def workspace_action(a):
    import hashlib
    import shutil
    import re
    import datetime
    root = Path(a.project).resolve()
    if not root.is_dir() or Path(a.project).is_symlink():
        raise ValueError('Existing non-symlink workspace required')
    working = root / '01_WORKING'
    checkpoint_root = root / '02_CHECKPOINTS'
    reports = root / '03_REPORTS'
    release = root / '04_RELEASE'
    index = root / 'CURRENT_PROJECT.json'
    def safe(rel, exists=True):
        p = Path(rel)
        if p.is_absolute() or '..' in p.parts:
            raise ValueError('Workspace-relative safe path required')
        path = root
        for part in p.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError('Symlinked workspace path refused')
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or (exists and not resolved.exists()):
            raise ValueError('Missing/out-of-workspace path')
        return resolved
    def shafile(p):
        h = hashlib.sha256()
        with p.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
        return h.hexdigest()
    action = a.action
    if action == 'init':
        if not a.project_file:
            raise ValueError('--project-file required')
        project = safe(a.project_file)
        if project.suffix != '.kicad_pro' or not project.is_file() or project.relative_to(root).parts[0] != '01_WORKING':
            raise ValueError('Select existing .kicad_pro under 01_WORKING')
        if index.exists():
            raise ValueError('CURRENT_PROJECT.json already exists; never overwrite')
        if a.apply:
            for d in (checkpoint_root,reports,release):
                if d.exists() and not d.is_dir():
                    raise ValueError('Workspace directory path occupied by a file')
            for d in (checkpoint_root,reports,release):
                d.mkdir(exist_ok=True)
            record={'schema_version':1,'project':project.relative_to(root).as_posix(),
                    'workspace_policy':'single_active_project','history_policy':'preserve_all',
                    'production_authorized':False}
            with index.open('x',encoding='utf-8') as f:
                f.write(encoded(record))
        return {'status':'WORKSPACE_READY' if a.apply else 'PREVIEW',
                'project':project.relative_to(root).as_posix(),
                'history_deleted':False,'production_authorized':False}
    if not index.is_file() or index.is_symlink():
        raise ValueError('First register workspace with --action init')
    state=read(index)
    if state.get('schema_version') != 1 or state.get('workspace_policy') != 'single_active_project':
        raise ValueError('Unrecognized workspace index')
    selected=state.get('project')
    if not isinstance(selected,str) or not selected.startswith('01_WORKING/') or not selected.endswith('.kicad_pro'):
        raise ValueError('Invalid authoritative project selection')
    project=safe(selected)
    if not project.is_file():
        raise ValueError('Authoritative KiCad project missing')
    if action == 'status':
        result={'status':'WORKSPACE_ACTIVE','project':selected,'project_sha256':shafile(project),
                'checkpoint_count':len(list(checkpoint_root.iterdir())) if checkpoint_root.is_dir() else 0,
                'report_count':len(list(reports.iterdir())) if reports.is_dir() else 0,
                'release_count':len(list(release.iterdir())) if release.is_dir() else 0,
                'history_deleted':False,'production_authorized':False}
        if a.detailed:
            result['design_files']=sorted(p.name for p in project.parent.glob(project.stem+'.kicad_*') if p.is_file())
        return result
    if action == 'inventory':
        groups={'historical_project':[],'candidate_or_backup':[],
                'configuration_bundle':[],'review_or_report':[],'unclassified':[]}
        for item in sorted(root.iterdir()):
            if item.name in ('CURRENT_PROJECT.json','01_WORKING','02_CHECKPOINTS','03_REPORTS','04_RELEASE'):
                continue
            name=item.name.lower()
            kind=('historical_project' if item.suffix in ('.kicad_pro','.kicad_sch','.kicad_pcb')
                  else 'candidate_or_backup' if any(x in name for x in ('candidate','backup','freeze','checkpoint'))
                  else 'configuration_bundle' if any(x in name for x in ('control-','bundle-','snapshot'))
                  else 'review_or_report' if any(x in name for x in ('review','report','g1-','g4-'))
                  else 'unclassified')
            groups[kind].append(item.name)
        rows=[{'category':k,'name':name} for k,items in groups.items() for name in items]
        return {'status':'HISTORY_CLASSIFIED_READ_ONLY','counts':{k:len(v) for k,v in groups.items()},
                'total':len(rows),'items':rows[:a.limit],'truncated':len(rows)>a.limit,
                'history_deleted':False,'production_authorized':False}
    if action == 'checkpoint':
        if not a.label or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',a.label):
            raise ValueError('Unique safe checkpoint label required')
        dest=checkpoint_root/a.label
        if dest.exists():raise ValueError('Immutable checkpoint already exists')
        if a.apply:
            if any(p.is_symlink() for p in project.parent.rglob('*')):
                raise ValueError('Symlinks in active project are not accepted')
            checkpoint_root.mkdir(exist_ok=True)
            shutil.copytree(project.parent,dest)
            details={'schema_version':1,'status':'CHECKPOINT_CREATED_NOT_APPROVED',
                     'project':selected,'project_sha256':shafile(project),
                     'files_sha256':{p.relative_to(dest).as_posix():shafile(p) for p in dest.rglob('*') if p.is_file()},
                     'production_authorized':False}
            with (dest/'checkpoint-manifest.json').open('x',encoding='utf-8') as f:
                f.write(encoded(details))
        return {'status':'CHECKPOINT_CREATED_NOT_APPROVED' if a.apply else 'PREVIEW',
                'checkpoint':str(dest),'history_deleted':False,'production_authorized':False}
    if action == 'register':
        if a.stage not in ('G1','G2','G3','G4','ERC','DRC','DFX','RELEASE') or not a.artifact:
            raise ValueError('Stage and artifact required')
        artifact=safe(a.artifact)
        required='04_RELEASE' if a.stage=='RELEASE' else '03_REPORTS'
        if not artifact.is_file() or artifact.relative_to(root).parts[0]!=required:
            raise ValueError('Evidence file must exist inside the declared evidence area')
        target=reports/'index'/ (hashlib.sha256((a.stage+':'+a.artifact).encode('utf-8')).hexdigest()[:24]+'.json')
        if target.exists():raise ValueError('Evidence already indexed; no overwriting')
        if a.apply:
            target.parent.mkdir(exist_ok=True)
            with target.open('x',encoding='utf-8') as f:
                f.write(encoded({'schema_version':1,'stage':a.stage,'artifact':a.artifact,
                                 'artifact_sha256':shafile(artifact),
                                 'project':selected,'project_sha256':shafile(project),
                                 'production_authorized':False}))
        return {'status':'EVIDENCE_INDEXED_NOT_APPROVED' if a.apply else 'PREVIEW',
                'index':str(target),'history_deleted':False,'production_authorized':False}
    raise ValueError('Unsupported workspace action')


def compact_navigation(report):
    findings=report.get('findings',[])
    return {'status':report.get('status'),'scope':'navigation_only',
            'findings_count':len(findings),'finding_preview':findings[:5],
            'findings_truncated':len(findings)>5,
            'unfilled_fields_count':len(report.get('unfilled_config_fields',[])),
            'groups':[{'group':g['group'],'confirmation_status':g['confirmation_status']}
                      for g in report.get('groups',[])],
            'production_authorized':False,'full_evidence':'Use status --format json'}


def report_brief(path, limit):
    from collections import Counter
    if not 1<=limit<=30:raise ValueError('Report limit must be 1..30')
    p=Path(path).resolve()
    if not p.is_file() or p.is_symlink() or p.suffix.lower()!='.json':
        raise ValueError('Existing JSON report required')
    report=read(p)
    if not isinstance(report,dict):raise ValueError('Expected JSON report object')
    issues=[]
    for key in ('findings','preparation_issues','issues','checks','items','results'):
        values=report.get(key)
        if not isinstance(values,list):continue
        for v in values:
            if isinstance(v,dict):
                status=str(v.get('status') or v.get('level') or v.get('severity') or 'UNKNOWN')
                desc=str(v.get('description') or v.get('detail') or v.get('message') or v.get('task_id') or '')[:200]
            else: status='ISSUE';desc=str(v)[:200]
            issues.append({'status':status,'detail':desc,'origin':key})
    counts=dict(Counter(v['status'] for v in issues))
    issues.sort(key=lambda v:0 if any(x in v['status'].upper() for x in ('BLOCK','FAIL','ERROR')) else 1)
    return {'status':report.get('status','REPORT_BRIEF'),'source':str(p),'issue_count':len(issues),
            'by_status':counts,'issues':issues[:limit],'truncated':len(issues)>limit,
            'production_authorized':False,'note':'Use complete disk evidence for engineering gates'}


def summary(report):
    lines = ['工作流待办（阶段确认仅控制协作节奏，不替代工程门禁）']
    labels = ('环境', '需求/架构/资料', '原理图/封装', 'PCB规则/布局/布线', 'DFX/NPI/制造', '试产/ECO')
    for group, label in zip(report['groups'], labels):
        lines.append(f"- {label} [{group['group']}] {group['confirmation_status']}: " + ', '.join(group['tasks']))
    lines.append(f"项目契约缺项：{len(report['findings'])}；配置未填字段：{len(report['unfilled_config_fields'])}（含可能合法留空的可选项）。")
    for item in report['findings'][:8]:
        lines.append(f"  {item['location']}: {item['description']}")
    lines.append('工程尚未生成的PCB等文件属于后续待办；环境/需求工作可先开始。')
    lines.append('详细缺项用 status --format json；实际检查、AI和工程师签核必须分别执行。')
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    modules = sub.add_parser('modules', help='List task-specific reading modules without creating a project')
    selection = modules.add_mutually_exclusive_group()
    selection.add_argument('--module')
    selection.add_argument('--intent')
    ws=sub.add_parser('workspace',help='Unique working project and immutable checkpoints')
    ws.add_argument('project')
    ws.add_argument('--action',choices=('init','status','inventory','checkpoint','register'),required=True)
    ws.add_argument('--project-file')
    ws.add_argument('--label')
    ws.add_argument('--stage')
    ws.add_argument('--artifact')
    ws.add_argument('--limit',type=int,default=12)
    ws.add_argument('--apply',action='store_true')
    ws.add_argument('--detailed',action='store_true')
    brief=sub.add_parser('report-brief')
    brief.add_argument('input')
    brief.add_argument('--limit',type=int,default=6)
    for cmd in ('init', 'build', 'status', 'plan', 'run', 'stage-prepare', 'stage-confirm', 'stage-check'):
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
        if cmd in ('stage-prepare', 'stage-confirm', 'stage-check'):
            a.add_argument('--group', choices=GROUP_ORDER, required=True)
        if cmd == 'stage-prepare':
            a.add_argument('--evidence', action='append', required=True)
        if cmd == 'stage-confirm':
            a.add_argument('--engineer-review', required=True)
        if cmd == 'status':
            a.add_argument('--format', choices=('text', 'json','compact'), default='text')
        if cmd in ('plan', 'run'):
            a.add_argument('--task', choices=TASKS, required=True)
            for key in ('output-dir', 'state', 'packet', 'ai-review', 'engineer-review', 'netlist', 'destination', 'candidate-dir', 'kicad-cli', 'board', 'resource-manifest', 'resource-lock', 'routing-request', 'after-attempt', 'route-problem', 'bridge-request', 'session-dir', 'sessions-root', 'python-executable', 'candidate-manifest', 'pcb-editor', 'runtime-dir', 'installation', 'high-speed-policy', 'device-cache', 'device-inventory', 'device-output', 'konnect-executable','konnect-config','konnect-enrollment','konnect-registry','konnect-tool','konnect-scope','konnect-toolset','source-board','arguments-json','expected-json'):
                a.add_argument('--' + key)
            a.add_argument('--mode', choices=('prototype', 'mass_production'), default='mass_production')
            a.add_argument('--apply', action='store_true')
            a.add_argument('--cli-only', action='store_true', help='CLI-only environment smoke; no pcbnew or manufacturing approval')
            a.add_argument('--konnect-all-toolsets', action='store_true')
            a.add_argument('--save-after', action='store_true')
            a.add_argument('--require-ipc', action='store_true', help='Block an IPC-dependent task when the optional live connection is unavailable')
    a = p.parse_args()
    try:
        if a.cmd == 'modules':
            from skill_modules import select
            print(encoded(select(a.module, a.intent)), end='')
            return 0
        if a.cmd == 'workspace':
            print(encoded(workspace_action(a)),end='')
            return 0
        if a.cmd == 'report-brief':
            print(encoded(report_brief(a.input,a.limit)),end='')
            return 0
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
        elif a.cmd in ('stage-prepare', 'stage-confirm', 'stage-check'):
            if not a.bundle:
                raise ValueError('Stage action requires --bundle')
            load_bundle(root, a.config, a.bundle)
            if a.cmd == 'stage-prepare':
                r = stage_prepare(root, a.config, a.bundle, a.group, a.evidence)
            elif a.cmd == 'stage-confirm':
                r = stage_confirm(root, a.config, a.bundle, a.group, a.engineer_review)
            else:
                r = validate_stage(root, a.config, a.bundle, a.group)
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
        elif a.cmd == 'status' and a.format == 'compact':
            print(encoded(compact_navigation(r)),end='')
        else:
            print(encoded(r), end='')
        return 2 if r['status'] in ('BLOCKED', 'NEEDS_INPUT', 'ENGINEER_REVIEW_PENDING') else 0
    except Exception as e:
        from schematic_io import blocking
        print(encoded({'status': 'BLOCKED', 'production_authorized': False,
                       'findings': [blocking('WORKFLOW.INPUT', e)]}), end='')
        return 2


if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
