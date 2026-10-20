import copy
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow';sys.path.insert(0,str(ROOT/'scripts'))
from design_intent import prepare,compile_intent,power_budget,stackup_digest,layout_digest
from design_intent_audit import audit
from npi_common import parse_sexpr,sha256

def fixture(root):
    root.mkdir(exist_ok=True)
    (root/'review.txt').write_text('TEST FIXTURE ONLY — not engineering approval or manufacturing data')
    approve={'reviewer':'TEST','date':'2026-10-17','reason':'UNIT TEST ONLY',
             'source':{'document':'TEST','revision':'0','section':'fixture'},
             'evidence':[{'file':'review.txt','sha256':sha256(root/'review.txt')}]}
    names=['USB0_P','USB0_N','CSI0_D0_P','CSI0_D0_N','VDD_TEST','RF_FEED']
    labels=[];nets=[]
    for i,name in enumerate(names):
        uid=str(uuid.uuid5(uuid.NAMESPACE_DNS,'test:'+name));cls='USB' if i<2 else 'MIPI' if i<4 else 'POWER' if i==4 else 'RF'
        kind='differential' if i<4 else 'power' if i==4 else 'rf'
        labels.append(f'(label "{name}" (at {10+i*5} 20 0) (effects (font (size 1.27 1.27))) (uuid "{uid}"))')
        nets.append({'name':name,'netclass':cls,'kind':kind,'anchors':[{'file':'test.kicad_sch','label_uuid':uid}]})
    (root/'test.kicad_sch').write_text('(kicad_sch (version 20260101) (generator "eeschema") (uuid "'+str(uuid.uuid4())+'") (paper "A4") (lib_symbols) '+'\n'.join(labels)+')')
    (root/'test.kicad_pro').write_text(json.dumps({'meta':{'version':3},'net_settings':{'meta':{'version':5},'classes':[{'name':'Default','priority':2147483647}],'netclass_patterns':[]}}))
    tracks=[];ns=[]
    for i,name in enumerate(names,1):
        ns.append(f'(net {i} "{name}")');w=.6 if name=='VDD_TEST' else .25
        tracks.append(f'(segment (start 10 {i*3}) (end 20 {i*3}) (width {w}) (layer "F.Cu") (net {i}) (uuid "{uuid.uuid4()}"))')
    board='(kicad_pcb (version 20260101) (generator "pcbnew") (general (thickness 1.6)) (layers (0 "F.Cu" signal) (2 "B.Cu" signal)) (setup (stackup (layer "F.Cu" (type "copper") (thickness 0.035)) (layer "dielectric 1" (type "core") (thickness 1.53) (epsilon_r 4.2)) (layer "B.Cu" (type "copper") (thickness 0.035)))) (net 0 "") (net 99 "GND") '+' '.join(ns+tracks)+' (footprint "TEST" (layer "F.Cu") (at 10 10) (property "Reference" "ANT1")) )'
    (root/'test.kicad_pcb').write_text(board);tree=parse_sexpr(board);stack=stackup_digest(tree);layout=layout_digest(tree)
    classes=[]
    for name,kind in [('USB','differential'),('MIPI','differential'),('POWER','power'),('RF','rf')]:
        g={'layer':'F.Cu','width_mm':.6 if kind=='power' else .25,'min_width_mm':.5 if kind=='power' else .24,'max_width_mm':2 if kind=='power' else .26}
        if kind!='power':g['reference_layers']=['B.Cu']
        if kind=='differential':g.update(gap_mm=.15,min_gap_mm=.14,max_gap_mm=.16)
        c={'name':name,'kind':kind,'clearance_mm':.2,'geometry':[g],'approval':copy.deepcopy(approve)}
        if kind!='power':c.update(target_impedance_ohm=90 if name=='USB' else 100 if name=='MIPI' else 50,impedance_tolerance_percent=10,stackup_sha256=stack)
        classes.append(c)
    power={'continuous_a':2,'peak_a':4,'peak_duration_ms':10,'peak_duty_cycle':.1,'ambient_c':40,'max_temp_rise_c':30,'max_conductor_c':70,
           'max_drop_v':.1,'max_peak_drop_v':.2,'max_path_length_mm':20,'thermal_min_width_mm':{'F.Cu':.5},'layer_copper_um':{'F.Cu':35},
           'path_model':'single_uniform_trace','stackup_sha256':stack,'approval':copy.deepcopy(approve),
           'layout_review':{**copy.deepcopy(approve),'layout_sha256':layout,'checks':{k:'PASS' for k in ('via_ampacity','pad_necks','copper_necks','return_path','contacts','fault_protection','transient_thermal')}}}
    nets[4]['power']=power
    nets[5]['rf']={'role':'feedline','frequency_hz':2.4e9,'power_dbm':10,'max_path_length_mm':20,'reference_net':'GND',
                   'return_review':{**copy.deepcopy(approve),'layout_sha256':layout},'matching_review':{**copy.deepcopy(approve),'layout_sha256':layout}}
    data={'schema_version':1,'project_file':'test.kicad_pro','board_file':'test.kicad_pcb','coverage':{**copy.deepcopy(approve),'critical_nets':names},'classes':classes,'nets':nets,
          'pairs':[{'id':'USB0','positive':names[0],'negative':names[1],'protocol':'USB2_HS','chain_id':'USB0','segment_index':0},
                   {'id':'CSI0_D0','positive':names[2],'negative':names[3],'protocol':'MIPI_DPHY','chain_id':'CSI0_D0','segment_index':0}],
          'regions':[{'id':'ANT_TEST','kind':'antenna_keepout','rf_net':'RF_FEED','layers':['F.Cu','B.Cu'],'polygon_mm':[[30,30],[35,30],[35,35],[30,35]],
                      'anchor':{'ref':'ANT1','position_mm':[10.,10.],'rotation_deg':0},'approval':copy.deepcopy(approve)}],
          'loops':[{'id':'TEST_LOOP','nets':['VDD_TEST'],'max_area_mm2':20,'review':{**copy.deepcopy(approve),'layout_sha256':layout,'method':'TEST measurement','measured_area_mm2':10}}]}
    (root/'intent.json').write_text(json.dumps(data));return data

