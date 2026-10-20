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
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from npi_common import (TARGET_VERSION, LEVELS, environment, run, sha256, load_board,
                        parse_sexpr, child, children, value, xy, distance,
                        segment_distance, polygon_area, write_json)

MANUAL = [
 ('NPI.CAM','npi','候选Gerber/CPL/BOM/装配内容与批准工程一致性审图','企业制造交付规范、PCB厂CAM/贴片厂装配要求','逐层检查极性/板框/孔位/CPL原点旋转/变体装配与版本；文件非空不能替代审图。'),
 ('SCH.PROTECTION','schematic','防反接/ESD TVS/保险丝/硬件看门狗/上电复位适用性与拓扑','原厂 datasheet 推荐应用电路；产品接口及故障安全要求','逐电源域/外部接口注明适用性、器件与网络；存在性不等于保护有效。'),
 ('SCH.CREEPAGE','schematic','高压网络爬电距离/电气间隙人工评审','适用产品安全标准、IEC 60664-1；不得套用统一距离','填写电压域、工作电压、污染等级、材料组、海拔、绝缘类型后人工签核。'),
 ('SCH.DERATING','schematic','电压/功率/电流/温度降额','器件原厂额定值、温度降额曲线与企业降额规则','将 MPN 查询清单对接经批准参数库；无参数库不判定降额合格。'),
 ('SCH.LIFECYCLE','schematic','EOL/NRND与替代料复核','制造商产品状态公告/PCN/PDN','人工查询制造商或授权供应链数据，保存来源及查询日期；本工具不自动联网。'),
 ('LAY.THERMAL','layout','散热铜、散热过孔及热源/热敏器件布局','原厂布局/散热建议；IPC-2152用于载流相关设计参考','核对热阻路径、实际填铜连接、散热孔尺寸数量及温升预算。'),
 ('LAY.DFT','layout','测试点可达性、夹具可达高度及JTAG链路','测试夹具供应商探针规范；IEEE 1149.1（适用时）','结合两面装配与夹具方向复核测试点遮挡；核对JTAG引脚网络而非仅连接器名称。'),
 ('LAY.HEIGHT','layout','器件高度、壳体/螺钉/连接器干涉','结构图纸、原厂机械图及公差链','用实际3D装配/限高图人工核对；二维包围盒不能证明无高度干涉。'),
 ('LAY.PLANES','layout','电源分割区域、参考平面和网络类适用性','原厂硬件设计指南；经批准叠层/网络类表','核对敏感信号参考平面连续性与电源域边界；网络类存在不等于配置正确。'),
 ('LAY.PARTITION','layout','模拟/数字/功率分区、差分对及噪声隔离','芯片原厂布局指南、接口设计规范','结合功能分区与回流路径审查；距离规则仅是静态预筛。'),
 ('ROUTE.COPPER','routing','铜箔锐角/窄颈/孤岛/覆铜重叠','PCB厂工艺规则；KiCad DRC规则与覆铜设置','核对真实填铜、最小颈宽、热焊盘和不同网络重叠；不能用区域外框代替填铜。'),
 ('ROUTE.BALANCE','routing','各铜层铜面积平衡及板翘风险','PCB厂叠层/铜平衡要求；IPC-6012按产品合同适用','面积估计不代表热机械翘曲仿真；交板厂核对铜分布与压合工艺。'),
 ('ROUTE.PANEL','routing','V-Cut/邮票孔/拼板Fiducial及铜避让','拼板厂/贴片厂经批准工艺图','填写拼板方案；V-Cut残厚、跳刀、板边铜距与邮票孔不能仅靠名称推断。'),
 ('SIM.SPICE','simulation','SPICE模型、激励、分析指令和仿真结果','原厂SPICE模型说明与电路验收目标','CLI只能导出SPICE网表；外部ngspice须独立安装且提供完整测试平台与模型。'),
 ('SIM.THERMAL','simulation','热仿真或温升验证计划','器件原厂温度上限、企业可靠性测试计划','导出热源清单交外部热仿真工具；无求解器时仅静态评估。'),
 ('SIM.EMC','simulation','高频噪声源/滤波/接地/屏蔽静态评审','产品适用EMC标准；原厂EMC设计建议','逐时钟、开关电源和外部线缆复核；不做电磁场求解或认证结论。'),
 ('NPI.ECO','npi','ECO变更记录与影响评估','企业配置管理/变更控制流程','记录变更项、原因、影响范围、风险、验证、审批人与基线版本。'),
 ('NPI.EVT','npi','EVT功能/电源/接口/可测试性验收','产品需求与EVT测试计划','填写样本数、条件、验收指标、实测结果、证据和负责人。'),
 ('NPI.DVT','npi','DVT高低温/湿热/振动/老化可靠性验收','产品要求；IEC 60068系列适用试验方法','由工程师选择适用试验，不自动认定所有产品都须同一等级测试。'),
 ('NPI.PVT','npi','PVT产线工艺/良率/测试覆盖/追溯验收','制造质量计划和产线验收规范','填写试产批量、直通率、缺陷闭环、测试覆盖、工装版本与追溯记录。'),
 ('NPI.CERT','npi','CCC/CE等认证适用性和前置设计评审','目标市场/产品类别对应法规及协调标准','人工确定适用认证和标准；不得把清单签核解释为已获认证。'),
]

