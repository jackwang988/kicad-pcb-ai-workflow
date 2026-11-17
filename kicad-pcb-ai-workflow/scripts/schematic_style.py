#!/usr/bin/env python3
"""Read-only project-specific schematic structure checks, not electrical proof."""
import argparse
from schematic_io import blocking
import json
import math
from pathlib import Path
from schematic_io import sheets
from engineering_gate import local
from npi_common import children,child,value,xy,segment_distance,sha256,finite_tree

# Project-bound, read-only composition checks. The geometry manifest contains
# measured bounds tied to a KiCad-exported view; it does not become a geometry
# solver or a native electrical proof just because the bounds pass screening.
PAPER_MM = {'A4': (297.0, 210.0), 'A3': (420.0, 297.0),
            'A2': (594.0, 420.0), 'A1': (841.0, 594.0),
            'A0': (1189.0, 841.0), 'USLetter': (279.4, 215.9),
            'USLegal': (355.6, 215.9), 'USLedger': (431.8, 279.4)}
VISIBLE_KINDS = {'symbol', 'wire', 'bus', 'bus_entry', 'label',
                 'global_label', 'hierarchical_label', 'text', 'text_box',
                 'sheet', 'junction', 'no_connect', 'polyline'}


def _bbox(raw, context):
    if (not isinstance(raw, list) or len(raw) != 4 or
            any(isinstance(n, bool) or not isinstance(n, (float, int)) or
                not math.isfinite(n) for n in raw) or
            raw[0] >= raw[2] or raw[1] >= raw[3]):
        raise ValueError('Expected finite [left, top, right, bottom] mm for ' + context)
    return tuple(float(v) for v in raw)


