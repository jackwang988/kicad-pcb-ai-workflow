import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow';sys.path.insert(0,str(ROOT/'scripts'))
from npi_common import sha256
from static_review import prepare,CATEGORIES,DYNAMIC,write_json,evaluate_rule
from static_review_gate import validate
from design_intent import digest

QUOTE='The feedback voltage must remain between 0.90 V and 1.10 V.'

def fixture(root):
    root.mkdir(exist_ok=True)
    (root/'source.md').write_text('# TEST ONLY — not a real device datasheet\n\n§1\n'+QUOTE+'\nThe synthetic device has no reset, boot or clock pins.\nThis software fixture does not specify EMC, thermal or reliability performance.\n')
    (root/'test.kicad_sch').write_text('(kicad_sch (version 20260101) (generator "eeschema") (uuid "11111111-1111-4111-8111-111111111111") (paper "A4") (lib_symbols) (symbol (lib_id "TEST:X") (property "Reference" "U1")) (symbol (lib_id "TEST:X") (property "Reference" "R1")) (symbol (lib_id "TEST:X") (property "Reference" "R2")))')
    (root/'test.kicad_pro').write_text(json.dumps({'net_settings':{},'erc':{}}))
    xml='''<export><components>
<comp ref="U1"><value>TEST_IC</value><footprint>TEST</footprint><fields><field name="MPN">TEST_ONLY</field></fields></comp>
<comp ref="R1"><value>40k</value><footprint>TEST</footprint></comp>
<comp ref="R2"><value>10k</value><footprint>TEST</footprint></comp>
</components><nets>
<net code="1" name="VIN"><node ref="R1" pin="1"/><node ref="U1" pin="2"/></net>
<net code="2" name="FB"><node ref="R1" pin="2"/><node ref="R2" pin="1"/><node ref="U1" pin="1"/></net>
<net code="3" name="GND"><node ref="R2" pin="2"/><node ref="U1" pin="3"/></net>
</nets></export>'''
    (root/'provided.xml').write_text(xml)
    board='''(kicad_pcb (version 20260101) (generator "pcbnew") (general (thickness 1.6))
    (layers (0 "F.Cu" signal) (2 "B.Cu" signal)) (setup (stackup (layer "F.Cu" (thickness 0.035)) (layer "B.Cu" (thickness 0.035))))
    (net 0 "") (net 1 "VIN") (net 2 "FB") (net 3 "GND")
    (segment (start 0 0) (end 10 0) (width 0.25) (layer "F.Cu") (net 2) (uuid "22222222-2222-4222-8222-222222222222"))
    (footprint "TEST" (layer "F.Cu") (at 10 10) (property "Reference" "U1") (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 2 "FB")))
    )'''
    (root/'test.kicad_pcb').write_text(board)
    config={'schema_version':1,'demonstration_only':False,'require_system_integration':True,'system_integration':{'contract':'system-integration.json'},'documents':[{'id':'TEST','file':'source.md','sha256':sha256(root/'source.md'),
        'title':'Synthetic test-only source','revision':'0','issuer':'TEST','authority':'datasheet','applicability':'Software test device only','approved_by':'TEST'}],'stages':{}}
    for stage,categories in CATEGORIES.items():
        tasks=[]
        for cat in categories:
            tasks.append({'id':stage+'.'+cat,'category':cat,'level':'阻断级','requirement':'核对测试电路的'+cat,
                          'strength':'mandatory','targets':{'refs':['U1'],'nets':['FB'],'layers':[]},
                          'source_refs':[{'document_id':'TEST','locator':'§1'}],'check':{'kind':'semantic'}})
        if stage=='schematic':
            tasks[0]['check']={'kind':'pin_net','pin':{'ref':'U1','pin':'1'},'net':'FB'}
            tasks[2]['check']={'kind':'resistor_divider','upper_ref':'R1','lower_ref':'R2','upper_pins':['1','2'],'lower_pins':['1','2'],
                'supply_net':'VIN','output_net':'FB','ground_net':'GND','upper_tolerance':.01,'lower_tolerance':.01,
                'input_min_v':4.9,'input_max_v':5.1,'output_min_v':.9,'output_max_v':1.1}
        else:tasks[2]['check']={'kind':'track_geometry','net':'FB','allowed_layers':['F.Cu'],'min_width_mm':.2,'max_width_mm':.3}
        config['stages'][stage]={'inputs':{'schematic':'test.kicad_sch','project':'test.kicad_pro','board':'test.kicad_pcb','provided_netlist':'provided.xml'},
                                 'critical_nets':['VIN','FB'],'component_sources':{r:['TEST'] for r in ('U1','R1','R2')},'support_files':[],'tasks':tasks}
    (root/'overview.svg').write_text('<svg>TEST ONLY architecture overview</svg>')
    write_json(root/'system-integration.json',{'schema_version':1,'project_id':'TEST','revision':'1',
        'overview':{'sheet':'test.kicad_sch','file':'overview.svg','sha256':sha256(root/'overview.svg'),'source':{'document_id':'TEST','locator':'§1'}},
        'modules':[{'id':'whole','name':'Whole test circuit','role':'single module','sheet':'test.kicad_sch','components':['U1','R1','R2']}],
        'interfaces':[],'system_checks':[{'id':'test_function','method':'semantic','acceptance':'TEST only functional requirement','source':{'document_id':'TEST','locator':'§1'}}]})
    write_json(root/'review-config.json',config);(root/'engineer-note.txt').write_text('TEST ONLY: not an actual engineer approval')
    return config