class Review:
    def __init__(self, config, mode, phase):
        self.config=config; self.mode=mode; self.phase=phase
        self.findings=[]; self.checks=[]; self.evidence=[]; self.inputs={}
    def risk(self, code, gate, level, description, location='工程级（无坐标）',
             standard='项目经批准设计要求', fix='复核并修复后重新运行评审。', method='静态脚本'):
        self.findings.append(dict(id=f'{code}-{len(self.findings)+1}',rule=code,gate=gate,
            level=level,location=location,description=description,reference=standard,
            suggestion=fix,method=method))
    def check(self, code, status, detail, method='静态脚本'):
        self.checks.append(dict(rule=code,status=status,detail=detail,method=method))
    def signoffs(self):
        signs=self.config.get('manual_reviews',{})
        for code,gate,title,standard,fix in MANUAL:
            if code=='NPI.CAM' and self.phase!='release':
                self.check(code,'deferred','实际候选输出生成后审图；不能因此授予生产放行','人工审图');continue
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
                self.check(code,record['status'],record,'人工签核')
            else:
                self.risk(code,gate,'阻断级',title+'：尚无完整人工签核证据',standard=standard,fix=fix,method='模板化人工评审/外部接口')
                self.check(code,'pending',title,'模板化人工评审/外部接口')

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
        r.risk('BOM.MISSING','schematic','阻断级','缺少用于评审的BOM输入',fix='提供含位号、MPN、制造商、封装、规格的CSV；它不是生产放行BOM。')
        return []
    rows=read_bom(path)
    if not rows:
        r.risk('BOM.EMPTY','schematic','阻断级','BOM只有表头或没有器件，不允许零行假通过',str(path));return []
    fields=r.config.get('bom_fields',{'ref':'Reference','mpn':'MPN','manufacturer':'Manufacturer','footprint':'Footprint','spec':'Value'})
    refs=[]; mpns=defaultdict(set)
    for i,row in enumerate(rows,2):
        ref=row.get(fields['ref'],'').strip(); refs.extend(re.split(r'[,;\s]+',ref) if ref else [])
        for key,column in fields.items():
            if not (row.get(column) or '').strip():
                r.risk('BOM.FIELD','schematic','阻断级',f'BOM第{i}行缺少字段 {column}',ref or f'BOM行{i}',
                       '企业BOM/采购字段规范','补充原厂可追溯字段，MPN不得由Value猜测。')
        if row.get(fields['mpn']):
            mpns[row[fields['mpn']]].add(tuple(row.get(fields[k],'') for k in ('manufacturer','footprint','spec')))
    for ref,count in Counter(refs).items():
        if count>1: r.risk('BOM.DUPLICATE','schematic','阻断级',f'位号在BOM重复出现{count}次',ref,fix='核对装配实例与分组，消除重复位号。')
    for mpn,definitions in mpns.items():
        if len(definitions)>1: r.risk('BOM.CONFLICT','schematic','高风险','同MPN对应不同制造商/封装/规格',mpn,fix='核对MPN完整后缀、封装及制造商，记录合法差异。')
    r.check('BOM.FIELDS','completed',f'{len(rows)}行、{len(refs)}个位号；字段完整性/重复/冲突已检查')
    return rows

