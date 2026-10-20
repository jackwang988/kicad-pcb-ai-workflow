import copy,csv,json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow/scripts'))
import reserve_review as rr
from npi_common import sha256

class ReserveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.policy=self.root/'reserve.json';self.ev=self.root/'test-only.txt';self.ev.write_text('TEST ONLY synthetic evidence, no real engineer approval')
        self.brd=self.root/'board.kicad_pcb';self.brd.write_text('TEST ONLY')
        self.e={'file':self.ev.name,'sha256':sha256(self.ev)}
        self.graph={'components':{'R1':{'value':'0R','fields':{'DNP':'no','MPN':'TEST0'}},'R2':{'value':'0R','fields':{'DNP':'yes'}}},'nets':{'A':[['R1','1'],['R2','1']],'B':[['R1','2']],'C':[['R2','2']]}}
        self.board={'footprints':[{'ref':'R1'},{'ref':'R2'}]}
        row=dict(id='source',block='TEST SOURCE',uncertainty='TEST choice',decision='reserve',required=False,reason='TEST',verification_plan='TEST verify both modes',context='low_speed',role='selection_link',refs=['R1','R2'],nets=['A','B','C'],source={**self.e,'locator':'TEST §1'},cost=dict(area_mm2=2,material_delta=.1,currency='TEST',assembly_risk='TEST',signal_risk='TEST',benefit_reason='TEST'),safety_evidence=[self.e],zero_ohm=dict(allowed=True,reason='TEST',evidence=[self.e]),layout_review=dict(reason='TEST',reviewer='TEST_NOT_REAL',date='2026-10-17',board_sha256=sha256(self.brd),evidence=[self.e],sensitive_path_checked=True),production=dict(action='retain',reason='TEST',evidence=[self.e]))
        a={'R1':dict(fitted=True,value='0R',mpn='TEST0'),'R2':dict(fitted=False,value='0R',mpn='TEST0')};b=copy.deepcopy(a);b['R1']['fitted']=False;b['R2']['fitted']=True
        self.q=dict(schema_version=1,default_variant='A',scope_reason='TEST ONLY',decisions=[row],variants=[dict(name='A',parts=a),dict(name='B',parts=b)],groups=[dict(id='pick-one',reason='TEST mutually exclusive',members=['R1','R2'],min_fitted=1,max_fitted=1)])
    def tearDown(self):self.tmp.cleanup()
    def run_audit(self,stage='schematic',**kw):
        self.policy.write_text(json.dumps(self.q));return rr.audit(self.root,self.policy,self.graph,stage,self.board,self.brd,**kw)
    def has(self,r,code):return any(f['rule']==code for f in r['findings'])
    def test_valid_declared_scope_not_production(self):
        r=self.run_audit();self.assertEqual(r['status'],'STATIC_CHECKS_COMPLETE');self.assertFalse(r['production_authorized'])
    def test_no_reserve_with_reason_passes(self):
        row=self.q['decisions'][0];row['decision']='no_reserve';row['refs']=[];self.q['variants']=[dict(name='A',parts={})];self.q['groups']=[]
        self.assertEqual(self.run_audit()['status'],'STATIC_CHECKS_COMPLETE')
    def test_no_reserve_removed_ref_still_present(self):
        row=self.q['decisions'][0];row.update(decision='no_reserve',refs=[],absent_refs=['R2']);self.q['variants']=[dict(name='A',parts={})];self.q['groups']=[]
        self.assertTrue(self.has(self.run_audit(),'RESERVE.ABSENT'))
    def test_required_missing_blocks(self):
        row=self.q['decisions'][0];row.update(decision='no_reserve',refs=[],required=True);self.q['variants']=[dict(name='A',parts={})];self.q['groups']=[]
        self.assertTrue(self.has(self.run_audit(),'RESERVE.REQUIRED'))
    def test_mutually_exclusive_both_populated(self):
        self.q['variants'][1]['parts']['R1']['fitted']=True;self.assertTrue(self.has(self.run_audit(),'RESERVE.MUTEX'))
    def test_required_selection_neither_populated(self):
        self.q['variants'][1]['parts']['R2']['fitted']=False;self.assertTrue(self.has(self.run_audit(),'RESERVE.MUTEX'))
    def test_no_group_for_alternatives(self):
        self.q['groups']=[];self.assertTrue(self.has(self.run_audit(),'RESERVE.MUTEX.MISSING'))
    def test_dnp_differs_from_schematic(self):
        self.graph['components']['R2']['fields']['DNP']='no';self.assertTrue(self.has(self.run_audit(),'RESERVE.DEFAULT'))
    def test_nc_not_accepted_as_dnp(self):
        self.graph['components']['R2']['fields']['DNP']='NC';self.assertTrue(self.has(self.run_audit(),'RESERVE.DEFAULT'))
    def test_unknown_value_is_not_zero_placeholder(self):
        self.graph['components']['R1']['value']='10k';self.assertTrue(self.has(self.run_audit(),'RESERVE.DEFAULT'))
    def test_zero_requires_evidence(self):
        self.q['decisions'][0]['zero_ohm']['evidence']=[];self.assertTrue(self.has(self.run_audit(),'RESERVE.ZERO'))
    def test_zero_r0_spelling(self):
        self.q['variants'][0]['parts']['R1']['value']='0R0';self.graph['components']['R1']['value']='0R0';self.q['decisions'][0]['zero_ohm']['evidence']=[];self.assertTrue(self.has(self.run_audit(),'RESERVE.ZERO'))
    def test_power_current(self):
        row=self.q['decisions'][0];row['context']='power';row['zero_ohm'].update(required_current_a=3,approved_current_a=1)
        self.assertTrue(self.has(self.run_audit(),'RESERVE.CURRENT'))
    def test_stale_layout(self):
        self.brd.write_text('CHANGED');self.assertTrue(self.has(self.run_audit('pcb'),'RESERVE.LAYOUT.STALE'))
    def test_sensitive_path_unreviewed(self):
        row=self.q['decisions'][0];row['context']='high_speed';row['layout_review']['sensitive_path_checked']=False
        self.assertTrue(self.has(self.run_audit('pcb'),'RESERVE.SENSITIVE'))
    def test_missing_reserved_footprint(self):
        self.board['footprints'].pop();self.assertTrue(self.has(self.run_audit('pcb'),'RESERVE.FOOTPRINT'))
    def test_changed_evidence(self):
        self.ev.write_text('CHANGED');self.assertEqual(self.run_audit()['status'],'BLOCKED')
    def test_invalid_cost(self):
        self.q['decisions'][0]['cost']['area_mm2']=-1;self.assertEqual(self.run_audit()['status'],'BLOCKED')
    def test_matrix_coverage(self):
        self.q['variants'][1]['parts'].pop('R2');self.assertEqual(self.run_audit()['status'],'BLOCKED')
    def production(self):
        bom=self.root/'bom.csv';cpl=self.root/'cpl.csv';fields=['Reference','MPN','Manufacturer','Footprint','Specification','Variant','DNP','Supplier','ApprovedAlternatives']
        with bom.open('w') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for ref,dnp in [('R1','no'),('R2','yes')]:w.writerow(dict(Reference=ref,MPN='TEST0',Manufacturer='TEST',Footprint='TEST',Specification='0R',Variant='A',DNP=dnp,Supplier='TEST',ApprovedAlternatives='NONE'))
        cpl.write_text('Reference,PosX,PosY,Rotation,Side\nR1,0,0,0,Top\n');return bom,cpl
    def test_npi_matrix_matches_bom_cpl(self):
        b,c=self.production();self.assertEqual(self.run_audit('npi',bom=b,cpl=c,variant='A')['status'],'STATIC_CHECKS_COMPLETE')
    def test_npi_dnp_in_cpl(self):
        b,c=self.production();c.write_text(c.read_text()+'R2,1,1,0,Top\n');self.assertEqual(self.run_audit('npi',bom=b,cpl=c,variant='A')['status'],'BLOCKED')
    def test_npi_wrong_bom_value(self):
        b,c=self.production();b.write_text(b.read_text().replace('0R','10k'));self.assertTrue(self.has(self.run_audit('npi',bom=b,cpl=c,variant='A'),'RESERVE.BOM'))
    def test_npi_pending_disposition(self):
        b,c=self.production();self.q['decisions'][0]['production']['action']='pending';self.assertTrue(self.has(self.run_audit('npi',bom=b,cpl=c,variant='A'),'RESERVE.PRODUCTION'))
    def test_npi_integration_declared_scope_with_test_double(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        self.policy.write_text(json.dumps(self.q));folder=self.root/'review';folder.mkdir()
        for n in ('ai.json','hw.json'):(folder/n).write_text('TEST DOUBLE ONLY')
        (folder/'packet.json').write_text(json.dumps({'config':{'reserve_review':{'policy':'reserve.json'},'stages':{'pcb':{'inputs':{'board':self.brd.name},'variant':'A'}}}}))
        (folder/'facts.json').write_text(json.dumps({'netlist':self.graph,'board':self.board}))
        (self.root/'profile.json').write_text(json.dumps({'assembly_variant':'A'}));b,c=self.production()
        r=SimpleNamespace(phase='release',risk=lambda *a,**k:self.calls.append(a),inputs={},evidence=[]);self.calls=[]
        cfg={'reserve_review':{'policy':'reserve.json','variant':'A'},'engineering_profile':'profile.json','delivery_manifest':{'bom':['bom.csv'],'cpl':['cpl.csv']},'static_ai_reviews':{'pcb':{'packet':'review','ai_review':'review/ai.json','engineer_review':'review/hw.json'}}}
        with patch('static_review_gate.validate',return_value={'status':'APPROVED_STATIC'}):rr.integrate(r,self.root,cfg,candidate=self.root,board_file=self.brd)
        self.assertEqual(self.calls,[]);self.assertFalse(r.evidence[0]['reserve_review']['production_authorized'])
    def test_npi_cannot_switch_to_unreviewed_policy(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        folder=self.root/'review';folder.mkdir();(folder/'ai.json').write_text('{}');(folder/'hw.json').write_text('{}')
        (folder/'packet.json').write_text(json.dumps({'config':{'reserve_review':{'policy':'approved.json'}}}))
        r=SimpleNamespace(phase='release',risk=lambda *a,**k:self.calls.append(a),inputs={},evidence=[]);self.calls=[]
        cfg={'reserve_review':{'policy':'different.json'},'static_ai_reviews':{'pcb':{'packet':'review','ai_review':'review/ai.json','engineer_review':'review/hw.json'}}}
        with patch('static_review_gate.validate',return_value={'status':'APPROVED_STATIC'}):rr.integrate(r,self.root,cfg,board_file=self.brd)
        self.assertTrue(any('differs' in str(c) for c in self.calls))
    def test_npi_cannot_switch_reviewed_variant(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        folder=self.root/'review';folder.mkdir();(folder/'ai.json').write_text('{}');(folder/'hw.json').write_text('{}');self.policy.write_text(json.dumps(self.q))
        (folder/'packet.json').write_text(json.dumps({'config':{'reserve_review':{'policy':'reserve.json'},'stages':{'pcb':{'inputs':{'board':self.brd.name},'variant':'A'}}}}))
        r=SimpleNamespace(phase='release',risk=lambda *a,**k:self.calls.append(a),inputs={},evidence=[]);self.calls=[]
        cfg={'reserve_review':{'policy':'reserve.json','variant':'B'},'static_ai_reviews':{'pcb':{'packet':'review','ai_review':'review/ai.json','engineer_review':'review/hw.json'}}}
        with patch('static_review_gate.validate',return_value={'status':'APPROVED_STATIC'}):rr.integrate(r,self.root,cfg,board_file=self.brd)
        self.assertTrue(any('variant' in str(c) for c in self.calls))
    def test_full_static_packet_includes_reserve(self):
        from test_static_review import fixture
        from static_review import prepare
        project=self.root/'project';cfg=fixture(project);self.policy=project/'reserve.json';self.ev=project/'test-only.txt';self.ev.write_text('TEST ONLY no reserve rationale')
        row=self.q['decisions'][0];row.update(decision='no_reserve',refs=[],source={'file':self.ev.name,'sha256':sha256(self.ev),'locator':'TEST §1'})
        self.q['variants']=[dict(name='A',parts={})];self.q['groups']=[];self.policy.write_text(json.dumps(self.q))
        cfg['documents'].append(dict(id='RESERVE_SOURCE',file=self.ev.name,sha256=sha256(self.ev),title='TEST',revision='0',issuer='TEST',authority='product_spec',applicability='TEST ONLY',approved_by='TEST'))
        cfg['reserve_review']={'policy':'reserve.json'};cfg['require_reserve_review']=True
        for spec in cfg['stages'].values():spec['tasks'].append({**copy.deepcopy(spec['tasks'][-1]),'id':'reserve','category':'reserve_options','source_refs':[{'document_id':'RESERVE_SOURCE','locator':'TEST §1'}]})
        (project/'review-config.json').write_text(json.dumps(cfg));out=self.root/'packet';prepare(project,project/'review-config.json','schematic',out)
        packet=json.loads((out/'packet.json').read_text());self.assertIn('test-only.txt',packet['baseline']);self.assertTrue((out/'reserve-review.json').exists())
if __name__=='__main__':unittest.main()
