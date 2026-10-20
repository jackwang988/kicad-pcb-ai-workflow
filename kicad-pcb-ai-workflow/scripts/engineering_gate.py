"""Evidence-backed publication checks for WORKFLOW findings R01-R25.

No native tool, engineer signature or factory review is simulated here.
An evidence record binds an actual file to a declared review; authenticity
and organizational approval authority remain the owner's responsibility.
"""
import json
import hashlib
import datetime as dt
import re
import csv
from pathlib import Path
from npi_common import sha256,parse_sexpr,children,child,value,finite_tree,runtime_inventory
from netlist_guard import compare

CATEGORIES=('requirements','schematic','footprints','stackup','signal_integrity','power_integrity',
            'thermal','safety','manufacturing','assembly','cam','factory_eq','validation_plan','change_control')

def local(project,name):
    original=project/name;p=original.resolve()
    if original.is_symlink() or not p.is_relative_to(project):raise ValueError('Unsafe input/evidence path: '+str(name))
    if any(x.is_symlink() for x in original.parents if x!=project.parent):raise ValueError('Symlinked parent')
    return p

def evidence(record,project,r):
    if not isinstance(record,dict) or not record.get('file') or not re.fullmatch('[0-9a-f]{64}',str(record.get('sha256',''))):
        raise ValueError('Evidence needs an actual local file and SHA-256')
    p=local(project,record['file'])
    if not p.is_file() or p.stat().st_size==0 or sha256(p)!=record['sha256']:raise ValueError('Evidence missing, empty or changed: '+record['file'])
    r.inputs[str(p)]=sha256(p)
    return p

def source(record):
    return isinstance(record,dict) and all(record.get(k) for k in ('document','revision','section'))

def inspect_inventory(r):
    root=Path(__file__).resolve().parents[1]
    try:
        active=runtime_inventory(root)
        r.check('TOOLS.INVENTORY','completed',f'{len(active)} required runtime tools verified; project archives are separate from production gates')
    except Exception as e:r.risk('TOOLS.INVENTORY','npi','阻断级',str(e),fix='恢复批准版本工具；缺脚本或工具合同不完整不得放行。')

