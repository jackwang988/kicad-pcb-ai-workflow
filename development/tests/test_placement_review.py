import copy,datetime as dt,json,pathlib,sys,tempfile,unittest,xml.etree.ElementTree as ET
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow/scripts'))
import placement_review as pr
from link_audit import primitives
from netlist_guard import read_netlist
from npi_common import sha256

def fixture(root):
    root.mkdir(exist_ok=True);src=root/'source.md';src.write_text('TEST ONLY layout source. Pin roles and limits are synthetic, not a real IC specification.\n')
    source={'file':'source.md','sha256':sha256(src),'locator':'TEST §1'}
    xml='<export><components>'+''.join(f'<comp ref="{r}"><value>TEST</value></comp>' for r in ('U1','C1','R1'))+'</components><nets><net code="1" name="VDD"><node ref="U1" pin="1"/><node ref="C1" pin="1"/></net><net code="2" name="GND"><node ref="U1" pin="2"/><node ref="C1" pin="2"/><node ref="R1" pin="2"/></net><net code="3" name="SIG"><node ref="R1" pin="1"/></net></nets></export>'
    (root/'current.xml').write_text(xml)
    pcb='(kicad_pcb (version 20260101) (generator "pcbnew") (general (thickness 1.6)) (layers (0 "F.Cu" signal) (2 "B.Cu" signal)) (net 0 "") (net 1 "VDD") (net 2 "GND") (net 3 "SIG")'
    for ref,x in [('U1',10),('C1',11),('R1',13)]:
        net=3 if ref=='R1' else 1;name='SIG' if ref=='R1' else 'VDD'
        pcb+=f'(footprint "TEST" (layer "F.Cu") (at {x} 10) (property "Reference" "{ref}") (fp_rect (start -0.4 -0.4) (end 0.4 1.4) (layer "F.CrtYd")) (pad "1" smd rect (at 0 0) (size .3 .3) (layers "F.Cu") (net {net} "{name}")) (pad "2" smd rect (at 0 1) (size .3 .3) (layers "F.Cu") (net 2 "GND")))'
    pcb+='(via (at 11 11) (size .6) (drill .3) (layers "F.Cu" "B.Cu") (net 2) (uuid "TEST_GND_VIA")))'
    (root/'board.kicad_pcb').write_text(pcb)
    q={'schema_version':1,'scope_reason':'TEST ONLY all components','modules':[{'id':'main','anchor':'U1','refs':['U1','C1','R1'],'roles':{'U1':'controller','C1':'decoupling','R1':'passive'},'bounds_mm':[9,9,14,12],'source':source}],
       'critical_subcircuits':[{'id':'power-local','type':'decoupling','reason':'TEST','refs':['U1','C1'],'check_ids':['dec'],'source':source}],
       'constraints':[{'id':'dec','kind':'decoupling','level':'阻断级','source':source,'ic_power':{'ref':'U1','pad':'1','net':'VDD'},'cap_power':{'ref':'C1','pad':'1','net':'VDD'},'cap_ground':{'ref':'C1','pad':'2','net':'GND'},'return_anchor':{'kind':'via','uuid':'TEST_GND_VIA','net':'GND'},'max_power_mm':2,'max_return_mm':1,'same_side':True},
                      {'id':'row','kind':'alignment','level':'优化建议','source':source,'refs':['U1','R1'],'axis':'y','tolerance':.05}],
       'reviews':{}}
    (root/'placement.json').write_text(json.dumps(q));return q

