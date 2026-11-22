"""Native KiCad S-expression symbol geometry, rotation and preplacement fixtures.

No mocked symbol bounding rectangles: all body/pins originate in real KiCad
(.kicad_sym/.kicad_sch) syntax. Font bounds remain a conservative estimate.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'
sys.path.insert(0,str(ROOT/'scripts'))
from schematic_native_geometry import symbol_geometry,placed_instance_geometry,snapshot,prospective_geometry,_arc_bbox,_bezier_bbox
from schematic_geometry import evidence,sha
from schematic_io import parse
from npi_common import children
from schematic_preplacement import layout
from schematic_space_map import placements
from schematic_incremental_gate import authorize

SYM='''(kicad_symbol_lib (version 20231120) (generator "kicad_symbol_editor")
 (symbol "Fixture" (pin_names (offset 0))
  (property "Reference" "R" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
  (property "Value" "Fixture" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
  (symbol "Fixture_1_1"
   (rectangle (start -2 1) (end 2 -1) (stroke (width 0.254) (type default)) (fill (type none)))
   (pin passive line (at -5.08 0 0) (length 3.08) (name "A" (effects (font (size 1 1)))) (number "1" (effects (font (size 1 1)))))
   (pin passive line (at 5.08 0 180) (length 3.08) (name "B" (effects (font (size 1 1)))) (number "2" (effects (font (size 1 1))))))))
'''
SCH='''(kicad_sch (version 20250114) (generator "eeschema") (paper "A4")
 (lib_symbols (symbol "Fixture:Fixture" (pin_names (offset 0))
  (property "Reference" "R" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
  (property "Value" "Fixture" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
  (symbol "Fixture_1_1"
   (rectangle (start -2 1) (end 2 -1) (stroke (width 0.254) (type default)) (fill (type none)))
   (pin passive line (at -5.08 0 0) (length 3.08) (name "A" (effects (font (size 1 1)))) (number "1" (effects (font (size 1 1)))))
   (pin passive line (at 5.08 0 180) (length 3.08) (name "B" (effects (font (size 1 1)))) (number "2" (effects (font (size 1 1))))))))
 (symbol (lib_id "Fixture:Fixture") (at 40 60 90) (unit 1) (uuid "fixture-uuid")
  (property "Reference" "R1" (at 40 52 0) (effects (font (size 1.27 1.27))))
  (property "Value" "10k" (at 40 68 0) (effects (font (size 1.27 1.27))))))
'''

class NativeGeometryTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=pathlib.Path(t.name);(self.root/'working.kicad_sch').write_text(SCH,encoding='utf-8')
        (self.root/'Fixture.kicad_sym').write_text(SYM,encoding='utf-8')
        self.protected={'*':[{'id':'worksheet-title','kind':'title_block','bbox_mm':[220,166,292,208]}]}
    def test_reads_real_library_without_manual_bbox(self):
        g=symbol_geometry(self.root,self.root/'working.kicad_sch','Fixture:Fixture',1,1)
        self.assertEqual(g['geometry_level'],'NATIVE_PRIMITIVES_AND_PINS; CONSERVATIVE_FONT_ESTIMATE')
        self.assertTrue(g['symbol_body_exact_for_supported_graphics'])
        self.assertEqual([p['number'] for p in g['pins']],['1','2'])
        self.assertEqual(g['pins'][0]['outward'],[-1,0])
        self.assertAlmostEqual(g['pins'][0]['xy_mm'][0],-5.08)
        self.assertLess(g['body_bbox_mm'][0],-5.08)
        self.assertFalse(g['text_render_exact'])
    def test_library_identifier_is_metadata_not_visible_geometry(self):
        original=symbol_geometry(self.root,self.root/'working.kicad_sch','Fixture:Fixture')
        long_name='UnreasonablyLongLibrarySymbolIdentifierWithNoDisplayedText'
        lib=SYM.replace('(symbol "Fixture"',f'(symbol "{long_name}"').replace('Fixture_1_1',f'{long_name}_1_1')
        (self.root/'Fixture.kicad_sym').write_text(lib, encoding="utf-8")
        (self.root/'empty.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))', encoding="utf-8")
        other=symbol_geometry(self.root,self.root/'empty.kicad_sch',f'Fixture:{long_name}',library_file='Fixture.kicad_sym')
        self.assertEqual(original['body_bbox_mm'],other['body_bbox_mm'])
        self.assertEqual([f['bbox_mm'] for f in original['fields']],[f['bbox_mm'] for f in other['fields']])
        self.assertNotIn('lib_id',{f['name'] for f in other['fields']})
        self.assertNotIn(f'Fixture:{long_name}',[f['text'] for f in other['fields']])

    def test_unset_value_inherits_actual_native_value_not_identifier_suffix(self):
        long_name='VeryLongSymbolNameNotPrintedInSchematic'
        lib=SYM.replace('(symbol "Fixture"',f'(symbol "{long_name}"').replace('Fixture_1_1',f'{long_name}_1_1')
        (self.root/'Fixture.kicad_sym').write_text(lib, encoding="utf-8")
        (self.root/'empty.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))', encoding="utf-8")
        topo={('R1','1'):'SIG',('R1','2'):'GND'}
        g=prospective_geometry(self.root,self.root/'empty.kicad_sch',
          {'ref':'R1','lib_id':f'Fixture:{long_name}','library_file':'Fixture.kicad_sym'},topo,5.0)
        self.assertEqual({f['name']:f['text'] for f in g['fields']},{'Reference':'R1','Value':'Fixture'})
        placed=placements({'ref':'R1','geometry':g},(50,50),0,5,0.4)
        self.assertEqual({n for n,b in placed['objects']},{'body','field:Reference','field:Value'})
        self.assertNotIn('lib_id',str(placed['objects']))
        self.assertLess(max(b[2]-b[0] for n,b in placed['objects']),22)
        with self.assertRaisesRegex(ValueError,'Visible Value must be'):
            prospective_geometry(self.root,self.root/'empty.kicad_sch',
              {'ref':'R1','lib_id':f'Fixture:{long_name}','library_file':'Fixture.kicad_sym','value':42},topo,5.0)

    def test_hidden_native_value_does_not_block_placement_space(self):
        hidden=SYM.replace('(property "Value" "Fixture" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))',
                           '(property "Value" "Fixture" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))')
        (self.root/'Fixture.kicad_sym').write_text(hidden, encoding="utf-8")
        (self.root/'empty.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))', encoding="utf-8")
        topo={('R1','1'):'SIG',('R1','2'):'GND'}
        g=prospective_geometry(self.root,self.root/'empty.kicad_sch',
          {'ref':'R1','lib_id':'Fixture:Fixture','library_file':'Fixture.kicad_sym'},topo,5.0)
        self.assertTrue(next(f for f in g['fields'] if f['name']=='Value')['hidden'])
        placed=placements({'ref':'R1','geometry':g},(50,50),0,5,0.4)
        self.assertEqual([n for n,b in placed['objects']],['body','field:Reference'])
        self.assertEqual(len(g['pins']),2)

    def test_instance_lib_id_not_in_rendered_collision_boxes(self):
        one=snapshot(self.root,'working.kicad_sch',self.protected)['pages']['working.kicad_sch']['objects'][0]
        expanded=SCH.replace('Fixture:Fixture','Fixture:AnExtremelyLongSymbolLibraryIdentifier')
        (self.root/'other.kicad_sch').write_text(expanded, encoding="utf-8")
        two=snapshot(self.root,'other.kicad_sch',self.protected)['pages']['other.kicad_sch']['objects'][0]
        self.assertEqual(one['bbox_mm'],two['bbox_mm'])
        self.assertEqual(one['collision_boxes_mm'],two['collision_boxes_mm'])

    def test_resolve_before_placement_from_actual_kicad_sym(self):
        (self.root/'empty.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))', encoding="utf-8")
        g=symbol_geometry(self.root,self.root/'empty.kicad_sch','Fixture:Fixture',1,1,'Fixture.kicad_sym')
        self.assertEqual(len(g['pins']),2)
        self.assertEqual(g['source']['file'],'Fixture.kicad_sym')
    def test_installed_library_env_resolves_without_per_symbol_file(self):
        (self.root/'empty.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))', encoding="utf-8")
        with patch.dict('os.environ',{'KICAD10_SYMBOL_DIR':str(self.root)}):
            g=symbol_geometry(self.root,self.root/'empty.kicad_sch','Fixture:Fixture')
        self.assertEqual(len(g['pins']),2)

    def test_project_symbol_table_uri_resolves_before_placement(self):
        (self.root/'empty.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))', encoding="utf-8")
        (self.root/'sym-lib-table').write_text('(sym_lib_table (lib (name "Fixture") (type "KiCad") (uri "${KIPRJMOD}/Fixture.kicad_sym") (options "") (descr "")))', encoding="utf-8")
        g=symbol_geometry(self.root,self.root/'empty.kicad_sch','Fixture:Fixture')
        self.assertEqual([x['number'] for x in g['pins']],['1','2'])

    def test_real_placed_rotation_90_maps_pin_left_to_bottom(self):
        t=parse(SCH);instance=children(t,'symbol')[0]
        native=symbol_geometry(self.root,self.root/'working.kicad_sch','Fixture:Fixture',1,1)
        obj=placed_instance_geometry(instance,native)
        pins={p['number']:p for p in obj['pins']}
        self.assertEqual(pins['1']['at_mm'],[40.,65.08])
        self.assertEqual(pins['1']['outward'],[0.,1.])
        self.assertEqual(pins['2']['at_mm'],[40.,54.92])
        self.assertGreater(obj['bbox_mm'][2],obj['bbox_mm'][0])
        self.assertEqual(obj['rotation_deg'],90)
    def test_mirrored_symbol_flips_pin_and_extent(self):
        t=parse(SCH);inst=children(t,'symbol')[0]
        inst.insert(3,['mirror','x'])
        native=symbol_geometry(self.root,self.root/'working.kicad_sch','Fixture:Fixture')
        obj=placed_instance_geometry(inst,native)
        pin={p['number']:p for p in obj['pins']}
        self.assertEqual(pin['1']['at_mm'],[40.,54.92])
        self.assertEqual(pin['1']['outward'],[0.,-1.])
    def test_snapshot_reads_instance_and_text_without_render_stub(self):
        result=snapshot(self.root,'working.kicad_sch',self.protected)
        pg=result['pages']['working.kicad_sch']
        self.assertEqual(len(pg['objects']),1)
        self.assertTrue(pg['complete_object_inventory'])
        self.assertGreater(len(pg['objects'][0]['collision_boxes_mm']),1)
        self.assertEqual(pg['objects'][0]['kind'],'symbol')
        self.assertFalse(result['text_render_exact'])
    def test_automatic_evidence_without_manual_geometry_file_or_svg(self):
        plan={'schema_version':1,'geometry_mode':'native_auto','schematic':'working.kicad_sch',
              'schematic_sha256':sha(self.root/'working.kicad_sch'),
              'protected_regions_by_page':self.protected,'page':'working.kicad_sch'}
        result=evidence(self.root,plan)
        self.assertEqual(len(result['page']['obstacles']),4) # body + 2 fields + worksheet
        self.assertIn('NATIVE_PRIMITIVES_AUTO',result['evidence_level'])
        self.assertEqual(len(result['geometry_sha256']),64)
    def test_unresolved_symbol_blocks_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError,'not located'):
            symbol_geometry(self.root,self.root/'working.kicad_sch','Device:NotPresent')
    def test_arcs_and_curves_bound_extrema_not_endpoints_only(self):
        b=_arc_bbox((1,0),(0,1),(-1,0))
        self.assertAlmostEqual(b[3],1.)
        q=_bezier_bbox([(0,0),(0,10),(10,10),(10,0)])
        self.assertGreater(q[3],7)
        self.assertLess(q[3],10)
    def test_missing_protected_title_is_separate_from_component_geometry(self):
        with self.assertRaisesRegex(ValueError,'title block'):
            snapshot(self.root,'working.kicad_sch',{'*':[]})
    def test_unknown_graphic_blocks(self):
        s=SYM.replace('(rectangle (start', '(polygon (start')
        (self.root/'Fixture.kicad_sym').write_text(s, encoding="utf-8")
        (self.root/'empty.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            symbol_geometry(self.root,self.root/'empty.kicad_sch','Fixture:Fixture',library_file='Fixture.kicad_sym')

class NativePrePlacementTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=pathlib.Path(t.name)
        (self.root/'main.kicad_sch').write_text('(kicad_sch (paper "A4") (lib_symbols))',encoding='utf-8')
        (self.root/'Fixture.kicad_sym').write_text(SYM,encoding='utf-8')
        (self.root/'basis.txt').write_text('Independent pin-to-net graph, fixture only', encoding="utf-8")
        self.topo={'schema_version':1,'source':{'file':'basis.txt','sha256':sha(self.root/'basis.txt'),'locator':'test fixture'},
                   'pins':[{'ref':r,'pin':p,'net':n} for r in ('R1','R2') for p,n in (('1','GND' if r=='R1' else 'SIG'),('2','SIG' if r=='R1' else 'GND'))]}
        (self.root/'topo.json').write_text(json.dumps(self.topo), encoding="utf-8")
        self.req={'schema_version':1,'schematic':'main.kicad_sch','schematic_sha256':sha(self.root/'main.kicad_sch'),
                  'geometry_mode':'native_auto','protected_regions_by_page':{'*':[{'id':'title','kind':'title_block','bbox_mm':[220,165,292,208]}]},
                  'page':'main.kicad_sch','topology_file':'topo.json','topology_sha256':sha(self.root/'topo.json'),
                  'grid_mm':2.5,'clearance_mm':1.0,'pin_escape_mm':5.0,'wire_corridor_width_mm':0.6,'power_rails':['GND'],
                  'symbols':[
                       {'ref':'R1','lib_id':'Fixture:Fixture','library_file':'Fixture.kicad_sym','value':'10k',
                        'labels':[{'pin':'1','kind':'power'}],'candidate_positions_mm':[[40,40]],'rotations_deg':[0,90]},
                       {'ref':'R2','lib_id':'Fixture:Fixture','library_file':'Fixture.kicad_sym','value':'10k',
                        'labels':[{'pin':'2','kind':'power'}],'candidate_positions_mm':[[110,40]],'rotations_deg':[0,90]}],
                  'connections':[{'net':'SIG','from':['R1','2'],'to':['R2','1']}],
                  'max_candidate_positions':40,'search_budget':1000}
    def test_real_source_symbols_plan_without_manual_geometry_and_render(self):
        r=layout(self.root,self.req)
        self.assertEqual(r['status'],'PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY',r)
        self.assertEqual(r['geometry_mode'],'native_auto')
        self.assertEqual([p for p in r['placements']],['R1','R2'])
        self.assertEqual(r['external_bindings'],{})
        self.assertFalse(r['executed'])
    def test_changed_native_library_invalidates_preflight_receipt(self):
        r=layout(self.root,self.req)
        (self.root/'request.json').write_text(json.dumps(self.req), encoding="utf-8")
        r['request_sha256']=sha(self.root/'request.json')
        (self.root/'03_REPORTS').mkdir()
        (self.root/'03_REPORTS/receipt.json').write_text(json.dumps(r), encoding="utf-8")
        self.assertTrue(authorize(self.root,'request.json',self.root/'03_REPORTS/receipt.json')['allow_placement_batch'])
        (self.root/'Fixture.kicad_sym').write_text(SYM+'\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'Pre-placement source changed'):
            authorize(self.root,'request.json',self.root/'03_REPORTS/receipt.json')
    def test_wrong_native_pin_number_stops_before_writing(self):
        self.topo['pins'].append({'ref':'R1','pin':'3','net':'X'})
        (self.root/'topo.json').write_text(json.dumps(self.topo), encoding="utf-8")
        self.req['topology_sha256']=sha(self.root/'topo.json')
        with self.assertRaisesRegex(ValueError,'extraneous pins'):
            layout(self.root,self.req)
    def test_native_symbol_collision_with_title_block(self):
        self.req['symbols'][0]['candidate_positions_mm']=[[240,180]]
        r=layout(self.root,self.req)
        self.assertEqual(r['status'],'BLOCKED')

if __name__=='__main__':unittest.main()
