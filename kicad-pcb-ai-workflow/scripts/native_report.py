"""Fail-closed validation of the KiCad ERC/DRC JSON subset used by this gate.

Pinned 10.0.7 runtime/schema integration remains a required native test.
Missing fields or unknown types are never interpreted as zero violations.
"""
from pathlib import Path
from npi_common import TARGET_VERSION,finite_tree

def extract(kind,data,input_path,*,allow_ignored=False):
    finite_tree(data)
    if not isinstance(data,dict):raise ValueError('Native report root must be an object')
    if data.get('$schema')!='https://schemas.kicad.org/'+kind+'.v1.json':raise ValueError('Unknown report schema')
    if data.get('kicad_version')!=TARGET_VERSION or data.get('coordinate_units')!='mm':raise ValueError('Wrong report version/units')
    if not isinstance(data.get('source'),str) or Path(data['source']).name!=Path(input_path).name:raise ValueError('Report source does not match input')
    severities=data.get('included_severities')
    if not isinstance(severities,list) or set(severities)!={'error','warning','exclusion'}:raise ValueError('Report severity coverage incomplete')
    ignored=data.get('ignored_checks')
    if not isinstance(ignored,list):raise ValueError('Ignored checks absent or non-list')
    if ignored and not allow_ignored:raise ValueError('Ignored checks nonempty; review required')
    if allow_ignored and any(not isinstance(v,dict) or not isinstance(v.get('key'),str) or not v['key'] or not isinstance(v.get('description'),str) for v in ignored):
        raise ValueError('Malformed ignored-check declaration')
    groups=[]
    if kind=='drc':
        for key in ('violations','unconnected_items','schematic_parity'):
            if not isinstance(data.get(key),list):raise ValueError('Missing or non-list DRC section: '+key)
            groups.extend(data[key])
    elif kind=='erc':
        if not isinstance(data.get('sheets'),list) or not data['sheets']:raise ValueError('ERC sheets missing or empty')
        for sheet in data['sheets']:
            if not isinstance(sheet,dict) or not isinstance(sheet.get('path'),str) or not isinstance(sheet.get('violations'),list):raise ValueError('Malformed ERC sheet')
            groups.extend(sheet['violations'])
    else:raise ValueError('Unknown native check')
    for v in groups:
        if not isinstance(v,dict) or v.get('severity') not in ('error','warning','exclusion') or not isinstance(v.get('type'),str) or not v['type'] or not isinstance(v.get('description'),str) or not isinstance(v.get('items'),list):
            raise ValueError('Malformed violation entry')
        for item in v['items']:
            if not isinstance(item,dict) or not isinstance(item.get('description'),str):raise ValueError('Malformed affected item')
    return groups
