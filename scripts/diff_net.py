#!/usr/bin/env python3
"""Compare exported KiCad XML netlists. 0=equivalent, 1=different, 2=invalid input.

--topo ignores net names only; it compares pin connectivity groups. This does
not prove component values, footprints, geometry, or design correctness.
Unconnected nets are included so missing pins are not silently ignored.
"""
import argparse
from collections import Counter
import json
import sys
import xml.etree.ElementTree as ET

def parse(path):
    root=ET.parse(path).getroot()
    if root.tag!='export':raise ValueError('Expected KiCad <export> root')
    nodes=root.find('nets')
    if nodes is None:raise ValueError('No <nets> section')
    result={}
    for net in nodes.findall('net'):
        name=net.get('name')
        if name is None or name in result:raise ValueError('Missing or duplicate net name')
        pins=[]
        for n in net.findall('node'):
            ref,pin=n.get('ref'),n.get('pin')
            if not ref or not pin:raise ValueError('Node missing ref or pin')
            pins.append((ref,pin))
        if len(pins)!=len(set(pins)):raise ValueError('Duplicate node in net')
        result[name]=frozenset(pins)
    if not result:raise ValueError('Empty netlist cannot establish equivalence')
    allpins=[p for v in result.values() for p in v]
    if len(allpins)!=len(set(allpins)):raise ValueError('Pin appears in multiple nets')
    return result

def compare(a,b,topo=False):
    if topo:return Counter(a.values())==Counter(b.values())
    return a==b

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('baseline');ap.add_argument('candidate')
    ap.add_argument('--topo',action='store_true');ap.add_argument('--json',action='store_true')
    a=ap.parse_args(argv)
    try:left,right=parse(a.baseline),parse(a.candidate)
    except (OSError,ET.ParseError,ValueError) as e:
        print('Invalid input: '+str(e),file=sys.stderr);return 2
    ok=compare(left,right,a.topo)
    result={'equivalent':ok,'mode':'topology' if a.topo else 'strict','baseline_nets':len(left),'candidate_nets':len(right),'baseline_pins':sum(map(len,left.values())),'candidate_pins':sum(map(len,right.values()))}
    if a.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        for k,v in result.items():print(f'{k}: {v}')
        if not ok:print('Difference found. Inspect exported netlists; no files were changed.')
    return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