def native_checks(r, env, sch, pcb):
    if not env.get('cli_exact_target'):
        r.risk('ENV.CLI','schematic','阻断级',f'需要KiCad {TARGET_VERSION} CLI，检测值={env["cli_version"]}',
               standard='KiCad 10.0.7官方CLI文档',fix='用--kicad-cli指定10.0.7可执行文件，实际运行version核对。',method='KiCad CLI')
        return
    # ERC does not support --variant in the official 10.0.7 CLI.
    with tempfile.TemporaryDirectory(prefix='kicad-npi-native-') as d:
        for kind,input_path in (('erc',sch),('drc',pcb)):
            if not input_path or not input_path.exists():
                r.risk('NATIVE.'+kind.upper(),'schematic' if kind=='erc' else 'routing','阻断级',f'缺少{kind}输入文件',method='KiCad CLI'); continue
            report=Path(d)/(kind+'.json')
            command=[env['kicad_cli'],'sch' if kind=='erc' else 'pcb',kind,
                     '--format','json','--units','mm','--severity-all','--exit-code-violations','--output',str(report),str(input_path)]
            if kind=='drc': command.insert(-1,'--schematic-parity')
            result=run(command); r.evidence.append(result)
            # Native results are evidence; missing/unparseable reports fail closed.
            if not report.is_file():
                r.risk('NATIVE.'+kind.upper(),'schematic' if kind=='erc' else 'routing','阻断级',f'{kind}没有生成有效报告',fix='查看native命令日志，修复CLI错误后重跑。',method='KiCad CLI'); continue
            try: data=json.loads(report.read_text(encoding='utf-8-sig'))
            except (ValueError,OSError):
                r.risk('NATIVE.'+kind.upper(),'routing','阻断级','原生JSON报告不可解析',method='KiCad CLI'); continue
            from native_report import extract
            try:groups=extract(kind,data,input_path)
            except (ValueError,TypeError,KeyError) as e:
                r.risk('NATIVE.SCHEMA','routing','阻断级','原生JSON不完整或结构不受支持：'+str(e),method='KiCad CLI');continue
            r.evidence.append({'kind':kind,'report':data})
            for v in groups:
                severity=str(v.get('severity','error')).lower()
                if v.get('excluded',False) or severity in ('exclusion','excluded'):
                    r.risk('NATIVE.EXCLUDED','routing','阻断级','存在已排除原生违规：'+str(v),fix='人工复核排除理由；量产签核时记录证据。',method='KiCad CLI'); continue
                location='; '.join(str(x.get('description',x))+(' @ '+str(x.get('pos')) if x.get('pos') else '') for x in v.get('items',[])) or str(input_path.name)
                r.risk('NATIVE.'+kind.upper(),'schematic' if kind=='erc' else 'routing',
                       '阻断级' if severity=='error' else '高风险',v.get('description',v.get('type','原生违规')),location,
                       'KiCad工程配置ERC/DRC规则','在KiCad定位该违规并修复；禁止仅靠减少计数或删除规则放行。','KiCad CLI')
            if result['returncode'] not in (0,5):
                r.risk('NATIVE.EXEC','routing','阻断级',f'{kind}命令失败，退出码{result["returncode"]}',method='KiCad CLI')
            if result['returncode'] and not groups:
                r.risk('NATIVE.UNKNOWN','routing','阻断级',f'{kind}非零退出但无已识别违规，不能判定通过',method='KiCad CLI')
            r.check('NATIVE.'+kind.upper(),'completed',f'{len(groups)}条原生结果（不额外传variant参数）','KiCad CLI')

def schematic_structure(r, root, project):
    visited=set(); active=set(); references=[]; hierarchy=[]
    def visit(path):
        if path in active:
            r.risk('SCH.CYCLE','schematic','阻断级','检测到层级文件循环',str(path)); return
        if path in visited: return
        active.add(path); visited.add(path)
        try: tree=parse_sexpr(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError) as e:
            r.risk('SCH.PARSE','schematic','阻断级',str(e),str(path)); active.remove(path); return
        if tree[0]!='kicad_sch': r.risk('SCH.FORMAT','schematic','阻断级','不是kicad_sch根节点',str(path))
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
                r.risk('SCH.SHEET','schematic','阻断级','分层页缺少Sheetfile',str(path)); continue
            sub=(path.parent/filename).resolve()
            if not sub.is_relative_to(project.resolve()):
                r.risk('SCH.SHEET','schematic','阻断级','子页路径超出工程目录',str(sub)); continue
            hierarchy.append({'parent':path.name,'child':str(sub.relative_to(project)),
                              'pins':[p[1] for p in children(sheet,'pin')]})
            visit(sub)
        active.remove(path)
    if root: visit(root)
    for path in visited:
        if path.is_file(): r.inputs[str(path.resolve())]=sha256(path)
    r.evidence.append({'hierarchy':hierarchy,'files':len(visited)})
    r.check('SCH.HIERARCHY','completed',f'{len(visited)}个文件；跨页网络实际连通性以ERC/网表为准')

