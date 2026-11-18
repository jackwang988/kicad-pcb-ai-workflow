"""Rules-first two-level PCB layout planning; synthetic KiCad board, mocked native rule gate.

These tests do NOT certify real KiCad/GUI/Konnect placement or manufacture.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'
sys.path.insert(0,str(ROOT/'scripts'))
import pcb_module_layout as pl


class ModuleLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'03_REPORTS').mkdir()
        (self.root/'manufacturer.txt').write_text('TEST-ONLY source dimensions, not fabricator authorization')
        vals={v:round(0.2+i*0.1,4) for i,v in enumerate(pl.REQUIRED_RULES.values())}
        self.pro={'board':{'design_settings':{'rules':vals}}}
        (self.root/'demo.kicad_pro').write_text(json.dumps(self.pro))
        def fp(ref,x,y,nets):
            pads=''.join(f'(pad "{i}" smd rect (at 0 {i-1}) (size .3 .3) (layers "F.Cu") (net {j} "{name}"))' for i,(j,name) in enumerate(nets,1))
            return f'(footprint "TEST:X" (layer "F.Cu") (at {x} {y}) (property "Reference" "{ref}") (fp_rect (start -1 -1) (end 1 2) (layer "F.CrtYd")) {pads})'
        self.board='(kicad_pcb (version 20260101) (generator pcbnew) (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (gr_rect (start 0 0) (end 80 50) (layer "Edge.Cuts")) (net 0 "") (net 1 "PWR") (net 2 "GND") (net 3 "CTRL") (net 4 "IO") '+fp('U1',10,10,[(1,'PWR'),(2,'GND')])+fp('C1',13,10,[(1,'PWR'),(2,'GND')])+fp('J1',70,25,[(4,'IO'),(2,'GND')])+')'
        (self.root/'demo.kicad_pcb').write_text(self.board)
        graph='<export><components>'+''.join(f'<comp ref="{r}"><value>TEST</value></comp>' for r in ['U1','C1','J1'])+'</components><nets>'
        graph+='<net code="1" name="PWR"><node ref="U1" pin="1"/><node ref="C1" pin="1"/></net>'
        graph+='<net code="2" name="GND"><node ref="U1" pin="2"/><node ref="C1" pin="2"/><node ref="J1" pin="2"/></net>'
        graph+='<net code="3" name="IO"><node ref="J1" pin="1"/></net></nets></export>'
        (self.root/'demo.xml').write_text(graph)
        (self.root/'intent.json').write_text(json.dumps({'project_file':'demo.kicad_pro','board_file':'demo.kicad_pcb'}))
        (self.root/'source.txt').write_text('TEST source')
        self.policy={'modules':[
            {'id':'power','anchor':'U1','refs':['U1','C1'],'roles':{'U1':'controller','C1':'decoupling'},'bounds_mm':[4,4,44,35]},
            {'id':'connector','anchor':'J1','refs':['J1'],'roles':{'J1':'connector'},'bounds_mm':[55,14,77,43]}]}
        (self.root/'placement.json').write_text(json.dumps(self.policy))
        profile={'schema_version':1,'minimums_mm':{key:0.1 for key in pl.REQUIRED_RULES},
                 'courtyard_clearance_mm':0.4,'source':{'file':'manufacturer.txt','sha256':pl.sha256(self.root/'manufacturer.txt'),'locator':'test only'}}
        (self.root/'fab.json').write_text(json.dumps(profile))
        self.request={'schema_version':1,'board':'demo.kicad_pcb','project':'demo.kicad_pro','netlist':'demo.xml','design_intent':'intent.json','placement_policy':'placement.json','fab_rules':'fab.json','grid_mm':2,'max_candidates_per_ref':800,'fixed_refs':['J1']}
        (self.root/'request.json').write_text(json.dumps(self.request))
        # These legacy tests intentionally isolate prior planner geometry/rule checks.
        # Genuine JLCPCB approval protocol is tested separately.
        (self.root/'03_REPORTS/test-approval.json').write_text('fixture approval')
        (self.root/'03_REPORTS/test-proposal.json').write_text('fixture proposal')
        stub={'approval_path':'03_REPORTS/test-approval.json',
              'approval_sha256':pl.sha256(self.root/'03_REPORTS/test-approval.json'),
              'proposal_path':'03_REPORTS/test-proposal.json',
              'proposal_sha256':pl.sha256(self.root/'03_REPORTS/test-proposal.json'),
              'status':'FAB_PROFILE_APPROVAL_CURRENT'}
        self.approval_patch=patch.object(pl,'validate_for_layout',return_value=stub)
        self.approval_patch.start()
    def tearDown(self):
        self.approval_patch.stop()
        self.tmp.cleanup()
    def ready(self):
        with patch.object(pl,'audit_design_rules',return_value={'status':'PASS','native_requested':True,'findings':[]}):
            p=pl.preflight(self.root,'request.json')
        receipt=self.root/'03_REPORTS/ready.json';receipt.write_text(json.dumps(p))
        return receipt
    def test_task_dispatch_is_readonly_and_bundle_free(self):
        import workflow
        tool,args=workflow.command(self.root,'workflow.json',None,'pcb.layout_preflight',
             {'layout_request':'request.json','layout_receipt':str(self.root/'03_REPORTS/receipt.json')})
        self.assertEqual(tool,'pcb_module_layout')
        self.assertEqual(args[0],'preflight')
        tool,args=workflow.command(self.root,'workflow.json',None,'pcb.layout_plan',
             {'layout_request':'request.json','layout_receipt':str(self.root/'03_REPORTS/receipt.json')})
        self.assertEqual(args[0],'plan')
        with self.assertRaisesRegex(ValueError,'only valid'):
            workflow.command(self.root,'workflow.json',None,'pcb.layout_plan',{'apply':True,'layout_request':'request.json'})

    def test_rule_gate_precedes_any_planning(self):
        before=(self.root/'demo.kicad_pcb').read_bytes()
        with patch.object(pl,'audit_design_rules',return_value={'status':'BLOCKED','native_requested':True,'findings':[{'rule':'INTENT.EFFECTIVE'}]}):
            with self.assertRaisesRegex(ValueError,'not verified'):pl.preflight(self.root,'request.json')
        self.assertEqual(before,(self.root/'demo.kicad_pcb').read_bytes())
    def test_real_project_minima_must_match_fabrication(self):
        self.pro['board']['design_settings']['rules']['min_through_hole_diameter']=0
        (self.root/'demo.kicad_pro').write_text(json.dumps(self.pro))
        with self.assertRaisesRegex(ValueError,'min_through_hole_diameter'):pl.preflight(self.root,'request.json')
    def test_missing_native_rule_is_not_guessed(self):
        del self.pro['board']['design_settings']['rules']['min_copper_edge_clearance']
        (self.root/'demo.kicad_pro').write_text(json.dumps(self.pro))
        with self.assertRaisesRegex(ValueError,'min_copper_edge_clearance'):pl.preflight(self.root,'request.json')
    def test_module_plan_from_real_courtyard_without_board_write(self):
        rec=self.ready();before=(self.root/'demo.kicad_pcb').read_bytes()
        result=pl.plan(self.root,'request.json',rec)
        self.assertEqual(result['status'],'BOUNDED_MODULAR_PLACEMENT_PROPOSAL')
        self.assertEqual(set(result['placements']),{'U1','C1','J1'})
        self.assertEqual(result['placements']['J1']['position_mm'],[70,25])
        self.assertEqual(before,(self.root/'demo.kicad_pcb').read_bytes())
        self.assertFalse(result['executed'])
        a=result['placements']['U1']['position_mm'];b=result['placements']['C1']['position_mm']
        self.assertGreaterEqual(abs(a[0]-b[0])+abs(a[1]-b[1]),2.4)
    def test_moving_footprint_does_not_repeat_native_rule_audit(self):
        rec=self.ready()
        (self.root/'demo.kicad_pcb').write_text(self.board.replace('(at 10 10)','(at 11 10)'))
        with patch.object(pl,'audit_design_rules',side_effect=AssertionError('full native gate repeated')):
            p=pl.plan(self.root,'request.json',rec)
        self.assertEqual(p['status'],'BOUNDED_MODULAR_PLACEMENT_PROPOSAL')
    def test_pad_net_change_requires_rerun_native_rule_gate(self):
        rec=self.ready()
        (self.root/'demo.kicad_pcb').write_text(self.board.replace('(net 1 "PWR"))','(net 4 "IO"))',1))
        with self.assertRaisesRegex(ValueError,'electrical/stackup/pad'):pl.plan(self.root,'request.json',rec)
    def test_source_and_project_rule_drift_block(self):
        rec=self.ready();(self.root/'manufacturer.txt').write_text('TAMPER')
        with self.assertRaisesRegex(ValueError,'missing or changed'):pl.plan(self.root,'request.json',rec)
    def test_missing_real_edge_cuts_blocks_before_placement(self):
        (self.root/'demo.kicad_pcb').write_text(self.board.replace('(gr_rect (start 0 0) (end 80 50) (layer "Edge.Cuts"))',''))
        with self.assertRaisesRegex(ValueError,'Edge.Cuts'):pl.preflight(self.root,'request.json')
    def test_module_does_not_falsely_move_connector(self):
        rec=self.ready();result=pl.plan(self.root,'request.json',rec)
        self.assertTrue(result['placements']['J1']['fixed'])
    def test_unverified_courtyard_blocks_not_guess(self):
        rec=self.ready()
        (self.root/'demo.kicad_pcb').write_text(self.board.replace('(layer "F.CrtYd")','(layer "F.SilkS")',1))
        with self.assertRaisesRegex(ValueError,'Courtyard'):pl.plan(self.root,'request.json',rec)
    def test_schematic_pad_net_parity_does_not_accept_mismatch(self):
        (self.root/'demo.xml').write_text((self.root/'demo.xml').read_text().replace('name="PWR"','name="BAD"'))
        with self.assertRaisesRegex(ValueError,'pad/net mismatch'):pl.preflight(self.root,'request.json')
    def test_policy_must_cover_every_footprint(self):
        rec=self.ready();self.policy['modules'][0]['refs'].remove('C1');self.policy['modules'][0]['roles'].pop('C1')
        (self.root/'placement.json').write_text(json.dumps(self.policy))
        with self.assertRaisesRegex(ValueError,'policy changed'):pl.plan(self.root,'request.json',rec)

if __name__=='__main__':unittest.main()
