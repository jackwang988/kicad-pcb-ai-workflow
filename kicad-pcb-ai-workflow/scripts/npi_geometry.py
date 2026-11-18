"""Conservative, explicitly approximate geometry screens (not SI/EMC solvers)."""
import math
from collections import defaultdict
from npi_common import distance,segment_distance,children,child,value

def point_inside(p, poly):
    inside=False
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if (a[1]>p[1])!=(b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]: inside=not inside
    return inside

def segments_gap(a,b,c,d):
    def cross(p,q,r): return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    if cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0: return 0
    return min(segment_distance(a,c,d),segment_distance(b,c,d),segment_distance(c,a,b),segment_distance(d,a,b))

def screen(r,b):
    process=r.config.get('process',{})
    tracks=b['tracks']; pads=[(f,p) for f in b['footprints'] for p in f['pads']]
    minimum=process.get('min_clearance_mm')
    # Segment-to-segment capsule clearance. DRC remains authoritative for other primitives.
    if minimum:
        for i,t in enumerate(tracks):
            for s in tracks[i+1:]:
                if t['layer']!=s['layer'] or t['net']==s['net']: continue
                gap=segments_gap(t['start'],t['end'],s['start'],s['end'])-(t['width']+s['width'])/2
                if gap<minimum:
                    r.risk('DFM.CLEARANCE','routing','\u963b\u65ad\u7ea7',f'Straight-track capsule clearance {gap:.4f}mm is below {minimum}mm',f'{t["net"]}/{s["net"]} @ {t["start"]}',process.get('source','PCB fabricator capability rules'),'Increase clearance and rerun native DRC on all relevant objects.')
    # Track sharp junction candidates; not a replacement for filled-copper geometry.
    vertices=defaultdict(list)
    for t in tracks:
        vertices[(t['net'],t['layer'],tuple(t['start']))].append(t['end'])
        vertices[(t['net'],t['layer'],tuple(t['end']))].append(t['start'])
    for (net,layer,p),ends in vertices.items():
        for i,a in enumerate(ends):
            for c in ends[i+1:]:
                x=(a[0]-p[0],a[1]-p[1]); y=(c[0]-p[0],c[1]-p[1]); length=math.hypot(*x)*math.hypot(*y)
                if not length: continue
                angle=math.degrees(math.acos(max(-1,min(1,(x[0]*y[0]+x[1]*y[1])/length))))
                if angle<45:
                    r.risk('COPPER.ACUTE','routing','\u4e2d\u98ce\u9669',f'Straight-track intersection angle {angle:.1f}°: candidate acute-angle copper feature',f'{net} {layer} @ {p}','PCB fabrication etching requirements','Inspect real copper geometry and smooth/obtuse-angle treatment; angle screening does not establish electrical performance.')
    # Nominal pad apertures; local/global mask settings and actual shapes require DRC review.
    web=process.get('min_mask_bridge_mm')
    if web:
        for i,(f,p) in enumerate(pads):
            for g,q in pads[i+1:]:
                if f['layer']!=g['layer'] or p['type']=='np_thru_hole' or q['type']=='np_thru_hole': continue
                gap=distance(p['pos'],q['pos'])-(max(p['size'])+max(q['size']))/2
                if gap<web:
                    r.risk('COPPER.MASK','routing','\u4e2d\u98ce\u9669',f'Pad enclosing-circle clearance {gap:.3f}mm: solder-mask bridge candidate',f'{f["ref"]}.{p["number"]}/{g["ref"]}.{q["number"]}',process.get('source','PCB fabricator solder-mask capability rules'),'Check actual mask openings, margins, minimum bridge via DRC and fab CAM; circular envelope can overreport.')
    # Explicit functional partition/noise inputs are required; do not infer function from placement.
    byref={f['ref']:f for f in b['footprints']}
    for region in r.config.get('regions',[]):
        x1,y1,x2,y2=region['bounds_mm']
        for ref in region['refs']:
            f=byref.get(ref)
            if not f: r.risk('SI.REGION','layout','\u9ad8\u98ce\u9669','Declared region component reference does not exist',ref); continue
            x,y=f['pos']
            if not(x1<=x<=x2 and y1<=y<=y2): r.risk('SI.REGION','layout','\u9ad8\u98ce\u9669','Component center falls outside approved functional region',f'{ref} @ {f["pos"]}','Approved placement region plan','Relocate component or obtain approval for revised functional-region boundaries.')
    for policy in r.config.get('noise_separation',[]):
        noise=[t for t in tracks if t['net'] in policy['noise_nets']]
        sensitive=[t for t in tracks if t['net'] in policy['sensitive_nets']]
        if not noise or not sensitive:
            r.risk('SI.NOISE','routing','\u9ad8\u98ce\u9669','Declared noisy/sensitive net has no matching routed tracks',str(policy)); continue
        for a in noise:
            for c in sensitive:
                gap=segments_gap(a['start'],a['end'],c['start'],c['end'])
                if gap<policy['min_distance_mm']:
                    r.risk('SI.NOISE','routing','\u4e2d\u98ce\u9669',f'Approximate 2D separation between noisy and sensitive nets: {gap:.3f}mm',a['net']+'/'+c['net'],policy.get('source','Manufacturer placement guidance'),'Review shielding, return paths, and actual coupling; 2D proximity alone does not prove EMC failure.')
                    break
    # JTAG presence screen checks connector exposure, not chain electrical correctness.
    jtag=r.config.get('jtag')
    if jtag:
        for net in jtag['required_nets']:
            exposed=[f['ref'] for f,p in pads if p['net']==net and f['ref'] in jtag['connector_refs']]
            if not exposed: r.risk('DFT.JTAG','layout','\u9ad8\u98ce\u9669','Required JTAG net not found on declared connector pads',net,'IEEE 1149.1 and manufacturer debug requirements','Verify schematic and PCB nets, JTAG chain order, voltage, and connector pin mapping.')
    # Stackup prescreen only checks stated parameters; it does not solve impedance.
    for layer in children(b['stackup'],'layer'):
        kind=value(layer,'type')
        if kind=='dielectric':
            if not child(layer,'thickness') or not child(layer,'epsilon_r'):
                r.risk('PI.STACKUP.PARAMS','routing','\u9ad8\u98ce\u9669','Dielectric layer thickness or permittivity Er is missing',str(layer[1]),'Fabricator-approved stackup and impedance control document','Add real material and frequency-dependent parameters; solve impedance using approved calculator or external field solver.')
    # Protection role existence relies on engineer-supplied mapping, not inferred topology.
    for domain in r.config.get('power_domains',[]):
        for role in domain.get('required_protection',[]):
            refs=domain.get('protection',{}).get(role,[])
            if not refs or any(ref not in byref for ref in refs):
                r.risk('SCH.PROTECTION.PRESENCE','schematic','\u4e2d\u98ce\u9669','Declared power domain has no mapped protection device: '+role,domain['name'],'Manufacturer reference circuit and product protection requirements','Add mapping or documented not-applicable rationale; manually review topology, part selection and ratings.')
    copper_estimate(r,b)