def fake_native(root):
    def execute(argv,**kwargs):
        out=Path(argv[argv.index('--output')+1]);out.parent.mkdir(parents=True,exist_ok=True)
        if argv[1:4]==['sch','export','netlist']:out.write_bytes((root/'provided.xml').read_bytes())
        elif argv[1:4]==['sch','export','pdf']:out.write_bytes(b'%PDF-TEST-ONLY')
        elif argv[1:3]==['sch','erc']:
            write_json(out,{'$schema':'https://schemas.kicad.org/erc.v1.json','kicad_version':'10.0.7','coordinate_units':'mm',
                     'source':'test.kicad_sch','included_severities':['error','warning','exclusion'],'ignored_checks':[],
                     'sheets':[{'path':'/','violations':[]}]})
        else:return {'command':argv,'returncode':1,'stdout':'','stderr':'Unsupported TEST tool operation'}
        return {'command':argv,'returncode':0,'stdout':'TEST ONLY','stderr':''}
    return execute

class StaticReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'source';self.cfg=fixture(self.root);self.out=self.base/'packet'
    def tearDown(self):self.tmp.cleanup()
    def test_system_integration_is_captured_in_review_packet(self):
        self.build();packet=json.loads((self.out/'packet.json').read_text());report=json.loads((self.out/'system-integration.json').read_text())
        self.assertTrue(packet['config']['require_system_integration']);self.assertEqual(report['status'],'CONTRACT_CHECKED_NOT_APPROVED')
        self.assertIn('system-integration.json',packet['artifacts_sha256']);self.assertTrue(packet['native_ready'])
    def test_system_contract_change_invalidates_schematic_gate(self):
        self.build();ai=self.ai();eng=self.engineer(ai)
        contract=json.loads((self.root/'system-integration.json').read_text());contract['revision']='2';write_json(self.root/'system-integration.json',contract)
        result=validate(self.root,self.out,ai,eng)
        self.assertEqual(result['status'],'BLOCKED')
    def test_system_review_must_observe_architecture_overview(self):
        self.build();ai=self.ai();data=json.loads(ai.read_text());task=next(t for t in self.cfg['stages']['schematic']['tasks'] if t['category']=='system_integration');row=next(r for r in data['items'] if r['task_id']==task['id']);row['observations']=[o for o in row['observations'] if 'view' not in o];write_json(ai,data)
        self.assertEqual(validate(self.root,self.out,ai,self.engineer(ai))['status'],'BLOCKED')
    def build(self,native=True,stage='schematic'):
        env={'cli_exact_target':native,'pcbnew_exact_target':False,'kicad_cli':'/TEST/kicad-cli'}
        with patch('static_review.environment',return_value=env),patch('static_review.run',side_effect=fake_native(self.root)):
            return prepare(self.root,self.root/'review-config.json',stage,self.out)
    def ai(self):
        ai=json.loads((self.out/'ai-review.template.json').read_text());ai['reviewer']={'type':'ai','model':'TEST_NOT_A_REAL_REVIEW','date':'2026-10-17'}
        facts=json.loads((self.out/'facts.json').read_text());ai['coverage']={'components':list(facts['netlist']['components']),'critical_nets':['VIN','FB'],'layers':(facts.get('board') or {}).get('copper_layers',[])}
        for row in ai['items']:
            row.update(status='PASS',applicability='Synthetic TEST mode only',reasoning='TEST ONLY: inspected declared facts against the synthetic source',verification='TEST comparison',observations=[{'ref':'U1','pin':'1','net':'FB'}],source_citations=[{'document_id':'TEST','locator':'§1','quote':QUOTE}])
            task=next(t for t in self.cfg['stages']['schematic']['tasks'] if t['id']==row['task_id'])
            if task['category']=='system_integration':
                report=json.loads((self.out/'system-integration.json').read_text())
                row['observations'] += [{'ref':ref} for refs in report['module_components'].values() for ref in refs]
                row['observations'] += [{'net':n['net']} for n in report['checked_nets']]
                row['observations'] += [{'view':v['file'],'detail':'TEST DOUBLE architecture/schematic view'} for v in json.loads((self.out/'packet.json').read_text())['views'] if v.get('kind') in ('system_architecture_overview','schematic')]
        ai['items'][0]['observations'] += [{'ref':'R1'},{'ref':'R2'},{'net':'VIN'}]
        for view in json.loads((self.out/'packet.json').read_text())['views']:
            ai['items'][0]['observations'].append({'view':view['file'],'detail':'TEST DOUBLE: not an actual visual inspection',**({'layer':view['layer']} if 'layer' in view else {})})
        p=self.base/'ai.json';write_json(p,ai);return p
    def engineer(self,ai):
        eng=json.loads((self.out/'engineer-review.template.json').read_text());eng.update(name='TEST_NOT_AN_ENGINEER',date='2026-10-17',decision='approve',reason='TEST ONLY',ai_review_sha256=sha256(ai),evidence=[{'file':'engineer-note.txt','sha256':sha256(self.root/'engineer-note.txt')}])
        p=self.base/'engineer.json';write_json(p,eng);return p
    def test_prepare_does_not_modify_design_and_never_fills_approval(self):
        before={p.name:sha256(p) for p in self.root.iterdir()};r=self.build()
        self.assertTrue(r['native_ready']);self.assertEqual(before,{p.name:sha256(p) for p in self.root.iterdir()})
        self.assertIsNone(json.loads((self.out/'engineer-review.template.json').read_text())['name'])
        self.assertTrue(all(x['status']=='NEEDS_EVIDENCE' for x in json.loads((self.out/'ai-review.template.json').read_text())['items']))
    def test_ai_report_requires_engineer_confirmation(self):
        self.build();ai=self.ai();r=validate(self.root,self.out,ai)
        self.assertEqual(r['status'],'ENGINEER_REVIEW_PENDING');self.assertFalse(r['production_authorized'])
    def test_test_double_complete_contract_not_production_approval(self):
        self.build();ai=self.ai();eng=self.engineer(ai);r=validate(self.root,self.out,ai,eng)
        self.assertEqual(r['findings'],[]);self.assertEqual(r['status'],'APPROVED_STATIC');self.assertFalse(r['production_authorized'])
    def test_missing_ai_is_pending_not_pass(self):
        self.build();self.assertEqual(validate(self.root,self.out)['status'],'AI_REVIEW_PENDING')
    def test_logic_error_divider_detected_without_connectivity_change(self):
        p=self.root/'provided.xml';p.write_text(p.read_text().replace('<value>40k</value>','<value>10k</value>'))
        r=self.build();failure=[c for c in r['checks'] if c['status']=='FAIL'];self.assertEqual(len(failure),1)
        self.assertGreater(failure[0]['detail']['output_min_v'],2)
    def test_ai_cannot_override_failed_divider(self):
        p=self.root/'provided.xml';p.write_text(p.read_text().replace('<value>40k</value>','<value>10k</value>'));self.build();ai=self.ai();eng=self.engineer(ai)
        r=validate(self.root,self.out,ai,eng);self.assertEqual(r['status'],'BLOCKED');self.assertTrue(any('override' in f['description'] for f in r['findings']))
    def test_fabricated_source_quote_blocks(self):
        self.build();ai=self.ai();d=json.loads(ai.read_text());d['items'][0]['source_citations'][0]['quote']='THIS SENTENCE DOES NOT EXIST';write_json(ai,d)
        r=validate(self.root,self.out,ai,self.engineer(ai));self.assertEqual(r['status'],'BLOCKED')
    def test_unknown_observed_connection_blocks(self):
        self.build();ai=self.ai();d=json.loads(ai.read_text());d['items'][0]['observations'][0]['net']='GND';write_json(ai,d)
        r=validate(self.root,self.out,ai,self.engineer(ai));self.assertEqual(r['status'],'BLOCKED')
    def test_missing_coverage_category_and_unknown_task_rejected(self):
        self.cfg['stages']['schematic']['tasks'].pop();write_json(self.root/'review-config.json',self.cfg)
        with self.assertRaisesRegex(ValueError,'categories'):self.build()
    def test_missing_component_coverage_blocks(self):
        self.build();ai=self.ai();d=json.loads(ai.read_text());d['coverage']['components'].remove('R2');write_json(ai,d)
        r=validate(self.root,self.out,ai,self.engineer(ai));self.assertEqual(r['status'],'BLOCKED')
    def test_source_change_invalidates_review(self):
        self.build();ai=self.ai();eng=self.engineer(ai);p=self.root/'source.md';p.write_text(p.read_text()+' changed')
        r=validate(self.root,self.out,ai,eng);self.assertEqual(r['status'],'BLOCKED')
    def test_schematic_change_invalidates_review(self):
        self.build();ai=self.ai();eng=self.engineer(ai);p=self.root/'test.kicad_sch';p.write_text(p.read_text()+'\n')
        r=validate(self.root,self.out,ai,eng);self.assertEqual(r['status'],'BLOCKED')
    def test_pcb_only_change_does_not_invalidate_schematic_stage(self):
        self.build();ai=self.ai();eng=self.engineer(ai);p=self.root/'test.kicad_pro';d=json.loads(p.read_text());d['board']={'design_settings':{'rules':{'min_track_width':.2}}};write_json(p,d)
        (self.root/'test.kicad_pcb').write_text('PCB CHANGED ONLY')
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'APPROVED_STATIC')
    def test_network_rule_change_invalidates_schematic_stage(self):
        self.build();ai=self.ai();eng=self.engineer(ai);p=self.root/'test.kicad_pro';d=json.loads(p.read_text());d['net_settings']['classes']=[{'name':'NEW'}];write_json(p,d)
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'BLOCKED')
    def test_ai_change_invalidates_old_engineer_signature(self):
        self.build();ai=self.ai();eng=self.engineer(ai);d=json.loads(ai.read_text());d['items'][0]['reasoning']='NEW TEST explanation';write_json(ai,d)
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'BLOCKED')
    def test_cannot_downgrade_or_claim_dynamic_tests(self):
        self.build();ai=self.ai();d=json.loads(ai.read_text());d['items'][0]['level']='优化建议';write_json(ai,d)
        self.assertEqual(validate(self.root,self.out,ai,self.engineer(ai))['status'],'BLOCKED')
        ai=self.ai();d=json.loads(ai.read_text());d['deferred_dynamic_tests']=[];write_json(ai,d)
        self.assertEqual(validate(self.root,self.out,ai,self.engineer(ai))['status'],'BLOCKED')
    def test_stale_packet_artifact_and_removed_inventory_block(self):
        self.build();ai=self.ai();eng=self.engineer(ai);p=self.out/'facts.json';p.write_text('{}')
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'BLOCKED')
    def test_static_import_cannot_be_promoted_by_signoff(self):
        self.build(False);ai=self.ai();r=validate(self.root,self.out,ai,self.engineer(ai))
        self.assertEqual(r['status'],'BLOCKED');self.assertTrue(any(f['rule']=='STATIC.PROVENANCE' for f in r['findings']))
    def test_blocker_is_primary_status_even_while_engineer_is_pending(self):
        self.build(False);ai=self.ai();r=validate(self.root,self.out,ai)
        self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['review_state'],'engineer_pending')
    def test_pcb_actual_track_geometry_failure_detected(self):
        p=self.root/'test.kicad_pcb';p.write_text(p.read_text().replace('(width 0.25)','(width 0.1)'));r=self.build(False,'pcb')
        self.assertTrue(any(c['status']=='FAIL' and c['task_id']=='pcb.critical_signal_paths' for c in r['checks']))
    def test_invalid_numeric_predicate_blocks_instead_of_pass(self):
        self.build();facts=json.loads((self.out/'facts.json').read_text());t=copy.deepcopy(self.cfg['stages']['schematic']['tasks'][2]);t['check']['input_max_v']=float('nan')
        self.assertEqual(evaluate_rule(t,facts)['status'],'BLOCKED')
    def test_packet_output_never_overwrites(self):
        self.build()
        with self.assertRaises(ValueError):self.build()
    def test_unreviewed_visual_evidence_cannot_pass(self):
        self.build();ai=self.ai();d=json.loads(ai.read_text());
        for row in d['items']:row['observations']=[o for o in row['observations'] if 'view' not in o]
        write_json(ai,d)
        self.assertEqual(validate(self.root,self.out,ai,self.engineer(ai))['status'],'BLOCKED')
    def test_task_target_must_be_identified(self):
        self.cfg['stages']['schematic']['tasks'][1]['targets']['refs'].append('U9');write_json(self.root/'review-config.json',self.cfg)
        self.build();ai=self.ai();self.assertEqual(validate(self.root,self.out,ai,self.engineer(ai))['status'],'BLOCKED')
    def test_na_requires_item_specific_hardware_decision(self):
        self.build();ai=self.ai();d=json.loads(ai.read_text());row=d['items'][3];row['status']='NOT_APPLICABLE';write_json(ai,d)
        eng=self.engineer(ai);self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'BLOCKED')
        e=json.loads(eng.read_text());e['dispositions'][row['task_id']]={'action':'not_applicable','reason':'TEST absent function','item_sha256':digest(row)};write_json(eng,e)
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'APPROVED_STATIC')
    def test_blocking_failure_cannot_be_waived_by_hardware_signature(self):
        p=self.root/'provided.xml';p.write_text(p.read_text().replace('<value>40k</value>','<value>10k</value>'));self.build();ai=self.ai()
        d=json.loads(ai.read_text());row=d['items'][2];row.update(status='FAIL',fix='TEST restore resistor');write_json(ai,d);eng=self.engineer(ai)
        e=json.loads(eng.read_text());e['dispositions'][row['task_id']]={'action':'accept_deviation','reason':'TEST waiver','item_sha256':digest(row)};write_json(eng,e)
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'BLOCKED')
    def test_nonblocking_additional_issue_needs_specific_disposition(self):
        self.build();ai=self.ai();d=json.loads(ai.read_text());extra={'id':'EXTRA1','level':'中风险','reasoning':'TEST extra issue','fix':'TEST fix','verification':'TEST verify',
            'observations':[{'ref':'U1'}],'source_citations':[{'document_id':'TEST','locator':'§1','quote':QUOTE}]};d['additional_findings'].append(extra);write_json(ai,d);eng=self.engineer(ai)
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'BLOCKED')
        e=json.loads(eng.read_text());e['dispositions']['EXTRA1']={'action':'accept_deviation','reason':'TEST acceptance','item_sha256':digest({**extra,'task_id':'EXTRA1','status':'FAIL'})};write_json(eng,e)
        self.assertEqual(validate(self.root,self.out,ai,eng)['status'],'APPROVED_STATIC')

if __name__=='__main__':unittest.main()
