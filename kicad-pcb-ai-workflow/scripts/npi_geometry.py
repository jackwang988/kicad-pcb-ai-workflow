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
                    r.risk('DFM.CLEARANCE','routing','阻断级',f'直线走线胶囊间距{gap:.4f}mm小于{minimum}mm',f'{t["net"]}/{s["net"]} @ {t["start"]}',process.get('source','PCB厂工艺规则'),'增大间距并运行原生DRC确认全部对象。')
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
                    r.risk('COPPER.ACUTE','routing','中风险',f'直线走线交汇夹角{angle:.1f}°：锐角铜候选',f'{net} {layer} @ {p}','PCB厂蚀刻工艺要求','检查实际铜形状并做圆滑/钝角处理；不把角度规则当电气性能结论。')
    # Nominal pad apertures; local/global mask settings and actual shapes require DRC review.
    web=process.get('min_mask_bridge_mm')
    if web:
        for i,(f,p) in enumerate(pads):
            for g,q in pads[i+1:]:
                if f['layer']!=g['layer'] or p['type']=='np_thru_hole' or q['type']=='np_thru_hole': continue
                gap=distance(p['pos'],q['pos'])-(max(p['size'])+max(q['size']))/2
                if gap<web:
                    r.risk('COPPER.MASK','routing','中风险',f'焊盘外接圆间距{gap:.3f}mm：阻焊桥候选',f'{f["ref"]}.{p["number"]}/{g["ref"]}.{q["number"]}',process.get('source','PCB厂阻焊工艺规则'),'按真实开窗、局部margin、阻焊最小桥运行DRC/板厂CAM；此圆包络可能误报。')
    # Explicit functional partition/noise inputs are required; do not infer function from placement.
    byref={f['ref']:f for f in b['footprints']}
    for region in r.config.get('regions',[]):
        x1,y1,x2,y2=region['bounds_mm']
        for ref in region['refs']:
            f=byref.get(ref)
            if not f: r.risk('SI.REGION','layout','高风险','分区声明位号不存在',ref); continue
            x,y=f['pos']
            if not(x1<=x<=x2 and y1<=y<=y2): r.risk('SI.REGION','layout','高风险','器件中心超出声明功能分区',f'{ref} @ {f["pos"]}','经批准布局分区图','重新布局或经评审调整功能分区边界。')
    for policy in r.config.get('noise_separation',[]):
        noise=[t for t in tracks if t['net'] in policy['noise_nets']]
        sensitive=[t for t in tracks if t['net'] in policy['sensitive_nets']]
        if not noise or not sensitive:
            r.risk('SI.NOISE','routing','高风险','噪声/敏感网络声明未匹配到走线',str(policy)); continue
        for a in noise:
            for c in sensitive:
                gap=segments_gap(a['start'],a['end'],c['start'],c['end'])
                if gap<policy['min_distance_mm']:
                    r.risk('SI.NOISE','routing','中风险',f'噪声与敏感网络二维距离约{gap:.3f}mm',a['net']+'/'+c['net'],policy.get('source','器件原厂布局指南'),'复核层间屏蔽、回流与真实耦合；二维接近不等于EMC不合格。')
                    break
    # JTAG presence screen checks connector exposure, not chain electrical correctness.
    jtag=r.config.get('jtag')
    if jtag:
        for net in jtag['required_nets']:
            exposed=[f['ref'] for f,p in pads if p['net']==net and f['ref'] in jtag['connector_refs']]
            if not exposed: r.risk('DFT.JTAG','layout','高风险','指定JTAG网络未在声明连接器焊盘找到',net,'IEEE 1149.1及芯片原厂调试要求','核对原理图/板上网络、链路顺序、电压和连接器引脚。')
    # Stackup prescreen only checks stated parameters; it does not solve impedance.
    for layer in children(b['stackup'],'layer'):
        kind=value(layer,'type')
        if kind=='dielectric':
            if not child(layer,'thickness') or not child(layer,'epsilon_r'):
                r.risk('PI.STACKUP.PARAMS','routing','高风险','介质层缺少厚度或Er',str(layer[1]),'PCB厂确认叠层及阻抗控制单','补齐实际材料/频率相关参数；在外部场求解器或经批准计算器求阻抗。')
    # Protection role existence relies on engineer-supplied mapping, not inferred topology.
    for domain in r.config.get('power_domains',[]):
        for role in domain.get('required_protection',[]):
            refs=domain.get('protection',{}).get(role,[])
            if not refs or any(ref not in byref for ref in refs):
                r.risk('SCH.PROTECTION.PRESENCE','schematic','中风险','声明电源域未找到保护器件映射：'+role,domain['name'],'原厂推荐电路/产品保护要求','补充映射或记录不适用理由，人工核对拓扑、选型、额定值。')
    copper_estimate(r,b)

def copper_estimate(r,b):
    """Raster estimate on a rectangular outline; bounded cost, never a warp solver."""
    if not b['edges'] or b['curved_outline']: return
    points=[p for edge in b['edges'] for p in edge]
    x1=min(x for x,y in points); x2=max(x for x,y in points); y1=min(y for x,y in points); y2=max(y for x,y in points)
    corners={(x1,y1),(x2,y1),(x2,y2),(x1,y2)}
    if len(b['edges'])!=4 or set(points)!=corners or x1==x2 or y1==y2:
        r.check('COPPER.AREA','pending','非简单矩形/有内槽的板形暂不做栅格占比；须外部几何处理','近似静态脚本'); return
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
            r.risk('COPPER.SAMPLING','routing','中风险','该层存在铜对象但采样无命中，分辨率不足，不能报告为无铜',layer,'板厂CAM铜平衡评审','改用精确CAM几何面积或更高分辨率独立核对；不得用零占比证明无铜。')
        else:
            estimates[layer]=hits/(nx*ny)
    r.evidence.append({'copper_area_ratio_estimate':estimates,'grid':[nx,ny],'method':'filled polygons + track capsules + pad outer circles + through-via circles',
                       'limitations':'仅矩形轮廓；焊盘按外接圆；未精确扣孔/所有曲线/盲埋孔/多层zone，不是CAM实铜面积；稀疏网格可能漏细线。'})
    limit=r.config.get('max_copper_ratio_spread')
    valid=[x for x in estimates.values() if x is not None]
    if limit is not None and len(valid)==len(estimates) and valid and max(valid)-min(valid)>limit:
        r.risk('COPPER.BALANCE','routing','中风险','铜面积粗估层间差值超过配置阈值',str(estimates),'PCB厂铜平衡及压合要求','交板厂CAM计算实际铜面积并评估叠层/分布；此结果不能预测板翘量。')
    for z in b['zones']:
        if not z['filled_polygons']: r.risk('COPPER.FILL','routing','高风险','覆铜区未发现填充多边形，不能用区域外框判定铜存在',f'{z["net"]}/{z["layer"]}','KiCad覆铜/DRC规则','在工程副本中更新覆铜后重新检查；审查孤岛移除和重叠。')
    r.check('COPPER.AREA','approximation',estimates,'静态栅格近似；不可代替板厂CAM/翘曲仿真')