def footprint_bounds(f):
    points=[(p['pos'][0]-max(p['size'])/2,p['pos'][1]-max(p['size'])/2,
             p['pos'][0]+max(p['size'])/2,p['pos'][1]+max(p['size'])/2) for p in f['pads']]
    if not points: return (*f['pos'],*f['pos'])
    return (min(p[0] for p in points),min(p[1] for p in points),max(p[2] for p in points),max(p[3] for p in points))

def geometry_checks(r,b):
    process=r.config.get('process',{}); fs=b['footprints']; byref={f['ref']:f for f in fs}
    if not process.get('source') or not process.get('approved_by'):
        r.risk('DFM.PROCESS','routing','阻断级','板厂工艺阈值缺少来源或批准人',fix='填写经板厂确认的process参数、来源和批准人，不使用通用默认值。')
    required=['min_track_width_mm','min_clearance_mm','min_drill_mm','min_annulus_mm','max_hole_aspect_ratio','min_mask_bridge_mm']
    for key in required:
        if not isinstance(process.get(key),(int,float)) or process[key]<=0:
            r.risk('DFM.THRESHOLD','routing','阻断级','缺少有效工艺阈值 '+key,fix='从目标PCB厂能力表填入经批准数值。')
    for t in b['tracks']:
        if t['width']<process.get('min_track_width_mm',0):
            r.risk('DFM.TRACK','routing','阻断级',f'线宽{t["width"]}mm小于工艺阈值',f'{t["net"]} {t["layer"]} @ {t["start"]}',process.get('source','PCB厂能力表'),'增大线宽或取得板厂确认并更新经批准工艺阈值。')
    for v in b['vias']:
        drill=v['drill']; ring=(v['diameter']-drill)/2
        if drill<process.get('min_drill_mm',0) or ring<process.get('min_annulus_mm',0):
            r.risk('DFM.VIA','routing','阻断级',f'孔径{drill}mm / 名义孔环{ring:.3f}mm低于阈值',str(v['pos']),process.get('source','PCB厂能力表'),'增大焊盘/孔径并复核成品孔公差。')
        # Only explicitly through vias have a valid full board thickness approximation.
        if drill and set(v['layers'])=={'F.Cu','B.Cu'} and b['thickness']/drill>process.get('max_hole_aspect_ratio',math.inf):
            r.risk('DFM.ASPECT','routing','阻断级',f'通孔名义纵横比{b["thickness"]/drill:.2f}超阈值',str(v['pos']),process.get('source','PCB厂能力表'),'增大孔径或调整板厚；盲埋孔须按实际跨层厚度人工复核。')
    for f in fs:
        loc=f'{f["ref"]} @ {tuple(round(x,3) for x in f["pos"])}mm'
        if f['ref'].startswith('TP'):
            limit=process.get('min_testpoint_diameter_mm')
            if limit and (not f['pads'] or max(min(p['size']) for p in f['pads'])<limit):
                r.risk('DFT.TP.SIZE','layout','高风险','测试点接触尺寸小于夹具阈值',loc,'夹具供应商探针要求','调整测试盘尺寸或与夹具供应商确认。')
            clearance=process.get('testpoint_clearance_mm')
            if clearance:
                for g in fs:
                    if g is f or g['layer']!=f['layer']: continue
                    x1,y1,x2,y2=footprint_bounds(g); px,py=f['pos']
                    dist=math.hypot(max(x1-px,0,px-x2),max(y1-py,0,py-y2))
                    if dist<clearance: r.risk('DFT.TP.ACCESS','layout','高风险',f'测试点距{g["ref"]}焊盘包围盒仅{dist:.3f}mm；遮挡候选',loc,'夹具探针与装配工艺要求','复核器件实体/高度和探针进针方向；焊盘盒仅预筛。')
        if b['edges']:
            limit=process.get('component_edge_clearance_mm')
            if limit:
                d=min(segment_distance(p['pos'],a,c)-max(p['size'])/2 for p in f['pads'] for a,c in b['edges']) if f['pads'] else math.inf
                if d<limit: r.risk('MECH.EDGE','layout','高风险',f'焊盘几何包络距直线板边约{d:.3f}mm',loc,'结构/PCB厂边缘装配要求','向板内移动并用实际courtyard/壳体/公差图复核；异形曲线板边须人工检查。')
                if 'BGA' in f['footprint'].upper() and d<process.get('bga_edge_clearance_mm',limit):
                    r.risk('SMT.BGA.EDGE','routing','高风险','BGA靠近板边的装配/分板风险',loc,'贴片厂及分板应力要求','调整位置或取得工艺工程师确认。')
    # Pad envelopes give conservative candidates, not body/courtyard or true mask geometry.
    placement=process.get('min_placement_clearance_mm')
    for i,f in enumerate(fs):
        for g in fs[i+1:]:
            if f['layer']!=g['layer']: continue
            a=footprint_bounds(f); c=footprint_bounds(g)
            gap=math.hypot(max(a[0]-c[2],c[0]-a[2],0),max(a[1]-c[3],c[1]-a[3],0))
            if placement and gap<placement:
                r.risk('SMT.SPACING','routing','中风险',f'焊盘包围盒间距{gap:.3f}mm低于贴装预筛阈值',f'{f["ref"]}/{g["ref"]}',process.get('source','贴片厂工艺要求'),'按真实器件实体/courtyard复核贴装、返修及公差空间。')
    fiducials=[f for f in fs if f['ref'].upper().startswith(('FID','FD')) or 'FIDUCIAL' in f['footprint'].upper()]
    minimum=r.config.get('panel',{}).get('min_fiducials')
    if minimum is not None and len(fiducials)<minimum:
        r.risk('PANEL.FIDUCIAL','routing','高风险',f'基准点命名/封装识别到{len(fiducials)}个，少于配置{minimum}个',standard='贴片厂拼板工艺要求',fix='补充基准点，人工复核非共线位置、禁铜和开窗；命名识别可能漏检。')
    allpads=[(f,p) for f in fs for p in f['pads']]
    holes=[(f,p) for f,p in allpads if f['ref'].startswith('H') and p['drill']>0]
    for f,h in holes:
        limit=process.get('mounting_hole_copper_clearance_mm')
        if not limit: continue
        for g,p in allpads:
            if f is g: continue
            d=distance(h['pos'],p['pos'])-h['drill']/2-max(p['size'])/2
            if d<limit: r.risk('MECH.HOLE','layout','高风险',f'固定孔至焊盘名义间距约{d:.3f}mm',f'{f["ref"]}/{g["ref"]}','螺钉/垫圈及PCB铜避让图纸','按金属螺钉、垫圈直径及公差建立真实铜禁布区；当前只筛焊盘候选。')
    for config in r.config.get('decouplers',[]):
        cap,ic=byref.get(config.get('capacitor')),byref.get(config.get('ic'))
        pads=[p for p in (ic or {}).get('pads',[]) if p['number']==str(config.get('power_pad'))]
        if not cap or not pads or not cap['pads']:
            r.risk('PI.DECOUPLING','layout','高风险','去耦配置缺少器件或电源引脚',str(config)); continue
        d=min(distance(p['pos'],q['pos']) for p in cap['pads'] for q in pads)
        if d>config['max_distance_mm']:
            r.risk('PI.DECOUPLING','layout','高风险',f'去耦焊盘至指定电源引脚直线距离{d:.3f}mm超阈值',f'{cap["ref"]}/{ic["ref"]}',config.get('source','器件原厂布局指南'),'把去耦电容贴近目标引脚，复核实际电流路径、接地过孔与回路电感。')
    for source in r.config.get('heat_sources',[]):
        hot=byref.get(source['ref'])
        if not hot: r.risk('DFR.SOURCE','layout','高风险','热源位号未找到',source['ref']); continue
        r.evidence.append({'heat_source':source,'position_mm':hot['pos']})
        nearby=[v for v in b['vias'] if distance(v['pos'],hot['pos'])<=source.get('via_radius_mm',2)]
        if not nearby: r.risk('DFR.VIAS','layout','高风险','热源附近未发现过孔候选（不等于已证明缺散热孔）',hot['ref'],'器件原厂散热布局建议','核对散热焊盘、铜连接与所需散热孔。')
        for ref in r.config.get('temperature_sensitive',[]):
            cold=byref.get(ref)
            if cold and distance(hot['pos'],cold['pos'])<source.get('min_sensitive_distance_mm',0):
                r.risk('DFR.PROXIMITY','layout','高风险','热敏器件接近已声明热源',f'{hot["ref"]}/{ref}','器件温度误差预算/原厂指南','调整位置并用温升实测或外部热仿真确认。')
    for loop in r.config.get('power_loops',[]):
        pts=[byref[x]['pos'] for x in loop['refs'] if x in byref]
        if len(pts)!=len(loop['refs']): r.risk('DFR.LOOP','layout','高风险','功率环路声明位号缺失',str(loop)); continue
        area=(max(x for x,y in pts)-min(x for x,y in pts))*(max(y for x,y in pts)-min(y for x,y in pts))
        r.evidence.append({'power_loop_bbox_mm2':area,'refs':loop['refs'],'limitation':'器件中心包围盒粗估，不是真实电流环面积'})
        if area>loop['max_bbox_area_mm2']: r.risk('DFR.LOOP','layout','高风险',f'功率器件中心包围盒{area:.3f}mm²超阈值',str(loop['refs']),'原厂参考布局','压缩关键功率器件布置并人工复核实际电流路径。')
    for pair in r.config.get('differential_pairs',[]):
        summary=[]
        for net in (pair['positive'],pair['negative']):
            tracks=[t for t in b['tracks'] if t['net']==net]
            summary.append((sum(distance(t['start'],t['end']) for t in tracks),{t['layer'] for t in tracks}))
        if not all(x[1] for x in summary): r.risk('SI.PAIR','routing','高风险','指定差分对有一侧未发现直线走线',str(pair)); continue
        if abs(summary[0][0]-summary[1][0])>pair['max_length_skew_mm'] or summary[0][1]!=summary[1][1]:
            r.risk('SI.PAIR','routing','高风险',f'差分对直线段长度/层集合不符：{summary}',pair['positive']+'/'+pair['negative'],'接口/原厂设计要求','检查全路径含弧线、焊盘、过孔延迟，不能把此预筛当阻抗验证。')
    r.check('BOARD.GEOMETRY','completed',f'{len(fs)}封装、{len(b["tracks"])}直线段、{len(b["vias"])}过孔；引擎={b["engine"]}',b['engine'])
    if b['curved_outline']: r.risk('MECH.CURVED','layout','高风险','发现曲线/多边形板边；直线板边距离预筛未覆盖全部轮廓',fix='用KiCad DRC/结构CAD复核实际轮廓距离。')
    r.check('NETCLASS.API','available' if b['netclasses'] else 'pending',b['netclasses'],'pcbnew.GetNetClasses；按网络归属在脚本筛选')
    r.evidence.append({'stackup_present':bool(b['stackup']), 'zones':len(b['zones'])})
    if not b['stackup']: r.risk('PI.STACKUP','routing','高风险','缺少可读取的叠层参数',fix='补齐经PCB厂确认的介质厚度/Er/铜厚，执行外部阻抗计算与规则核对。')