def inspect(r,project,config,candidate,board_path=None):
    inspect_inventory(r)
    from design_intent_audit import integrate as intent_integrate
    intent_integrate(r,project,config)
    from static_review_gate import integrate as static_ai_integrate
    static_ai_integrate(r,project,config)
    if config.get('workflow_contract'):
        try:
            from project_flow import check as flow_check
            flow=flow_check(project,config['workflow_contract'],'npi' if r.phase!='release' else 'cam_release')
            r.inputs.update(flow['inputs_sha256']);r.evidence.append({'workflow_intake':flow})
            for f in flow['findings']:r.risk(f['rule'],'npi',f['level'],f['description'],f['location'],f['reference'],f['suggestion'])
            if not config.get('schematic_style',{}).get('policy'):raise ValueError('R9 workflow requires schematic_style policy')
            from schematic_style import audit as style_audit
            style=style_audit(project,config['inputs']['schematic'],config['schematic_style']['policy']);r.inputs.update(style['inputs_sha256'])
            for f in style['findings']:r.risk(f['rule'],'schematic',f['level'],f['description'],f['location'],f['reference'],f['suggestion'])
            record=config['static_ai_reviews']['schematic'];packet_path=local(project,record['packet'])/'packet.json';packet=json.loads(packet_path.read_text())
            if packet['config'].get('schematic_style')!=config['schematic_style'] or packet['config'].get('require_schematic_style') is not True:raise ValueError('R9 style policy differs from confirmed schematic review')
            if config.get('require_system_integration') is not True or not config.get('system_integration',{}).get('contract'):
                raise ValueError('R9 workflow requires a system architecture/interface contract')
            if packet['config'].get('system_integration')!=config['system_integration'] or packet['config'].get('require_system_integration') is not True:
                raise ValueError('System architecture/interface contract differs from confirmed schematic review')
            from system_integration import audit as system_audit
            netlist=local(project,Path(record['packet'])/'netlist.xml')
            facts=json.loads(local(project,Path(record['packet'])/'facts.json').read_text())
            result=system_audit(project,config['system_integration']['contract'],config['inputs']['schematic'],facts['netlist'],config['documents'])
            captured=json.loads(local(project,Path(record['packet'])/'system-integration.json').read_text())
            if result!=captured or not netlist.is_file():raise ValueError('System interface audit is stale or packet evidence is incomplete')
        except Exception as e:r.risk('FLOW.NPI','npi','阻断级',str(e),fix='完成当前项目契约、结构检查与实际原理图AI/工程师确认；不改用旧模板绕过R9。')
    from reserve_review import integrate as reserve_integrate
    reserve_integrate(r,project,config,candidate,board_path)
    from placement_review import integrate as placement_integrate
    placement_integrate(r,project,config,board_path)
    profile_path=config.get('engineering_profile')
    if not profile_path:
        r.risk('ENG.PROFILE','npi','阻断级','缺少产品工程规格与证据配置 engineering_profile',fix='按references/engineering-rules.md及assets/engineering-profile.template.json填写产品规格；不能拿通用经验替代。');return
    try:
        pp=local(project,profile_path);profile=finite_tree(json.loads(pp.read_text()));r.inputs[str(pp)]=sha256(pp)
        if not profile.get('product_id') or not profile.get('revision') or not profile.get('owner'):
            raise ValueError('Product id/revision/owner required')
        # Reproducible in-project source/library/rule inventory, never an implicit external library.
        declared=profile.get('source_files',[])
        if not declared:r.risk('ENG.SOURCE.INVENTORY','npi','阻断级','缺少规则/库/工程源文件清单source_files')
        for name in declared:
            file=local(project,name)
            if not file.is_file():raise ValueError('Missing declared source '+name)
            r.inputs[str(file)]=sha256(file)
        reviews=profile.get('reviews',{})
        for category in CATEGORIES:
            if r.phase!='release' and category in ('cam','factory_eq'):
                r.check('ENG.'+category.upper(),'deferred','最终候选包生成后审查；本阶段不得生产放行');continue
            item=reviews.get(category,{})
            try:
                if item.get('status') not in ('PASS','N/A') or not all(item.get(k) for k in ('reviewer','date','reason')):
                    raise ValueError('Missing review/status/owner/date/rationale')
                dt.date.fromisoformat(item['date'])
                if not source(item.get('source')):raise ValueError('Missing source document/revision/section')
                records=item.get('evidence',[])
                if not records:raise ValueError('No review evidence files')
                for rec in records:evidence(rec,project,r)
                r.check('ENG.'+category.upper(),item['status'],item['reason'],'工程师/工厂评审证据')
            except Exception as e:
                r.risk('ENG.'+category.upper(),'npi','阻断级',f'{category}: {e}',standard='产品要求/原厂指南/经批准工艺文件',fix='补充真实规格、评审结论、文件哈希及责任人。')
        requirements=profile.get('requirements',[])
        if not requirements:r.risk('ENG.TRACE','npi','阻断级','没有逐项产品需求→规则→验证追踪记录')
        ids=[]
        for req in requirements:
            ids.append(req.get('id'))
            try:
                if not req.get('id') or req.get('status') not in ('PASS','N/A') or not source(req.get('source')):
                    raise ValueError('Requirement identity/status/source absent')
                if not req.get('design_rule') or not req.get('verification_method'):raise ValueError('No rule/method mapping')
                if req['status']=='N/A' and not req.get('reason'):raise ValueError('N/A without rationale')
                if req['status']=='PASS' and ('acceptance' not in req or req['acceptance'] in (None,'',{})):raise ValueError('No quantified/explicit acceptance criterion')
                if not req.get('evidence'):raise ValueError('No verification evidence')
                for rec in req['evidence']:evidence(rec,project,r)
            except Exception as e:r.risk('ENG.TRACE','npi','阻断级',str(e),str(req.get('id')))
        if len(ids)!=len(set(ids)):r.risk('ENG.TRACE','npi','阻断级','重复需求ID')
        netlist=profile.get('netlist',{})
        try:
            before=local(project,netlist['before']);after=local(project,netlist['after'])
            eco=json.loads(local(project,netlist['eco']).read_text()) if netlist.get('eco') else None
            result=compare(before,after,netlist.get('mode','preserve'),netlist.get('topology',False),eco,netlist.get('allow_zero_nets',False))
            r.inputs[str(before)]=sha256(before);r.inputs[str(after)]=sha256(after)
            if netlist.get('eco'):
                eco_file=local(project,netlist['eco']);r.inputs[str(eco_file)]=sha256(eco_file)
            r.evidence.append({'strict_netlist':result})
            if result['status']!='PASS':r.risk('ENG.NETLIST','schematic','阻断级','实际网表/属性变化与保持拓扑或ECO预期不符')
            from netlist_guard import read_netlist
            for variant in config.get('variants',['default']):
                xml_name=profile.get('variant_netlists',{}).get(variant)
                if not xml_name and variant==profile.get('assembly_variant','default'):xml_name=netlist['after']
                if not xml_name:raise ValueError('Missing variant-specific netlist '+variant)
                xml_file=local(project,xml_name);parts=set(read_netlist(xml_file,netlist.get('allow_zero_nets',False))['components'])
                r.inputs[str(xml_file)]=sha256(xml_file)
                for category,operation in [('bom_exclusions','remove'),('bom_additions','add')]:
                    for ref,record in profile.get(category,{}).items():
                        if not record.get('reviewer') or not record.get('reason') or not record.get('evidence'):raise ValueError('Unapproved BOM exception '+ref)
                        for rec in record['evidence']:evidence(rec,project,r)
                        if operation=='remove':parts.discard(ref)
                        else:parts.add(ref)
                bom_name=config.get('variant_boms',{}).get(variant) or config.get('inputs',{}).get('bom')
                bom_file=local(project,bom_name)
                with bom_file.open(encoding='utf-8-sig',newline='') as handle:rows=list(csv.DictReader(handle))
                column=config.get('bom_fields',{}).get('ref','Reference');refs=set()
                for row in rows:
                    if row.get('Variant') and row['Variant']!=variant:continue
                    refs.update(x for x in re.split(r'[,;\s]+',(row.get(column) or '').strip()) if x)
                if not refs or refs!=parts:raise ValueError('BOM/design references differ for variant '+variant+': missing='+str(sorted(parts-refs))+', extra='+str(sorted(refs-parts)))

        except Exception as e:r.risk('ENG.NETLIST','schematic','阻断级',str(e),fix='使用XML导出，运行netlist_guard；不接受旧diff_net的0退出作为证据。')
        # SI path applicability must be explicit; no-interface products may use N/A with evidence.
        if reviews.get('signal_integrity',{}).get('status')=='PASS':
            try:
                from link_audit import primitives,audit
                pathspec=local(project,profile['link_profile']);r.inputs[str(pathspec)]=sha256(pathspec)
                b,edges=primitives(board_path,True);result=audit(b,edges,json.loads(pathspec.read_text()))
                r.evidence.append({'endpoint_path_audit':result})
                if result['status']!='PASS':r.risk('ENG.LINK','routing','阻断级','端点链路检查未通过；圆弧/分支/缺路径不得跳过')
            except Exception as e:r.risk('ENG.LINK','routing','阻断级',str(e))
        if board_path:
            inspect_courtyards(r,board_path,profile,project)
            from pad_audit import inspect as pad_inspect
            pad_inspect(r,board_path)
        # High risks require specific evidence-backed acceptance, never a type-wide waiver.
        for finding in list(r.findings):
            if finding['level']!='高风险':continue
            fingerprint=hashlib.sha256(json.dumps({k:finding[k] for k in ('rule','location','description')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            acceptance=profile.get('risk_acceptance',{}).get(fingerprint,{})
            try:
                if not all(acceptance.get(k) for k in ('reviewer','date','reason')) or not acceptance.get('evidence'):
                    raise ValueError('High-risk item has no individual acceptance')
                for rec in acceptance['evidence']:evidence(rec,project,r)
            except (OSError,ValueError,KeyError,TypeError):
                r.risk('ENG.RISK.ACCEPTANCE','npi','阻断级','高风险未逐项关闭或经证据批准：'+fingerprint,finding['location'])
        if r.phase=='release':inspect_production(r,project,config,profile,Path(candidate).resolve() if candidate else None)
    except Exception as e:r.risk('ENG.PROFILE','npi','阻断级',str(e))

def inspect_courtyards(r,board_path,profile,project):
    try:
        tree=parse_sexpr(Path(board_path).read_text(encoding='utf-8-sig'))
        exemptions=profile.get('courtyard_exemptions',{})
        for fp in children(tree,'footprint'):
            props={x[1]:x[2] for x in children(fp,'property') if len(x)>2};ref=props.get('Reference','?')
            outlines=[x for x in fp if isinstance(x,list) and x and x[0] in ('fp_line','fp_rect','fp_poly','fp_arc') and value(x,'layer') in ('F.CrtYd','B.CrtYd')]
            if not outlines:
                ex=exemptions.get(ref,{})
                if not all(ex.get(k) for k in ('reason','reviewer')) or not ex.get('evidence'):
                    r.risk('ENG.COURTYARD','layout','阻断级','缺少courtyard；不能默认布局合格',ref,fix='补齐经核对的courtyard或记录有证据的不适用审批；原生DRC仍必须执行。')
                else:
                    for rec in ex['evidence']:evidence(rec,project,r)
            else:
                # Line/arc outlines must form closed endpoint chains. No silent Boolean failure.
                from collections import Counter
                from npi_common import xy
                points=[]
                for outline in outlines:
                    if outline[0] in ('fp_line','fp_arc'):
                        if xy(outline,'start')==xy(outline,'end'):raise ValueError('Degenerate courtyard edge '+ref)
                        points.extend([tuple(round(v,6) for v in xy(outline,'start')),tuple(round(v,6) for v in xy(outline,'end'))])
                    if outline[0]=='fp_rect' and xy(outline,'start')==xy(outline,'end'):
                        raise ValueError('Degenerate courtyard rectangle '+ref)
                    if outline[0]=='fp_poly' and len(children(child(outline,'pts',[]),'xy'))<3:
                        raise ValueError('Degenerate courtyard polygon '+ref)
                if any(n!=2 for n in Counter(points).values()):
                    r.risk('ENG.COURTYARD','layout','阻断级','Courtyard线段/圆弧链未闭合或分叉',ref)
    except Exception as e:r.risk('ENG.COURTYARD','layout','阻断级','Courtyard检查异常：'+str(e))

def inspect_production(r,project,config,profile,candidate):
    if candidate and candidate.is_relative_to(project):
        r.risk('ENG.BUILD','npi','阻断级','制造候选包目录必须位于工程目录外，防止源/输出混淆');return
    if not candidate or not candidate.is_dir():
        r.risk('ENG.BUILD','npi','阻断级','缺少可复验候选制造包');return
    try:
        manifest_path=local(candidate,'build-manifest.json');build=json.loads(manifest_path.read_text())
        if build.get('level')!='D2' or not build.get('production_authorization'):
            raise ValueError('D2打样生产授权未记录；D0/D1不允许生产发布')
        # Production authorization is a record, not permission for ChatGPT to send an order.
        for k in ('reviewer','date','factory','order_scope'):
            if not build['production_authorization'].get(k):raise ValueError('Incomplete production authorization')
        sources=build.get('source_sha256',{})
        expected={str(Path(p).relative_to(project)):h for p,h in r.inputs.items() if Path(p).is_relative_to(project)}
        for name,digest in expected.items():
            if sources.get(name)!=digest:raise ValueError('候选制造包源文件不一致或缺源追踪：'+name)
        files={f for group in config.get('delivery_manifest',{}).values() for f in group}
        for name in files-{'build-manifest.json'}:
            p=local(candidate,name)
            if not p.is_file() or sha256(p)!=build.get('output_sha256',{}).get(name):raise ValueError('候选输出哈希不一致：'+name)
            if name in config.get('delivery_manifest',{}).get('gerber',[]):
                data=p.read_text(encoding='ascii',errors='strict')
                if not re.search(r'%FS[^%]*\*%',data) or not re.search(r'%MO(?:MM|IN)\*%',data) or not re.search(r'M0?2\*',data):
                    raise ValueError('Gerber结构标记缺失：'+name)
            if name in config.get('delivery_manifest',{}).get('drill',[]):
                data=p.read_text(encoding='ascii',errors='strict')
                if 'M48' not in data or not ('METRIC' in data or 'INCH' in data) or not re.search(r'M(?:30|00)',data):
                    raise ValueError('Excellon结构标记缺失：'+name)
        for key in ('tools','commands','logs','cam_review','final_state_validation','factory_eq'):
            if not build.get(key):raise ValueError('制造证据缺失：'+key)
        from production_contract import records as production_records,cam_checks
        design_basis,manufacturing_binding=production_records(build,config,profile)
        for rec in build['logs']:evidence(rec,candidate,r)
        from assembly_guard import read_bom,check_cpl
        bom_files=config.get('delivery_manifest',{}).get('bom',[])
        cpl_files=config.get('delivery_manifest',{}).get('cpl',[])
        if len(bom_files)!=1 or len(cpl_files)!=1:raise ValueError('One selected variant BOM/CPL required per release package')
        check_cpl(read_bom(local(candidate,bom_files[0])),local(candidate,cpl_files[0]),profile.get('assembly_variant'))
        for key in ('cam_review','final_state_validation','factory_eq'):
            evidence(build[key],candidate,r)
        cam=json.loads(local(candidate,build['cam_review']['file']).read_text())
        if cam.get('status')!='PASS' or not all(cam.get(k) for k in ('viewer','viewer_version','reviewer','date','checks')):
            raise ValueError('独立CAM加载/审图证据无效')
        cam_checks(cam)
        for name in config.get('delivery_manifest',{}).get('gerber',[])+config.get('delivery_manifest',{}).get('drill',[]):
            if cam.get('actual_files_sha256',{}).get(name)!=sha256(local(candidate,name)):
                raise ValueError('CAM审图并非针对当前实际Gerber/钻孔：'+name)
        eq=json.loads(local(candidate,build['factory_eq']['file']).read_text())
        if eq.get('status')!='CLOSED' or eq.get('open_items')!=[] or eq.get('factory')!=build['production_authorization']['factory']:
            raise ValueError('板厂EQ未关闭或工厂不一致')
        if eq.get('source_basis_sha256')!=design_basis or eq.get('output_sha256')!=manufacturing_binding:raise ValueError('工厂EQ不是针对当前设计/制造包')
        dt.date.fromisoformat(eq['date'])
        final=json.loads(local(candidate,build['final_state_validation']['file']).read_text())
        expected_ops=['refill','save','reload','erc','drc','schematic_parity','spec_review']
        if final.get('operations')!=expected_ops or final.get('status')!='PASS':raise ValueError('没有最终状态refill/save/reload/原生/规格审计证据')
        board=local(project,config['inputs']['board'])
        if final.get('board_sha256')!=sha256(board):raise ValueError('最终验证对应的PCB版本不一致')
        late=set()
        for category in ('cam','factory_eq'):
            for rec in profile.get('reviews',{}).get(category,{}).get('evidence',[]):late.add(str(local(project,rec['file'])))
        for rec in config.get('manual_reviews',{}).get('NPI.CAM',{}).get('evidence',[]):
            if isinstance(rec,dict) and rec.get('file'):late.add(str(local(project,rec['file'])))
        freeze=project/'freeze-log.json'
        if not freeze.is_file() or final.get('freeze_log_sha256')!=sha256(freeze):raise ValueError('冻结记录缺失或与最终验证不一致')
        review_name=str(Path(build['final_state_validation']['file']).parent/final['full_review_file'])
        review_file=evidence({'file':review_name,'sha256':final['full_review_sha256']},candidate,r)
        full=json.loads(review_file.read_text())
        if full.get('blocked') is not False or full.get('counts',{}).get('阻断级')!=0 or not full.get('environment',{}).get('cli_exact_target') or not full.get('environment',{}).get('pcbnew_exact_target'):
            raise ValueError('完整最终检查报告并未在目标原生环境通过')
        for file,digest in r.inputs.items():
            if Path(file).is_relative_to(project) and file not in late and full.get('inputs_sha256',{}).get(file)!=digest:
                raise ValueError('最终检查后原理图/BOM/规则/profile/证据已变化或未检查：'+file)
        freeze_name=str(Path(build['final_state_validation']['file']).parent/final['freeze_log_file'])
        evidence({'file':freeze_name,'sha256':final['freeze_log_sha256']},candidate,r)
        if not {'erc','drc'}.issubset({e.get('kind') for e in full.get('evidence',[]) if isinstance(e,dict)}):
            raise ValueError('完整报告缺少原生ERC/DRC证据')
        r.inputs[str(manifest_path)]=sha256(manifest_path)
        r.check('ENG.BUILD','completed','D2源/输出哈希、实际文件结构和工程审核记录齐全；独立CAM内容正确性由审图证据负责')
    except Exception as e:r.risk('ENG.BUILD','npi','阻断级',str(e),fix='从冻结源重建实际制造包；补齐独立Gerber/钻孔CAM复核、最终状态验证、EQ与生产授权记录。')

def violation_identity(v):
    """Development regression identity; equal counts do not imply equivalence."""
    items=sorted((json.dumps({k:item.get(k) for k in ('uuid','description','pos','net','layer')},sort_keys=True) for item in v.get('items',[])))
    return json.dumps({'type':v.get('type'),'rule':v.get('rule'),'severity':v.get('severity'),'items':items},sort_keys=True)

def new_violations(before,after):
    old={violation_identity(v) for v in before}
    return [v for v in after if violation_identity(v) not in old]
