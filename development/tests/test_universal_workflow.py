import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow/scripts'))
import schematic_io as sio
import schematic_style as style
import schematic_candidate as candidate
import project_flow as flow
import manufacturing_export as export
import system_integration as system
from npi_common import sha256

def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False))

class UniversalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=pathlib.Path(self.tmp.name);self.root=self.base/'source';self.root.mkdir()
        (self.root/'spec.md').write_text('TEST ONLY independent expected circuit and explicit page preference.')
        self.src={'file':'spec.md','sha256':sha256(self.root/'spec.md'),'locator':'TEST section'}
        self.sch='(kicad_sch (version 20260101) (paper "A4") (lib_symbols) (symbol (lib_id "TEST:R") (at 10 10 0) (property "Reference" "R1")))'
        (self.root/'main.kicad_sch').write_text(self.sch);(self.root/'main.kicad_pro').write_text('{}')
        (self.root/'main.kicad_pcb').write_text('(kicad_pcb (version 20260101) (layers (0 "F.Cu" signal) (2 "B.Cu" signal)) (general (thickness 1.6)))')
        self.policy={'schema_version':1,'pages':{},'require_sheet_pin_wire':False,'source':self.src};dump(self.root/'style.json',self.policy)
    def tearDown(self):self.tmp.cleanup()
    def audit(self):dump(self.root/'style.json',self.policy);return style.audit(self.root,'main.kicad_sch','style.json')
    def test_whitespace_independent(self):
        a='(kicad_sch\n\t(lib_symbols)\n\t(symbol (property "Reference" "R1")))'
        self.assertEqual(sio.parse(a),sio.parse(a.replace('\t','  ')))
    def test_malformed_quote_rejected(self):
        with self.assertRaises(ValueError):sio.parse('(kicad_sch (text "unfinished))')
    def test_quoted_parentheses(self):self.assertEqual(sio.parse('(text "(not structure)")'),['text','(not structure)'])
    def test_sheet_cycle_rejected(self):
        (self.root/'main.kicad_sch').write_text('(kicad_sch (sheet (property "Sheetfile" "main.kicad_sch")))')
        with self.assertRaises(ValueError):sio.sheets(self.root,'main.kicad_sch')
    def test_sheet_escape_rejected(self):
        (self.root/'main.kicad_sch').write_text('(kicad_sch (sheet (property "Sheetfile" "../outside.kicad_sch")))')
        with self.assertRaises(ValueError):sio.sheets(self.root,'main.kicad_sch')
    def test_missing_sheet_rejected(self):
        (self.root/'main.kicad_sch').write_text('(kicad_sch (sheet (property "Sheetfile" "absent.kicad_sch")))')
        with self.assertRaises(FileNotFoundError):sio.sheets(self.root,'main.kicad_sch')
    def test_style_no_arbitrary_page_default(self):
        (self.root/'main.kicad_sch').write_text(self.sch.replace('"A4"','"A2"'));r=self.audit();self.assertFalse(r['findings']);self.assertFalse(r['production_authorized'])
    def test_style_explicit_page_failure(self):
        self.policy['pages']={'main.kicad_sch':{'paper':'A3'}};self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_style_source_change_invalidates(self):
        self.policy['pages']={'main.kicad_sch':{'paper':'A4'}};(self.root/'spec.md').write_text('changed')
        with self.assertRaises(ValueError):self.audit()
    def hierarchy(self,wire=False):
        (self.root/'sub.kicad_sch').write_text('(kicad_sch (hierarchical_label "DATA" (at 10 10 0)))')
        (self.root/'main.kicad_sch').write_text('(kicad_sch (sheet (property "Sheetfile" "sub.kicad_sch") (pin "DATA" input (at 10 10 0)))'+('(wire (pts (xy 5 10) (xy 15 10)))' if wire else '')+')')
    def test_hierarchy_matches_without_forced_wire(self):self.hierarchy();self.assertFalse(self.audit()['findings'])
    def test_hierarchy_mismatch(self):
        self.hierarchy();(self.root/'sub.kicad_sch').write_text('(kicad_sch (hierarchical_label "OTHER"))');self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_midsegment_sheet_pin_allowed(self):
        self.hierarchy(True);self.policy['require_sheet_pin_wire']=True;self.assertFalse(self.audit()['findings'])
    def test_explicit_sheet_wire_missing(self):
        self.hierarchy();self.policy['require_sheet_pin_wire']=True;self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_wrong_boolean_rejected(self):
        self.policy['require_sheet_pin_wire']='yes'
        with self.assertRaises(ValueError):self.audit()
    def system_contract(self):
        (self.root/'sub.kicad_sch').write_text('(kicad_sch (lib_symbols) (symbol (lib_id "TEST:X") (property "Reference" "U2")))')
        (self.root/'main.kicad_sch').write_text('(kicad_sch (lib_symbols) (symbol (lib_id "TEST:X") (property "Reference" "U1")) (sheet (property "Sheetfile" "sub.kicad_sch")))')
        (self.root/'overview.svg').write_text('<svg>TEST architecture</svg>')
        c={'schema_version':1,'project_id':'TEST','revision':'A','overview':{'sheet':'main.kicad_sch','file':'overview.svg','sha256':sha256(self.root/'overview.svg'),'source':{'document_id':'SPEC','locator':'§1'}},
           'modules':[{'id':'logic_a','name':'A','role':'source','sheet':'main.kicad_sch','components':['U1']},{'id':'logic_b','name':'B','role':'sink','sheet':'sub.kicad_sch','components':['U2']}],
           'interfaces':[{'id':'BUS1','kind':'digital','purpose':'TEST link','from_module':'logic_a','to_module':'logic_b','source':{'document_id':'SPEC','locator':'§2'},'nets':[{'name':'DATA','terminals':[{'ref':'U1','pin':'1'},{'ref':'U2','pin':'1'}]}],
                          'checks':[{'id':'voltage','method':'semantic','acceptance':'Datasheet-compatible levels','source':{'document_id':'SPEC','locator':'§3'}}]}],
           'system_checks':[{'id':'boot','method':'semantic','acceptance':'Boot/reset sequencing works','source':{'document_id':'SPEC','locator':'§4'}}]}
        dump(self.root/'system.json',c)
        return {'components':{'U1':{},'U2':{}},'nets':{'DATA':[('U1','1'),('U2','1')]}}
    def test_system_contract_checks_hierarchy_modules_and_interfaces(self):
        graph=self.system_contract();r=system.audit(self.root,'system.json','main.kicad_sch',graph,[{'id':'SPEC'}])
        self.assertEqual(r['status'],'CONTRACT_CHECKED_NOT_APPROVED');self.assertEqual(r['checked_nets'][0]['status'],'PASS')
    def test_system_contract_blocks_wrong_cross_module_endpoints(self):
        graph=self.system_contract();graph['nets']['DATA']=[('U1','1'),('U2','2')]
        r=system.audit(self.root,'system.json','main.kicad_sch',graph,[{'id':'SPEC'}])
        self.assertEqual(r['status'],'BLOCKED');self.assertIn('SYS.NET.TOPOLOGY',[f['rule'] for f in r['findings']])
    def test_system_contract_rejects_unassigned_component(self):
        graph=self.system_contract();graph['components']['R3']={}
        with self.assertRaisesRegex(ValueError,'cover all components'):system.audit(self.root,'system.json','main.kicad_sch',graph,[{'id':'SPEC'}])
    def test_system_contract_allows_one_module_without_cross_module_links(self):
        graph=self.system_contract();c=json.loads((self.root/'system.json').read_text());(self.root/'main.kicad_sch').write_text('(kicad_sch (lib_symbols) (symbol (lib_id "TEST:X") (property "Reference" "U1")) (symbol (lib_id "TEST:X") (property "Reference" "U2")))');c['modules']=[{'id':'whole','name':'Whole','role':'single module','sheet':'main.kicad_sch','components':['U1','U2']}];c['interfaces']=[];dump(self.root/'system.json',c)
        r=system.audit(self.root,'system.json','main.kicad_sch',graph,[{'id':'SPEC'}]);self.assertEqual(r['interface_count'],0)
    def draft(self):
        self.q={'schema_version':1,'design_basis':self.src,'top':'main.kicad_sch','project':'main.kicad_pro','files':{'main.kicad_sch':self.sch,'main.kicad_pro':'{}'},'expected':{'components':{'R1':{'value':'1k'}},'nets':{'SIG':[['R1','1']]}}}
        self.draftfile=self.root/'draft.json';dump(self.draftfile,self.q);return self.base/'candidate'
    def test_candidate_preview_does_not_write(self):
        out=self.draft();r=candidate.materialize(self.draftfile,out);self.assertEqual(r['status'],'PREVIEW');self.assertFalse(out.exists())
    def test_candidate_rejects_existing(self):
        out=self.draft();out.mkdir()
        with self.assertRaises(ValueError):candidate.materialize(self.draftfile,out)
    def test_candidate_path_escape(self):
        out=self.draft();self.q['files']['../escape.kicad_sch']=self.sch;dump(self.draftfile,self.q)
        with self.assertRaises(ValueError):candidate.materialize(self.draftfile,out)
        self.assertFalse(out.exists())
    def test_candidate_source_missing(self):
        out=self.draft();self.q['design_basis']['sha256']='bad';dump(self.draftfile,self.q)
        with self.assertRaises(ValueError):candidate.materialize(self.draftfile,out)
    def test_duplicate_expected_pin_blocks(self):
        out=self.draft();self.q['expected']['nets']['OTHER']=[['R1','1']];dump(self.draftfile,self.q)
        with self.assertRaises(ValueError):candidate.materialize(self.draftfile,out)
    def test_missing_native_writes_nothing(self):
        out=self.draft()
        with patch.object(candidate,'environment',return_value={}):
            with self.assertRaises(ValueError):candidate.materialize(self.draftfile,out,True)
        self.assertFalse(out.exists())
    def fake_native(self,argv):
        out=pathlib.Path(argv[argv.index('--output')+1]);kind=argv[2]
        if kind=='export':
            if argv[3]=='netlist':out.write_text('<export><components><comp ref="R1"><value>1k</value></comp></components><nets><net code="1" name="SIG"><node ref="R1" pin="1"/></net></nets></export>')
            else:out.write_bytes(b'%PDF-TEST DOUBLE ONLY')
        else:dump(out,{'$schema':'https://schemas.kicad.org/erc.v1.json','source':'main.kicad_sch','coordinate_units':'mm','kicad_version':'10.0.7','included_severities':['error','warning','exclusion'],'ignored_checks':[],'sheets':[{'path':'/','violations':[]}]})
        return {'returncode':0,'command':argv,'stdout':'TEST DOUBLE','stderr':''}
    def test_candidate_native_contract_double_not_approval(self):
        out=self.draft()
        with patch.object(candidate,'environment',return_value={'cli_exact_target':True,'kicad_cli':'TEST'}),patch.object(candidate,'run',side_effect=self.fake_native):r=candidate.materialize(self.draftfile,out,True)
        self.assertEqual(r['status'],'NATIVE_CANDIDATE_CHECKED_NOT_APPROVED');self.assertFalse(r['production_authorized'])
    def test_candidate_wrong_native_topology_stays_blocked(self):
        out=self.draft();self.q['expected']['nets']={'WRONG':[['R1','1']]};dump(self.draftfile,self.q)
        with patch.object(candidate,'environment',return_value={'cli_exact_target':True,'kicad_cli':'TEST'}),patch.object(candidate,'run',side_effect=self.fake_native):r=candidate.materialize(self.draftfile,out,True)
        self.assertEqual(r['status'],'BLOCKED');self.assertTrue((out/'candidate-result.json').exists())
    def contract(self):
        q=flow.template();q.update(project_id='TEST',revision='A',inputs={'schematic':'main.kicad_sch','project':'main.kicad_pro','board':'main.kicad_pcb'})
        q['requirements']=[{'id':'REQ1','requirement':'TEST target','acceptance':'TEST measurement','source':self.src,'stages':['prototype'],'verification':[{'kind':'external_test_plan','source':self.src}]}]
        for f in q['features'].values():f.update(applicability='not_applicable',reason='TEST scope only',source=self.src)
        for s in q['stages'].values():s.update(executor='combined',method='TEST method only',required_files=['spec.md'],verification_tools=[])
        dump(self.root/'project-flow.json',q);return q
    def test_flow_ready_is_not_engineering_approval(self):
        self.contract()
        with patch.object(flow,'registry',return_value={}):r=flow.check(self.root,'project-flow.json')
        self.assertEqual(r['status'],'DECLARED_CONTRACT_READY_NOT_APPROVED');self.assertFalse(r['production_authorized'])
    def test_requirement_missing_verification_blocks(self):
        q=self.contract();q['requirements'][0].pop('verification');dump(self.root/'project-flow.json',q)
        with patch.object(flow,'registry',return_value={}):self.assertEqual(flow.check(self.root,'project-flow.json')['status'],'BLOCKED')
    def test_legacy_tool_excluded_from_stage(self):
        q=self.contract();q['stages']['routing']['verification_tools']=['route_p2p'];dump(self.root/'project-flow.json',q)
        with patch.object(flow,'registry',return_value={}):self.assertEqual(flow.check(self.root,'project-flow.json')['status'],'BLOCKED')
    def test_legacy_dispatch_refused(self):
        with patch.object(flow,'registry',return_value={}):
            with self.assertRaises(ValueError):flow.dispatch('route_p2p',[])
    def test_future_stage_does_not_deadlock_preexport(self):
        q=self.contract();q['stages']['cam_release']['required_files']=['factory-confirmation.md'];dump(self.root/'project-flow.json',q)
        with patch.object(flow,'registry',return_value={}):
            self.assertEqual(flow.check(self.root,'project-flow.json','npi')['status'],'DECLARED_CONTRACT_READY_NOT_APPROVED');self.assertEqual(flow.check(self.root,'project-flow.json')['status'],'BLOCKED')
    def export_config(self):
        cfg={'workflow_contract':'project-flow.json','schematic_style':{'policy':'style.json'},'inputs':{'schematic':'main.kicad_sch','board':'main.kicad_pcb'},'variants':['default'],'bom_fields':{'ref':'Reference','mpn':'MPN'},'delivery_manifest':{'gerber':['gerber/a.gbr'],'drill':['drill/a.drl'],'cpl':['asm/cpl.csv'],'bom':['asm/bom.csv'],'assembly':['draw/asm.pdf']},'delivery_export':{'schema_version':1,'origin':'drill','variant':'default','gerber_layers':['F.Cu','B.Cu','F.Mask','B.Mask','Edge.Cuts'],'assembly_layers':['F.Fab','B.Fab','Edge.Cuts'],'bom_fields':['Reference','MPN','Value'],'gerber_dir':'gerber','drill_dir':'drill','position_file':'asm/cpl.csv','bom_file':'asm/bom.csv','assembly_file':'draw/asm.pdf'}}
        dump(self.root/'config.json',cfg);return cfg
    def test_export_typed_commands_and_consistent_origins(self):
        cfg=self.export_config();cmds=export.commands(self.root,cfg,self.base/'export','TEST');self.assertEqual(len(cmds),5);self.assertIn('--use-drill-file-origin',cmds[0]);self.assertIn('plot',cmds[1]);self.assertIn('--exclude-dnp',cmds[2]);self.assertIn('Reference',cmds[3]);self.assertNotIn('jobset',str(cmds))
    def test_export_missing_copper_blocks(self):
        cfg=self.export_config();cfg['delivery_export']['gerber_layers'].remove('B.Cu')
        with self.assertRaises(ValueError):export.commands(self.root,cfg,self.base/'export','TEST')
    def test_export_target_overlap_blocks(self):
        cfg=self.export_config();cfg['delivery_export']['bom_file']='gerber/bom.csv'
        with self.assertRaises(ValueError):export.commands(self.root,cfg,self.base/'export','TEST')
    def test_export_variant_mismatch_blocks(self):
        cfg=self.export_config();cfg['delivery_export']['variant']='other'
        with self.assertRaises(ValueError):export.commands(self.root,cfg,self.base/'export','TEST')
    def test_export_preview_no_writes(self):
        self.export_config();out=self.base/'export'
        with patch.object(export,'environment',return_value={}):r=export.export(self.root,self.root/'config.json',out)
        self.assertEqual(r['status'],'PREVIEW');self.assertFalse(out.exists())
    def test_preexport_block_executes_no_production_command(self):
        self.export_config();out=self.base/'export'
        with patch.object(export,'environment',return_value={'cli_exact_target':True,'pcbnew_exact_target':True,'kicad_cli':'TEST'}),patch.object(export,'evaluate',return_value={'blocked':True,'findings':[{'TEST':'block'}]}),patch.object(export,'run') as runner:r=export.export(self.root,self.root/'config.json',out,True)
        self.assertEqual(r['status'],'BLOCKED');runner.assert_not_called();self.assertFalse(out.exists())
    def test_style_packet_captures_policy_and_result(self):
        from test_static_review import fixture
        from static_review import prepare
        project=self.base/'packet-project';cfg=fixture(project);dump(project/'style.json',{'schema_version':1,'pages':{},'source':{'file':'source.md','sha256':sha256(project/'source.md'),'locator':'§1'}})
        cfg['schematic_style']={'policy':'style.json'};cfg['require_schematic_style']=True
        cfg['stages']['schematic']['tasks'].append({'id':'style','category':'schematic_style','level':'阻断级','requirement':'TEST structure','strength':'mandatory','targets':{'refs':['U1'],'nets':['FB'],'layers':[]},'source_refs':[{'document_id':'TEST','locator':'§1'}],'check':{'kind':'semantic'}})
        dump(project/'review-config.json',cfg);out=self.base/'packet';prepare(project,project/'review-config.json','schematic',out)
        packet=json.loads((out/'packet.json').read_text());self.assertIn('style.json',packet['baseline']);self.assertIn('schematic-style.json',packet['artifacts_sha256'])
    def frozen(self):
        dump(self.root/'freeze-log.json',{'operations':['copy','refill','save','reload'],'candidate_sha256':sha256(self.root/'main.kicad_pcb')})
    def fake_export(self,argv):
        p=pathlib.Path(argv[argv.index('--output')+1]);kind=argv[3]
        if kind in ('gerbers','drill'):p.mkdir(parents=True,exist_ok=True);p=p/('a.gbr' if kind=='gerbers' else 'a.drl')
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text('TEST DOUBLE OUTPUT, NOT MANUFACTURABLE')
        return {'returncode':0,'command':argv,'stdout':'TEST DOUBLE','stderr':''}
    def test_export_positive_double_never_releases(self):
        self.export_config();self.frozen();out=self.base/'export'
        with patch.object(export,'environment',return_value={'cli_exact_target':True,'pcbnew_exact_target':True,'kicad_cli':'TEST'}),patch.object(export,'evaluate',return_value={'blocked':False,'inputs_sha256':{}}),patch.object(export,'run',side_effect=self.fake_export):r=export.export(self.root,self.root/'config.json',out,True)
        self.assertEqual(r['status'],'EXPORTED_NOT_RELEASED');self.assertFalse(r['production_authorized']);self.assertTrue((out/'gerber/a.gbr').is_file())
    def test_export_failure_removes_partial_manufacturing_files(self):
        self.export_config();self.frozen();out=self.base/'export';calls=[]
        def failed(argv):
            calls.append(argv);r=self.fake_export(argv)
            if len(calls)==2:r['returncode']=1
            return r
        with patch.object(export,'environment',return_value={'cli_exact_target':True,'pcbnew_exact_target':True,'kicad_cli':'TEST'}),patch.object(export,'evaluate',return_value={'blocked':False,'inputs_sha256':{}}),patch.object(export,'run',side_effect=failed):r=export.export(self.root,self.root/'config.json',out,True)
        self.assertEqual(r['status'],'BLOCKED');self.assertEqual([p.name for p in out.iterdir()],['export-result.json'])
    def test_export_changed_source_invalidates(self):
        self.export_config();self.frozen();out=self.base/'export'
        def mutate(argv):
            r=self.fake_export(argv);(self.root/'spec.md').write_text('changed during export');return r
        with patch.object(export,'environment',return_value={'cli_exact_target':True,'pcbnew_exact_target':True,'kicad_cli':'TEST'}),patch.object(export,'evaluate',return_value={'blocked':False,'inputs_sha256':{}}),patch.object(export,'run',side_effect=mutate):r=export.export(self.root,self.root/'config.json',out,True)
        self.assertEqual(r['status'],'BLOCKED');self.assertFalse((out/'gerber').exists())
    def test_export_stale_freeze_executes_nothing(self):
        self.export_config();self.frozen();(self.root/'main.kicad_pcb').write_text((self.root/'main.kicad_pcb').read_text()+' ')
        with patch.object(export,'environment',return_value={'cli_exact_target':True,'pcbnew_exact_target':True,'kicad_cli':'TEST'}),patch.object(export,'evaluate',return_value={'blocked':False,'inputs_sha256':{}}),patch.object(export,'run') as runner:
            with self.assertRaises(ValueError):export.export(self.root,self.root/'config.json',self.base/'export',True)
            runner.assert_not_called()
    def test_task_requirement_mapping_unknown_blocks(self):
        q=self.contract();q['requirements'][0]['verification']=[{'kind':'static_task','config':'tasks.json','stage':'schematic','task_id':'unknown'}];dump(self.root/'tasks.json',{'stages':{'schematic':{'tasks':[]}}});dump(self.root/'project-flow.json',q)
        with patch.object(flow,'registry',return_value={}):self.assertEqual(flow.check(self.root,'project-flow.json')['status'],'BLOCKED')
    def test_export_apply_requires_r9_contract(self):
        cfg=self.export_config();cfg.pop('workflow_contract');dump(self.root/'config.json',cfg)
        with patch.object(export,'environment',return_value={'cli_exact_target':True,'pcbnew_exact_target':True,'kicad_cli':'TEST'}),patch.object(export,'run') as runner:
            with self.assertRaisesRegex(ValueError,'R9 export requires'):export.export(self.root,self.root/'config.json',self.base/'export',True)
            runner.assert_not_called()
    def test_npi_missing_workflow_contract_is_a_blocker(self):
        import shutil
        from mass_production_review import evaluate
        project=self.base/'npi';shutil.copytree(pathlib.Path(__file__).resolve().parents[1]/'fixtures/npi-demo',project)
        cfg=json.loads((project/'review-config.json').read_text());cfg['workflow_contract']='missing-project-flow.json';dump(project/'review-config.json',cfg)
        r=evaluate(project,project/'review-config.json','mass_production','pre_export',static_preview=True)
        self.assertTrue(any(f['rule']=='FLOW.NPI' for f in r['findings']));self.assertFalse(r['release_allowed'])
    def test_style_template_requires_semantic_task(self):
        from static_review import validate_config
        cfg={'schema_version':1,'require_schematic_style':True,'schematic_style':{'policy':'style.json'},'stages':{'schematic':{'tasks':[]}}}
        with self.assertRaisesRegex(ValueError,'style policy'):validate_config(cfg,'schematic')

if __name__=='__main__':unittest.main()
