#!/usr/bin/env python3
"""Fail-closed system architecture and cross-module net contract audit.

This checks declared hierarchy/module ownership and exact interface net
endpoints. Functional behavior, sequencing, analog margins and source
interpretation remain explicit AI/engineer review tasks.
"""
import argparse
import json
import re
from pathlib import Path

from npi_common import sha256
from npi_common import children
from schematic_io import sheets


def local(root, name):
    raw = root / name
    path = raw.resolve()
    if raw.is_symlink() or not path.is_relative_to(root):
        raise ValueError('Unsafe system contract path: ' + str(name))
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('Missing/empty system integration input: ' + str(name))
    return path


def audit(root, contract_name, top_schematic, graph, documents):
    root = Path(root).resolve()
    contract_path = local(root, contract_name)
    contract = json.loads(contract_path.read_text(encoding='utf-8-sig'))
    if contract.get('schema_version') != 1:
        raise ValueError('Unknown system integration contract schema')
    if not contract.get('project_id') or not contract.get('revision'):
        raise ValueError('System contract requires project_id and revision')
    docids = {d['id'] for d in documents}

    def source_ref(item, label):
        source = item.get('source')
        if not isinstance(source, dict) or source.get('document_id') not in docids or not source.get('locator'):
            raise ValueError(label + ' needs a bound source document and locator')

    overview = contract.get('overview')
    if not isinstance(overview, dict) or overview.get('sheet') != top_schematic:
        raise ValueError('System architecture overview must be bound to the actual top-level schematic sheet')
    source_ref(overview, 'Architecture overview')
    overview_file = local(root, overview.get('file', ''))
    if overview_file.suffix.lower() not in ('.pdf','.svg','.png'):
        raise ValueError('Architecture overview must be a reviewable PDF, SVG or PNG artifact')
    if overview.get('sha256') != sha256(overview_file):
        raise ValueError('Architecture overview hash mismatch')

    hierarchy = sheets(root, top_schematic)
    ref_sheets = {}
    for sheet_name, tree in hierarchy.items():
        for symbol in children(tree, 'symbol'):
            props={x[1]:x[2] for x in children(symbol,'property') if len(x)>2}
            ref=props.get('Reference','')
            if ref and not ref.startswith('#'):
                ref_sheets.setdefault(ref,set()).add(sheet_name)
    modules = contract.get('modules')
    if not isinstance(modules, list) or not modules:
        raise ValueError('At least one explicitly mapped architecture module is required')
    module_by_id = {}
    module_sheets = {}
    ref_owner = {}
    for module in modules:
        mid = module.get('id')
        if not isinstance(mid, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', mid) or mid in module_by_id:
            raise ValueError('Missing/duplicate/invalid architecture module id')
        if not module.get('name') or not module.get('role'):
            raise ValueError('Every module needs a name and role: ' + mid)
        declared_sheets = module.get('sheets') or ([module['sheet']] if module.get('sheet') else [])
        if not declared_sheets or len(declared_sheets)!=len(set(declared_sheets)) or not set(declared_sheets).issubset(hierarchy):
            raise ValueError('Module sheets must be unique reachable hierarchy pages: ' + mid)
        refs = module.get('components')
        if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
            raise ValueError('Every module needs a unique physical/logical component inventory: ' + mid)
        for ref in refs:
            if ref not in graph['components']:
                raise ValueError('Module references unknown schematic component: ' + str(ref))
            if not ref_sheets.get(ref) or not ref_sheets[ref].issubset(declared_sheets):
                raise ValueError('Module component is not physically declared on its assigned schematic page: ' + str(ref))
            if ref in ref_owner:
                raise ValueError('Component belongs to multiple modules: ' + str(ref))
            ref_owner[ref] = mid
        module_by_id[mid] = module
        module_sheets[mid] = declared_sheets
    if set(ref_owner) != set(graph['components']):
        missing = sorted(set(graph['components']) - set(ref_owner))
        raise ValueError('Architecture module inventory does not cover all components: ' + ', '.join(missing))

    interfaces = contract.get('interfaces')
    if not isinstance(interfaces, list):
        raise ValueError('interfaces must be an explicit list (empty is valid for a single-module design)')
    if len(modules) > 1 and not interfaces:
        raise ValueError('Multi-module designs require explicit cross-module interface contracts')
    seen_ids = set()
    checked_nets = []
    findings = []
    for interface in interfaces:
        iid = interface.get('id')
        if not isinstance(iid, str) or iid in seen_ids or not iid:
            raise ValueError('Missing/duplicate interface id')
        seen_ids.add(iid)
        source_ref(interface, 'Interface ' + iid)
        left, right = interface.get('from_module'), interface.get('to_module')
        if left not in module_by_id or right not in module_by_id or left == right:
            raise ValueError('Interface must connect two distinct declared modules: ' + iid)
        if not interface.get('purpose') or not interface.get('kind'):
            raise ValueError('Interface needs kind and purpose: ' + iid)
        nets = interface.get('nets')
        if not isinstance(nets, list) or not nets:
            raise ValueError('Interface needs explicit net endpoint contracts: ' + iid)
        for item in nets:
            name, terminals = item.get('name'), item.get('terminals')
            if not isinstance(name, str) or name not in graph['nets']:
                findings.append({'rule':'SYS.NET.MISSING','level':'阻断级','location':iid+':'+str(name),'description':'接口网络在当前KiCad网表中不存在','reference':f"KiCad当前XML网表；接口来源{interface['source']['document_id']} {interface['source']['locator']}",'fix':'修复原理图连接或更新有依据的接口契约。'})
                continue
            expected = {(n.get('ref'), str(n.get('pin'))) for n in terminals or [] if isinstance(n, dict)}
            if len(expected) < 2 or len(expected) != len(terminals or []):
                raise ValueError('Net needs at least two unique explicit terminal endpoints: ' + iid + '/' + name)
            actual = {(ref, str(pin)) for ref, pin in graph['nets'][name]}
            if expected != actual:
                findings.append({'rule':'SYS.NET.TOPOLOGY','level':'阻断级','location':iid+':'+name,
                                 'description':'接口预期引脚端点与当前KiCad网表不完全一致','expected':sorted(expected),'actual':sorted(actual),
                                 'reference':f"KiCad当前XML网表；接口来源{interface['source']['document_id']} {interface['source']['locator']}",
                                 'fix':'核对系统接口和原理图网络；不要为消除差异而盲目修改契约。'})
            owners = {ref_owner.get(ref) for ref, _ in expected}
            if left not in owners or right not in owners:
                findings.append({'rule':'SYS.NET.MODULE_BOUNDARY','level':'阻断级','location':iid+':'+name,
                                 'description':'该网络未实际跨越接口声明的两个模块','reference':f"项目模块接口契约；来源{interface['source']['document_id']} {interface['source']['locator']}",'fix':'核对模块归属、接口方向和网络端点。'})
            checked_nets.append({'interface_id':iid,'net':name,'expected':sorted(expected),'actual':sorted(actual),'status':'PASS' if expected == actual and left in owners and right in owners else 'FAIL'})
        checks = interface.get('checks')
        if not isinstance(checks, list) or not checks:
            raise ValueError('Each interface needs explicit electrical/functional review checks: ' + iid)
        for check in checks:
            if not check.get('id') or check.get('method') not in ('static_task','semantic','external_test_plan') or not check.get('acceptance'):
                raise ValueError('Interface check needs id, accepted method and acceptance condition: ' + iid)
            source_ref(check, 'Interface check ' + str(check.get('id')))

    system_checks = contract.get('system_checks')
    if not isinstance(system_checks, list) or not system_checks:
        raise ValueError('At least one system-level acceptance/check item is required')
    for check in system_checks:
        if not check.get('id') or check.get('method') not in ('static_task','semantic','external_test_plan') or not check.get('acceptance'):
            raise ValueError('System check needs id, accepted method and acceptance condition')
        source_ref(check, 'System check ' + str(check.get('id')))

    source_refs=[]
    for item in [overview, *interfaces, *[c for i in interfaces for c in i.get('checks',[])], *system_checks]:
        src=item['source'];key=(src['document_id'],src['locator'])
        if key not in source_refs:source_refs.append(key)
    return {'schema_version':1,'status':'CONTRACT_CHECKED_NOT_APPROVED' if not findings else 'BLOCKED',
            'project_id':contract['project_id'],'revision':contract['revision'],'hierarchy_sheets':hierarchy,
            'module_pages':module_sheets,
            'module_count':len(modules),'interface_count':len(interfaces),'system_check_count':len(system_checks),'checked_nets':checked_nets,
            'module_components':{m['id']:m['components'] for m in modules},'interfaces':interfaces,
            'system_checks':system_checks,'source_refs':[{'document_id':d,'locator':l} for d,l in source_refs],
            'unautomated_checks':'Electrical compatibility, power budget, sequencing, analog margins and system behavior require the bound AI/engineer or external verification tasks.',
            'findings':findings,'inputs_sha256':{str(contract_path):sha256(contract_path),str(overview_file):sha256(overview_file)}}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project');ap.add_argument('--contract',required=True);ap.add_argument('--schematic',required=True);ap.add_argument('--netlist',required=True);ap.add_argument('--documents',required=True,help='JSON array of reviewed source document records')
    a=ap.parse_args();root=Path(a.project).resolve()
    try:
        from netlist_guard import read_netlist
        graph=read_netlist(local(root,a.netlist))
        result=audit(root,a.contract,a.schematic,graph,json.loads(local(root,a.documents).read_text(encoding='utf-8-sig')))
        print(json.dumps(result,ensure_ascii=False,indent=2));return 1 if result['findings'] else 0
    except Exception as e:
        print(json.dumps({'status':'BLOCKED','error':str(e)},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
