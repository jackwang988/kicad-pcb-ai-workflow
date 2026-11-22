"""Adversarial pre-placement fixtures: all results are software-only, not KiCad approval."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'
sys.path.insert(0,str(ROOT/'scripts'))
from schematic_geometry import sha
from schematic_preplacement import layout
from schematic_incremental_gate import authorize

class PrePlacementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        (self.root/'main.kicad_sch').write_text('(kicad_sch (paper "A4"))',encoding='utf-8')
        (self.root/'render.svg').write_text('<svg>fixture only</svg>', encoding="utf-8")
        (self.root/'geometry-source.txt').write_text('Verified library example fixture', encoding="utf-8")
        (self.root/'electrical-basis.txt').write_text('Independent net contract: R1.2->R2.1=SIG; R1.1 and R2.2=GND', encoding="utf-8")
        self.topo={'schema_version':1,'source':{'file':'electrical-basis.txt','sha256':sha(self.root/'electrical-basis.txt'),'locator':'fixture expected graph'},'pins':[
             {'ref':'R1','pin':'1','net':'GND'},{'ref':'R1','pin':'2','net':'SIG'},
             {'ref':'R2','pin':'1','net':'SIG'},{'ref':'R2','pin':'2','net':'GND'}]}
        self.write('topology.json',self.topo)
        self.geometry={'schema_version':1,'pages':{'main.kicad_sch':{'schematic_sha256':sha(self.root/'main.kicad_sch'),
                      'sheet_mm':[297,210],'complete_object_inventory':True,'visible_fields_included':True,
                      'protected_regions':[{'id':'title','kind':'title_block','bbox_mm':[220,165,292,207]}],
                      'objects':[]}}}
        self.write('geometry.json',self.geometry)
        self.req={'schema_version':1,'schematic':'main.kicad_sch','schematic_sha256':sha(self.root/'main.kicad_sch'),
             'geometry_manifest':'geometry.json','geometry_sha256':sha(self.root/'geometry.json'),
             'render_file':'render.svg','render_sha256':sha(self.root/'render.svg'),
             'page':'main.kicad_sch','topology_file':'topology.json','topology_sha256':sha(self.root/'topology.json'),
             'grid_mm':2.5,'clearance_mm':1.0,'pin_escape_mm':5.0,'wire_corridor_width_mm':0.6,
             'max_candidate_positions':200,'search_budget':600,'power_rails':['GND'],
             'symbols':[self.sym('R1',[40,40],{'1':'GND','2':'SIG'},'left'),self.sym('R2',[110,40],{'1':'SIG','2':'GND'},'right')],
             'connections':[{'net':'SIG','from':['R1','2'],'to':['R2','1']}]}
    def sym(self,ref,location,nets,outer):
        geom={'source':{'file':'geometry-source.txt','sha256':sha(self.root/'geometry-source.txt'),'locator':'fixture symbol geometry'},
            'body_bbox_mm':[-3,-2,3,2],
            'fields':[{'name':'Reference','bbox_mm':[-2,-10,6,-7]},{'name':'Value','bbox_mm':[-2,7,8,10]}],
            'pins':[{'number':'1','xy_mm':[-5,0],'outward':[-1,0],'net':nets['1']},
                    {'number':'2','xy_mm':[5,0],'outward':[1,0],'net':nets['2']}],
            'labels':[{'pin':outer=='left' and '1' or '2','net':'GND','text':'GND','kind':'power',
                       'anchor_local_mm':([-10,0] if outer=='left' else [10,0]),
                       'bbox_mm':([-22,-3,-10,3] if outer=='left' else [10,-3,22,3])}]}
        return {'ref':ref,'geometry':geom,'candidate_positions_mm':[location]}
    def write(self,name,data):
        (self.root/name).write_text(json.dumps(data,sort_keys=True),encoding='utf-8')
    def sync(self):
        self.write('geometry.json',self.geometry);self.req['geometry_sha256']=sha(self.root/'geometry.json')
        self.write('topology.json',self.topo);self.req['topology_sha256']=sha(self.root/'topology.json')
    def check(self):
        self.sync();return layout(self.root,self.req)
    def test_clean_two_resistor_preplacement(self):
        result=self.check();self.assertEqual(result['status'],'PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY',result)
        self.assertEqual(len(result['placements']),2);self.assertEqual(len(result['trial_routes']),1)
        self.assertFalse(result['executed']);self.assertFalse(result['production_authorized'])
    def test_title_block_protected_before_write(self):
        self.req['symbols'][0]['candidate_positions_mm']=[[245,180]]
        self.assertEqual(self.check()['status'],'BLOCKED')
    def test_existing_symbol_collision_preflight(self):
        sch=self.root/'main.kicad_sch';sch.write_text('(kicad_sch (paper "A4") (symbol (uuid "existing")))', encoding="utf-8")
        self.req['schematic_sha256']=sha(sch);self.geometry['pages']['main.kicad_sch']['schematic_sha256']=sha(sch)
        self.geometry['pages']['main.kicad_sch']['objects'].append({'uuid':'existing','kind':'symbol','bbox_mm':[33,33,48,48]})
        self.assertEqual(self.check()['status'],'BLOCKED')
    def test_existing_wire_blocks_candidate(self):
        sch=self.root/'main.kicad_sch';sch.write_text('(kicad_sch (paper "A4") (wire (uuid "w1")))', encoding="utf-8")
        self.req['schematic_sha256']=sha(sch);self.geometry['pages']['main.kicad_sch']['schematic_sha256']=sha(sch)
        self.geometry['pages']['main.kicad_sch']['objects'].append({'uuid':'w1','kind':'wire','bbox_mm':[38,36,42,44]})
        self.assertEqual(self.check()['status'],'BLOCKED')
    def test_visible_text_overlap_rejected(self):
        self.req['symbols'][0]['geometry']['fields'][0]['bbox_mm']=[-3,-2,4,3]
        self.assertEqual(self.check()['status'],'BLOCKED')
    def test_external_label_has_no_space(self):
        self.req['symbols'][0]['geometry']['labels'][0]['bbox_mm']=[-8,-3,-3,3]
        with self.assertRaisesRegex(ValueError,'connection anchor'):self.check()
    def test_insufficient_pin_escape(self):
        self.req['symbols'][0]['geometry']['fields'].append({'name':'Note','bbox_mm':[-12,-1,-9,2]})
        self.assertEqual(self.check()['status'],'BLOCKED')
    def test_stale_current_schematic_refused(self):
        self.check();(self.root/'main.kicad_sch').write_text('modified', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'Schematic changed'):layout(self.root,self.req)
    def test_missing_native_uuid_refused(self):
        sch=self.root/'main.kicad_sch';sch.write_text('(kicad_sch (paper "A4") (symbol (uuid "new")))', encoding="utf-8")
        self.req['schematic_sha256']=sha(sch);self.geometry['pages']['main.kicad_sch']['schematic_sha256']=sha(sch)
        with self.assertRaisesRegex(ValueError,'UUID'):self.check()
    def test_wrong_electrical_pin_net_blocks(self):
        self.req['symbols'][0]['geometry']['pins'][0]['net']='VIN'
        with self.assertRaisesRegex(ValueError,'differs'):self.check()
    def test_missing_net_connection_or_label_blocks(self):
        self.req['connections']=[]
        with self.assertRaisesRegex(ValueError,'No connection or label'):self.check()
    def test_missing_source_geometry_blocks(self):
        self.req['symbols'][0]['geometry']['source']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source evidence'):self.check()
    def test_candidate_fallback_finds_second_slot(self):
        self.req['symbols'][0]['candidate_positions_mm']=[[245,180],[40,40]]
        r=self.check();self.assertEqual(r['status'],'PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY',r)
        self.assertEqual(r['placements']['R1']['position_mm'],[40,40])
    def test_a_star_detours_existing_obstacle(self):
        sch=self.root/'main.kicad_sch';sch.write_text('(kicad_sch (paper "A4") (text (uuid "note")))', encoding="utf-8")
        self.req['schematic_sha256']=sha(sch);self.geometry['pages']['main.kicad_sch']['schematic_sha256']=sha(sch)
        self.geometry['pages']['main.kicad_sch']['objects'].append({'uuid':'note','kind':'text','bbox_mm':[70,35,85,45]})
        r=self.check();self.assertEqual(r['status'],'PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY',r)
        self.assertGreater(len(r['trial_routes'][0]['path_mm']),2)
    def test_gate_requires_same_project_and_receipt(self):
        r=self.check();self.write('request.json',self.req);r['request_sha256']=sha(self.root/'request.json')
        receipt=Path(self.temp.name)/'immutable-receipt.json';receipt.write_text(json.dumps(r), encoding="utf-8")
        x=authorize(self.root,'request.json',receipt)
        self.assertEqual(x['status'],'PREPLACEMENT_RECEIPT_CURRENT_FOR_NEXT_BATCH')
        self.assertFalse(x['executed'])
        (self.root/'main.kicad_sch').write_text('(kicad_sch (paper "A4"))\n', encoding="utf-8")
        with self.assertRaises(ValueError):authorize(self.root,'request.json',receipt)
    def test_two_nets_cannot_short_through_route(self):
        # Both GND terminals have power-label reservations. SIG uses a separate route.
        result=self.check();self.assertEqual(result['trial_routes'][0]['net'],'SIG')
    def test_existing_render_change_invalidates(self):
        self.check();(self.root/'render.svg').write_text('changed view', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'Rendered view'):layout(self.root,self.req)
    def test_missing_title_block_refused(self):
        self.geometry['pages']['main.kicad_sch']['protected_regions']=[]
        with self.assertRaisesRegex(ValueError,'title-block'):self.check()
    def test_label_identity_mismatch_refused(self):
        self.req['symbols'][0]['geometry']['labels'][0]['net']='SIG'
        with self.assertRaisesRegex(ValueError,'Power label'):self.check()
    def test_wrong_label_anchor_rejected(self):
        self.req['symbols'][0]['geometry']['labels'][0]['anchor_local_mm']=[-20,0]
        with self.assertRaisesRegex(ValueError,'pin-escape endpoint'):self.check()
    def test_local_label_not_substitute_for_ground_power_symbol(self):
        self.req['symbols'][0]['geometry']['labels'][0]['kind']='local'
        with self.assertRaisesRegex(ValueError,'native power-symbol'):self.check()
    def test_off_grid_anchor_rejected(self):
        self.req['symbols'][0]['candidate_positions_mm']=[[40.12,40.12]]
        with self.assertRaisesRegex(ValueError,'off the declared'):self.check()
    def test_workflow_routes_new_readonly_tasks_without_bundle(self):
        import workflow
        self.check()
        self.write('request.json',self.req)
        dest=Path(self.temp.name)/'immutable-receipt.json'
        tool,args=workflow.command(self.root,'workflow.json',None,'schematic.preplacement_plan',
                                    {'preplacement_request':'request.json','preplacement_receipt':str(dest)})
        self.assertEqual(tool,'schematic_preplacement')
        self.assertIn('--request',args)
        self.assertFalse(dest.exists())
        checker,argv=workflow.command(self.root,'workflow.json',None,'schematic.preplacement_check',
                                       {'preplacement_request':'request.json','preplacement_receipt':str(dest)})
        self.assertEqual(checker,'schematic_incremental_gate')
        self.assertIn('--receipt',argv)
        with self.assertRaisesRegex(ValueError,'only valid'):
            workflow.command(self.root,'workflow.json',None,'schematic.preplacement_plan',
                             {'preplacement_request':'request.json','apply':True})
    def test_grid_snapped_candidates_are_required(self):
        self.req['symbols'][0]['candidate_positions_mm']=[[40.01,40]]
        with self.assertRaisesRegex(ValueError,'off the declared'):self.check()
    def test_overly_long_traces_are_rejected_before_placement(self):
        self.req['max_trial_wire_length_mm']=10
        r=self.check();self.assertEqual(r['status'],'PREPLACEMENT_GEOMETRY_READY_ROUTE_REVIEW_REQUIRED');self.assertIsNone(r['trial_routes'])
    def test_excessive_bends_block_under_strict_project_policy(self):
        sch=self.root/'main.kicad_sch';sch.write_text('(kicad_sch (paper "A4") (text (uuid "note")))', encoding="utf-8")
        self.req['schematic_sha256']=sha(sch)
        self.geometry['pages']['main.kicad_sch']['schematic_sha256']=sha(sch)
        self.geometry['pages']['main.kicad_sch']['objects'].append({'uuid':'note','kind':'text','bbox_mm':[70,35,85,45]})
        self.req['max_trial_wire_bends']=0
        r=self.check();self.assertEqual(r['status'],'PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY');self.assertTrue(all(x['bends']==0 for x in r['trial_routes']))
    def test_no_path_when_all_corridors_blocked(self):
        sch=self.root/'main.kicad_sch';sch.write_text('(kicad_sch (paper "A4") (text (uuid "wall")))', encoding="utf-8")
        self.req['schematic_sha256']=sha(sch);self.geometry['pages']['main.kicad_sch']['schematic_sha256']=sha(sch)
        self.geometry['pages']['main.kicad_sch']['objects'].append({'uuid':'wall','kind':'text','bbox_mm':[70,1,75,160]})
        # Detour may remain possible above or below, a wall spanning full page height blocks.
        self.geometry['pages']['main.kicad_sch']['objects'][0]['bbox_mm']=[70,0,75,210]
        r=self.check();self.assertEqual(r['status'],'PREPLACEMENT_GEOMETRY_READY_ROUTE_REVIEW_REQUIRED');self.assertIsNone(r['trial_routes'])

    def test_search_budget_exhaustion_is_replan_not_page_full(self):
        self.req['symbols'][0]['candidate_positions_mm']=[[245,180],[40,40]]
        self.req['search_budget']=1
        result=self.check()
        self.assertEqual(result['status'],'REPLAN_REQUIRED')
        self.assertFalse(result['executed'])

    def test_rotation_rescues_candidate_before_mcp_write(self):
        doc=self.root/'main.kicad_sch'
        doc.write_text('(kicad_sch (paper "A4") (text (uuid "existing-note")))', encoding="utf-8")
        self.req['schematic_sha256']=sha(doc)
        self.geometry['pages']['main.kicad_sch']['schematic_sha256']=sha(doc)
        self.geometry['pages']['main.kicad_sch']['objects'].append({'uuid':'existing-note','kind':'text','bbox_mm':[43,31,46,34]})
        self.req['symbols'][0]['rotations_deg']=[0,90]
        result=self.check()
        self.assertEqual(result['status'],'PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY',result)
        self.assertEqual(result['placements']['R1']['rotation_deg'],90)

    def test_hash_gate_does_not_repeat_a_star_search(self):
        import schematic_incremental_gate as gate
        from unittest.mock import patch
        result=self.check()
        self.write('request.json',self.req)
        result['request_sha256']=sha(self.root/'request.json')
        receipt=Path(self.temp.name)/'receipt.json'
        receipt.write_text(json.dumps(result), encoding="utf-8")
        with patch('schematic_preplacement.layout',side_effect=AssertionError('repeat A*')):
            actual=gate.authorize(self.root,'request.json',receipt)
        self.assertTrue(actual['allow_placement_batch'])
        self.assertFalse(actual['allow_unverified_wiring'])

    def test_conditional_route_does_not_grant_wiring_approval(self):
        import schematic_incremental_gate as gate
        self.req['max_trial_wire_length_mm']=10
        result=self.check()
        self.assertEqual(result['status'],'PREPLACEMENT_GEOMETRY_READY_ROUTE_REVIEW_REQUIRED')
        self.write('request.json',self.req)
        result['request_sha256']=sha(self.root/'request.json')
        receipt=Path(self.temp.name)/'receipt.json'
        receipt.write_text(json.dumps(result), encoding="utf-8")
        actual=gate.authorize(self.root,'request.json',receipt)
        self.assertEqual(actual['status'],'PREPLACEMENT_GEOMETRY_CURRENT_WIRING_REVIEW_REQUIRED')
        self.assertFalse(actual['allow_unverified_wiring'])

if __name__=='__main__':unittest.main()