def effective(root,d):
    classes={c['name']:c for c in d['classes']};out={}
    for n in d['nets']:
        c=classes[n['netclass']];g=c['geometry'][0]
        out[n['name']]={'contains_expected':True,'track_width_mm':g['width_mm'],'clearance_mm':c['clearance_mm'],
                        'diff_width_mm':g['width_mm'],'diff_gap_mm':g.get('gap_mm',0),'tuning_profile':'' if n['kind']=='power' else 'DI_'+c['name']}
    return out

class IntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'source';self.d=fixture(self.root);self.dest=self.base/'candidate'
    def tearDown(self):self.tmp.cleanup()
    def save(self): (self.root/'intent.json').write_text(json.dumps(self.d))
    def prepared(self):self.save();prepare(self.root,self.root/'intent.json',self.dest,True)
    def test_preview_has_no_file_changes(self):
        before={p.name:sha256(p) for p in self.root.iterdir()};r=prepare(self.root,self.root/'intent.json',self.dest)
        self.assertEqual(r['status'],'PREVIEW');self.assertFalse(self.dest.exists());self.assertEqual(before,{p.name:sha256(p) for p in self.root.iterdir()})
    def test_apply_generates_labels_native_classes_profiles_rules_and_keepout(self):
        before={p.name:sha256(p) for p in self.root.iterdir()};self.prepared()
        self.assertEqual(before,{p.name:sha256(p) for p in self.root.iterdir()})
        pro=json.loads((self.dest/'test.kicad_pro').read_text());self.assertEqual(len(pro['net_settings']['netclass_patterns']),6)
        profile=pro['tuning_profiles']['tuning_profiles_impedance_geometric'][0]
        self.assertEqual(profile['layer_entries'][0]['width'],250000);self.assertFalse(profile['enable_time_domain_tuning'])
        self.assertIn('(property "Net Class" "USB"',(self.dest/'test.kicad_sch').read_text())
        self.assertIn('(constraint track_width (min 0.5mm)',(self.dest/'test.kicad_dru').read_text())
        self.assertIn('(copperpour not_allowed)',(self.dest/'test.kicad_pcb').read_text())
    def test_complete_contract_with_test_native_provider(self):
        self.prepared();r=audit(self.dest,self.dest/'intent.json',True,effective)
        self.assertEqual(r['findings'],[]);self.assertEqual(r['status'],'PASS');self.assertFalse(r['production_authorized'])
    def test_static_or_missing_native_never_authorizes(self):
        self.prepared();r=audit(self.dest,self.dest/'intent.json',False)
        self.assertIn('INTENT.STATIC',{i['rule'] for i in r['findings']})
    def test_width_below_approved_thermal_or_drop_bound_is_rejected(self):
        self.d['classes'][2]['geometry'][0]['min_width_mm']=.1
        with self.assertRaisesRegex(ValueError,'below DC'):compile_intent(self.root,self.d)
    def test_current_alone_is_not_ampacity_approval(self):
        self.d['nets'][4]['power'].pop('thermal_min_width_mm')
        with self.assertRaises(ValueError):compile_intent(self.root,self.d)
    def test_power_model_units_and_peak_drop(self):
        p=self.d['nets'][4]['power'];b=power_budget(p)['F.Cu']
        expected=1.724e-8*(1+.00393*50)*20*2*1e6/(35*.1)
        self.assertAlmostEqual(b['dc_min_width_mm'],expected);self.assertEqual(b['required_min_width_mm'],.5)
        p['max_peak_drop_v']=.01;self.assertGreater(power_budget(p)['F.Cu']['required_min_width_mm'],.5)
    def test_negative_operating_ambient_is_supported(self):
        self.d['nets'][4]['power']['ambient_c']=-40;power_budget(self.d['nets'][4]['power'])
    def test_unpaired_or_inconsistent_pair_is_rejected(self):
        self.d['pairs'].pop()
        with self.assertRaisesRegex(ValueError,'Unpaired'):compile_intent(self.root,self.d)
    def test_cphy_cannot_be_accepted_as_two_wire_differential(self):
        self.d['pairs'][1]['protocol']='MIPI_CPHY'
        with self.assertRaisesRegex(ValueError,'C-PHY'):compile_intent(self.root,self.d)
    def test_bottom_signal_gets_top_reference_in_native_profile(self):
        g=self.d['classes'][3]['geometry'][0];g['layer']='B.Cu';g['reference_layers']=['F.Cu']
        p=compile_intent(self.root,self.d)['proposed']['test.kicad_pro'];profiles=json.loads(p)['tuning_profiles']['tuning_profiles_impedance_geometric']
        g=next(p for p in profiles if p['profile_name']=='DI_RF')['layer_entries'][0]
        self.assertEqual(g['top_reference_layer'],'F.Cu');self.assertEqual(g['bottom_reference_layer'],'UNDEFINED')
    def test_pre_route_defers_routed_completeness_without_granting_release(self):
        self.prepared();p=self.dest/'test.kicad_pcb'
        from design_intent import spans
        raw=p.read_text()
        for a,b in reversed(spans(raw)):
            if parse_sexpr(raw[a:b])[0]=='segment':raw=raw[:a]+raw[b:]
        p.write_text(raw)
        r=audit(self.dest,self.dest/'intent.json',True,effective,phase='pre_route')
        self.assertEqual(r['status'],'PASS');self.assertTrue(r['deferred']);self.assertFalse(r['production_authorized'])
        r=audit(self.dest,self.dest/'intent.json',True,effective)
        self.assertIn('INTENT.UNROUTED',{i['rule'] for i in r['findings']})
    def test_stale_stackup_is_rejected(self):
        self.d['classes'][0]['stackup_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'stackup'):compile_intent(self.root,self.d)
    def test_missing_anchor_or_conflicting_label_blocks(self):
        self.d['nets'][0]['anchors'][0]['label_uuid']=str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError,'Missing schematic'):compile_intent(self.root,self.d)
    def test_net_name_renaming_not_implicit(self):
        self.d['nets'][4]['name']='OTHER_POWER';self.d['coverage']['critical_nets'][4]='OTHER_POWER'
        with self.assertRaisesRegex(ValueError,'renaming requires ECO'):compile_intent(self.root,self.d)
    def test_effective_override_is_detected(self):
        self.prepared()
        def bad(root,d):
            out=effective(root,d);out['USB0_P']['diff_gap_mm']=.9;return out
        r=audit(self.dest,self.dest/'intent.json',True,bad);self.assertIn('INTENT.EFFECTIVE',{i['rule'] for i in r['findings']})
    def test_generated_rule_tamper_is_detected(self):
        self.prepared();p=self.dest/'test.kicad_dru';p.write_text(p.read_text().replace('(min 0.5mm)','(min 0.05mm)'))
        r=audit(self.dest,self.dest/'intent.json',True,effective);self.assertEqual(r['status'],'BLOCKED')
    def test_disabled_tuning_geometry_check_is_detected(self):
        self.prepared();p=self.dest/'test.kicad_pro';d=json.loads(p.read_text());d['board']['design_settings']['rule_severities']['tuning_profile_track_geometries']='ignore';p.write_text(json.dumps(d))
        r=audit(self.dest,self.dest/'intent.json',True,effective);self.assertIn('INTENT.NOT_APPLIED',{i['rule'] for i in r['findings']})
    def test_antenna_movement_invalidates_keepout_and_layout_evidence(self):
        self.prepared();p=self.dest/'test.kicad_pcb';p.write_text(p.read_text().replace('(at 10 10)','(at 11 10)'))
        r=audit(self.dest,self.dest/'intent.json',True,effective);codes={i['rule'] for i in r['findings']}
        self.assertIn('RF.ANCHOR',codes);self.assertIn('POWER.LAYOUT',codes);self.assertIn('RF.REVIEW',codes)
    def test_wrong_keepout_layer_or_allowed_copper_blocks(self):
        self.prepared();p=self.dest/'test.kicad_pcb';p.write_text(p.read_text().replace('(copperpour not_allowed)','(copperpour allowed)'))
        r=audit(self.dest,self.dest/'intent.json',True,effective);self.assertIn('RF.KEEPOUT',{i['rule'] for i in r['findings']})
    def test_thin_actual_power_segment_blocks(self):
        self.prepared();p=self.dest/'test.kicad_pcb';p.write_text(p.read_text().replace('(width 0.6)','(width 0.1)'))
        r=audit(self.dest,self.dest/'intent.json',True,effective);self.assertIn('INTENT.WIDTH',{i['rule'] for i in r['findings']})
    def test_missing_declared_critical_network_blocks(self):
        self.d['coverage']['critical_nets'].append('MISSING')
        with self.assertRaisesRegex(ValueError,'inventory'):compile_intent(self.root,self.d)
    def test_nan_path_traversal_duplicate_apply_and_old_rule_preservation(self):
        self.d['nets'][4]['power']['continuous_a']=float('nan')
        with self.assertRaises(ValueError):compile_intent(self.root,self.d)
        self.d=fixture(self.root);self.d['project_file']='../outside.kicad_pro'
        with self.assertRaises(ValueError):compile_intent(self.root,self.d)
        self.d=fixture(self.root);(self.root/'test.kicad_dru').write_text('(version 1)\n# ORIGINAL RULES\n')
        self.prepared();self.assertIn('# ORIGINAL RULES',(self.dest/'test.kicad_dru').read_text())
        with self.assertRaises(ValueError):prepare(self.root,self.root/'intent.json',self.dest,True)

if __name__=='__main__':unittest.main()