def baseline_checks(r, project, files, variants):
    baseline=r.config.get('baseline',{})
    if not baseline:
        r.risk('NPI.BASELINE','npi','阻断级','尚未提供原理图/PCB/BOM及变体的锁定基线',fix='审阅输入后生成SHA-256清单，人工批准并写入baseline，不自动接受当前文件。'); return
    for p in files:
        if not p or not p.is_file(): continue
        key=str(p.relative_to(project)); actual=sha256(p)
        if baseline.get('sha256',{}).get(key)!=actual:
            r.risk('NPI.BASELINE','npi','阻断级','文件与批准基线不一致或未纳入基线',key,fix='走ECO确认变更，重新评审后更新批准基线；不要仅重写哈希跳过审核。')
    if set(baseline.get('variants',[]))!=set(variants):
        r.risk('NPI.VARIANT.BASELINE','npi','阻断级','评审变体集合与批准基线不一致',str(variants),fix='逐变体完成BOM/网表及版本核对并锁定变体集合。')
    if not baseline.get('approved_by') or not baseline.get('revision'):
        r.risk('NPI.BASELINE.APPROVAL','npi','阻断级','基线缺少版本或批准人')

def package_checks(r, directory, copper_layers=None):
    # Explicit manifest avoids guessing layer lists from filename suffixes.
    manifest=r.config.get('delivery_manifest',{})
    categories={'gerber','drill','cpl','assembly','bom'}
    if set(manifest)<categories or not categories.issubset(manifest):
        r.risk('NPI.PACKAGE.MANIFEST','npi','阻断级','交付清单未覆盖Gerber/钻孔/CPL/装配图/BOM全部类别',fix='显式填写每一铜层/阻焊/丝印/板框等所需文件；禁用模糊通配符充数。')
    layer_map=r.config.get('delivery_layers',{})
    required_layers=set(copper_layers or []) | {'F.Mask','B.Mask','Edge.Cuts'}
    for layer in sorted(required_layers):
        if layer not in layer_map or layer_map[layer] not in manifest.get('gerber',[]):
            r.risk('NPI.PACKAGE.LAYER','npi','阻断级','缺少所需生产图层到Gerber清单的映射',layer,fix='逐铜层及要求的阻焊/板框配置delivery_layers，并与板厂交付规范核对。')
    if r.phase!='release':
        r.check('NPI.PACKAGE','deferred','生产包完整性在release阶段检查；本阶段不允许生产放行'); return
    if not directory or not directory.is_dir():
        r.risk('NPI.PACKAGE','npi','阻断级','缺少候选交付包目录',fix='设计门禁通过后，在隔离暂存目录生成候选包；再执行release完整性检查。'); return
    for category in sorted(categories):
        entries=manifest.get(category,[])
        if not entries: r.risk('NPI.PACKAGE','npi','阻断级','交付清单类别为空：'+category)
        for name in entries:
            original=directory/name
            p=original.resolve()
            if any(x in name for x in '*?[') or not p.is_relative_to(directory.resolve()):
                r.risk('NPI.PACKAGE.PATH','npi','阻断级','清单路径越界或含通配符',name); continue
            if original.is_symlink() or not p.is_file() or p.stat().st_size==0:
                r.risk('NPI.PACKAGE','npi','阻断级','缺少或空的交付文件：'+category,name,fix='补齐对应输出并检查内容；仅有文件名/非空仍须Gerber/装配人工审图。')
            else: r.inputs[str(p)]=sha256(p)

