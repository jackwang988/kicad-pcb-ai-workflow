"""Synthetic KiCad FR4 structures and human-authorization protocol; no real KiCad GUI claim."""
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'
sys.path.insert(0,str(ROOT/'scripts'))
import pcb_fab_approval as fab
import pcb_module_layout as layout
import workflow


def board_string(layers=2,with_stack=True,inner=0.0175,outer=0.035,thickness=1.6):
    copper=['F.Cu']+[f'In{i}.Cu' for i in range(1,layers-1)]+['B.Cu']
    layertext=' '.join(f'({0 if i==0 else 31 if i==len(copper)-1 else i} "{layer}" signal)' for i,layer in enumerate(copper))
    stack='(setup (stackup '+' '.join(f'(layer "{ly}" (type "copper") (thickness {outer if ly in ("F.Cu","B.Cu") else inner}))' for ly in copper)+'))' if with_stack else ''
    fp='''(footprint "Fixture:IC" (layer "F.Cu") (at 10 10) (property "Reference" "U1")
      (fp_rect (start -1 -1) (end 1 1) (layer "F.CrtYd"))
      (pad "1" smd rect (at 0 0) (size 0.4 0.4) (layers "F.Cu") (net 1 "VCC")))'''
    return '(kicad_pcb (version 20260101) (generator pcbnew) (general (thickness '+str(thickness)+')) (layers '+layertext+') '+stack+' (gr_rect (start 0 0) (end 50 50) (layer "Edge.Cuts")) (net 1 "VCC") '+fp+')'


class FactoryConsentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'03_REPORTS').mkdir();(self.root/'demo.kicad_pcb').write_text(board_string(), encoding="utf-8")
        (self.root/'demo.kicad_pro').write_text('{}', encoding="utf-8")
        self.path='03_REPORTS/proposal.json';self.approval='03_REPORTS/approval.json';self.fabric='03_REPORTS/fab.json'
    def tearDown(self):self.tmp.cleanup()
    def files(self):return {(p.name,p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
    def preview(self,layers=2):
        p=fab.propose(self.root,'demo.kicad_pcb',layers)
        (self.root/self.path).write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n', encoding="utf-8")
        return p
    def accept(self):return fab.confirm(self.root,self.path,'engineering-owner','CONFIRM',self.approval,self.fabric)
    def request(self):return {'schema_version':1,'board':'demo.kicad_pcb','project':'demo.kicad_pro',
        'fab_rules':self.fabric,'fab_approval':self.approval}
    def test_all_four_layer_profiles_source_from_catalog_not_minima(self):
        for layers in (2,4,6,8):
            (self.root/'demo.kicad_pcb').write_text(board_string(layers), encoding="utf-8")
            p=fab.propose(self.root,'demo.kicad_pcb',layers)
            self.assertEqual(p['status'],'FAB_USER_CONFIRMATION_REQUIRED')
            self.assertEqual(p['selection']['layers'],layers)
            self.assertGreater(p['selection']['user_reviewed_design_rules_mm']['min_clearance_mm'],p['selection']['manufacturer_1oz_trace_space_floor_mm'])
            self.assertGreaterEqual(p['selection']['user_reviewed_design_rules_mm']['min_via_diameter_mm'],0.7)
            self.assertIn('sources',fab.load_catalog())
            self.assertFalse(p['executed'])
    def test_preview_has_no_project_mutation(self):
        before=self.files();p=fab.propose(self.root,'demo.kicad_pcb',2)
        self.assertEqual(before,self.files());self.assertEqual(p['copper_layers'],2)
    def test_no_user_approval_does_not_call_native_audit(self):
        with patch.object(layout,'audit_design_rules',side_effect=AssertionError('native invoked')):
            with self.assertRaisesRegex(ValueError,'FAB_USER_CONFIRMATION_REQUIRED'):
                layout.preflight(self.root,'request.json') if (self.root/'request.json').exists() else fab.validate_for_layout(self.root,self.request())
    def test_wrong_layer_count_refused(self):
        with self.assertRaisesRegex(ValueError,'layer count'):fab.propose(self.root,'demo.kicad_pcb',4)
    def test_wrong_thickness_refused(self):
        (self.root/'demo.kicad_pcb').write_text(board_string(thickness=0.8), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'thickness'):fab.propose(self.root,'demo.kicad_pcb',2)
    def test_confirm_refused_without_real_positive_decision(self):
        self.preview();before=self.files()
        for actor,decision in (('','CONFIRM'),('owner','REJECT'),('owner','')):
            with self.assertRaisesRegex(ValueError,'human CONFIRM'):
                fab.confirm(self.root,self.path,actor,decision,self.approval,self.fabric)
        self.assertEqual(before,self.files())
    def test_user_confirmation_creates_immutable_approval_and_fab_sidecar_only(self):
        self.preview();before=(self.root/'demo.kicad_pcb').read_bytes();out=self.accept()
        self.assertEqual(out['status'],'FAB_PROFILE_USER_CONFIRMED')
        self.assertFalse(out['executed']);self.assertFalse(out['production_authorized'])
        self.assertEqual(before,(self.root/'demo.kicad_pcb').read_bytes())
        self.assertEqual(json.loads((self.root/self.fabric).read_text(encoding="utf-8"))['minimums_mm']['min_clearance_mm'],0.2)
        with self.assertRaisesRegex(ValueError,'NEW'):
            self.accept()
    def test_rule_and_copper_readback_after_user_confirmation(self):
        self.preview();self.accept()
        selected=json.loads((self.root/self.fabric).read_text(encoding="utf-8"))['minimums_mm']
        pro={'board':{'design_settings':{'rules':{layout.REQUIRED_RULES[k]:v for k,v in selected.items()}}}}
        (self.root/'demo.kicad_pro').write_text(json.dumps(pro), encoding="utf-8")
        result=fab.validate_for_layout(self.root,self.request())
        self.assertEqual(result['status'],'FAB_PROFILE_APPROVAL_CURRENT')
        (self.root/'demo.kicad_pcb').write_text(board_string(with_stack=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'stackup'):fab.validate_for_layout(self.root,self.request())
    def test_approval_hash_binds_the_actual_written_bytes_on_windows_too(self):
        self.preview();receipt=self.accept();payload=(self.root/self.fabric).read_bytes()
        self.assertNotIn(b'\r\n',payload)
        self.assertEqual(receipt['fab_rules_sha256'],hashlib.sha256(payload).hexdigest())
    def test_fab_rule_edit_invalidates_confirmation(self):
        self.preview();self.accept();p=self.root/self.fabric
        p.write_text(p.read_text(encoding="utf-8").replace('0.7','0.4'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'differ from exactly user-approved'):fab.validate_for_layout(self.root,self.request())
    def test_proposal_and_catalog_provenance_tamper_invalidates(self):
        self.preview();self.accept();path=self.root/self.path
        path.write_text(path.read_text(encoding="utf-8")+' ', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'source changed|proposal|Confirmed'):fab.validate_for_layout(self.root,self.request())
    def test_changed_layers_after_user_confirmation_invalidates(self):
        self.preview();self.accept();(self.root/'demo.kicad_pcb').write_text(board_string(layers=4), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'layer count|Selected'):fab.validate_for_layout(self.root,self.request())
    def test_changed_inner_copper_weight_invalidates(self):
        (self.root/'demo.kicad_pcb').write_text(board_string(layers=4), encoding="utf-8")
        self.preview(4);self.accept()
        (self.root/'demo.kicad_pcb').write_text(board_string(layers=4,inner=0.035), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'finished copper thickness'):fab.validate_for_layout(self.root,self.request())
    def test_workflow_preview_requires_no_apply_and_confirm_requires_user(self):
        tool,args=workflow.command(self.root,'workflow.json',None,'pcb.fab_preview',
            {'fab_board':'demo.kicad_pcb','fab_layers':'2','fab_proposal':'03_REPORTS/proposal.json'})
        self.assertEqual(tool,'pcb_fab_approval');self.assertEqual(args[0],'preview')
        self.assertEqual(Path(args[1]).resolve(),self.root.resolve())
        with self.assertRaisesRegex(ValueError,'only valid|preview is read-only'):
            workflow.command(self.root,'workflow.json',None,'pcb.fab_preview',{'apply':True,'fab_board':'demo.kicad_pcb','fab_layers':'2'})
        with self.assertRaisesRegex(ValueError,'confirm'):
            workflow.command(self.root,'workflow.json',None,'pcb.fab_confirm',{'apply':True,'fab_decision':'REJECT'})
        tool,args=workflow.command(self.root,'workflow.json',None,'pcb.fab_confirm',{'apply':True,'fab_decision':'CONFIRM',
            'fab_proposal':self.path,'fab_confirmed_by':'owner','fab_approval':self.approval,'fab_rule_output':self.fabric})
        self.assertEqual(tool,'pcb_fab_approval');self.assertIn('--apply',args)
    def test_real_approved_fab_gate_precedes_existing_native_rule_preflight(self):
        self.preview();self.accept()
        expected=json.loads((self.root/self.fabric).read_text(encoding="utf-8"))['minimums_mm']
        pro={'board':{'design_settings':{'rules':{layout.REQUIRED_RULES[k]:v for k,v in expected.items()}}}}
        (self.root/'demo.kicad_pro').write_text(json.dumps(pro), encoding="utf-8")
        # Remaining layout inputs for an exact trivial one-footprint demo
        (self.root/'demo.xml').write_text('<export><components><comp ref="U1"><value>IC</value></comp></components><nets><net code="1" name="VCC"><node ref="U1" pin="1"/></net></nets></export>', encoding="utf-8")
        (self.root/'intent.json').write_text(json.dumps({'project_file':'demo.kicad_pro','board_file':'demo.kicad_pcb'}), encoding="utf-8")
        (self.root/'placement.json').write_text(json.dumps({'modules':[]}), encoding="utf-8")
        request={**self.request(),'netlist':'demo.xml','design_intent':'intent.json','placement_policy':'placement.json'}
        (self.root/'request.json').write_text(json.dumps(request), encoding="utf-8")
        with patch.object(layout,'audit_design_rules',return_value={'status':'PASS','native_requested':True,'findings':[]}):
            r=layout.preflight(self.root,'request.json')
        self.assertEqual(r['status'],'RULES_VERIFIED_FOR_LAYOUT_PLANNING')
        self.assertEqual(r['fab_user_confirmation']['status'],'FAB_PROFILE_APPROVAL_CURRENT')
        self.assertEqual(r['active_fabrication_rules']['min_track_width']['active_mm'],0.2)

if __name__=='__main__':unittest.main()
