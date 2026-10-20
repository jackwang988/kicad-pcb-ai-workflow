#!/usr/bin/env python3
"""R20: unambiguous BOM/CPL consistency. Standard CSV, no network queries."""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

FIELDS=('Reference','MPN','Manufacturer','Footprint','Specification','Variant','DNP','Supplier','ApprovedAlternatives')

def read_bom(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not set(FIELDS).issubset(reader.fieldnames or []):raise ValueError('Production BOM missing columns: '+str(set(FIELDS)-set(reader.fieldnames or [])))
        rows=list(reader)
    if not rows:raise ValueError('Empty production BOM')
    expanded=[];seen=set()
    for row in rows:
        if any(not (row.get(k) or '').strip() for k in FIELDS):raise ValueError('Production BOM has empty required fields; use explicit NONE for no alternatives')
        if row['DNP'].lower() not in ('yes','no'):raise ValueError('DNP must explicitly be yes/no')
        refs=[x for x in re.split(r'[,;\s]+',row['Reference'].strip()) if x]
        if not refs or any(not re.fullmatch(r'[A-Za-z_]+\d+[A-Za-z]?',x) for x in refs):raise ValueError('Ambiguous reference/range; export explicit reference list')
        for ref in refs:
            key=(row['Variant'],ref)
            if key in seen:raise ValueError('Duplicate reference within variant: '+ref)
            seen.add(key);expanded.append({**row,'Reference':ref})
    return expanded

def grouped(rows):
    groups=defaultdict(list)
    keys=sorted(set().union(*(set(row) for row in rows))-{'Reference','Quantity'})
    for row in rows:groups[tuple(row.get(k,'') for k in keys)].append(row['Reference'])
    return [{'Reference':';'.join(sorted(refs)),**dict(zip(keys,key)),'Quantity':len(refs)} for key,refs in sorted(groups.items())]

def check_cpl(rows,cpl_path,variant):
    fitted={r['Reference']:r for r in rows if r['Variant']==variant and r['DNP'].lower()=='no'}
    if not fitted:raise ValueError('No fitted parts for requested variant')
    with Path(cpl_path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not {'Reference','PosX','PosY','Rotation','Side'}.issubset(reader.fieldnames or []):raise ValueError('CPL column contract not met')
        positions=list(reader)
    refs=[]
    for row in positions:
        refs.append(row['Reference'])
        if row['Side'] not in ('Top','Bottom'):raise ValueError('Explicit Top/Bottom side required')
        for k in ('PosX','PosY','Rotation'):
            n=float(row[k])
            if not (-1e8<n<1e8):raise ValueError('Nonfinite/unreasonable CPL coordinate')
    if len(refs)!=len(set(refs)) or set(refs)!=set(fitted):raise ValueError('CPL fitted reference coverage differs from selected variant BOM')
    return {'status':'PASS','variant':variant,'fitted_parts':len(fitted),'scope':'Reference/field/numeric consistency only; angle zero, bottom transform and polarity still need assembly review.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('bom');p.add_argument('--cpl');p.add_argument('--variant');p.add_argument('--output',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:
        rows=read_bom(a.bom);result=check_cpl(rows,a.cpl,a.variant) if a.cpl else {'status':'PASS','parts':len(rows),'groups':len(grouped(rows))}
        if a.output:
            if a.output.exists():raise ValueError('Output exists; overwrite forbidden')
            if a.apply:
                output=grouped(rows);a.output.parent.mkdir(parents=True,exist_ok=True)
                with a.output.open('x',encoding='utf-8-sig',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
            else:result['preview_output']=str(a.output)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,TypeError,KeyError) as e:print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