def evaluate(project, config_path, mode='mass_production', phase='pre_export', cli=None, static_preview=False, candidate=None):
    project=Path(project).resolve(); config_path=Path(config_path).resolve()
    from npi_common import finite_tree
    config=finite_tree(json.loads(config_path.read_text(encoding='utf-8')))
    r=Review(config,mode,phase); r.project=project; r.inputs[str(config_path)]=sha256(config_path)
    env=environment(cli)
    paths={k:safe_input(project,config.get('inputs',{}).get(k)) for k in ('schematic','board','bom','project')}
    for p in paths.values():
        if p and p.is_file(): r.inputs[str(p)]=sha256(p)
    if mode=='prototype':
        r.check('MODE.PROTOTYPE','delegated','保留原有脚本与原型流程；本脚本不声称执行旧版全套评审。')
        # Prototype intentionally never grants mass-production release authorization.
    else:
        rows=bom_checks(r,paths['bom'])
        if paths['schematic']: schematic_structure(r,paths['schematic'],project)
        native_checks(r,env,paths['schematic'],paths['board'])
        if not env.get('pcbnew_exact_target'):
            r.risk('ENV.PCBNEW','layout','阻断级','未验证KiCad 10.0.7 pcbnew绑定；静态预览不能用于生产放行',
                   fix='用能导入10.0.7 pcbnew的Python运行；不要pip安装同名第三方包。',method='环境自检')
        board=None
        if paths['board'] and paths['board'].is_file():
            try:
                board=load_board(paths['board'],require_native=not static_preview)
                geometry_checks(r,board)
                from npi_geometry import screen
                screen(r,board)
            except Exception as e:
                r.risk('BOARD.LOAD','layout','阻断级','PCB解析失败：'+str(e),str(paths['board']),fix='检查文件格式与对应KiCad Python版本，禁止将解析失败当成无风险。')
        else: r.risk('BOARD.MISSING','layout','阻断级','缺少PCB文件')
        variants=config.get('variants',['default'])
        if not variants or len(variants)!=len(set(variants)): r.risk('BOM.VARIANTS','schematic','阻断级','变体集合为空或重复')
        variant_files=[]
        for variant in variants:
            entry=config.get('variant_boms',{}).get(variant)
            p=safe_input(project,entry)
            if p and p.is_file():
                variant_rows=bom_checks(r,p); variant_files.append(p); r.inputs[str(p)]=sha256(p)
                r.check('BOM.VARIANT','completed',{'variant':variant,'rows':len(variant_rows),'file':entry})
            elif variant!='default':
                r.risk('BOM.VARIANT','schematic','阻断级','缺少声明变体的评审BOM',variant,fix='用CLI sch export bom --variant生成评审BOM到隔离暂存目录，逐变体核对。')
        for comparison in config.get('variant_consistency',[]):
            # Explicit immutable fields only; legal variant changes are not assumed errors.
            a=safe_input(project,config.get('variant_boms',{}).get(comparison['a']))
            b=safe_input(project,config.get('variant_boms',{}).get(comparison['b']))
            if not a or not b or not a.is_file() or not b.is_file(): continue
            field=config.get('bom_fields',{}).get('ref','Reference')
            amap={x.get(field):x for x in read_bom(a)}; bmap={x.get(field):x for x in read_bom(b)}
            for ref in amap.keys() & bmap.keys():
                if any(amap[ref].get(k)!=bmap[ref].get(k) for k in comparison['fixed_fields']):
                    r.risk('BOM.VARIANT.CONFLICT','schematic','阻断级','变体间禁止变化的字段不一致',ref,fix='核对变体策略；合法替代须在策略/ECO中明确批准。')
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
    return {'schema_version':1,'target_kicad':TARGET_VERSION,'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'project':str(project),'mode':mode,'phase':phase,'static_preview':static_preview,'environment':env,
            'counts':counts,'blocked':counts['阻断级']>0,
            'release_allowed':mode=='mass_production' and phase=='release' and not static_preview and counts['阻断级']==0,
            'inputs_sha256':r.inputs,'findings':r.findings,'checks':r.checks,'evidence':r.evidence,
            'limitations':['不能拦截用户绕过本工作流直接运行KiCad CLI/GUI导出。',
                '仅受控发布脚本执行门禁；二维几何预筛不是SI/PI/热/EMC求解。',
                '原型模式沿用原流程；本脚本不执行或修改旧脚本。']}