def copper_estimate(r,b):
    """Raster estimate on a rectangular outline; bounded cost, never a warp solver."""
    if not b['edges'] or b['curved_outline']: return
    points=[p for edge in b['edges'] for p in edge]
    x1=min(x for x,y in points); x2=max(x for x,y in points); y1=min(y for x,y in points); y2=max(y for x,y in points)
    corners={(x1,y1),(x2,y1),(x2,y2),(x1,y2)}
    if len(b['edges'])!=4 or set(points)!=corners or x1==x2 or y1==y2:
        r.check('COPPER.AREA','pending','Nonrectangular/notched board not covered by grid-area estimate; external geometry processing required','Approximate static script'); return
    step=max(float(r.config.get('copper_sampling_mm',.5)),math.sqrt((x2-x1)*(y2-y1)/20000))
    nx=max(1,math.ceil((x2-x1)/step)); ny=max(1,math.ceil((y2-y1)/step))
    layers=set(b.get('copper_layers',['F.Cu','B.Cu']))
    estimates={}
    for layer in sorted(layers):
        polygons=[p for z in b['zones'] if z['layer']==layer for p in z['filled_polygons']]
        tracks=[t for t in b['tracks'] if t['layer']==layer]
        pads=[p for f in b['footprints'] for p in f['pads'] if f['layer']==layer and p['type']!='np_thru_hole']
        hits=0
        for ix in range(nx):
            for iy in range(ny):
                p=(x1+(ix+.5)*(x2-x1)/nx,y1+(iy+.5)*(y2-y1)/ny)
                occupied=any(point_inside(p,poly) for poly in polygons)
                occupied=occupied or any(segment_distance(p,t['start'],t['end'])<=t['width']/2 for t in tracks)
                occupied=occupied or any(distance(p,q['pos'])<=max(q['size'])/2 for q in pads)
                occupied=occupied or any(distance(p,v['pos'])<=v['diameter']/2 for v in b['vias'])
                hits+=bool(occupied)
        if hits==0 and (polygons or tracks or pads or b['vias']):
            estimates[layer]=None
            r.risk('COPPER.SAMPLING','routing','\u4e2d\u98ce\u9669','Copper objects exist but sampling detected none; insufficient resolution cannot establish zero copper',layer,'Fabricator CAM copper-balance review','Use exact CAM geometry or independent higher-resolution analysis; never infer no copper from zero estimated coverage.')
        else:
            estimates[layer]=hits/(nx*ny)
    r.evidence.append({'copper_area_ratio_estimate':estimates,'grid':[nx,ny],'method':'filled polygons + track capsules + pad outer circles + through-via circles',
                       'limitations':'Rectangular outlines only; pads approximated as enclosing circles; not all holes/curves/blind vias/zone layers accounted for. Not exact CAM copper area; sparse samples may miss thin tracks.'})
    limit=r.config.get('max_copper_ratio_spread')
    valid=[x for x in estimates.values() if x is not None]
    if limit is not None and len(valid)==len(estimates) and valid and max(valid)-min(valid)>limit:
        r.risk('COPPER.BALANCE','routing','\u4e2d\u98ce\u9669','Approximate layer copper-area imbalance exceeds configured threshold',str(estimates),'Fabricator copper-balance and lamination requirements','Request exact CAM copper-area and layer-distribution review; estimate cannot predict board warpage.')
    for z in b['zones']:
        if not z['filled_polygons']: r.risk('COPPER.FILL','routing','\u9ad8\u98ce\u9669','Zone has no filled polygons; outline alone does not establish copper presence',f'{z["net"]}/{z["layer"]}','KiCad zone-fill and DRC rules','Refill zones in controlled project candidate and recheck; review island removal and overlap.')
    r.check('COPPER.AREA','approximation',estimates,'Static grid approximation; not a substitute for fab CAM or warpage simulation')
