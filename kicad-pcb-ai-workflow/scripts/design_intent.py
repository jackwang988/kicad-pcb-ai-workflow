#!/usr/bin/env python3
"""Compile declared schematic intent into an isolated KiCad project candidate.

No inferred ampacity, impedance solution, field solver or schematic-to-PCB CLI.
Native formats are pinned to KiCad 10.0.7; native integration remains required.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import uuid
from pathlib import Path
from npi_common import parse_sexpr, children, child, value, sha256, finite_tree

KINDS = {'differential', 'power', 'rf', 'single_ended'}
PAIR_PROTOCOLS = {'USB2_HS','USB3','MIPI_DPHY','HDMI_TMDS','HDMI_FRL','ETH_MDI','PCIE','LVDS','DDR_DQS','DDR_CK'}
NAME = re.compile(r'^[A-Za-z0-9_./+\-]+$')
LAYER = re.compile(r'^(?:F|B|In[1-9][0-9]*)\.Cu$')

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def local(root, name):
    if not isinstance(name, str) or not name: raise ValueError('Missing relative file path')
    root=Path(root).resolve(); p=root/name
    if p.is_absolute() and Path(name).is_absolute(): raise ValueError('Absolute input forbidden')
    if any(x.is_symlink() for x in [p,*p.parents] if x.is_relative_to(root)):
        raise ValueError('Symlink forbidden: '+name)
    p=p.resolve()
    if not p.is_relative_to(root): raise ValueError('Input escapes project: '+name)
    return p

def positive(n, name, zero=False):
    if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or (n<0 if zero else n<=0):
        raise ValueError('Invalid numeric value: '+name)
    return n

def approval(record, root, inputs):
    if not isinstance(record,dict) or not all(record.get(k) for k in ('reviewer','date','reason','source','evidence')):
        raise ValueError('Approval requires reviewer/date/reason/source/evidence')
    dt.date.fromisoformat(record['date'])
    if not isinstance(record['source'],dict) or not all(record['source'].get(k) for k in ('document','revision','section')):
        raise ValueError('Approval source needs document/revision/section')
    if not isinstance(record['evidence'],list):raise ValueError('Evidence must be an array')
    for item in record['evidence']:
        p=local(root,item['file'])
        if not p.is_file() or not p.stat().st_size or sha256(p)!=item.get('sha256'):
            raise ValueError('Approval evidence missing/changed: '+item['file'])
        inputs[str(p)]=sha256(p)

def stackup_digest(board):
    return digest(child(child(board,'setup',[]),'stackup',[]))

def layout_digest(board):
    tags={'footprint','segment','arc','via','gr_line','gr_arc','gr_rect','gr_circle','gr_poly'}
    entries=[n for n in board if isinstance(n,list) and n and (n[0] in tags or n[0]=='zone' and child(n,'keepout') is None)]
    return digest(entries)

def power_budget(p):
    """Uniform copper trace DC bound only. Thermal width is externally approved.

    I^2R and voltage drop are reported; there is no IPC-2152 ampacity claim.
    Parallel copper, vias, necks, contacts and return path need separate review.
    """
    for k in ('continuous_a','peak_a','peak_duration_ms','max_temp_rise_c',
              'max_conductor_c','max_drop_v','max_peak_drop_v','max_path_length_mm'):
        positive(p.get(k),k)
    ambient=p.get('ambient_c')
    if isinstance(ambient,bool) or not isinstance(ambient,(int,float)) or not math.isfinite(ambient) or ambient<=-273.15:raise ValueError('Invalid ambient temperature')
    if p['peak_a']<p['continuous_a']:raise ValueError('Peak current below continuous current')
    duty=positive(p.get('peak_duty_cycle'),'peak duty cycle',zero=True)
    if duty>1:raise ValueError('Peak duty cycle must be between 0 and 1')
    rms=math.sqrt(p['continuous_a']**2*(1-duty)+p['peak_a']**2*duty)
    if p['max_conductor_c']<p['ambient_c']+p['max_temp_rise_c']:raise ValueError('Conductor temperature budget inconsistent')
    if p.get('path_model')!='single_uniform_trace':raise ValueError('Unsupported power distribution model')
    copper=p.get('layer_copper_um',{})
    if not copper:raise ValueError('Approved finished copper thickness per layer required')
    rho=1.724e-8*(1+0.00393*(p['max_conductor_c']-20))
    result={}
    for layer,t in copper.items():
        positive(t,'finished copper um')
        dc=rho*p['max_path_length_mm']*p['continuous_a']*1e6/(t*p['max_drop_v'])
        peak=rho*p['max_path_length_mm']*p['peak_a']*1e6/(t*p['max_peak_drop_v'])
        thermal=positive(p.get('thermal_min_width_mm',{}).get(layer),'approved per-layer thermal minimum')
        width=max(dc,peak,thermal)
        resistance=rho*p['max_path_length_mm']*1e6/(width*t)
        result[layer]={'dc_min_width_mm':dc,'peak_drop_min_width_mm':peak,'required_min_width_mm':width,
                       'resistance_ohm':resistance,'continuous_loss_w':p['continuous_a']**2*resistance,
                       'rms_current_upper_bound_a':rms,'rms_loss_w':rms**2*resistance,
                       'scope':'DC uniform-trace bound plus externally approved thermal minimum; not total rail or ampacity signoff'}
    return result

def spans(text):
    """Top-level child spans, respecting quoted strings; preserve unknown bytes."""
    depth=0; quoted=False; escaped=False; start=None; out=[]
    for i,c in enumerate(text):
        if quoted:
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
        elif c=='"':quoted=True
        elif c=='(':
            depth+=1
            if depth==2:start=i
        elif c==')':
            if depth==2:out.append((start,i+1))
            depth-=1
    if depth or quoted:raise ValueError('Malformed S-expression')
    return out

def q(s):return json.dumps(s,ensure_ascii=False)

def annotate(text, anchors):
    edits=[]; used=set()
    for a,b in spans(text):
        node=parse_sexpr(text[a:b]); uid=value(node,'uuid')
        if uid not in anchors:continue
        net,cls,summary=anchors[uid]
        if node[0] not in ('label','global_label','hierarchical_label') or node[1]!=net.rsplit('/',1)[-1]:
            raise ValueError('Label UUID/name mismatch; net renaming requires ECO: '+net)
        props={x[1]:x[2] for x in children(node,'property')}
        if props.get('Net Class') not in (None,'',cls) or props.get('Design Intent') not in (None,'',summary):
            raise ValueError('Existing label field conflict: '+net)
        x,y=child(node,'at')[1:3]; additions=[]
        for key,val in [('Net Class',cls),('Design Intent',summary)]:
            if props.get(key)==val:continue
            if key in props:raise ValueError('Existing empty field must be reviewed explicitly: '+net)
            additions.append(f'\n  (property {q(key)} {q(val)} (at {x} {y} 0) (hide yes) (effects (font (size 1.27 1.27))))')
        edits.append((b-1,''.join(additions)));used.add(uid)
    if used!=set(anchors):raise ValueError('Missing schematic labels: '+str(set(anchors)-used))
    for end,addition in sorted(edits,reverse=True):text=text[:end]+addition+text[end:]
    parse_sexpr(text)
    return text

def add_at_end(text,addition):
    end=text.rfind(')')
    out=text[:end]+'\n'+addition+'\n'+text[end:];parse_sexpr(out);return out

def native_profile(cls, layer_order):
    # KiCad10.0.7 common/project/tuning_profiles.cpp: geometric widths in nm.
    # Delay 0 is deliberate: this compiler does NOT enable time-domain tuning.
    def entry(g):
        signal=layer_order.index(g['layer'])
        top=[r for r in g['reference_layers'] if layer_order.index(r)<signal]
        bottom=[r for r in g['reference_layers'] if layer_order.index(r)>signal]
        if len(top)>1 or len(bottom)>1:raise ValueError('Reference planes must be on their actual physical sides')
        return {'signal_layer':g['layer'],'top_reference_layer':top[0] if top else 'UNDEFINED',
                'bottom_reference_layer':bottom[0] if bottom else 'UNDEFINED','width':round(g['width_mm']*1e6),
                'diff_pair_gap':round(g.get('gap_mm',0)*1e6),'delay':0}
    return {'profile_name':'DI_'+cls['name'],'type':1 if cls['kind']=='differential' else 0,
            'target_impedance':cls['target_impedance_ohm'],'enable_time_domain_tuning':False,
            'layer_entries':[entry(g) for g in cls['geometry']],
            'via_prop_delay':0,'via_overrides':[]}

def compile_intent(root, intent, verify=False):
    root=Path(root).resolve();d=finite_tree(copy.deepcopy(intent));inputs={};proposed={};budgets={}
    if d.get('schema_version')!=1:raise ValueError('Unsupported design intent schema')
    pro=local(root,d['project_file']);pcb=local(root,d['board_file'])
    if pro.with_suffix('.kicad_pcb')!=pcb:raise ValueError('Project/board basename must match')
    project=json.loads(pro.read_text(encoding='utf-8-sig'));board=parse_sexpr(pcb.read_text(encoding='utf-8-sig'))
    if board[0]!='kicad_pcb':raise ValueError('Invalid PCB')
    inputs.update({str(p):sha256(p) for p in (pro,pcb)})
    layer_order=[n[1] for n in child(board,'layers',[])[1:] if isinstance(n,list) and len(n)>1 and n[1].endswith('.Cu')]
    layers=set(layer_order)
    classes={c['name']:c for c in d.get('classes',[])};nets={n['name']:n for n in d.get('nets',[])}
    if not classes or not nets or len(classes)!=len(d['classes']) or len(nets)!=len(d['nets']):raise ValueError('Empty/duplicate intent classes or nets')
    approval(d.get('coverage'),root,inputs)
    if set(d['coverage'].get('critical_nets',[]))!=set(nets):raise ValueError('Critical-net inventory and declarations differ')
    for name,c in classes.items():
        if not NAME.fullmatch(name) or name=='Default' or c.get('kind') not in KINDS:raise ValueError('Invalid/reserved netclass')
        positive(c.get('clearance_mm'),'clearance');approval(c.get('approval'),root,inputs)
        geom=c.get('geometry',[])
        if not geom or len({g['layer'] for g in geom})!=len(geom):raise ValueError('Missing/duplicate layer geometry')
        for g in geom:
            if g['layer'] not in layers or not LAYER.fullmatch(g['layer']):raise ValueError('Unknown signal layer')
            for k in ('width_mm','min_width_mm','max_width_mm'):positive(g.get(k),k)
            if g['min_width_mm']<0.000001:raise ValueError('Width below native coordinate resolution')
            if not g['min_width_mm']<=g['width_mm']<=g['max_width_mm']:raise ValueError('Width bounds inconsistent')
            if c['kind']=='differential':
                for k in ('gap_mm','min_gap_mm','max_gap_mm'):positive(g.get(k),k)
                if not g['min_gap_mm']<=g['gap_mm']<=g['max_gap_mm']:raise ValueError('Gap bounds inconsistent')
            global_rules=project.get('board',{}).get('design_settings',{}).get('rules',{})
            if g['min_width_mm']<global_rules.get('min_track_width',0):raise ValueError('Intent width conflicts with global manufacturing minimum')
            if c['kind']=='differential' and g['min_gap_mm']<global_rules.get('min_clearance',0):raise ValueError('Pair gap conflicts with global manufacturing minimum')
            if c['kind'] in ('differential','rf','single_ended'):
                refs=g.get('reference_layers',[])
                if not 1<=len(refs)<=2 or len(set(refs))!=len(refs) or any(x not in layers or x==g['layer'] for x in refs):raise ValueError('Reference layer specification invalid')
        if c['kind'] in ('differential','rf','single_ended'):
            positive(c.get('target_impedance_ohm'),'impedance');positive(c.get('impedance_tolerance_percent'),'impedance tolerance')
            if not child(child(board,'setup',[]),'stackup',[]) or c.get('stackup_sha256')!=stackup_digest(board):raise ValueError('Impedance geometry needs a real matching approved stackup')
    anchor_files={};paired=set();chains=set()
    for pair in d.get('pairs',[]):
        p,n=pair['positive'],pair['negative']
        if not ((p.endswith('_P') and n==p[:-2]+'_N') or (p.endswith('+') and n==p[:-1]+'-')):raise ValueError('Native P/N suffix pairing invalid')
        if p in paired or n in paired or p not in nets or n not in nets:raise ValueError('Duplicate/missing pair member')
        if nets[p]['kind']!='differential' or nets[n]['kind']!='differential' or nets[p]['netclass']!=nets[n]['netclass']:raise ValueError('Pair kind/class mismatch')
        if pair.get('protocol') not in PAIR_PROTOCOLS:raise ValueError('Unsupported differential PHY/protocol; C-PHY trios are not pairs')
        if not pair.get('chain_id') or type(pair.get('segment_index')) is not int or pair['segment_index']<0:raise ValueError('Pair protocol/chain/segment required')
        chain=(pair['chain_id'],pair['segment_index'])
        if chain in chains:raise ValueError('Duplicate chain segment')
        chains.add(chain);paired.update((p,n))
    for name,n in nets.items():
        if not NAME.fullmatch(name) or any(x in name for x in '*?[') or n.get('kind') not in KINDS:raise ValueError('Unsafe or unsupported exact net name')
        c=classes.get(n.get('netclass'))
        if not c or c['kind']!=n['kind']:raise ValueError('Net/class kind mismatch')
        if n['kind']=='differential' and name not in paired:raise ValueError('Unpaired differential net')
        if not n.get('anchors'):raise ValueError('Explicit existing schematic label anchors required')
        # Hidden custom label field is documentation; Net Class + generated rules
        # are the native machine-enforced part. Keep full evidence in intent JSON.
        note={'kind':n['kind'],'net':name,'class':n['netclass'],
              'loops':[x['id'] for x in d.get('loops',[]) if name in x.get('nets',[])]}
        if n['kind']=='power':
            note.update({k:n['power'].get(k) for k in ('continuous_a','peak_a','peak_duration_ms','peak_duty_cycle',
                'ambient_c','max_temp_rise_c','max_drop_v','max_peak_drop_v','max_path_length_mm','layer_copper_um')})
        if n['kind']=='rf':
            note.update({k:n['rf'].get(k) for k in ('role','frequency_hz','power_dbm','reference_net','max_path_length_mm')})
            note['antenna_keepouts']=[x['id'] for x in d.get('regions',[]) if x.get('rf_net')==name]
        if n['kind']=='differential':
            note['pair']=next({k:p[k] for k in ('id','protocol','chain_id','segment_index','positive','negative')} for p in d['pairs'] if name in (p['positive'],p['negative']))
        summary='DI:'+json.dumps(note,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        for a in n['anchors']:
            f=local(root,a['file']);uid=a['label_uuid'];uuid.UUID(uid)
            by_id=anchor_files.setdefault(a['file'],{})
            if uid in by_id:raise ValueError('Label anchor reused')
            by_id[uid]=(name,n['netclass'],summary)
        if n['kind']=='power':
            p=n['power'];approval(p.get('approval'),root,inputs);budgets[name]=power_budget(p)
            if p.get('stackup_sha256')!=stackup_digest(board) or not child(child(board,'setup',[]),'stackup',[]):raise ValueError('Power copper analysis needs matching approved stackup')
            if set(p['layer_copper_um'])!={g['layer'] for g in c['geometry']}:raise ValueError('Power copper/geometry layer mismatch')
            for g in c['geometry']:
                if g['min_width_mm']+1e-9<budgets[name][g['layer']]['required_min_width_mm']:raise ValueError('Power width below DC/approved thermal bound: '+name)
        if n['kind']=='rf':
            rf=n['rf'];positive(rf.get('frequency_hz'),'RF frequency');positive(rf.get('max_path_length_mm'),'RF max length')
            if not isinstance(rf.get('power_dbm'),(int,float)) or isinstance(rf.get('power_dbm'),bool):raise ValueError('RF power dBm required')
            if rf.get('role')!='feedline' or not rf.get('reference_net'):raise ValueError('RF feedline needs explicit continuous reference net; antenna is a separate region')
            for k in ('return_review','matching_review'):approval(rf.get(k),root,inputs)
    for name,anchors in anchor_files.items():
        f=local(root,name);inputs[str(f)]=sha256(f)
        proposed[name]=annotate(f.read_text(encoding='utf-8-sig'),anchors)
    ns=project.setdefault('net_settings',{});version=ns.get('meta',{}).get('version',5)
    if version not in (3,4,5):raise ValueError('Unsupported net-settings schema')
    existing=ns.setdefault('classes',[])
    if not any(c.get('name')=='Default' for c in existing):existing.insert(0,{'name':'Default','priority':2147483647})
    priorities=[x.get('priority',0) for x in existing if x.get('name')!='Default'];priority=min(priorities+[0])-len(classes)
    for name,c in classes.items():
        g=c['geometry'][0]
        generated={'name':name,'priority':priority,'clearance':c['clearance_mm'],'track_width':g['width_mm'],
                   'tuning_profile':'DI_'+name if c['kind']!='power' else ''}
        priority+=1
        if c['kind']=='differential':generated.update(diff_pair_width=g['width_mm'],diff_pair_gap=g['gap_mm'])
        old=next((x for x in existing if x.get('name')==name),None)
        if old:generated['priority']=old.get('priority')
        if old and (any(old.get(k)!=v for k,v in generated.items()) if verify else old!=generated):raise ValueError('Existing netclass conflict; choose a new approved name: '+name)
        if not old:existing.append(generated)
    patterns=ns.setdefault('netclass_patterns',[])
    for name,n in nets.items():
        record={'pattern':name,'netclass':n['netclass']}
        if record not in patterns:patterns.append(record)
    ns['meta']={'version':5}
    tuning=project.setdefault('tuning_profiles',{'meta':{'version':0},'tuning_profiles_impedance_geometric':[]})
    if tuning.get('meta',{}).get('version')!=0:raise ValueError('Unsupported native tuning-profile schema')
    profiles=tuning['tuning_profiles_impedance_geometric']
    for c in classes.values():
        if c['kind']=='power':continue
        generated=native_profile(c,layer_order);old=next((p for p in profiles if p.get('profile_name')==generated['profile_name']),None)
        if old and old!=generated:raise ValueError('Existing tuning profile conflict')
        if not old:profiles.append(generated)
    severity=project.setdefault('board',{}).setdefault('design_settings',{}).setdefault('rule_severities',{})
    for k in ('track_width','clearance','diff_pair_gap_out_of_range','tuning_profile_track_geometries','items_not_allowed'):
        severity[k]='error'
    proposed[d['project_file']]=json.dumps(project,ensure_ascii=False,indent=2)+'\n'
    rules=['# BEGIN DESIGN INTENT R3']
    for name,n in nets.items():
        c=classes[n['netclass']];cond=f"A.NetName == '{name}'"
        for g in c['geometry']:
            constraints=[f"(constraint track_width (min {g['min_width_mm']}mm) (opt {g['width_mm']}mm) (max {g['max_width_mm']}mm))"]
            if n['kind']=='differential':constraints.append(f"(constraint diff_pair_gap (min {g['min_gap_mm']}mm) (opt {g['gap_mm']}mm) (max {g['max_gap_mm']}mm))")
            for ix,con in enumerate(constraints):
                rules.append(f'(rule {q("DI_"+name+"_"+g["layer"]+"_"+str(ix))} (severity error) (condition {q(cond)}) (layer {g["layer"]}) {con})')
        permitted=' || '.join("A.Layer == '"+g['layer']+"'" for g in c['geometry'])
        rules.append(f'(rule {q("DI_LAYERS_"+name)} (severity error) (condition {q(cond+" && !("+permitted+")")}) (constraint disallow track))')
        clear_cond=cond+' && !AB.isCoupledDiffPair()' if n['kind']=='differential' else cond
        rules.append(f'(rule {q("DI_CLEARANCE_"+name)} (severity error) (condition {q(clear_cond)}) (constraint clearance (min {c["clearance_mm"]}mm)))')
        if n['kind']=='differential':
            for g in c['geometry']:
                rules.append(f'(rule {q("DI_PAIR_CLEARANCE_"+name+"_"+g["layer"])} (severity error) (condition {q(cond+" && AB.isCoupledDiffPair()")}) (layer {g["layer"]}) (constraint clearance (min {g["min_gap_mm"]}mm)))')
    rules.append('# END DESIGN INTENT R3')
    dru=pro.with_suffix('.kicad_dru');key=str(dru.relative_to(root));original=dru.read_text() if dru.exists() else '(version 1)\n'
    generated_rules='\n'.join(rules)+'\n'
    if '# BEGIN DESIGN INTENT' in original:
        if not verify or original.count('# BEGIN DESIGN INTENT R3')!=1 or not original.endswith(generated_rules):raise ValueError('Existing generated rules conflict or duplicate append')
        original=original[:original.index('# BEGIN DESIGN INTENT R3')]
    if dru.exists():inputs[str(dru)]=sha256(dru)
    if not original.lstrip().startswith('(version 1)'):raise ValueError('Unsupported custom rule format')
    proposed[key]=original.rstrip()+'\n'+generated_rules
    pcbtext=pcb.read_text(encoding='utf-8-sig')
    ids=set()
    for region in d.get('regions',[]):
        rid=region['id']
        if not NAME.fullmatch(rid) or rid in ids:raise ValueError('Duplicate/unsafe region id')
        ids.add(rid)
        if region.get('kind')!='antenna_keepout':raise ValueError('Only explicit antenna_keepout geometry is supported')
        if nets.get(region.get('rf_net'),{}).get('kind')!='rf':raise ValueError('Antenna region must identify its declared RF feed net')
        approval(region.get('approval'),root,inputs)
        polygon=region.get('polygon_mm',[])
        if len(polygon)!=4 or len({tuple(p) for p in polygon})!=4:raise ValueError('Only axis-aligned rectangle keepouts supported')
        for p in polygon:
            if len(p)!=2 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in p):raise ValueError('Invalid keepout point')
        xs={p[0] for p in polygon};ys={p[1] for p in polygon}
        if len(xs)!=2 or len(ys)!=2 or any(polygon[i][0]!=polygon[(i+1)%4][0] and polygon[i][1]!=polygon[(i+1)%4][1] for i in range(4)):raise ValueError('Keepout must be a simple ordered rectangle')
        if not region.get('layers') or not set(region['layers']).issubset(layers):raise ValueError('Explicit keepout layers required')
        if not region.get('anchor',{}).get('ref'):raise ValueError('Antenna footprint anchor required')
        if any(value(z,'name')=='DI_'+rid for z in children(board,'zone')):
            if verify:continue
            raise ValueError('Keepout name already exists')
        pts=' '.join(f'(xy {x} {y})' for x,y in polygon)
        zone=f'(zone (net 0) (net_name "") (layers '+ ' '.join(q(x) for x in region['layers'])+f') (uuid {q(str(uuid.uuid5(uuid.NAMESPACE_URL,"DI:"+rid)))}) (name {q("DI_"+rid)}) (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) (filled_areas_thickness no) (keepout (tracks not_allowed) (vias not_allowed) (pads not_allowed) (copperpour not_allowed) (footprints not_allowed)) (polygon (pts {pts})))'
        pcbtext=add_at_end(pcbtext,zone)
    if d.get('regions'):proposed[d['board_file']]=pcbtext
    for loop in d.get('loops',[]):
        positive(loop.get('max_area_mm2'),'loop area');approval(loop.get('review'),root,inputs)
        if not loop.get('nets') or not set(loop['nets']).issubset(nets):raise ValueError('Loop net mapping missing')
    return {'proposed':proposed,'inputs_sha256':inputs,'power_budgets':budgets,'intent_sha256':digest(d),
            'layout_sha256':layout_digest(board),'native_validated':False}

def prepare(root, intent_file, destination, apply=False):
    root=Path(root).resolve();intent_file=Path(intent_file).resolve();dest=Path(destination).resolve()
    if dest.exists() or dest.is_relative_to(root) or root.is_relative_to(dest):raise ValueError('New independent candidate directory required')
    intent=json.loads(intent_file.read_text());plan=compile_intent(root,intent)
    source_files=[p for p in root.rglob('*') if p.is_file()]
    if any(p.is_symlink() for p in root.rglob('*')):raise ValueError('Source tree contains symlinks')
    before={str(p.relative_to(root)):sha256(p) for p in source_files}
    result={'status':'PREVIEW','production_authorized':False,'changes':sorted(plan['proposed']),
            'power_budgets':plan['power_budgets'],'intent_sha256':plan['intent_sha256'],
            'note':'Candidate only. No schematic-to-PCB sync, native ERC/DRC or manufacturing authorization performed.'}
    if not apply:return result
    owned=False
    try:
        dest.mkdir(parents=True,exist_ok=False);owned=True
        shutil.copytree(root,dest,dirs_exist_ok=True)
        for name,content in plan['proposed'].items():local(dest,name).write_text(content,encoding='utf-8')
        evidence=dest/'design-intent-source.json'
        if evidence.exists():raise ValueError('Reserved candidate evidence already exists')
        evidence.write_text(json.dumps(intent,ensure_ascii=False,indent=2)+'\n')
        result['status']='CANDIDATE_UNVERIFIED';result['source_sha256']=before
        result['output_sha256']={name:sha256(local(dest,name)) for name in plan['proposed']}
        marker=dest/'design-intent-compile.json'
        if marker.exists():raise ValueError('Reserved compile record exists')
        marker.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        if any(not local(root,n).is_file() or sha256(local(root,n))!=h for n,h in before.items()):raise ValueError('Source changed during compile')
    except Exception:
        if owned:shutil.rmtree(dest)
        raise
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project');p.add_argument('--intent',required=True);p.add_argument('--destination',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:r=prepare(a.project,a.intent,a.destination,a.apply)
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
