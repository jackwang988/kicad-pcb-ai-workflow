#!/usr/bin/env python3
"""Revalidate the immutable schematic pre-placement receipt immediately before a write.

No KiCad writes or direct MCP calls. This is a verification boundary for a
cooperating Konnect orchestrator; it cannot stop a client bypassing the Skill.
"""
import argparse
import json
from pathlib import Path
from schematic_geometry import bounded, sha



def authorize(root,request,receipt):
    """Fast tier-one recheck of the immutable plan and its source bindings.

    Do not run the exhaustive A* search a second time for the same immutable
    request. The planned placements are what the Konnect host must execute;
    native netlist, ERC and visual geometry are post-edit gates, not pretexts
    to re-create the schematic on every operation.
    """
    root=Path(root).resolve()
    current=bounded(root,request)
    saved=Path(receipt).resolve()
    allowed=not saved.is_relative_to(root) or saved.is_relative_to(root/'03_REPORTS')
    if not saved.is_file() or saved.is_symlink() or not allowed:
        raise ValueError('Immutable receipt must be in 03_REPORTS or outside active project')
    data=json.loads(saved.read_text(encoding='utf-8-sig'))
    allowed_statuses=('PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY',
                      'PREPLACEMENT_GEOMETRY_READY_ROUTE_REVIEW_REQUIRED')
    if data.get('status') not in allowed_statuses or data.get('request_sha256')!=sha(current):
        raise ValueError('No current geometry-feasible pre-placement receipt')
    req=json.loads(current.read_text(encoding='utf-8-sig'))
    if req.get('schematic')!=data.get('schematic') or req.get('page')!=data.get('page'):
        raise ValueError('Receipt targets a different schematic or page')
    native=req.get('geometry_mode')=='native_auto'
    if (req.get('schematic_sha256')!=data.get('schematic_sha256') or
        (not native and req.get('geometry_sha256')!=data.get('geometry_sha256')) or
        (native and data.get('geometry_mode')!='native_auto') or
        req.get('topology_sha256')!=data.get('topology_sha256')):
        raise ValueError('Plan request digest differs from receipt')
    if not isinstance(data.get('bindings'),dict) or not data['bindings']:
        raise ValueError('Missing source-bound plan inputs')
    for relative,expected_sha in data['bindings'].items():
        if sha(bounded(root,relative))!=expected_sha:
            raise ValueError('Pre-placement source changed: '+str(relative))
    solver_dir=Path(__file__).resolve().parent
    if not isinstance(data.get('solver_hashes'),dict) or not data['solver_hashes']:
        raise ValueError('Pre-placement receipt lacks bound solver version')
    for name,expected in data['solver_hashes'].items():
        if name not in ('schematic_native_geometry.py','schematic_preplacement.py',
                        'schematic_space_map.py','schematic_wire_planner.py') or sha(solver_dir/name)!=expected:
            raise ValueError('Placement engine version changed; re-plan')
    if native:
        # Avoid re-parsing every symbol and rerunning A* for an unchanged plan.
        # All current native files, the request (worksheet reservation) and
        # the engine hash have already been checked above.
        for absolute,expected in data.get('external_bindings',{}).items():
            source=Path(absolute)
            if not source.is_absolute() or not source.is_file() or sha(source)!=expected:
                raise ValueError('External KiCad symbol library changed: '+absolute)
    if not isinstance(data.get('placements'),dict) or not data['placements']:
        raise ValueError('No placements in the current receipt')
    if {s.get('ref') for s in req.get('symbols',[]) if isinstance(s,dict)} != set(data['placements']):
        raise ValueError('Planned symbol identities differ from request')
    # A conditional placement is only permission to attempt bounded symbol
    # placement. Trial wiring remains unverified and cannot auto-advance G1.
    conditional=data['status']==allowed_statuses[1]
    return {'status':('PREPLACEMENT_GEOMETRY_CURRENT_WIRING_REVIEW_REQUIRED' if conditional
                      else 'PREPLACEMENT_RECEIPT_CURRENT_FOR_NEXT_BATCH'),
            'schematic':data['schematic'],'schematic_sha256':data['schematic_sha256'],
            'request_sha256':data['request_sha256'],'receipt_sha256':sha(saved),
            'placements':data['placements'],
            'allow_placement_batch':True,'allow_unverified_wiring':False,
            'post_write_checks_required':['exact_symbol_positions','saved_native_netlist','ERC','current_visual_placement'],
            'scope':'execute only this coordinate/rotation batch then read back actual saved KiCad state',
            'executed':False,'production_authorized':False,
            'warning':'Direct calls to Konnect outside this Skill path cannot be intercepted.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project');p.add_argument('--request',required=True);p.add_argument('--receipt',required=True)
    a=p.parse_args()
    try:
        result=authorize(a.project,a.request,a.receipt)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'executed':False,'production_authorized':False}))
        return 2

if __name__=='__main__':raise SystemExit(main())
