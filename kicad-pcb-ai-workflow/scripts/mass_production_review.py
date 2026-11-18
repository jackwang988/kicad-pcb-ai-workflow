#!/usr/bin/env python3
"""Additive read-only DFX/NPI review. Exit 2 = blocked, 0 = no blocking findings.

Reports are new artifacts; engineering source files are never written.
Heuristics are explicitly marked and cannot replace engineering sign-off.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import fnmatch
import json
import math
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from npi_common import (TARGET_VERSION, LEVELS, environment, run, sha256, load_board,
                        parse_sexpr, child, children, value, xy, distance,
                        segment_distance, polygon_area, write_json, cli_compatible, pcbnew_compatible, pair_compatible, patch_native_ready)

MANUAL = [
 ('NPI.CAM','npi','CAM review of Gerber/CPL/BOM/assembly parity against the approved design','Approved manufacturing package contract, fabricator CAM and assembly-house requirements','Inspect layer polarity, outline, drills, CPL origin/rotation and assembly variants; nonempty files do not replace CAM review.'),
 ('SCH.PROTECTION','schematic','Reverse-polarity, ESD/TVS, fuse, watchdog and reset topology review','Manufacturer datasheet reference circuit and product interface/fail-safe requirements','Identify relevant devices, nets and applicability per power domain/external interface; presence alone does not prove protection.'),
 ('SCH.CREEPAGE','schematic','Engineer review of high-voltage creepage and clearance','Applicable product safety standard and IEC 60664-1; no universal distance assumption','Record voltage domain, working voltage, pollution degree, material group, altitude and insulation type; obtain engineer sign-off.'),
 ('SCH.DERATING','schematic','Voltage, power, current and thermal derating','Manufacturer ratings/temperature derating curves and approved internal derating rules','Cross-check exact MPNs against an approved parameter database; without it, do not declare derating compliant.'),
 ('SCH.LIFECYCLE','schematic','EOL/NRND status and alternate-part review','Manufacturer lifecycle notices and PCN/PDN','Manually consult manufacturer/authorized supply data and record source/check date; this tool does not browse automatically.'),
 ('LAY.THERMAL','layout','Thermal copper, heat vias and thermal-source/sensitive-part placement','Manufacturer layout/thermal recommendations and IPC-2152 current-carrying guidance','Check thermal resistance path, actual filled copper links, heat via size/count and temperature-rise budget.'),
 ('LAY.DFT','layout','Test-point access, fixture clearance and JTAG chain','Fixture probe vendor limits and IEEE 1149.1 where applicable','Review access with both assembly sides and probe direction; check actual JTAG pin nets, not connector name only.'),
 ('LAY.HEIGHT','layout','Component height and enclosure/screw/connector interference','Mechanical drawings, manufacturer packages and tolerance stack','Review actual 3D assembly and height limits; 2D bounding boxes cannot prove clearance in Z.'),
 ('LAY.PLANES','layout','Power plane regions, reference continuity and NetClass applicability','Manufacturer hardware guide and approved stack-up/NetClass contract','Verify sensitive signal reference plane continuity and power-domain boundaries; a named NetClass does not prove correct settings.'),
 ('LAY.PARTITION','layout','Analog/digital/power partitions, differential pairs and noise separation','Manufacturer layout guidance and interface specification','Review functional partitions and return paths; distance rules are static screening only.'),
 ('ROUTE.COPPER','routing','Acute copper corners, neckdowns, islands and zone overlap','Fabricator process rules, KiCad DRC and zone settings','Check actual zone fill, minimum neck, thermal spokes and different-net overlap; zone outline is not filled copper.'),
 ('ROUTE.BALANCE','routing','Copper layer balance and PCB warpage risk','Fabricator stack-up/copper balance rules; IPC-6012 if applicable to product contract','Area estimates are not thermo-mechanical warp simulation; send copper distribution and lamination to the fabricator.'),
 ('ROUTE.PANEL','routing','V-cut, mouse-bite, panel fiducials and copper clearance','Approved panelization and assembly-house process drawings','Specify panel plan; check v-score residual thickness, skip areas, edge copper gap and mouse bites explicitly.'),
 ('SIM.SPICE','simulation','SPICE model, stimuli, analysis commands and simulation results','Manufacturer SPICE model documentation and circuit acceptance criteria','CLI can export a SPICE netlist; install ngspice and provide verified models/bench separately.'),
 ('SIM.THERMAL','simulation','Thermal simulation or temperature-rise validation plan','Manufacturer thermal limits and product reliability plan','Export source list to an external thermal solver; without one, only static screening is available.'),
 ('SIM.EMC','simulation','Static review of RF/EMI sources, filtering, grounding and shielding','Applicable product EMC standard and manufacturer EMC guidance','Review clocks, switching rails and cables; do not claim full-wave EM simulation or certification.'),
 ('NPI.ECO','npi','ECO change record and impact analysis','Approved configuration management and ECO procedure','Record change, cause, impacted scope, risks, verification, approver and baseline revision.'),
 ('NPI.EVT','npi','EVT functionality, power, interface and testability acceptance','Product requirements and EVT test plan','Record samples, conditions, criteria, real results, evidence and test owner.'),
 ('NPI.DVT','npi','DVT thermal, humidity, vibration and aging reliability acceptance','Product requirements and applicable IEC 60068 test methods','Engineer chooses applicable tests; do not apply one universal test grade to all products.'),
 ('NPI.PVT','npi','PVT line process, yield, test coverage and traceability acceptance','Manufacturing quality and line acceptance contract','Record pilot lot, first-pass yield, defect closure, test coverage, fixture version and traceability.'),
 ('NPI.CERT','npi','CCC/CE certification applicability and pre-compliance design review','Regulatory and harmonized standards for the target market/product category','Engineer determines applicable certification; checklist sign-off is not an issued certificate.'),
]

class Review:
    def __init__(self, config, mode, phase):
        self.config=config; self.mode=mode; self.phase=phase
        self.findings=[]; self.checks=[]; self.evidence=[]; self.inputs={}
    def risk(self, code, gate, level, description, location='project-wide (no coordinates)',
             standard='approved project requirements', fix='Review, repair and rerun the checks.', method='deterministic screening'):
        self.findings.append(dict(id=f'{code}-{len(self.findings)+1}',rule=code,gate=gate,
            level=level,location=location,description=description,reference=standard,
            suggestion=fix,method=method))
    def check(self, code, status, detail, method='deterministic screening'):
        self.checks.append(dict(rule=code,status=status,detail=detail,method=method))
    def signoffs(self):
        signs=self.config.get('manual_reviews',{})
        for code,gate,title,standard,fix in MANUAL:
            if code=='NPI.CAM' and self.phase!='release':
                self.check(code,'deferred','Review actual candidate outputs; no production release is implied','human CAM review');continue
            record=signs.get(code,{})
            valid=False
            try:
                from engineering_gate import evidence
                if record.get('status') not in ('approved','not_applicable') or not all(record.get(x) for x in ('reviewer','date','reason','evidence')):raise ValueError('Incomplete signoff')
                dt.date.fromisoformat(record['date'])
                if not isinstance(record['evidence'],list) or not getattr(self,'project',None):raise ValueError('Hashed evidence list/project required')
                for rec in record['evidence']:evidence(rec,self.project,self)
                valid=True
            except (OSError,ValueError,TypeError,KeyError):valid=False
            if valid:
                self.check(code,record['status'],record,'human engineer review')
            else:
                self.risk(code,gate,'\u963b\u65ad\u7ea7',title+': complete human sign-off evidence is missing',standard=standard,fix=fix,method='external human review interface')
                self.check(code,'pending',title,'external human review interface')

def safe_input(project, entry):
    if not entry: return None
    p=(project/entry).resolve()
    if not p.is_relative_to(project.resolve()): raise ValueError('Input must be inside project: '+str(entry))
    return p

def read_bom(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def bom_checks(r, path):
    if not path or not path.is_file():
        r.risk('BOM.MISSING','schematic','\u963b\u65ad\u7ea7','Missing BOM input for current design review',fix='Provide CSV with reference, MPN, manufacturer, package and specification; it is not an approved production BOM.')
        return []
    rows=read_bom(path)
    if not rows:
        r.risk('BOM.EMPTY','schematic','\u963b\u65ad\u7ea7','BOM contains a header only or no components; zero-row cannot be accepted',str(path));return []
    fields=r.config.get('bom_fields',{'ref':'Reference','mpn':'MPN','manufacturer':'Manufacturer','footprint':'Footprint','spec':'Value'})
    refs=[]; mpns=defaultdict(set)
    for i,row in enumerate(rows,2):
        ref=row.get(fields['ref'],'').strip(); refs.extend(re.split(r'[,;\s]+',ref) if ref else [])
        for key,column in fields.items():
            if not (row.get(column) or '').strip():
                r.risk('BOM.FIELD','schematic','\u963b\u65ad\u7ea7',f'BOM row {i} missing field {column}',ref or f'BOM row {i}',
                       'Approved BOM and procurement-field contract','Add manufacturer-traceable fields; do not infer MPN from Value.')
        if row.get(fields['mpn']):
            mpns[row[fields['mpn']]].add(tuple(row.get(fields[k],'') for k in ('manufacturer','footprint','spec')))
    for ref,count in Counter(refs).items():
        if count>1: r.risk('BOM.DUPLICATE','schematic','\u963b\u65ad\u7ea7',f'Reference appears in BOM {count} times',ref,fix='Check fitted instance/grouping and remove duplicate references.')
    for mpn,definitions in mpns.items():
        if len(definitions)>1: r.risk('BOM.CONFLICT','schematic','\u9ad8\u98ce\u9669','Same MPN maps to conflicting manufacturer, package or specification',mpn,fix='Check full MPN suffix, package and manufacturer; document legitimate differences.')
    r.check('BOM.FIELDS','completed',f'{len(rows)} rows, {len(refs)} references; fields, duplicates and conflicts checked')
    return rows

def native_checks(r, env, project, sch, pcb):
    if not cli_compatible(env):
        r.risk('ENV.CLI','schematic','\u963b\u65ad\u7ea7',f'Matching stable KiCad 10.0.x CLI required; detected={env["cli_version"]}',
               standard='KiCad 10.0 CLI documentation and current command verification',fix='Select actual stable KiCad CLI with --kicad-cli and verify version/commands.',method='KiCad CLI')
        return
    # ERC does not support --variant in the official 10.0.7 CLI.
    with tempfile.TemporaryDirectory(prefix='kicad-npi-native-') as d:
        from environment_start import inventory
        snapshot=Path(d)/'project'
        try:
            for name in inventory(project):
                target=snapshot/name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(project/name,target)
        except (OSError,ValueError) as e:
            r.risk('NATIVE.SNAPSHOT','routing','\u963b\u65ad\u7ea7','Cannot create isolated candidate snapshot: '+str(e),method='KiCad CLI')
            return
        for kind,input_path in (('erc',sch),('drc',pcb)):
            if not input_path or not input_path.exists():
                r.risk('NATIVE.'+kind.upper(),'schematic' if kind=='erc' else 'routing','\u963b\u65ad\u7ea7',f'Missing {kind} input file',method='KiCad CLI'); continue
            report=Path(d)/(kind+'.json')
            native_input=snapshot/input_path.relative_to(project)
            command=[env['kicad_cli'],'sch' if kind=='erc' else 'pcb',kind,
                     '--format','json','--units','mm','--severity-all','--exit-code-violations','--output',str(report),str(native_input)]
            if kind=='drc': command.insert(-1,'--schematic-parity')
            result=run(command); r.evidence.append(result)
            # Native results are evidence; missing/unparseable reports fail closed.
            if not report.is_file():
                r.risk('NATIVE.'+kind.upper(),'schematic' if kind=='erc' else 'routing','\u963b\u65ad\u7ea7',f'{kind} did not generate a valid report',fix='Inspect native CLI log and rerun after fixing the error.',method='KiCad CLI'); continue
            try: data=json.loads(report.read_text(encoding='utf-8-sig'))
            except (ValueError,OSError):
                r.risk('NATIVE.'+kind.upper(),'routing','\u963b\u65ad\u7ea7','Cannot parse native JSON report',method='KiCad CLI'); continue
            from native_report import extract
            try:groups=extract(kind,data,input_path,expected_version=env['cli_version'])
            except (ValueError,TypeError,KeyError) as e:
                r.risk('NATIVE.SCHEMA','routing','\u963b\u65ad\u7ea7','Native JSON schema is incomplete or unsupported: '+str(e),method='KiCad CLI');continue
            r.evidence.append({'kind':kind,'report':data})
            for v in groups:
                severity=str(v.get('severity','error')).lower()
                if v.get('excluded',False) or severity in ('exclusion','excluded'):
                    r.risk('NATIVE.EXCLUDED','routing','\u963b\u65ad\u7ea7','Native report includes excluded violation: '+str(v),fix='Manually inspect exclusion rationale and record approved manufacturing evidence.',method='KiCad CLI'); continue
                location='; '.join(str(x.get('description',x))+(' @ '+str(x.get('pos')) if x.get('pos') else '') for x in v.get('items',[])) or str(input_path.name)
                r.risk('NATIVE.'+kind.upper(),'schematic' if kind=='erc' else 'routing',
                       '\u963b\u65ad\u7ea7' if severity=='error' else '\u9ad8\u98ce\u9669',v.get('description',v.get('type','native violation')),location,
                       'Current KiCad ERC/DRC rules','Locate and fix the violation in KiCad; do not remove rules or suppress counts to release.','KiCad CLI')
            if result['returncode'] not in (0,5):
                r.risk('NATIVE.EXEC','routing','\u963b\u65ad\u7ea7',f'{kind} command failed with return code {result["returncode"]}',method='KiCad CLI')
            if result['returncode'] and not groups:
                r.risk('NATIVE.UNKNOWN','routing','\u963b\u65ad\u7ea7',f'{kind} exited nonzero without a recognized violation; cannot pass',method='KiCad CLI')
            r.check('NATIVE.'+kind.upper(),'completed',f'{len(groups)} native result(s); no extra variant parameter supplied','KiCad CLI')

def schematic_structure(r, root, project):
    visited=set(); active=set(); references=[]; hierarchy=[]
    def visit(path):
        if path in active:
            r.risk('SCH.CYCLE','schematic','\u963b\u65ad\u7ea7','Hierarchical sheet cycle detected',str(path)); return
        if path in visited: return
        active.add(path); visited.add(path)
        try: tree=parse_sexpr(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError) as e:
            r.risk('SCH.PARSE','schematic','\u963b\u65ad\u7ea7',str(e),str(path)); active.remove(path); return
        if tree[0]!='kicad_sch': r.risk('SCH.FORMAT','schematic','\u963b\u65ad\u7ea7','Not a kicad_sch root',str(path))
        localrefs=[]
        for sym in children(tree,'symbol'):
            if not child(sym,'lib_id'): continue
            props={x[1]:x[2] for x in children(sym,'property') if len(x)>2}
            ref=props.get('Reference','')
            if ref and not ref.startswith('#'): localrefs.append(ref); references.append((ref,str(path.name)))
        # Multi-unit symbols legitimately share references; BOM duplicate test is separate.
        for sheet in children(tree,'sheet'):
            props={x[1]:x[2] for x in children(sheet,'property') if len(x)>2}
            filename=props.get('Sheetfile') or props.get('Sheet file')
            if not filename:
                r.risk('SCH.SHEET','schematic','\u963b\u65ad\u7ea7','Hierarchical sheet missing Sheetfile',str(path)); continue
            sub=(path.parent/filename).resolve()
            if not sub.is_relative_to(project.resolve()):
                r.risk('SCH.SHEET','schematic','\u963b\u65ad\u7ea7','Child sheet path escapes project root',str(sub)); continue
            hierarchy.append({'parent':path.name,'child':str(sub.relative_to(project)),
                              'pins':[p[1] for p in children(sheet,'pin')]})
            visit(sub)
        active.remove(path)
    if root: visit(root)
    for path in visited:
        if path.is_file(): r.inputs[str(path.resolve())]=sha256(path)
    r.evidence.append({'hierarchy':hierarchy,'files':len(visited)})
    r.check('SCH.HIERARCHY','completed',f'{len(visited)} sheet file(s); true cross-sheet connectivity must be validated with native ERC/netlist')

def footprint_bounds(f):
    points=[(p['pos'][0]-max(p['size'])/2,p['pos'][1]-max(p['size'])/2,
             p['pos'][0]+max(p['size'])/2,p['pos'][1]+max(p['size'])/2) for p in f['pads']]
    if not points: return (*f['pos'],*f['pos'])
    return (min(p[0] for p in points),min(p[1] for p in points),max(p[2] for p in points),max(p[3] for p in points))

def geometry_checks(r,b):
    process=r.config.get('process',{}); fs=b['footprints']; byref={f['ref']:f for f in fs}
    if not process.get('source') or not process.get('approved_by'):
        r.risk('DFM.PROCESS','routing','\u963b\u65ad\u7ea7','Fabrication thresholds lack an approved source or reviewer',fix='Specify board-house-confirmed process parameters, source and approver; no universal defaults.')
    required=['min_track_width_mm','min_clearance_mm','min_drill_mm','min_annulus_mm','max_hole_aspect_ratio','min_mask_bridge_mm']
    for key in required:
        if not isinstance(process.get(key),(int,float)) or process[key]<=0:
            r.risk('DFM.THRESHOLD','routing','\u963b\u65ad\u7ea7','Missing valid fabrication threshold '+key,fix='Use approved limits from the target PCB fabricator.')
    for t in b['tracks']:
        if t['width']<process.get('min_track_width_mm',0):
            r.risk('DFM.TRACK','routing','\u963b\u65ad\u7ea7',f'Track width {t["width"]}mm below approved fabrication limit',f'{t["net"]} {t["layer"]} @ {t["start"]}',process.get('source','board-house capability sheet'),'Increase width or obtain fab approval and update the approved process limit.')
    for v in b['vias']:
        drill=v['drill']; ring=(v['diameter']-drill)/2
        if drill<process.get('min_drill_mm',0) or ring<process.get('min_annulus_mm',0):
            r.risk('DFM.VIA','routing','\u963b\u65ad\u7ea7',f'Hole drill {drill}mm / nominal annular ring {ring:.3f}mm below limit',str(v['pos']),process.get('source','board-house capability sheet'),'Increase pad/drill as appropriate and check finished-hole tolerance.')
        # Only explicitly through vias have a valid full board thickness approximation.
        if drill and set(v['layers'])=={'F.Cu','B.Cu'} and b['thickness']/drill>process.get('max_hole_aspect_ratio',math.inf):
            r.risk('DFM.ASPECT','routing','\u963b\u65ad\u7ea7',f'Nominal through-hole aspect ratio {b["thickness"]/drill:.2f} exceeds approved limit',str(v['pos']),process.get('source','board-house capability sheet'),'Increase drill or adjust board thickness; blind/buried vias require actual crossed-layer thickness.')
    for f in fs:
        loc=f'{f["ref"]} @ {tuple(round(x,3) for x in f["pos"])}mm'
        if f['ref'].startswith('TP'):
            limit=process.get('min_testpoint_diameter_mm')
            if limit and (not f['pads'] or max(min(p['size']) for p in f['pads'])<limit):
                r.risk('DFT.TP.SIZE','layout','\u9ad8\u98ce\u9669','Test-point contact geometry below fixture limit',loc,'fixture supplier probe requirement','Resize test pad or obtain fixture supplier acceptance.')
            clearance=process.get('testpoint_clearance_mm')
            if clearance:
                for g in fs:
                    if g is f or g['layer']!=f['layer']: continue
                    x1,y1,x2,y2=footprint_bounds(g); px,py=f['pos']
                    dist=math.hypot(max(x1-px,0,px-x2),max(y1-py,0,py-y2))
                    if dist<clearance: r.risk('DFT.TP.ACCESS','layout','\u9ad8\u98ce\u9669',f'Test point is only {dist:.3f}mm from {g["ref"]} pad bounding box; possible fixture obstruction',loc,'fixture probe and assembly requirements','Review actual part envelope/height and probe direction; pad box is only a screen.')
        if b['edges']:
            limit=process.get('component_edge_clearance_mm')
            if limit:
                d=min(segment_distance(p['pos'],a,c)-max(p['size'])/2 for p in f['pads'] for a,c in b['edges']) if f['pads'] else math.inf
                if d<limit: r.risk('MECH.EDGE','layout','\u9ad8\u98ce\u9669',f'Pad is approximately {d:.3f}mm from board edge',loc,'mechanical and fab-edge assembly requirements','Move inward and check actual courtyard/enclosure/tolerances; curved edges require human inspection.')
                if 'BGA' in f['footprint'].upper() and d<process.get('bga_edge_clearance_mm',limit):
                    r.risk('SMT.BGA.EDGE','routing','\u9ad8\u98ce\u9669','BGA near board edge can be damaged by assembly/depanelization',loc,'assembler and depanelization stress requirements','Adjust placement or seek process engineer approval.')
    # Pad envelopes give conservative candidates, not body/courtyard or true mask geometry.
    placement=process.get('min_placement_clearance_mm')
    for i,f in enumerate(fs):
        for g in fs[i+1:]:
            if f['layer']!=g['layer']: continue
            a=footprint_bounds(f); c=footprint_bounds(g)
            gap=math.hypot(max(a[0]-c[2],c[0]-a[2],0),max(a[1]-c[3],c[1]-a[3],0))
            if placement and gap<placement:
                r.risk('SMT.SPACING','routing','\u4e2d\u98ce\u9669',f'Pad bounding-box clearance {gap:.3f}mm below assembly screening limit',f'{f["ref"]}/{g["ref"]}',process.get('source','assembly-house process limits'),'Review actual body/courtyard for placement, rework and tolerances.')
    fiducials=[f for f in fs if f['ref'].upper().startswith(('FID','FD')) or 'FIDUCIAL' in f['footprint'].upper()]
    minimum=r.config.get('panel',{}).get('min_fiducials')
    if minimum is not None and len(fiducials)<minimum:
        r.risk('PANEL.FIDUCIAL','routing','\u9ad8\u98ce\u9669',f'Detected {len(fiducials)} fiducial(s), fewer than configured {minimum}',standard='assembly-house panelization requirements',fix='Add fiducials; inspect noncollinearity, copper clearances and mask. Name matching may miss features.')
    allpads=[(f,p) for f in fs for p in f['pads']]
    holes=[(f,p) for f,p in allpads if f['ref'].startswith('H') and p['drill']>0]
    for f,h in holes:
        limit=process.get('mounting_hole_copper_clearance_mm')
        if not limit: continue
        for g,p in allpads:
            if f is g: continue
            d=distance(h['pos'],p['pos'])-h['drill']/2-max(p['size'])/2
            if d<limit: r.risk('MECH.HOLE','layout','\u9ad8\u98ce\u9669',f'Mounting hole nominal distance to pad is about {d:.3f}mm',f'{f["ref"]}/{g["ref"]}','screw/washer and PCB copper keepout drawings','Use real screw/washer/tolerances for copper keepout; current logic screens pads only.')
    for config in r.config.get('decouplers',[]):
        cap,ic=byref.get(config.get('capacitor')),byref.get(config.get('ic'))
        pads=[p for p in (ic or {}).get('pads',[]) if p['number']==str(config.get('power_pad'))]
        if not cap or not pads or not cap['pads']:
            r.risk('PI.DECOUPLING','layout','\u9ad8\u98ce\u9669','Decoupling policy lacks device or power pin',str(config)); continue
        d=min(distance(p['pos'],q['pos']) for p in cap['pads'] for q in pads)
        if d>config['max_distance_mm']:
            r.risk('PI.DECOUPLING','layout','\u9ad8\u98ce\u9669',f'Decoupling pad to power pin distance {d:.3f}mm exceeds approved limit',f'{cap["ref"]}/{ic["ref"]}',config.get('source','manufacturer layout guide'),'Move capacitor close to pin; verify actual power/ground via path and loop inductance.')
    for source in r.config.get('heat_sources',[]):
        hot=byref.get(source['ref'])
        if not hot: r.risk('DFR.SOURCE','layout','\u9ad8\u98ce\u9669','Declared heat-source reference not found',source['ref']); continue
        r.evidence.append({'heat_source':source,'position_mm':hot['pos']})
        nearby=[v for v in b['vias'] if distance(v['pos'],hot['pos'])<=source.get('via_radius_mm',2)]
        if not nearby: r.risk('DFR.VIAS','layout','\u9ad8\u98ce\u9669','No via candidate found near heat source; not proof that thermal vias are missing',hot['ref'],'manufacturer thermal layout guidance','Check thermal pad, real copper and required heat vias.')
        for ref in r.config.get('temperature_sensitive',[]):
            cold=byref.get(ref)
            if cold and distance(hot['pos'],cold['pos'])<source.get('min_sensitive_distance_mm',0):
                r.risk('DFR.PROXIMITY','layout','\u9ad8\u98ce\u9669','Thermally sensitive component is near declared heat source',f'{hot["ref"]}/{ref}','temperature error budget and manufacturer guidance','Relocate and validate via real temperature test or external thermal model.')
    for loop in r.config.get('power_loops',[]):
        pts=[byref[x]['pos'] for x in loop['refs'] if x in byref]
        if len(pts)!=len(loop['refs']): r.risk('DFR.LOOP','layout','\u9ad8\u98ce\u9669','Declared power-loop reference is missing',str(loop)); continue
        area=(max(x for x,y in pts)-min(x for x,y in pts))*(max(y for x,y in pts)-min(y for x,y in pts))
        r.evidence.append({'power_loop_bbox_mm2':area,'refs':loop['refs'],'limitation':'Crude footprint-center box estimate, not the actual current-loop area'})
        if area>loop['max_bbox_area_mm2']: r.risk('DFR.LOOP','layout','\u9ad8\u98ce\u9669',f'Power-component center bounding box {area:.3f}mm² exceeds approved limit',str(loop['refs']),'manufacturer reference layout','Compact critical power components and inspect real current path.')
    for pair in r.config.get('differential_pairs',[]):
        summary=[]
        for net in (pair['positive'],pair['negative']):
            tracks=[t for t in b['tracks'] if t['net']==net]
            summary.append((sum(distance(t['start'],t['end']) for t in tracks),{t['layer'] for t in tracks}))
        if not all(x[1] for x in summary): r.risk('SI.PAIR','routing','\u9ad8\u98ce\u9669','One side of declared differential pair has no observed straight track',str(pair)); continue
        if abs(summary[0][0]-summary[1][0])>pair['max_length_skew_mm'] or summary[0][1]!=summary[1][1]:
            r.risk('SI.PAIR','routing','\u9ad8\u98ce\u9669',f'Differential straight-segment length/layer mismatch: {summary}',pair['positive']+'/'+pair['negative'],'interface/manufacturer design specification','Check full path including arcs, pads and via delay; screening is not impedance proof.')
    r.check('BOARD.GEOMETRY','completed',f'{len(fs)} footprints, {len(b["tracks"])} straight tracks, {len(b["vias"])} vias; engine={b["engine"]}',b['engine'])
    if b['curved_outline']: r.risk('MECH.CURVED','layout','\u9ad8\u98ce\u9669','Curved/polygonal outline detected; straight-edge screening does not cover all geometry',fix='Use KiCad DRC/mechanical CAD to check actual outline clearances.')
    r.check('NETCLASS.API','available' if b['netclasses'] else 'pending',b['netclasses'],'pcbnew.GetNetClasses; scope selection by net in script')
    r.evidence.append({'stackup_present':bool(b['stackup']), 'zones':len(b['zones'])})
    if not b['stackup']: r.risk('PI.STACKUP','routing','\u9ad8\u98ce\u9669','Readable stack-up data are missing',fix='Provide fab-approved dielectric thickness/Er/copper and independent impedance solve/rule validation.')

def baseline_checks(r, project, files, variants):
    baseline=r.config.get('baseline',{})
    if not baseline:
        r.risk('NPI.BASELINE','npi','\u963b\u65ad\u7ea7','No approved source baseline for schematic/PCB/BOM and variants',fix='Review inputs; create SHA-256 inventory and explicit baseline approval rather than auto-accepting files.'); return
    for p in files:
        if not p or not p.is_file(): continue
        key=str(p.relative_to(project)); actual=sha256(p)
        if baseline.get('sha256',{}).get(key)!=actual:
            r.risk('NPI.BASELINE','npi','\u963b\u65ad\u7ea7','File differs from or is absent from approved baseline',key,fix='Confirm change through ECO and rerun review before updating approved baseline; do not only rewrite hashes.')
    if set(baseline.get('variants',[]))!=set(variants):
        r.risk('NPI.VARIANT.BASELINE','npi','\u963b\u65ad\u7ea7','Reviewed variant set differs from approved baseline',str(variants),fix='Check per-variant BOM/netlist/revision and lock the accepted variant set.')
    if not baseline.get('approved_by') or not baseline.get('revision'):
        r.risk('NPI.BASELINE.APPROVAL','npi','\u963b\u65ad\u7ea7','Baseline lacks revision or approver')

def package_checks(r, directory, copper_layers=None):
    # Explicit manifest avoids guessing layer lists from filename suffixes.
    manifest=r.config.get('delivery_manifest',{})
    categories={'gerber','drill','cpl','assembly','bom'}
    if set(manifest)<categories or not categories.issubset(manifest):
        r.risk('NPI.PACKAGE.MANIFEST','npi','\u963b\u65ad\u7ea7','Deliverable manifest omits Gerber, drill, CPL, assembly drawings or BOM categories',fix='Declare required files for every copper/mask/silk/outline layer; do not use wildcards as evidence.')
    layer_map=r.config.get('delivery_layers',{})
    required_layers=set(copper_layers or []) | {'F.Mask','B.Mask','Edge.Cuts'}
    for layer in sorted(required_layers):
        if layer not in layer_map or layer_map[layer] not in manifest.get('gerber',[]):
            r.risk('NPI.PACKAGE.LAYER','npi','\u963b\u65ad\u7ea7','Required manufacturing layer missing from Gerber delivery map',layer,fix='Map copper/mask/outline files in delivery_layers and check fab contract.')
    if r.phase!='release':
        r.check('NPI.PACKAGE','deferred','Manufacturing package completeness is evaluated at release stage; no production release now'); return
    if not directory or not directory.is_dir():
        r.risk('NPI.PACKAGE','npi','\u963b\u65ad\u7ea7','Manufacturing candidate directory missing',fix='Create candidate in isolated staging only after design gates and run release integrity checks.'); return
    for category in sorted(categories):
        entries=manifest.get(category,[])
        if not entries: r.risk('NPI.PACKAGE','npi','\u963b\u65ad\u7ea7','Deliverable manifest category is empty: '+category)
        for name in entries:
            original=directory/name
            p=original.resolve()
            if any(x in name for x in '*?[') or not p.is_relative_to(directory.resolve()):
                r.risk('NPI.PACKAGE.PATH','npi','\u963b\u65ad\u7ea7','Manifest path escapes scope or contains wildcard',name); continue
            if original.is_symlink() or not p.is_file() or p.stat().st_size==0:
                r.risk('NPI.PACKAGE','npi','\u963b\u65ad\u7ea7','Missing or empty deliverable: '+category,name,fix='Provide and inspect real output; a filename/nonempty file does not replace CAM/assembly review.')
            else: r.inputs[str(p)]=sha256(p)

def evaluate(project, config_path, mode='mass_production', phase='pre_export', cli=None, static_preview=False, candidate=None):
    project=Path(project).resolve(); config_path=Path(config_path).resolve()
    from npi_common import finite_tree
    config=finite_tree(json.loads(config_path.read_text(encoding='utf-8')))
    r=Review(config,mode,phase); r.project=project; r.inputs[str(config_path)]=sha256(config_path)
    env=environment(cli)
    if mode=='mass_production' and pair_compatible(env) and not patch_native_ready(env, cli):
        r.risk('ENV.PATCH.SMOKE','layout','\u963b\u65ad\u7ea7','No valid current native setup record for nonbaseline KiCad 10.0.x',fix='Run environment_start.py setup --apply, set KICAD_PATCH_STARTUP_STATE to startup-state.json and recheck.',method='native environment evidence')
    paths={k:safe_input(project,config.get('inputs',{}).get(k)) for k in ('schematic','board','bom','project')}
    for p in paths.values():
        if p and p.is_file(): r.inputs[str(p)]=sha256(p)
    if mode=='prototype':
        r.check('MODE.PROTOTYPE','delegated','Historic prototype path remains separate; this script does not claim full old review.')
        # Prototype intentionally never grants mass-production release authorization.
    else:
        rows=bom_checks(r,paths['bom'])
        if paths['schematic']: schematic_structure(r,paths['schematic'],project)
        native_checks(r,env,project,paths['schematic'],paths['board'])
        if not pair_compatible(env):
            r.risk('ENV.PCBNEW','layout','\u963b\u65ad\u7ea7','Konnect migration lacks verified native-equivalent geometry/rule access; static parsing cannot grant manufacturing preflight',
                   fix='Use matched pcbnew read-only audits temporarily; remove this block only after equivalent Konnect geometry/NetClass acceptance.',method='current backend capability gate')
        board=None
        if paths['board'] and paths['board'].is_file():
            try:
                board=load_board(paths['board'],require_native=not static_preview)
                geometry_checks(r,board)
                from npi_geometry import screen
                screen(r,board)
            except Exception as e:
                r.risk('BOARD.LOAD','layout','\u963b\u65ad\u7ea7','PCB parse failed: '+str(e),str(paths['board']),fix='Check file format and matching KiCad Python reader; parse errors must not count as zero risk.')
        else: r.risk('BOARD.MISSING','layout','\u963b\u65ad\u7ea7','PCB source file missing')
        variants=config.get('variants',['default'])
        if not variants or len(variants)!=len(set(variants)): r.risk('BOM.VARIANTS','schematic','\u963b\u65ad\u7ea7','Assembly variant set empty or duplicated')
        variant_files=[]
        for variant in variants:
            entry=config.get('variant_boms',{}).get(variant)
            p=safe_input(project,entry)
            if p and p.is_file():
                variant_rows=bom_checks(r,p); variant_files.append(p); r.inputs[str(p)]=sha256(p)
                r.check('BOM.VARIANT','completed',{'variant':variant,'rows':len(variant_rows),'file':entry})
            elif variant!='default':
                r.risk('BOM.VARIANT','schematic','\u963b\u65ad\u7ea7','Declared assembly variant has no review BOM',variant,fix='Use CLI sch export bom --variant into isolated staging and review each variant.')
        for comparison in config.get('variant_consistency',[]):
            # Explicit immutable fields only; legal variant changes are not assumed errors.
            a=safe_input(project,config.get('variant_boms',{}).get(comparison['a']))
            b=safe_input(project,config.get('variant_boms',{}).get(comparison['b']))
            if not a or not b or not a.is_file() or not b.is_file(): continue
            field=config.get('bom_fields',{}).get('ref','Reference')
            amap={x.get(field):x for x in read_bom(a)}; bmap={x.get(field):x for x in read_bom(b)}
            for ref in amap.keys() & bmap.keys():
                if any(amap[ref].get(k)!=bmap[ref].get(k) for k in comparison['fixed_fields']):
                    r.risk('BOM.VARIANT.CONFLICT','schematic','\u963b\u65ad\u7ea7','Forbidden cross-variant fields differ',ref,fix='Check variant policy and explicitly approve allowed substitution through policy/ECO.')
        hierarchy_files=[Path(p) for p in r.inputs if Path(p).suffix=='.kicad_sch']
        baseline_checks(r,project,[*paths.values(),*variant_files,*hierarchy_files],variants)
        package_checks(r,Path(candidate).resolve() if candidate else None,(board or {}).get('copper_layers',[]))
        r.signoffs()
        from engineering_gate import inspect as engineering_inspect
        engineering_inspect(r,project,config,candidate,paths['board'])
        fields=config.get('bom_fields',{'ref':'Reference','mpn':'MPN'})
        r.evidence.append({'external_query_list':[{'reference':row.get(fields.get('ref','Reference')),
                              'mpn':row.get(fields.get('mpn','MPN')),'lifecycle':'not_queried','derating':'manual_required'} for row in rows]})
    counts={level:sum(f['level']==level for f in r.findings) for level in LEVELS}
    return {'schema_version':1,'target_kicad':TARGET_VERSION,'recommended_kicad':TARGET_VERSION,'tested_runtime_kicad':env.get('cli_version'),'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'project':str(project),'mode':mode,'phase':phase,'static_preview':static_preview,'environment':env,
            'counts':counts,'blocked':counts['\u963b\u65ad\u7ea7']>0,
            'release_allowed':mode=='mass_production' and phase=='release' and not static_preview and counts['\u963b\u65ad\u7ea7']==0,
            'inputs_sha256':r.inputs,'findings':r.findings,'checks':r.checks,'evidence':r.evidence,
            'limitations':['Users can bypass this workflow by invoking KiCad CLI/GUI directly; script cannot prevent it.',
                'Only controlled release script runs these gates; 2D screening is not SI/PI/thermal/EMC simulation.',
                'Prototype mode uses a separate historical workflow; this script does not execute or change it.']}

def write_report(report, output):
    output=Path(output)
    if output.exists() and any(output.iterdir()): raise ValueError('Report directory must be empty; never overwrite existing evidence')
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/'npi-report.json',report)
    lines=['# DFX/NPI Production Review Report','',f'Recommended KiCad baseline: {TARGET_VERSION}; actual runtime: {report.get("tested_runtime_kicad")}',f'Mode: {report["mode"]}; stage: {report["phase"]}',
           f'Production release: {"allowed" if report["release_allowed"] else "prohibited"}',
           '', '## Risk Summary','', '| Severity | Count |','|---|---:|']
    lines += [f'| {k} | {v} |' for k,v in report['counts'].items()]
    lines += ['', '## Risk Details','']
    for f in report['findings']:
        lines += [f'### {f["id"]} · {f["level"]}',f'- Gate: {f["gate"]}; implementation: {f["method"]}',
                  f'- Location: {f["location"]}',f'- Issue: {f["description"]}',f'- Reference: {f["reference"]}',f'- Remediation: {f["suggestion"]}','']
    lines += ['## Completed Checks and Evidence','', 'Complete machine evidence, input hashes and native command log are in npi-report.json.','']
    for c in report['checks']: lines.append(f'- {c["rule"]} [{c["status"]}] {c["detail"]}')
    lines += ['', '## Capability Boundaries','']+['- '+x for x in report['limitations']]
    (output/'npi-report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project',type=Path); p.add_argument('--config',required=True,type=Path)
    p.add_argument('--mode',choices=['prototype','mass_production'],default='prototype')
    p.add_argument('--phase',choices=['pre_export','release'],default='pre_export')
    p.add_argument('--kicad-cli'); p.add_argument('--static-preview',action='store_true')
    p.add_argument('--candidate-dir',type=Path); p.add_argument('--output-dir',required=True,type=Path)
    a=p.parse_args()
    try:
        report=evaluate(a.project,a.config,a.mode,a.phase,a.kicad_cli,a.static_preview,a.candidate_dir)
        write_report(report,a.output_dir)
    except (OSError,ValueError,KeyError,TypeError) as e:
        p.exit(2,'Review failed (release prohibited): '+str(e)+'\n')
    print(json.dumps({'blocked':report['blocked'],'release_allowed':report['release_allowed'],'counts':report['counts']},ensure_ascii=False))
    return 2 if report['blocked'] else 0

if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__': raise SystemExit(main())
