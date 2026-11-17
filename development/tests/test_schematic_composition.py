import unittest, tempfile, json, hashlib, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'
sys.path.insert(0,str(ROOT/'scripts'))
from npi_common import sha256
from schematic_style import audit, plan_partition

class CompTest(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=pathlib.Path(self.t.name)
  self.doc=self.root/'main.kicad_sch'
  self.doc.write_text('''(kicad_sch (paper "A4")
(symbol (lib_id "power:+12V") (property "Reference" "#PWR01") (property "Value" "+12V") (uuid "p1"))
(symbol (lib_id "power:GND") (property "Reference" "#PWR02") (property "Value" "GND") (uuid "p2"))
(symbol (lib_id "Device:R") (property "Reference" "R1") (property "Value" "10k") (uuid "r1"))
(polyline (uuid "f1")) (polyline (uuid "f2")))''')
  self.view=self.root/'main.svg';self.view.write_text('<svg>sample rendered evidence placeholder for geometry review</svg>')
  self.boxes=[{'uuid':'p1','kind':'symbol','bbox_mm':[20,20,28,35]},
              {'uuid':'p2','kind':'symbol','bbox_mm':[20,45,28,60]},
              {'uuid':'r1','kind':'symbol','bbox_mm':[65,25,72,40]},
              {'uuid':'f1','kind':'polyline','bbox_mm':[15,15,95,70]},
              {'uuid':'f2','kind':'polyline','bbox_mm':[110,15,190,70]}]
 def go(self,modify=None):
  geometry={'schema_version':1,'pages':{'main.kicad_sch':{
   'schematic_sha256':sha256(self.doc),'sheet_mm':[297,210],
   'complete_object_inventory':True,'visible_fields_included':True,
   'protected_regions':[{'id':'document-title','kind':'title_block','bbox_mm':[220,175,291,207]}],
   'objects':self.boxes}}}
  p=self.root/'geometry.json';p.write_text(json.dumps(geometry))
  composition={'schema_version':1,'required':True,'geometry':{'file':p.name,'sha256':sha256(p),'evidence_file':self.view.name,'evidence_sha256':sha256(self.view),'locator':'sample fixture view'},'power':{'rails':['+12V','GND']},'partition':{'mode':'auto','modules':[{'id':'supply','page':self.doc.name,'frame_uuid':'f1'},{'id':'logic','page':self.doc.name,'frame_uuid':'f2'}], 'max_occupancy':0.75}}
  if modify:modify(composition,geometry)
  q=self.root/'style.json';q.write_text(json.dumps({'schema_version':1,'pages':{},'composition':composition}))
  return audit(self.root,'main.kicad_sch','style.json')
 def test_good_project_still_needs_visual_review(self):
  a=self.go();self.assertEqual(a['findings'],[]);self.assertEqual(a['status'],'DECLARED_STRUCTURE_CHECKS_COMPLETE');self.assertIn('GEOMETRY_SCREENED_REQUIRES_RENDER_REVIEW',[x.get('status') for x in a['checks']]);self.assertFalse(a['production_authorized'])
 def test_title_block_overlap(self):
  self.boxes[2]['bbox_mm']=[230,180,250,205]
  r=self.go();self.assertIn('TITLE_BLOCK_CLEAR',[x['rule'] for x in r['findings']]);self.assertEqual(r['status'],'BLOCKED')
 def test_missing_power_symbol(self):
  r=self.go(lambda q,g:q['power'].update(rails=['+12V','GND','+5V']))
  self.assertIn('POWER_SYMBOL_POLICY.MISSING',[x['rule'] for x in r['findings']])
 def test_single_page_missing_module_frame(self):
  r=self.go(lambda q,g:q['partition']['modules'][1].update(frame_uuid='no-frame'))
  self.assertIn('SHEET_PARTITION_POLICY.FRAME',[x['rule'] for x in r['findings']])
 def test_declared_hierarchy_without_pages(self):
  r=self.go(lambda q,g:q['partition'].update(mode='hierarchical'))
  self.assertIn('SHEET_PARTITION_POLICY.MODE',[x['rule'] for x in r['findings']])
 def test_stale_geometry(self):
  r=self.go(lambda q,g:None);self.doc.write_text(self.doc.read_text()+'\n');r=audit(self.root,self.doc.name,'style.json');self.assertIn('COMPOSITION.STALE_SCHEMATIC',[x['rule'] for x in r['findings']])
 def test_incomplete_object_coverage(self):
  self.boxes=self.boxes[:-1]
  r=self.go();self.assertIn('TITLE_BLOCK_CLEAR.INCOMPLETE',[x['rule'] for x in r['findings']])
 def test_native_rail_label_is_not_a_power_symbol(self):
  self.doc.write_text(self.doc.read_text().replace('"r1"))','"r1")) (label "+12V" (uuid "lab1"))'))
  self.boxes.append({'uuid':'lab1','kind':'label','bbox_mm':[90,20,105,28]})
  r=self.go();self.assertIn('POWER_SYMBOL_POLICY.LABEL',[x['rule'] for x in r['findings']])
 def test_title_zone_is_correct_even_when_id_does_not_say_title(self):
  self.boxes[2]['bbox_mm']=[230,180,250,205]
  r=self.go();self.assertIn('TITLE_BLOCK_CLEAR',[x['rule'] for x in r['findings']])
 def test_frame_must_be_native_polyline(self):
  r=self.go(lambda q,g:q['partition']['modules'][1].update(frame_uuid='r1'))
  self.assertIn('SHEET_PARTITION_POLICY.FRAME',[x['rule'] for x in r['findings']])
 def test_no_rail_policies_is_invalid(self):
  with self.assertRaises(ValueError):self.go(lambda q,g:q['power'].update(rails=[]))
 def test_plan_small_modules_one_sheet(self):
  r=plan_partition({'schema_version':1,'paper':'A4','protected_regions':[{'bbox_mm':[220,165,292,207]}],
   'modules':[{'id':'input','estimated_box_mm':[50,35]},{'id':'core','estimated_box_mm':[60,50]}],
   'cross_module_connections':4})
  self.assertEqual(r['recommended_mode'],'single');self.assertFalse(r['production_authorized'])
 def test_plan_dense_or_highly_coupled_splits(self):
  base={'schema_version':1,'paper':'A4','protected_regions':[{'bbox_mm':[220,165,292,207]}],
   'modules':[{'id':'input','estimated_box_mm':[85,85]},{'id':'core','estimated_box_mm':[190,180]}]}
  self.assertEqual(plan_partition(base)['recommended_mode'],'hierarchical')
  base['modules']=[{'id':'small','estimated_box_mm':[10,10]}]
  base['cross_module_connections']=15
  self.assertEqual(plan_partition(base)['recommended_mode'],'hierarchical')
 def test_plan_requires_title_reserve(self):
  with self.assertRaises(ValueError):plan_partition({'schema_version':1,'paper':'A4','modules':[{'id':'A','estimated_box_mm':[10,10]}]})
 def test_preserve_legacy_mode(self):
  (self.root/'style.json').write_text(json.dumps({'schema_version':1,'pages':{}}));r=audit(self.root,self.doc.name,'style.json');self.assertEqual(r['status'],'DECLARED_STRUCTURE_CHECKS_COMPLETE');self.assertEqual(r['checks'][-1]['status'],'NOT_CONFIGURED_LEGACY_REVIEW_REQUIRED')

if __name__=='__main__': unittest.main()
