#!/usr/bin/env python3
"""Read-only native revalidation of the published LED case, not live MCP replay.
Exports/checks a new copy; never saves or edits the input board or host config.
"""
import argparse,collections,csv,hashlib,json,math,os,re,shutil,subprocess,sys,warnings
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kicad-pcb-ai-workflow/scripts'))
from schematic_io import parse
from npi_common import child,children,value
CASE=ROOT/'development/fixtures/led-8x8-12v'
STEM='LED_Matrix_8x8_12V'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def refs(text):
    result=[]
    for token in text.split(','):
        token=token.strip();m=re.fullmatch(r'([A-Za-z]+)(\d+)-\1(\d+)',token)
        if m:
            if int(m[3])<int(m[2]):raise ValueError('Reversed reference range')
            result += [m[1]+str(i) for i in range(int(m[2]),int(m[3])+1)]
        elif re.fullmatch(r'[A-Za-z]+\d+',token):result.append(token)
        else:raise ValueError('Invalid reference: '+token)
    return result
def audit_bom(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    byprefix={};seen=[]
    for row in rows:
        rr=refs(row['References'])
        if int(row['Quantity'])!=len(rr):raise ValueError('BOM quantity mismatch')
        seen+=rr;prefix=rr[0][0]
        if prefix in byprefix:raise ValueError('Unexpected split group')
        byprefix[prefix]=row
    expected={f'D{i}' for i in range(1,65)}|{f'R{i}' for i in range(1,17)}|{f'J{i}' for i in range(1,5)}
    if len(seen)!=84 or set(seen)!=expected:raise ValueError('Duplicate/missing/extra BOM reference')
    if byprefix['D']['MPN']!='150283RS73103' or byprefix['D']['Manufacturer']!='Wurth Elektronik':raise ValueError('LED manufacturer/MPN changed')
    if byprefix['R']['Value']!='1k' or byprefix['R']['Specification']!='1k 1% 1206 0.25W':raise ValueError('Resistor specification changed')
    return {'references':84,'purchasable_components':80,'PCB_pad_pairs':4,'resistor_MPN':'not_selected_specification_only'}
def native_violations(data):
    if isinstance(data,dict):
        found=[data] if data.get('severity') in ('error','warning') else []
        return found+[v for x in data.values() for v in native_violations(x)]
    if isinstance(data,list):return [v for x in data for v in native_violations(x)]
    return []
def audit_netlist(path,case=CASE):
    tree=parse(Path(path).read_text(encoding='utf-8'));actual=[]
    for n in children(child(tree,'nets'),'net'):
        terms=frozenset((value(p,'ref'),value(p,'pin')) for p in children(n,'node') if not value(p,'ref').startswith('#'))
        if terms:actual.append(terms)
    expected=collections.defaultdict(set)
    for p in json.loads((case/'expected-pin-nets.json').read_text())['pins']:
        if not p['ref'].startswith('#'):expected[p['net']].add((p['ref'],p['pin']))
    if len(actual)!=66 or set(actual)!={frozenset(v) for v in expected.values()}:raise ValueError('Independent endpoint partition changed')
    return 66
def audit_saved_source(source):
    tree=parse((source/(STEM+'.kicad_pcb')).read_text(encoding='utf-8'));pads=[]
    mask_margin=float(value(child(tree,'setup'),'pad_to_mask_clearance',0))
    fps=children(tree,'footprint');segments=children(tree,'segment');zones=children(tree,'zone')
    if (len(fps),len(segments),len(children(tree,'via')),len(zones))!=(84,205,0,1):raise ValueError('Native object counts changed')
    for fp in fps:
        props={p[1]:p[2] for p in children(fp,'property')};ref=props['Reference'];a=child(fp,'at');x,y=map(float,a[1:3]);angle=float(a[3]) if len(a)>3 else 0;t=math.radians(angle)
        if value(fp,'layer')!='F.Cu':raise ValueError('Backside component')
        for p in children(fp,'pad'):
            if p[2]!='smd' or 'B.Cu' in child(p,'layers'):raise ValueError('Unexpected through-hole/backside pad')
            if any(child(n,k) is not None for n in [fp,p] for k in ['solder_mask_margin','solder_paste_margin','solder_paste_margin_ratio']):raise ValueError('Case mask/paste override needs separate support')
            loc=child(p,'at');lx,ly=map(float,loc[1:3]);sx,sy=map(float,child(p,'size')[1:]);pa=math.radians(float(loc[3]) if len(loc)>3 else angle)
            width=abs(sx*math.cos(pa))+abs(sy*math.sin(pa));height=abs(sx*math.sin(pa))+abs(sy*math.cos(pa))
            pads.append({'ref':ref,'x':x+lx*math.cos(t)+ly*math.sin(t),'y':-(y-lx*math.sin(t)+ly*math.cos(t)),
                         'w':width,'h':height,'mask_w':width+2*mask_margin,'mask_h':height+2*mask_margin})
    if len(pads)!=168 or not children(zones[0],'filled_polygon'):raise ValueError('Missing pads/filled copper')
    if any(value(n,'layer')!='F.Cu' for n in segments+zones):raise ValueError('Backside copper')
    filled=[]
    for poly in children(zones[0],'filled_polygon'):
        pts=child(poly,'pts')
        if children(pts,'arc'):raise ValueError('Filled polygon arcs not part of this case')
        filled.append([(float(p[1]),-float(p[2])) for p in children(pts,'xy')])
    return pads,segments,filled
def canonical_contour(points):
    p=tuple((round(x,6),round(y,6)) for x,y in points)
    if p and p[-1]==p[0]:p=p[:-1]
    if not p:raise ValueError('Empty contour')
    candidates=[]
    for seq in [p,p[::-1]]:
        lowest=min(seq)
        candidates.extend(seq[i:]+seq[:i] for i,v in enumerate(seq) if v==lowest)
    return min(candidates)
def audit_gerbers(directory,pads,segments,filled):
    from gerbonara import GerberFile,LayerStack
    from gerbonara.graphic_objects import Flash,Line,Region
    layers={ext:GerberFile.open(directory/(STEM+suffix+ext)) for ext,suffix in [('.gtl','-F_Cu'),('.gts','-F_Mask'),('.gtp','-F_Paste'),('.gto','-F_Silkscreen'),('.gm1','-Edge_Cuts')]}
    functions={'.gtl':('copper','l1','top'),'.gts':('soldermask','top'),'.gtp':('paste','top'),'.gto':('legend','top'),'.gm1':('profile','np')}
    for ext,g in layers.items():
        if tuple(v.lower() for v in g.file_attrs.get('.FileFunction',()))!=functions[ext] or g.file_attrs.get('.SameCoordinates')!=('Original',):raise ValueError('Gerber layer function/coordinate mismatch')
    if any(p.name.endswith(('.gbl','.gbs','.gbo')) for p in directory.iterdir()):raise ValueError('Unexpected back plot')
    cu=layers['.gtl'];flashes=[o for o in cu.objects if isinstance(o,Flash)];lines=[o for o in cu.objects if isinstance(o,Line)]
    if (len(flashes),len(lines),sum(isinstance(o,Region) for o in cu.objects))!=(168,205,1):raise ValueError('Copper plot inventory mismatch')
    def match(objects,expected,dimension_keys=('w','h')):
        pending=list(objects)
        for p in expected:
            found=[i for i,o in enumerate(pending) if max(abs(o.x-p['x']),abs(o.y-p['y']))<=.000002]
            if len(found)!=1:raise ValueError('Gerber pad position mismatch')
            o=pending.pop(found[0])
            if dimension_keys:
                (x1,y1),(x2,y2)=o.bounding_box()
                if max(abs(x2-x1-p[dimension_keys[0]]),abs(y2-y1-p[dimension_keys[1]]))>.000003:raise ValueError('Gerber pad/mask/paste size mismatch')
        if pending:raise ValueError('Extra Gerber flash')
    match(flashes,pads);match(layers['.gts'].objects,pads,('mask_w','mask_h'));match(layers['.gtp'].objects,[p for p in pads if p['ref'][0] in 'DR'])
    actual_regions=[o for o in cu.objects if isinstance(o,Region)]
    if any(not o.polarity_dark or any(c is not None for c in o.arc_centers) for o in actual_regions):raise ValueError('Unexpected filled region polarity/arcs')
    if {canonical_contour(o.outline) for o in actual_regions}!={canonical_contour(p) for p in filled}:raise ValueError('Filled copper contour changed')
    def near(a,b):return max(abs(a[0]-b[0]),abs(a[1]-b[1]))<=.000002
    for s in segments:
        a=child(s,'start');b=child(s,'end');a=(float(a[1]),-float(a[2]));b=(float(b[1]),-float(b[2]));w=float(value(s,'width'))
        found=[i for i,o in enumerate(lines) if abs(o.aperture.diameter-w)<=.000002 and ((near((o.x1,o.y1),a) and near((o.x2,o.y2),b)) or (near((o.x1,o.y1),b) and near((o.x2,o.y2),a)))]
        if len(found)!=1:raise ValueError('Gerber track/width mismatch')
        lines.pop(found[0])
    if lines:raise ValueError('Extra Gerber track')
    outline=layers['.gm1'].objects
    if len(outline)!=4 or not all(isinstance(o,Line) for o in outline):raise ValueError('Unexpected board profile')
    graph=collections.Counter((round(x,6),round(y,6)) for o in outline for x,y in [(o.x1,o.y1),(o.x2,o.y2)])
    if len(graph)!=4 or set(graph.values())!={2} or {x for x,y in graph}!={100.,160.} or {y for x,y in graph}!={-100.,-160.}:raise ValueError('Profile not closed 60x60 mm')
    # Render the verified FileFunction mapping explicitly. Neither job files
    # nor filename guessing are authoritative for a physical single side.
    stack=LayerStack(graphic_layers={('top','copper'):layers['.gtl'],('top','mask'):layers['.gts'],
        ('top','paste'):layers['.gtp'],('top','silk'):layers['.gto'],('mechanical','outline'):layers['.gm1']},board_name=STEM)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always');svg=str(stack.to_pretty_svg(side='top',margin=1))
    (directory.parent/'Gerber_top_preview.svg').write_text(svg,encoding='utf-8')
    import resvg_py
    (directory.parent/'Gerber_top_preview.png').write_bytes(resvg_py.svg_to_bytes(svg_string=svg,width=1400,dpi=96.0))
    return {'pads':168,'tracks':205,'GND_regions':1,'GND_contour_vertices':sum(len(p) for p in filled),'mask':168,'paste':160,
            'pad_mask_paste_bounds_verified':True,'file_functions_verified':True,'centerline_mm':[60,60],
            'silkscreen_render_generated':True,'automated_visual_acceptance':False,'parser_warnings':[str(w.message) for w in caught],
            'parser_warning_disposition':'Known unused RoundRect arguments; actual pad/mask/paste bounds compared independently. Factory CAM approval not inferred.'}
def verify(cli,output,case=CASE):
    out=Path(output).resolve()
    if out.exists():raise ValueError('Fresh native output directory required')
    observed=json.loads((case/'evidence/observed-validation.json').read_text())
    for rel,h in observed['source_hashes'].items():
        if sha(case/'source'/rel)!=h:raise ValueError('Published case source changed: '+rel)
    out.mkdir(parents=True);source=out/'source';shutil.copytree(case/'source',source)
    commands=[]
    def run(*args):
        command=[str(cli),*map(str,args)];result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
        commands.append({'argv':command,'returncode':result.returncode,'stderr':result.stderr[-1500:]})
        if result.returncode:raise ValueError('Native command failed: '+str(command)+': '+result.stderr[-1500:])
        return result.stdout.strip()
    version=run('version')
    if version!='10.0.8':raise ValueError('This acceptance case requires exact KiCad 10.0.8, got '+version)
    pcb=source/(STEM+'.kicad_pcb');sch=source/(STEM+'.kicad_sch');pads,segments,filled=audit_saved_source(source)
    run('pcb','drc','--format','json','--schematic-parity','--severity-all','--exit-code-violations','--output',out/'DRC.json',pcb)
    run('sch','erc','--format','json','--severity-all','--exit-code-violations','--output',out/'ERC.json',sch)
    for name in ['DRC.json','ERC.json']:
        data=json.loads((out/name).read_text())
        if native_violations(data):raise ValueError('Nonzero native warning/error: '+name)
        if name=='DRC.json' and any(k not in data or data[k] for k in ['violations','unconnected_items','schematic_parity']):raise ValueError('Incomplete/nonempty native DRC categories')
    run('sch','export','netlist','--format','kicadsexpr','--output',out/'netlist.net',sch);nets=audit_netlist(out/'netlist.net',case)
    plots=out/'gerbers';plots.mkdir()
    run('pcb','export','gerbers','--layers','F.Cu,F.Mask,F.SilkS,F.Paste,Edge.Cuts','--output',str(plots)+os.sep,pcb)
    run('sch','export','bom','--fields','Reference,${QUANTITY},Value,Footprint,Manufacturer,MPN,Specification,Datasheet,Description',
        '--labels','References,Quantity,Value,Footprint,Manufacturer,MPN,Specification,Datasheet,Description',
        '--group-by','Value,Footprint,Manufacturer,MPN,Specification','--exclude-dnp','--output',out/'BOM.csv',sch)
    bom=audit_bom(out/'BOM.csv');gerbers=audit_gerbers(plots,pads,segments,filled)
    for rel,h in observed['source_hashes'].items():
        if sha(case/'source'/rel)!=h or sha(source/rel)!=h:raise ValueError('Native source mutation')
    report={'status':'PASS','scope':'native CLI revalidation/export of published saved case; not live MCP design replay',
            'kicad':version,'native_ERC':{'errors':0,'warnings':0},'native_DRC':{'errors':0,'warnings':0,'unconnected':0},
            'source_unchanged':True,'board_sha256':sha(pcb),'exact_net_partitions':nets,'gerber':gerbers,'BOM':bom,
            'formal_freeze_gate_exercised':False,'live_MCP_replay_exercised':False,'production_authorized':False,'commands':commands}
    (out/'native-led-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kicad-cli',default='kicad-cli');p.add_argument('--output',required=True);a=p.parse_args()
    try:result=verify(a.kicad_cli,a.output);print(json.dumps({k:v for k,v in result.items() if k!='commands'},indent=2))
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e),'production_authorized':False}));raise SystemExit(2)
