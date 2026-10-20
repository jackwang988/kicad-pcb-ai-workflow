#!/usr/bin/env python3
"""R01/R06: strict KiCad XML comparison. 0 PASS / 1 FAIL / 2 BLOCKED.

Never use the legacy regex comparator as a production gate. XML input only.
"""
from __future__ import annotations
import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from npi_common import sha256

class InvalidNetlist(ValueError): pass

def read_netlist(path, allow_zero_nets=False):
    raw=Path(path).read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise InvalidNetlist('DTD/entity declarations are not accepted')
    try: root=ET.fromstring(raw)
    except ET.ParseError as e: raise InvalidNetlist('Malformed XML: '+str(e)) from e
    if root.tag!='export': raise InvalidNetlist('Expected KiCad XML <export> root')
    components=root.find('components'); nets=root.find('nets')
    if components is None or nets is None: raise InvalidNetlist('Required components/nets sections absent')
    comps={}
    for c in components.findall('comp'):
        ref=c.get('ref')
        if not ref or ref in comps: raise InvalidNetlist('Missing/duplicate component reference')
        # Include all metadata except source sheet placement/UUID timestamps. Do not guess MPN.
        fields={}
        for f in c.findall('./fields/field'):
            name=f.get('name')
            if not name or name in fields: raise InvalidNetlist('Missing/duplicate component field')
            fields[name]=(f.text or '').strip()
        comps[ref]={'value':(c.findtext('value') or '').strip(),
                    'footprint':(c.findtext('footprint') or '').strip(),
                    'datasheet':(c.findtext('datasheet') or '').strip(),'fields':fields,
                    'libsource':dict(c.find('libsource').attrib) if c.find('libsource') is not None else {},
                    'properties':sorted((p.get('name',''),p.get('value','')) for p in c.findall('property'))}
    if not comps: raise InvalidNetlist('No components: not an acceptable production netlist')
    networks={}; pin_to_net={}; pin_metadata={}
    for net in nets.findall('net'):
        name=net.get('name'); code=net.get('code')
        if not name or not code or name in networks: raise InvalidNetlist('Missing/duplicate net name or code')
        pins=[]
        for n in net.findall('node'):
            ref,pin=n.get('ref'),n.get('pin')
            if ref not in comps or not pin: raise InvalidNetlist('Unknown component or absent pin in net')
            key=(ref,pin)
            if key in pin_to_net: raise InvalidNetlist('Pin repeated or assigned to multiple nets: '+str(key))
            pin_to_net[key]=name; pins.append(key)
            pin_metadata['.'.join(key)]={k:v for k,v in n.attrib.items() if k not in ('ref','pin')}
        if not pins: raise InvalidNetlist('Empty network: '+name)
        networks[name]=sorted(pins)
    if not networks and not allow_zero_nets: raise InvalidNetlist('Zero networks requires explicit --allow-zero-nets')
    codes=[n.get('code') for n in nets.findall('net')]
    if len(codes)!=len(set(codes)): raise InvalidNetlist('Duplicate network code')
    return {'components':comps,'nets':networks,'pin_metadata':pin_metadata,
            'singleton_nets':{n:p for n,p in networks.items() if len(p)==1},
            'unconnected_nets':{n:p for n,p in networks.items() if n.startswith('unconnected-')},
            'sha256':sha256(path)}

def differences(a,b,topology=False):
    changes=[]
    for ref in sorted(set(a['components']) | set(b['components'])):
        x,y=a['components'].get(ref),b['components'].get(ref)
        if x!=y: changes.append({'kind':'component','key':ref,'before':x,'after':y})
    if topology:
        # Multiset of connectivity groups; singleton/unconnected pins are retained.
        x=Counter(tuple(tuple(p) for p in pins) for pins in a['nets'].values())
        y=Counter(tuple(tuple(p) for p in pins) for pins in b['nets'].values())
        if x!=y: changes.append({'kind':'topology','key':'pin_groups','before':sorted(x.elements()),'after':sorted(y.elements())})
    else:
        for name in sorted(set(a['nets']) | set(b['nets'])):
            x,y=a['nets'].get(name),b['nets'].get(name)
            if x!=y: changes.append({'kind':'net','key':name,'before':x,'after':y})
    for key in sorted(set(a['pin_metadata']) | set(b['pin_metadata'])):
        x,y=a['pin_metadata'].get(key),b['pin_metadata'].get(key)
        if x!=y: changes.append({'kind':'pin_metadata','key':key,'before':x,'after':y})
    return json.loads(json.dumps(changes))

def compare(before,after,mode='preserve',topology=False,eco=None,allow_zero_nets=False):
    a=read_netlist(before,allow_zero_nets);b=read_netlist(after,allow_zero_nets)
    actual=differences(a,b,topology)
    matched=not actual
    if mode=='eco':
        if not eco or not all(eco.get(x) for x in ('id','reason','approved_by','impact','expected_changes')):
            raise InvalidNetlist('ECO requires identity, reason, impact, approver and exact expected changes')
        if eco.get('baseline_sha256')!=a['sha256']: raise InvalidNetlist('ECO baseline hash does not match')
        expected=eco['expected_changes']
        canon=lambda x:sorted(json.dumps(t,sort_keys=True,separators=(',',':')) for t in x)
        matched=canon(actual)==canon(expected)
    return {'status':'PASS' if matched else 'FAIL','mode':mode,'topology':topology,
            'input_sha256':{'before':a['sha256'],'after':b['sha256']},'actual_changes':actual,
            'components':[len(a['components']),len(b['components'])],
            'nets':[len(a['nets']),len(b['nets'])],
            'unconnected_before':a['unconnected_nets'],'unconnected_after':b['unconnected_nets'],
            'limitations':'Topology comparison proves connectivity preservation only; it does not validate electrical design or unused library pins absent from exported netlist.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('before');p.add_argument('after')
    p.add_argument('--mode',choices=['preserve','eco'],default='preserve');p.add_argument('--topology',action='store_true')
    p.add_argument('--allow-zero-nets',action='store_true');p.add_argument('--eco',type=Path)
    a=p.parse_args()
    try: result=compare(a.before,a.after,a.mode,a.topology,json.loads(a.eco.read_text()) if a.eco else None,a.allow_zero_nets)
    except (OSError,ValueError,TypeError,KeyError) as e:
        print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