def _intersects(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0.001 and min(a[3], b[3]) - max(a[1], b[1]) > 0.001


def _composition(root, trees, spec, inputs):
    """Validate bound geometry, rail symbols and single/hierarchical pages.

    Fail closed for missing or stale evidence. Actual bounding boxes must be
    supplied from independently reviewed rendered geometry, not guessed here.
    """
    if not isinstance(spec, dict) or spec.get('required') is not True or spec.get('schema_version') != 1:
        raise ValueError('Composition policy requires schema_version=1 and required=true')
    findings, checks = [], []
    def risk(rule, location, description, suggestion):
        findings.append({'rule':rule, 'level':'\u963b\u65ad\u7ea7',
                         'location':location, 'description':description,
                         'reference':'Bound schematic style policy and actual KiCad file',
                         'suggestion':suggestion})
    geo = spec.get('geometry', {})
    if not isinstance(geo, dict) or not geo.get('locator') or not geo.get('file') or not geo.get('evidence_file'):
        raise ValueError('Composition requires geometry manifest and current rendered evidence')
    gfile = local(root, geo['file']); view = local(root, geo['evidence_file'])
    if (not gfile.is_file() or sha256(gfile) != geo.get('sha256') or
            not view.is_file() or not view.stat().st_size or sha256(view) != geo.get('evidence_sha256')):
        raise ValueError('Composition geometry or rendered evidence SHA mismatch')
    inputs[str(gfile)] = sha256(gfile);inputs[str(view)] = sha256(view)
    manifest = finite_tree(json.loads(gfile.read_text(encoding='utf-8-sig')))
    pages = manifest.get('pages')
    if manifest.get('schema_version') != 1 or not isinstance(pages, dict) or set(pages) != set(trees):
        raise ValueError('Geometry manifest must cover every reachable schematic sheet')
    power = spec.get('power',{})
    rails = power.get('rails',[]) if isinstance(power,dict) else None
    if not isinstance(rails,list) or not rails or len(set(rails)) != len(rails) or any(not isinstance(x,str) or not x.strip() for x in rails):
        raise ValueError('Power rails must be unique, explicit net names')
    allow_labels=power.get('allow_rail_labels',[]) if isinstance(power,dict) else None
    if (not isinstance(allow_labels,list) or len(set(allow_labels)) != len(allow_labels) or
            not set(allow_labels).issubset(rails)):
        raise ValueError('Only explicitly exempted power rails can use signal labels')
    native_powers=set();evidenced_rail_labels=[];layout_rectangles={}
    for name, tree in trees.items():
        page=pages[name]
        if not isinstance(page,dict) or page.get('schematic_sha256') != sha256(local(root,name)):
            risk('COMPOSITION.STALE_SCHEMATIC',name,'Geometry not bound to current schematic','Render current schematic and rebuild verified geometry manifest.');continue
        paper=child(tree,'paper',[]);paper_name=paper[1] if len(paper)>1 else None
        nominal=PAPER_MM.get(paper_name)
        if nominal is None:
            risk('COMPOSITION.PAPER_UNSUPPORTED',name,'Unknown page dimensions; cannot prove title-block clearance','Provide supported current KiCad paper size with verified worksheet geometry.');continue
        if 'portrait' in paper:nominal=(nominal[1],nominal[0])
        if (not isinstance(page.get('sheet_mm'),list) or len(page['sheet_mm'])!=2 or
                any(abs(float(a)-b)>0.05 for a,b in zip(page['sheet_mm'],nominal))):
            risk('COMPOSITION.PAPER_MISMATCH',name,'Geometry sheet dimensions differ from KiCad paper','Regenerate geometry for actual page orientation.');continue
        if page.get('complete_object_inventory') is not True or page.get('visible_fields_included') is not True:
            risk('TITLE_BLOCK_CLEAR.INCOMPLETE',name,'Full object/visible-text bounding inventory is not confirmed','Provide symbol, fields, labels, wires, notes and frame bounds.');continue
        protected=page.get('protected_regions',[]);objects=page.get('objects',[])
        if not isinstance(protected,list) or not isinstance(objects,list) or not any(z.get('kind')=='title_block' for z in protected if isinstance(z,dict)):
            risk('TITLE_BLOCK_CLEAR.MISSING',name,'No title-block keep-out is defined','Derive protected region from current worksheet/export and include source evidence.');continue
        seen={};obbs=[];zones=[];all_native=set()
        for kind in VISIBLE_KINDS:
            for obj in children(tree,kind):
                uid=value(obj,'uuid')
                if uid:all_native.add(str(uid))
        try:
            for reg in protected:
                key=reg['id'];box=_bbox(reg['bbox_mm'],name+':'+str(key))
                if not (0<=box[0]<box[2]<=nominal[0] and 0<=box[1]<box[3]<=nominal[1]):
                    raise ValueError('Protected region outside page: '+name+':'+str(key))
                zones.append((str(key),str(reg.get('kind')),box))
            for obj in objects:
                uid=str(obj['uuid']);kind=obj['kind'];box=_bbox(obj['bbox_mm'],name+':'+uid)
                if uid in seen or kind not in VISIBLE_KINDS:
                    raise ValueError('Duplicate object ID or unsupported kind: '+uid)
                seen[uid]=kind;obbs.append((uid,kind,box))
            if set(seen) != all_native:
                raise ValueError('Object UUID inventory differs from current KiCad: missing='+str(len(all_native-set(seen)))+' extra='+str(len(set(seen)-all_native)))
        except (ValueError,KeyError,TypeError) as exc:
            risk('TITLE_BLOCK_CLEAR.INCOMPLETE',name,str(exc),'Re-export and review complete object bounds for this exact schematic.');continue
        for uid,kind,box in obbs:
            if not (0<=box[0]<box[2]<=nominal[0] and 0<=box[1]<box[3]<=nominal[1]):
                risk('SHEET_BORDER_CLEAR',name+':'+uid,'Schematic object extends outside current paper','Move or split sheet; preserve the net graph.')
            for region,region_kind,rbox in zones:
                if _intersects(box,rbox):
                    risk('TITLE_BLOCK_CLEAR' if region_kind == 'title_block' else 'NOTES_REGION_CLEAR',
                         name+':'+uid,'Visible object overlaps protected region '+region,'Move object, expand sheet or use a subsheet.')
        layout_rectangles[name]={'boxes':dict((uid,box) for uid,kind,box in obbs),
                                 'kinds':dict((uid,kind) for uid,kind,box in obbs),
                                 'usable_area':nominal[0]*nominal[1]-sum((z[2][2]-z[2][0])*(z[2][3]-z[2][1]) for z in zones),
                                 'occupied_area':sum((b[2]-b[0])*(b[3]-b[1]) for _,_,b in obbs)}
        checks.append({'rule':'TITLE_BLOCK_CLEAR','page':name,'status':'GEOMETRY_SCREENED_REQUIRES_RENDER_REVIEW',
                       'source':'bound_manifest_and_rendered_view','objects':len(obbs),'regions':len(zones)})
        for sym in children(tree,'symbol'):
            lib=str(value(sym,'lib_id') or '')
            props={p[1]:p[2] for p in children(sym,'property') if len(p)>2}
            if lib.startswith('power:') and lib != 'power:PWR_FLAG' and props.get('Value') in rails:
                native_powers.add(props['Value'])
        for kind in ('label','global_label','hierarchical_label'):
            for label in children(tree,kind):
                if len(label)>1 and label[1] in rails and label[1] not in allow_labels:
                    evidenced_rail_labels.append((name,kind,label[1]))
    for rail in rails:
        if rail not in native_powers:
            risk('POWER_SYMBOL_POLICY.MISSING',rail,'Declared rail has no real power-library symbol on any sheet','Place native KiCad power symbol for the exact net; check exported native netlist.')
    for name,kind,rail in evidenced_rail_labels:
        risk('POWER_SYMBOL_POLICY.LABEL',name+':'+rail,'Rail drawn using '+kind+' instead of project-required native power symbol','Use native KiCad power symbol; do not merge distinct rails.')
    checks.append({'rule':'POWER_SYMBOL_POLICY','required_rails':rails,'found_power_symbols':sorted(native_powers),
                   'scope':'symbol_types_and_labels_only; native XML/ERC must independently verify actual nets'})
    part=spec.get('partition',{})
    if not isinstance(part,dict) or part.get('mode') not in ('auto','single','hierarchical'):
        raise ValueError('Partition mode must be auto, single or hierarchical')
    modules=part.get('modules')
    if not isinstance(modules,list) or not modules or len({x.get('id') for x in modules})!=len(modules):
        raise ValueError('Partition needs distinct actual functional modules')
    for item in modules:
        if not isinstance(item,dict) or not item.get('id') or item.get('page') not in trees:
            risk('SHEET_PARTITION_POLICY.MODULE',str(item),'Functional module page missing','Bind module to an actual reachable sheet.');continue
        page=item['page'];uid=item.get('frame_uuid')
        if len(trees)==1 and len(modules)>1:
            if not uid or layout_rectangles.get(page,{}).get('kinds',{}).get(uid) != 'polyline':
                risk('SHEET_PARTITION_POLICY.FRAME',str(item['id']),'Single-sheet module needs a verified functional frame','Add native functional frame and bound geometry evidence.')
    if part['mode']=='single' and len(trees)>1:
        risk('SHEET_PARTITION_POLICY.MODE','project','Single-sheet policy conflicts with actual hierarchical project','Update sourced partition policy or project hierarchy.')
    if part['mode']=='hierarchical' and len(trees)<2:
        risk('SHEET_PARTITION_POLICY.MODE','project','Required hierarchical pages are absent','Create reachable subsheets and checked hierarchical ports.')
    if len(trees)>1 and not any(isinstance(m,dict) and m.get('page') != next(iter(trees)) for m in modules):
        risk('SHEET_PARTITION_POLICY.MODULE','project','Hierarchy has no declared module on a child sheet','Map real functional modules to actual child sheets and verify hierarchical ports.')
    max_occupancy=part.get('max_occupancy',0.75)
    if isinstance(max_occupancy,bool) or not isinstance(max_occupancy,(int,float)) or not 0.2<=max_occupancy<=0.9:
        raise ValueError('Partition occupancy target must be 0.2..0.9')
    for page,d in layout_rectangles.items():
        if d['usable_area']<=0:
            risk('SHEET_PARTITION_POLICY.CAPACITY',page,'No usable drawing area remains','Correct worksheet and protected regions.');continue
        # Summing bounding areas overestimates overlap; it is only a density trigger.
        ratio=d['occupied_area']/d['usable_area']
        if ratio>max_occupancy:
            risk('SHEET_PARTITION_POLICY.CAPACITY',page,'Conservative occupancy estimate exceeds configured threshold','Re-layout, enlarge page or move functions to a subsheet; preserve native nets.')
        checks.append({'rule':'SHEET_PARTITION_POLICY','page':page,'occupancy_upper_estimate':round(ratio,4),
                       'threshold':max_occupancy,'scope':'heuristic_not_native_visual_or_electrical_acceptance'})
    return findings,checks


def plan_partition(request):
    """Read-only topology-first page suggestion; never creates KiCad sheets.

    Estimated module dimensions are supplied by the designer, not derived from
    schematic symbols. This is a preflight heuristic and cannot approve layout.
    """
    if not isinstance(request,dict) or request.get('schema_version')!=1:
        raise ValueError('Expected sheet preflight schema_version=1')
    paper=request.get('paper');nominal=PAPER_MM.get(paper)
    if nominal is None:raise ValueError('Supply a supported explicit KiCad paper type')
    if request.get('portrait',False):nominal=nominal[::-1]
    protected=request.get('protected_regions',[])
    if not isinstance(protected,list) or not protected:
        raise ValueError('Supply actual title-block/worksheet protected regions')
    occupied=0.0
    for block in protected:
        b=_bbox(block.get('bbox_mm') if isinstance(block,dict) else None,'protected region')
        if not(0<=b[0]<b[2]<=nominal[0] and 0<=b[1]<b[3]<=nominal[1]):
            raise ValueError('Protected region outside declared page')
        occupied+=(b[2]-b[0])*(b[3]-b[1])
    usable=nominal[0]*nominal[1]-occupied
    if usable<=0:raise ValueError('No free page area')
    modules=request.get('modules')
    if not isinstance(modules,list) or not modules or len({m.get('id') for m in modules})!=len(modules):
        raise ValueError('Provide distinct actual functional modules')
    circuit=0.0
    for m in modules:
        if not isinstance(m,dict) or not m.get('id'):raise ValueError('Module ID missing')
        wh=m.get('estimated_box_mm')
        if (not isinstance(wh,list) or len(wh)!=2 or any(isinstance(x,bool) or
                not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in wh)):
            raise ValueError('Each module needs measured/estimated positive width and height')
        circuit+=wh[0]*wh[1]
    ratio=request.get('max_occupancy',0.72)
    allowance=request.get('routing_text_allowance',1.35)
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (ratio,allowance)) or not 0.2<=ratio<=0.9 or not 1<=allowance<=3:
        raise ValueError('Unsupported occupancy or routing allowance')
    links=request.get('cross_module_connections',0)
    max_links=request.get('max_single_sheet_cross_connections',12)
    if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (links,max_links)):
        raise ValueError('Cross-module links must be nonnegative counts')
    forecast=circuit*allowance/usable
    hierarchical=forecast>ratio or links>max_links
    return {'schema_version':1,'status':'PAGE_PLAN_PREVIEW_NOT_APPLIED',
            'recommended_mode':'hierarchical' if hierarchical else 'single',
            'estimated_occupancy':round(forecast,4),'threshold':ratio,
            'module_ids':[m['id'] for m in modules],
            'pages':(['root_overview', *[m['id'] for m in modules]] if hierarchical else ['single_with_function_frames']),
            'reasons':(['estimated_density_exceeds_target'] if forecast>ratio else []) +
                      (['cross_module_links_exceed_target'] if links>max_links else []),
            'production_authorized':False,
            'limitations':['Estimated dimensions, not rendered KiCad geometry.',
                           'Hierarchical pin/label scopes must be verified after real editing.',
                           'No schematic file or electrical net was modified.']}