def write_report(report, output):
    output=Path(output)
    if output.exists() and any(output.iterdir()): raise ValueError('报告目录必须为空，防止覆盖已有证据')
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/'npi-report.json',report)
    lines=['# DFX/NPI量产评审报告','',f'目标：KiCad {TARGET_VERSION}',f'模式：{report["mode"]}；阶段：{report["phase"]}',
           f'生产放行：{"允许" if report["release_allowed"] else "禁止"}',
           '', '## 风险汇总','', '| 等级 | 数量 |','|---|---:|']
    lines += [f'| {k} | {v} |' for k,v in report['counts'].items()]
    lines += ['', '## 风险明细','']
    for f in report['findings']:
        lines += [f'### {f["id"]} · {f["level"]}',f'- 门禁：{f["gate"]}；实现：{f["method"]}',
                  f'- 位置：{f["location"]}',f'- 问题：{f["description"]}',f'- 参考：{f["reference"]}',f'- 修复：{f["suggestion"]}','']
    lines += ['## 已执行检查与证据','', '完整机器证据、输入哈希及原生命令日志见同目录 npi-report.json。','']
    for c in report['checks']: lines.append(f'- {c["rule"]} [{c["status"]}] {c["detail"]}')
    lines += ['', '## 能力边界','']+['- '+x for x in report['limitations']]
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
        p.exit(2,'评审失败（禁止放行）：'+str(e)+'\n')
    print(json.dumps({'blocked':report['blocked'],'release_allowed':report['release_allowed'],'counts':report['counts']},ensure_ascii=False))
    return 2 if report['blocked'] else 0

if __name__=='__main__': raise SystemExit(main())
