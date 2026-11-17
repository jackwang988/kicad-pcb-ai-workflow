#!/usr/bin/env python3
"""Revalidate the immutable schematic pre-placement receipt immediately before a write.

No KiCad writes or direct MCP calls. This is a verification boundary for a
cooperating Konnect orchestrator; it cannot stop a client bypassing the Skill.
"""
import argparse
import json
from pathlib import Path
from schematic_geometry import bounded, sha
from schematic_preplacement import layout


def authorize(root,request,receipt):
    root=Path(root).resolve()
    current=bounded(root,request)
    saved=Path(receipt).resolve()
    allowed=not saved.is_relative_to(root) or saved.is_relative_to(root/'03_REPORTS')
    if not saved.is_file() or saved.is_symlink() or not allowed:
        raise ValueError('Immutable receipt must be in 03_REPORTS or outside active project')
    data=json.loads(saved.read_text(encoding='utf-8-sig'))
    if data.get('status')!='PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY' or data.get('request_sha256')!=sha(current):
        raise ValueError('No current, successfully verified pre-placement receipt')
    rechecked=layout(root,json.loads(current.read_text(encoding='utf-8-sig')))
    if rechecked.get('status')!='PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY':
        raise ValueError('Current project is not pre-placement feasible')
    for k in ('page','schematic','schematic_sha256','geometry_sha256','topology_sha256','bindings','placements','trial_routes'):
        if data.get(k)!=rechecked.get(k):
            raise ValueError('Pre-placement plan/evidence changed: '+k)
    return {'status':'PREPLACEMENT_RECEIPT_CURRENT_FOR_NEXT_BATCH','schematic':data['schematic'],
            'schematic_sha256':data['schematic_sha256'],'request_sha256':data['request_sha256'],
            'receipt_sha256':sha(saved),'scope':'must execute precisely this planned batch, then re-read and run native ERC/netlist and visual checks',
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