def audit(root,top,policy_file):
    root=Path(root).resolve();p=local(root,policy_file);q=finite_tree(json.loads(p.read_text(encoding='utf-8-sig')))
    if q.get('schema_version')!=1:raise ValueError('Unknown style policy')
    trees=sheets(root,top);inputs={str(p):sha256(p)};findings=[];checks=[]
    def risk(code,where,description,fix,level='\u963b\u65ad\u7ea7'):
        findings.append(dict(rule=code,level=level,location=where,description=description,reference='KiCad hierarchical label/sheet pin semantics; explicit project style policy',suggestion=fix))
    # No default page size, device count, distance or forced hierarchy.
    if 'require_sheet_pin_wire' in q and not isinstance(q['require_sheet_pin_wire'],bool):raise ValueError('Explicit boolean sheet-pin-wire setting required')
    declared=q.get('pages',{})
    if not isinstance(declared,dict) or set(declared)-set(trees):raise ValueError('Policy contains unreachable page')
    if declared or q.get('require_sheet_pin_wire') is True:
        src=q.get('source',{});f=local(root,src['file'])
        if not src.get('locator') or sha256(f)!=src.get('sha256'):raise ValueError('Explicit page constraints need current source and locator')
        inputs[str(f)]=sha256(f)
    archetype_contract = q.get('prototype_validation')
    if archetype_contract is not None:
        if not isinstance(archetype_contract, dict) or archetype_contract.get('required') is not True:
            raise ValueError('prototype_validation must explicitly request required=true')
        cases = archetype_contract.get('cases')
        if not isinstance(cases, list):
            raise ValueError('prototype_validation.cases must be a list')
        allowed = {'power_conversion','mcu_soc','multi_pin_interface','bus_storage',
                   'analog_audio','discrete_io','hierarchy_overview','debug'}
        declared_types = set()
        declared_pages = set()
        for case in cases:
            if not isinstance(case,dict) or case.get('archetype') not in allowed:
                risk('STYLE.PROTOTYPE_KIND',str(case),'Unknown or missing page archetype','Select a defined page archetype and provide actual evidence.')
                continue
            name = case.get('page')
            kind = case['archetype']
            if not isinstance(name,str) or name not in trees or name in declared_pages:
                risk('STYLE.PROTOTYPE_PAGE',str(name),'Archetype evidence sheet is missing, inaccessible or duplicated','Use distinct real pages from current project.')
                continue
            declared_pages.add(name)
            declared_types.add(kind)
            evidence = case.get('evidence')
            if not isinstance(evidence,dict) or not evidence.get('locator'):
                risk('STYLE.PROTOTYPE_EVIDENCE',name,'Actual visual review evidence locator missing','Provide evidence file, current SHA and specific locator.')
                continue
            try:
                file = local(root,evidence['file'])
                if file.is_symlink() or not file.is_file() or not file.stat().st_size:
                    raise ValueError('Missing evidence file')
                if sha256(file) != evidence.get('sha256'):
                    raise ValueError('Evidence has changed')
                inputs[str(file)] = sha256(file)
            except (KeyError,ValueError,OSError) as exc:
                risk('STYLE.PROTOTYPE_EVIDENCE',name,str(exc),'Use actual current project visual/PDF/human review evidence and rebind hashes.')
        if len(declared_pages) < 2 or len(declared_types) < 2:
            risk('STYLE.PROTOTYPE_DIVERSITY','prototype_validation',
                 'At least two distinct page archetypes require independent evidence before generalizing drawing strategy',
                 'Use two distinct archetypes, with full-page/200% detail, netlist, ERC and human checks.')
        if 'power_conversion' in declared_types and not ({'mcu_soc','multi_pin_interface'} & declared_types):
            risk('STYLE.PROTOTYPE_GENERALIZE','prototype_validation',
                 'Power-sheet strategy has not been validated on MCU or many-pin interface sheet',
                 'Add representative MCU/mult_pin interface verification; avoid fixed coordinate templates.')
        checks.append({'prototype_validation': 'declared_evidence_only',
                       'archetypes': sorted(declared_types), 'pages': sorted(declared_pages),
                       'scope': 'evidence identity and archetype diversity, not automatic visual proof'})
    for name,tree in trees.items():
        inputs[str(local(root,name))]=sha256(local(root,name));paper=child(tree,'paper',[])
        expected=declared.get(name,{})
        if expected.get('paper') and (len(paper)<2 or paper[1]!=expected['paper']):risk('STYLE.PAPER',name,'Paper size differs from explicit project requirement','Adjust page settings only; preserve electrical connectivity.')
        if 'portrait' in expected:
            if not isinstance(expected['portrait'],bool):raise ValueError('Portrait must be explicit boolean')
            if ('portrait' in paper)!=expected['portrait']:risk('STYLE.ORIENTATION',name,'Page orientation differs from requirements','Set specified page orientation.')
        electrical=children(tree,'symbol');seen={}
        for symbol in electrical:
            props={p[1]:p[2] for p in children(symbol,'property') if len(p)>2};ref=props.get('Reference','')
            # Across distinct pages/local instances is assessed natively; do not confuse repeated units with duplicate components.
            if ref.startswith(('#PWR','#FLG')):
                if ref in seen:risk('STYLE.POWER_REF',name+':'+ref,'Duplicate power-symbol reference on a page','Correct power reference annotations and native export; do not merge power nets.')
                seen[ref]=True
        for sheet in children(tree,'sheet'):
            props={p[1]:p[2] for p in children(sheet,'property') if len(p)>2};filename=props.get('Sheetfile') or props.get('Sheet file')
            sub=local(root,str((local(root,name).parent/filename).relative_to(root)));subname=sub.relative_to(root).as_posix()
            pins=[str(pin[1]) for pin in children(sheet,'pin')];labels=[str(x[1]) for x in children(trees[subname],'hierarchical_label')]
            if len(pins)!=len(set(pins)) or set(pins)!=set(labels):risk('STYLE.HIERARCHY',name+' -> '+subname,'Hierarchical sheet pins do not match child labels or are duplicated','Map pins to actual interfaces then verify native XML/ERC connectivity.')
            if q.get('require_sheet_pin_wire') is True:
                segments=[]
                for wire in children(tree,'wire'):
                    pts=[(float(v[1]),float(v[2])) for v in children(child(wire,'pts',[]),'xy')];segments+=list(zip(pts,pts[1:]))
                for pin in children(sheet,'pin'):
                    if not any(segment_distance(xy(pin),a,b)<1e-6 for a,b in segments):risk('STYLE.SHEET_WIRE',name+':'+str(pin[1]),'Hierarchical pin needing a real wire has no recognizable connected segment','Connect explicitly; verify buses/complex interfaces with native netlist.')
        checks.append({'page':name,'paper':paper[1:],'symbol_instances':len(electrical),'scope':'declared page constraints and immediate sheet mapping only'})
    if q.get('composition') is not None:
        new_findings,new_checks=_composition(root,trees,q['composition'],inputs)
        findings.extend(new_findings);checks.extend(new_checks)
    else:
        checks.append({'rule':'COMPOSITION','status':'NOT_CONFIGURED_LEGACY_REVIEW_REQUIRED'})
    return {'status':'BLOCKED' if findings else 'DECLARED_STRUCTURE_CHECKS_COMPLETE','scope':'schematic_structure_only','production_authorized':False,'findings':findings,'checks':checks,'inputs_sha256':inputs,
            'manual_remaining':['Actual readability, clusters, text overlap, power symbol scope, NC correctness and device recommendations', 'Prototype evidence identity does not prove its visual or ERC content; AI and engineer must review','Native ERC/XML and complete AI/engineer review; this is not electrical approval']}