class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.q=fixture(self.root);self.policy=self.root/'placement.json';self.board=self.root/'board.kicad_pcb';self.graph=read_netlist(self.root/'current.xml')
        self.seed()
    def tearDown(self):self.tmp.cleanup()
    def audit(self,phase='final'):
        self.policy.write_text(json.dumps(self.q));b,e=primitives(self.board,False);return pr.audit(self.root,self.policy,self.graph,b,e,self.board,phase)
    def seed(self):
        r=self.audit('pre_route');snap=r['snapshots'];ev={'file':'source.md','sha256':sha256(self.root/'source.md')}
        review={'reviewer':'TEST_NOT_REAL_APPROVAL','date':dt.date.today().isoformat(),'reason':'TEST only contract exercise','evidence':[ev],'subcircuits':['power-local'],'topics':{k:True for k in pr.TOPICS|{'visual','moves_rechecked'}},**snap}
        self.q['reviews']={'pre_route':copy.deepcopy(review),'final':copy.deepcopy(review)}
    def has(self,r,code):return any(f['rule']==code for f in r['findings'])
    def test_declared_static_scope_only(self):
        r=self.audit();self.assertEqual(r['status'],'DECLARED_LAYOUT_CHECKS_COMPLETE');self.assertFalse(r['production_authorized']);self.assertFalse(r['native_geometry_verified'])
    def test_module_coverage(self):
        self.q['modules'][0]['refs'].remove('R1');self.q['modules'][0]['roles'].pop('R1');self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_duplicate_module_assignment(self):
        self.q['modules'].append(copy.deepcopy(self.q['modules'][0]));self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_courtyard_not_only_center(self):
        self.q['modules'][0]['bounds_mm']=[9,9,13.1,12];self.seed();self.assertTrue(self.has(self.audit(),'PLACE.MODULE.BOUNDS'))
    def test_missing_courtyard_not_silent(self):
        self.board.write_text(self.board.read_text().replace('(layer "F.CrtYd")','(layer "F.SilkS")'));self.seed();self.assertTrue(self.has(self.audit(),'PLACE.GEOMETRY'))
    def test_pin_net_mismatch(self):
        self.q['constraints'][0]['cap_power']['pad']='2';self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_nearest_ground_pad_cannot_fake_decoupling(self):
        s=self.board.read_text();start=s.index('(property "Reference" "C1")');end=s.index('(footprint "TEST"',start);part=s[start:end].replace('(at 0 0)','(at 3 0)').replace('(at 0 1)','(at -0.9 0)');self.board.write_text(s[:start]+part+s[end:]);self.seed();r=self.audit();self.assertTrue(self.has(r,'PLACE.DECOUPLING'));self.assertTrue(any(c.get('actual',{}).get('power_terminal_distance_mm',0)>2 for c in r['checks']))
    def test_wrong_return_via_net(self):
        self.q['constraints'][0]['return_anchor']['net']='SIG';self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_ground_distance_limit(self):
        self.q['constraints'][0]['max_return_mm']=0;self.board.write_text(self.board.read_text().replace('(via (at 11 11)','(via (at 12 11)'));self.seed();self.assertTrue(self.has(self.audit(),'PLACE.DECOUPLING'))
    def test_critical_role_requires_local_review(self):
        self.q['critical_subcircuits']=[];self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_decoupling_role_requires_pin_rule(self):
        self.q['critical_subcircuits'][0]['check_ids']=[];self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_missing_pre_route_review(self):
        self.q['reviews'].pop('pre_route');self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_changed_rules_invalidate(self):
        self.q['constraints'][0]['max_power_mm']=3;self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_beauty_move_invalidates(self):
        self.board.write_text(self.board.read_text().replace('(at 13 10)','(at 13 10.2)'));self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_tracks_do_not_invalidate_pre_route_placement(self):
        s=self.board.read_text();self.board.write_text(s[:-1]+'(segment (start 10 10) (end 11 10) (width .2) (layer "F.Cu") (net 1))'+')');self.assertEqual(self.audit('pre_route')['status'],'DECLARED_LAYOUT_CHECKS_COMPLETE');self.assertEqual(self.audit('final')['status'],'BLOCKED')
    def test_aesthetic_violation_only_advice(self):
        self.board.write_text(self.board.read_text().replace('(at 13 10)','(at 13 10.2)'));self.seed();r=self.audit();self.assertEqual(r['status'],'DECLARED_LAYOUT_CHECKS_COMPLETE');self.assertTrue(self.has(r,'PLACE.ALIGNMENT'))
    def test_beauty_cannot_override_hard_fail(self):
        self.q['constraints'][0]['max_power_mm']=.1;self.q['constraints'][0]['exception']={'reason':'Looks nicer','evidence':{'file':'source.md','sha256':sha256(self.root/'source.md')}};self.seed();self.assertTrue(self.has(self.audit(),'PLACE.DECOUPLING'))
    def test_beauty_cannot_be_blocker(self):
        self.q['constraints'][1]['level']='阻断级';self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_fixed_anchor(self):
        self.q['constraints'].append({'id':'fixed','kind':'fixed','level':'阻断级','source':self.q['modules'][0]['source'],'ref':'U1','position_mm':[9,9],'position_tolerance_mm':0,'angle_deg':0,'angle_tolerance_deg':0});self.seed();self.assertTrue(self.has(self.audit(),'PLACE.FIXED'))
    def test_nonfinite(self):
        self.q['constraints'][0]['max_power_mm']=float('nan');self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_reports_are_new_artifacts(self):
        b,_=primitives(self.board,False);r=self.audit();out=self.root/'report';before=self.board.read_bytes();pr.write_artifacts(r,b,out);ET.parse(out/'module-map.svg');self.assertTrue((out/'local-1.svg').exists());self.assertEqual(self.board.read_bytes(),before)
        with self.assertRaises(ValueError):pr.write_artifacts(r,b,out)
    def test_physical_footprint_observation(self):
        from static_review_gate import observations
        b,_=primitives(self.board,False);facts={'netlist':self.graph,'board':b};packet={'views':[]}
        observations([{'footprint':'C1','detail':'Actual decoupling footprint'}],facts,packet)
        with self.assertRaises(ValueError):observations([{'footprint':'DOES_NOT_EXIST','detail':'bad'}],facts,packet)
    def test_full_pcb_packet_includes_layout_artifacts(self):
        from test_static_review import fixture as static_fixture
        from static_review import prepare
        project=self.root/'project';cfg=static_fixture(project);q=fixture(project)
        cfg['documents'][0]['sha256']=sha256(project/'source.md')
        for stage,spec in cfg['stages'].items():
            spec['inputs']['provided_netlist']='current.xml';spec['inputs']['board']='board.kicad_pcb';spec['critical_nets']=['VDD','GND','SIG'];spec['component_sources']={r:['TEST'] for r in ('U1','C1','R1')}
            for task in spec['tasks']:task['check']={'kind':'semantic'};task['targets']={'refs':['U1'],'nets':['VDD'],'layers':[]}
        cfg['placement_review']={'policy':'placement.json'};cfg['require_placement_review']=True
        cfg['stages']['pcb']['tasks'].append({'id':'layout','category':'placement_quality','level':'阻断级','requirement':'TEST layout','strength':'mandatory','check':{'kind':'semantic'},'targets':{'refs':['U1'],'nets':['VDD','GND'],'layers':[],'footprints':['U1','C1','R1']},'source_refs':[{'document_id':'TEST','locator':'TEST §1'}]})
        (project/'review-config.json').write_text(json.dumps(cfg));out=self.root/'packet';prepare(project,project/'review-config.json','pcb',out)
        packet=json.loads((out/'packet.json').read_text());self.assertIn('placement.json',packet['baseline']);self.assertIn('placement/module-map.svg',packet['artifacts_sha256']);self.assertTrue((out/'placement/local-1.svg').exists())
    def test_binding_requires_named_power_return_nets(self):
        from test_static_review import fixture as static_fixture
        project=self.root/'binding';cfg=static_fixture(project);q=fixture(project);cfg['documents'][0]['sha256']=sha256(project/'source.md');cfg['placement_review']={'policy':'placement.json'}
        cfg['stages']['pcb']['tasks'].append({'category':'placement_quality','check':{'kind':'semantic'},'targets':{'footprints':['U1','C1','R1'],'nets':['VDD']},'source_refs':[{'document_id':'TEST','locator':'TEST §1'}]})
        with self.assertRaises(ValueError):pr.validate_review_binding(project,cfg)
    def test_uniform_spacing_requires_three_parts(self):
        self.q['constraints'][1]['kind']='uniform_spacing';self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_explicit_schematic_only_exclusion(self):
        self.graph['components']['VIRTUAL']={'value':'TEST ONLY'};self.assertEqual(self.audit()['status'],'BLOCKED')
        self.q['schematic_only']=[{'ref':'VIRTUAL','reason':'TEST schematic-only symbol','evidence':[{'file':'source.md','sha256':sha256(self.root/'source.md')}]}];self.seed();self.assertEqual(self.audit()['status'],'DECLARED_LAYOUT_CHECKS_COMPLETE')
    def test_rotated_courtyard_uses_native_pad_registration(self):
        self.board.write_text(self.board.read_text().replace('(at 11 10)','(at 11 10 90)'))
        b,_=primitives(self.board,False);self.assertEqual(pr.metadata(self.board,b)['C1']['courtyard_mode'],'manual_required')
        b['engine']='pcbnew.LoadBoard';cap=next(f for f in b['footprints'] if f['ref']=='C1');next(p for p in cap['pads'] if p['number']=='2')['pos']=(12,10)
        m=pr.metadata(self.board,b)['C1'];self.assertEqual(m['courtyard_mode'],'straight_top_polygon');self.assertAlmostEqual(min(y for x,y in m['courtyard']),9.6)
    def test_review_evidence_changed(self):
        (self.root/'source.md').write_text('CHANGED');self.assertEqual(self.audit()['status'],'BLOCKED')
    def test_independent_missing_reviews_and_demo(self):
        self.q['reviews']={};self.q['demonstration_only']=True;r=self.audit()
        for code in ('PLACE.DEMO','PLACE.REVIEW.PRE_ROUTE','PLACE.REVIEW.FINAL'):self.assertTrue(self.has(r,code))
    def test_overlap_is_candidate_not_collision_proof(self):
        self.board.write_text(self.board.read_text().replace('(at 13 10)','(at 11.5 10)'));r=self.audit();f=next(f for f in r['findings'] if f['rule']=='PLACE.COURTYARD.CANDIDATE');self.assertEqual(f['level'],'高风险')
    def test_local_svg_contains_return_anchor_and_limits(self):
        b,_=primitives(self.board,False);r=self.audit();out=self.root/'render';pr.write_artifacts(r,b,out)
        s=(out/'local-1.svg').read_text();self.assertIn('TEST_GND_VIA',s);self.assertIn('max_return_mm',''.join(ET.fromstring(s).itertext()));self.assertIn('C1.2 GND',s)
        c=next(c for c in r['checks'] if c.get('id')=='dec');self.assertEqual(c['source']['locator'],'TEST §1');self.assertEqual(c['actual']['max_power_mm'],2)
if __name__=='__main__':unittest.main()
