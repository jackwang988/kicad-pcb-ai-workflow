"""Synthetic KiCad geometry tests: not an EDA DRC or Konnect acceptance test."""
import itertools
import json
import unittest
from pathlib import Path
import test_pcb_module_layout as fixtures
from pcb_placement_geometry import intersects, footprint_keepouts, locked, hits_holes, npth_holes
from npi_common import parse_sexpr
from pcb_module_layout import _candidates
import pcb_module_layout as pl


class CourtyardGeometryTests(unittest.TestCase):
    def test_contoured_courtyard_does_not_forbid_empty_corner(self):
        a=[(0,0),(4,0),(4,1),(1,1),(1,4),(0,4)]
        b=[(2,2),(3,2),(3,3),(2,3)]
        self.assertFalse(intersects(a,b,0))
        self.assertFalse(intersects(a,b,.5))
        self.assertTrue(intersects(a,b,1.42))
    def test_overlap_and_courtyard_clearance(self):
        a=[(0,0),(1,0),(1,1),(0,1)]
        b=[(1.25,0),(2.25,0),(2.25,1),(1.25,1)]
        self.assertFalse(intersects(a,b,.2))
        self.assertTrue(intersects(a,b,.30))
        self.assertTrue(intersects(a,[(.5,.5),(1.5,.5),(1.5,1.5),(.5,1.5)],0))
    def test_lazy_candidates_do_not_enumerate_millions(self):
        items=list(_candidates((50.,50.),[0,0,150,200],.1,120))
        self.assertEqual(len(items),120)
        self.assertEqual(items[0],(50.,50.))
        self.assertEqual(len(items),len(set(items)))
    def test_footprint_zone_keepout_from_native_source(self):
        board=parse_sexpr('''(kicad_pcb (zone (net 0) (layer "F.Cu")
            (keepout (tracks allowed) (vias allowed) (pads allowed) (footprints not_allowed) (copperpour allowed))
            (polygon (pts (xy 5 5) (xy 9 5) (xy 9 9) (xy 5 9))) (uuid "ko")))''')
        k=footprint_keepouts(board)
        self.assertEqual(len(k),1)
        self.assertTrue(intersects(k[0]['polygon'],[(6,6),(7,6),(7,7),(6,7)],0))
    def test_invalid_zone_keepout_blocks_not_guess(self):
        with self.assertRaisesRegex(ValueError,'Keepout'):
            footprint_keepouts(parse_sexpr('(kicad_pcb (zone (keepout (footprints not_allowed))))'))
    def test_bare_kicad_locked_flag(self):
        self.assertTrue(locked(parse_sexpr('(footprint "R" locked (layer "F.Cu"))')))
        self.assertTrue(locked(parse_sexpr('(footprint "R" (locked yes))')))
        self.assertFalse(locked(parse_sexpr('(footprint "R" (locked no))')))
    def test_npth_hole_fixed_and_avoidance(self):
        board=parse_sexpr('''(kicad_pcb (footprint "MH" (layer "F.Cu") (at 20 20)
          (property "Reference" "H1") (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask"))))''')
        with self.assertRaisesRegex(ValueError,'must be fixed'):
            npth_holes(board,set())
        h=npth_holes(board,{'H1'})
        self.assertTrue(hits_holes([(19,19),(21,19),(21,21),(19,21)],h,.2,own_ref='R1'))
        self.assertFalse(hits_holes([(22,22),(23,22),(23,23),(22,23)],h,.2,own_ref='R1'))