def validate_binding(root,config):
    entry=config['schematic_style'];q=json.loads(local(Path(root).resolve(),entry['policy']).read_text(encoding='utf-8-sig'))
    tasks=[t for t in config['stages']['schematic']['tasks'] if t.get('category')=='schematic_style' and t.get('check',{}).get('kind')=='semantic']
    if not tasks:raise ValueError('Schematic style requires an actual semantic review task')
    src=q.get('source')
    if src:
        docs={d['id']:d for d in config['documents']}
        if not any(docs[s['document_id']]['file']==src['file'] and docs[s['document_id']]['sha256']==src['sha256'] and s['locator']==src['locator'] for t in tasks for s in t['source_refs']):raise ValueError('Style source/locator missing from AI review')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--schematic');p.add_argument('--policy');p.add_argument('--plan-input');p.add_argument('--output-dir');a=p.parse_args()
    try:
        if a.plan_input:
            r=plan_partition(finite_tree(json.loads(local(Path(a.project).resolve(),a.plan_input).read_text(encoding='utf-8-sig'))))
        else:
            if not a.schematic or not a.policy:
                raise ValueError('Schematic audit requires --schematic and --policy')
            r=audit(a.project,a.schematic,a.policy)
        if a.output_dir:
            out=Path(a.output_dir)
            if out.exists():raise ValueError('New report directory required')
            out.mkdir(parents=True);(out/('page-plan.json' if a.plan_input else 'style-report.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
        print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r['status']=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False,'findings':[blocking('INPUT.CONTRACT',e)]},ensure_ascii=False));return 2
if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__':raise SystemExit(main())