class PlacementHardRuleIntegration(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.ModuleLayoutTests('test_module_plan_from_real_courtyard_without_board_write')
        self.base.setUp()
        self.root=self.base.root
    def tearDown(self):self.base.tearDown()
    def _ready(self):return self.base.ready()
    def _save_policy(self): (self.root/'placement.json').write_text(json.dumps(self.base.policy))
    def _save_request(self):(self.root/'request.json').write_text(json.dumps(self.base.request))
    def test_connector_role_alone_is_automatically_fixed(self):
        self.base.request['fixed_refs']=[];self._save_request()
        r=pl.plan(self.root,'request.json',self._ready())
        self.assertEqual(r['status'],'BOUNDED_MODULAR_PLACEMENT_PROPOSAL')
        self.assertEqual(r['placements']['J1']['position_mm'],[70,25])
        self.assertTrue(r['placements']['J1']['fixed'])
    def test_footprint_keepout_disallows_candidate(self):
        self.base.board=self.base.board[:-1]+''' (zone (net 0) (layer "F.Cu")
          (keepout (footprints not_allowed))
          (polygon (pts (xy 3 3) (xy 45 3) (xy 45 36) (xy 3 36)))) )'''
        (self.root/'demo.kicad_pcb').write_text(self.base.board)
        r=pl.plan(self.root,'request.json',self._ready())
        self.assertEqual(r['status'],'REPLAN_REQUIRED')
    def test_keepout_changed_after_rule_check_invalidates_fingerprint(self):
        receipt=self._ready()
        txt=(self.root/'demo.kicad_pcb').read_text()
        txt=txt[:-1]+''' (zone (net 0) (layer "F.Cu") (keepout (footprints not_allowed))
              (polygon (pts (xy 5 5) (xy 6 5) (xy 6 6) (xy 5 6)))) )'''
        (self.root/'demo.kicad_pcb').write_text(txt)
        with self.assertRaisesRegex(ValueError,'electrical/stackup/pad'):
            pl.plan(self.root,'request.json',receipt)
    def test_hard_pin_proximity_prevents_false_success(self):
        self.base.policy['constraints']=[
            {'id':'close','kind':'pad_proximity','level':'阻断级',
             'a':{'ref':'U1','pad':'1','net':'PWR'},
             'b':{'ref':'C1','pad':'1','net':'PWR'},'max_mm':1,'same_side':True}]
        self._save_policy()
        r=pl.plan(self.root,'request.json',self._ready())
        self.assertEqual(r['status'],'REPLAN_REQUIRED')
    def test_reasonable_hard_proximity_allows_layout(self):
        self.base.policy['constraints']=[
            {'id':'close','kind':'pad_proximity','level':'阻断级',
             'a':{'ref':'U1','pad':'1','net':'PWR'},
             'b':{'ref':'C1','pad':'1','net':'PWR'},'max_mm':8,'same_side':True}]
        self._save_policy()
        r=pl.plan(self.root,'request.json',self._ready())
        self.assertEqual(r['status'],'BOUNDED_MODULAR_PLACEMENT_PROPOSAL')
    def test_unknown_critical_pad_reference_does_not_defer_forever(self):
        self.base.policy['constraints']=[{'id':'missing','kind':'pad_proximity','level':'阻断级',
          'a':{'ref':'U999','pad':'1','net':'PWR'},'b':{'ref':'C1','pad':'1','net':'PWR'},'max_mm':5}]
        self._save_policy()
        with self.assertRaisesRegex(ValueError,'absent footprint'):
            pl.plan(self.root,'request.json',self._ready())
    def test_candidate_budget_must_be_positive_integer(self):
        self.base.request['max_candidates_per_ref']=0.5
        self._save_request()
        with self.assertRaisesRegex(ValueError,'Integer placement search candidate budget'):
            pl.plan(self.root,'request.json',self._ready())
    def test_unknown_mandatory_constraint_is_never_ignored(self):
        self.base.policy['constraints']=[{'id':'bad','kind':'custom_unknown','level':'阻断级'}]
        self._save_policy()
        with self.assertRaisesRegex(ValueError,'Unsupported mandatory'):
            pl.plan(self.root,'request.json',self._ready())
    def test_fixed_source_rule_preserves_original_position(self):
        self.base.policy['constraints']=[{'id':'fix','kind':'fixed','level':'阻断级',
           'ref':'U1','position_mm':[10,10],'position_tolerance_mm':0,
           'angle_deg':0,'angle_tolerance_deg':0}]
        self._save_policy()
        r=pl.plan(self.root,'request.json',self._ready())
        self.assertEqual(r['placements']['U1']['position_mm'],[10,10])
        self.assertTrue(r['placements']['U1']['fixed'])
    def test_custom_kicad_courtyard_clearance_is_honored(self):
        (self.root/'demo.kicad_dru').write_text('(version 1) (rule "courtyard" (constraint courtyard_clearance (min 1.1mm)))')
        ready=self._ready()
        import json as _json
        self.assertAlmostEqual(_json.loads(ready.read_text())['courtyard_clearance_mm'],1.1)
        r=pl.plan(self.root,'request.json',ready)
        self.assertEqual(r['status'],'BOUNDED_MODULAR_PLACEMENT_PROPOSAL')
    def test_unknown_courtyard_rule_expression_blocks(self):
        (self.root/'demo.kicad_dru').write_text('(version 1) (rule "unknown" (constraint courtyard_clearance (min ${param})))')
        with self.assertRaisesRegex(ValueError,'Unknown custom courtyard_clearance'):
            self._ready()
    def test_disabled_courtyard_drc_is_refused(self):
        self.base.pro['board']['design_settings']['rule_severities']={'courtyards_overlap':'ignore'}
        (self.root/'demo.kicad_pro').write_text(json.dumps(self.base.pro))
        with self.assertRaisesRegex(ValueError,'severity'):
            self._ready()
    def test_no_geometry_guess_for_rotated_footprint_without_native(self):
        self.base.board=self.base.board.replace('(at 13 10)','(at 13 10 45)')
        (self.root/'demo.kicad_pcb').write_text(self.base.board)
        with self.assertRaisesRegex(ValueError,'Courtyard'):
            pl.plan(self.root,'request.json',self._ready())
    def test_decoupling_pin_and_real_return_via_rule(self):
        self.base.board=self.base.board[:-1]+ ' (via (at 13 12) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 2) (uuid "RETURN_GND")))'
        (self.root/'demo.kicad_pcb').write_text(self.base.board)
        self.base.policy['constraints']=[{
            'id':'decouple','kind':'decoupling','level':'阻断级','same_side':True,
            'ic_power':{'ref':'U1','pad':'1','net':'PWR'},
            'cap_power':{'ref':'C1','pad':'1','net':'PWR'},
            'cap_ground':{'ref':'C1','pad':'2','net':'GND'},
            'return_anchor':{'kind':'via','uuid':'RETURN_GND','net':'GND'},
            'max_power_mm':8,'max_return_mm':3
        }]
        self._save_policy()
        r=pl.plan(self.root,'request.json',self._ready())
        self.assertEqual(r['status'],'BOUNDED_MODULAR_PLACEMENT_PROPOSAL',r)
        self.base.policy['constraints'][0]['max_return_mm']=.01
        self._save_policy()
        r=pl.plan(self.root,'request.json',self._ready())
        self.assertEqual(r['status'],'REPLAN_REQUIRED')
    def test_netlist_extra_live_net_cannot_be_ignored(self):
        self.base.board=self.base.board.replace('(net 3 "CTRL")','(net 3 "CTRL") (net 5 "EXTRA")')
        self.base.board=self.base.board.replace('(net 4 "IO"))','(net 5 "EXTRA"))',1)
        (self.root/'demo.kicad_pcb').write_text(self.base.board)
        with self.assertRaisesRegex(ValueError,'pad/net mismatch|electrical pad'):
            pl.preflight(self.root,'request.json',native_audit=lambda *a,**k:{'status':'PASS','native_requested':True})

if __name__=='__main__':unittest.main()
