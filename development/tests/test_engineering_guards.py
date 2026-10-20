import copy
import csv
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'
sys.path.insert(0,str(ROOT/'scripts'))
import netlist_guard as ng
import link_audit as la
import engineering_gate as eg
from npi_common import sha256,finite_tree
from mass_production_review import Review
from assembly_guard import read_bom,grouped,check_cpl
from pad_audit import signed_gap
from freeze_candidate import freeze
from validate_frozen_candidate import validate

class GuardTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.p=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def xml(self,name,pin='1',net='VCC',value='10k',empty=False):
        root=ET.Element('export',version='E');comps=ET.SubElement(root,'components');c=ET.SubElement(comps,'comp',ref='U1')
        ET.SubElement(c,'value').text=value;ET.SubElement(c,'footprint').text='Package:Part'
        fields=ET.SubElement(c,'fields');ET.SubElement(fields,'field',name='MPN').text='PART-001'
        nets=ET.SubElement(root,'nets')
        if not empty:ET.SubElement(ET.SubElement(nets,'net',code='1',name=net),'node',ref='U1',pin=pin,pintype='passive')
        p=self.p/name;p.write_bytes(ET.tostring(root));return p
    def test_invalid_inputs_cli_exit_2(self):
        a=self.p/'a';b=self.p/'b';a.write_text('(export (nets))');b.write_text('not a netlist')
        r=subprocess.run([sys.executable,str(ROOT/'scripts/netlist_guard.py'),str(a),str(b)],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertEqual(json.loads(r.stdout)['status'],'BLOCKED')
    def test_changed_pin_cli_exit_1(self):
        a=self.xml('a.xml');b=self.xml('b.xml',pin='2')
        r=subprocess.run([sys.executable,str(ROOT/'scripts/netlist_guard.py'),str(a),str(b)],capture_output=True,text=True)
        self.assertEqual(r.returncode,1)
    def test_zero_networks_need_explicit_opt_in(self):
        a=self.xml('a.xml',empty=True);b=self.xml('b.xml',empty=True)
        with self.assertRaises(ng.InvalidNetlist):ng.compare(a,b)
        self.assertEqual(ng.compare(a,b,allow_zero_nets=True)['status'],'PASS')
    def test_unconnected_pin_changes_are_not_ignored(self):
        a=self.xml('a.xml',net='unconnected-U1');b=self.xml('b.xml',net='unconnected-U1',pin='2')
        self.assertEqual(ng.compare(a,b)['status'],'FAIL')
    def test_component_attributes_not_just_topology(self):
        a=self.xml('a.xml');b=self.xml('b.xml',value='20k')
        self.assertEqual(ng.compare(a,b,topology=True)['status'],'FAIL')
    def test_topology_rename_and_exact_eco(self):
        a=self.xml('a.xml');b=self.xml('b.xml',net='/Power/VCC')
        self.assertEqual(ng.compare(a,b,topology=True)['status'],'PASS')
        actual=ng.compare(a,b)['actual_changes']
        eco={'id':'ECO-1','reason':'rename','approved_by':'fixture','impact':'net name','baseline_sha256':sha256(a),'expected_changes':actual}
        self.assertEqual(ng.compare(a,b,'eco',eco=eco)['status'],'PASS')
        c=self.xml('c.xml',net='/Power/VCC',value='wrong')
        self.assertEqual(ng.compare(a,c,'eco',eco=eco)['status'],'FAIL')
    def test_equal_drc_count_does_not_hide_new_identity(self):
        a={'type':'clearance','items':[{'uuid':'a','pos':[1,2]}]};b={'type':'clearance','items':[{'uuid':'b','pos':[1,2]}]}
        self.assertEqual(eg.new_violations([a],[b]),[b])
    def model(self):
        board={'footprints':[{'ref':'U1','pads':[{'number':'1','net':'P','pos':(0,0)}]}, {'ref':'J1','pads':[{'number':'1','net':'P','pos':(2,0)}]}]}
        edges=[{'id':'a','kind':'arc','net':'P','a':(0,0,'F.Cu'),'b':(2,0,'F.Cu'),'length_mm':la.arc_length((0,0),(1,1),(2,0)),'layer':'F.Cu'}]
        spec={'id':'P1','net':'P','start':{'ref':'U1','pad':'1','layer':'F.Cu'},'end':{'ref':'J1','pad':'1','layer':'F.Cu'},'source':{'document':'fixture','revision':'1','section':'1'},'reference_planes':['B.Cu'],'allowed_layers':['F.Cu'],'delay_ps_per_mm':{'F.Cu':6},'max_length_mm':4,'max_delay_ps':25,'max_vias':0}
        return board,edges,spec
    def test_arc_is_length_not_a_via(self):
        b,e,s=self.model();r=la.audit_path(b,e,s)
        self.assertAlmostEqual(r['length_mm'],math.pi);self.assertEqual(r['transitions'],[])
    def test_missing_net_blocks(self):
        b,e,s=self.model();s['net']='missing'
        with self.assertRaises(ValueError):la.audit_path(b,e,s)
    def test_duplicate_primitive_blocks(self):
        b,e,s=self.model()
        with self.assertRaises(ValueError):la.audit_path(b,e+e,s)
    def test_branch_or_disconnected_segment_blocks(self):
        b,e,s=self.model();e.append({'id':'stub','kind':'segment','net':'P','a':(0,0,'F.Cu'),'b':(3,3,'F.Cu'),'length_mm':4,'layer':'F.Cu'})
        with self.assertRaises(ValueError):la.audit_path(b,e,s)
    def test_nonfinite_delay_is_not_false_pass(self):
        b,e,s=self.model();s['delay_ps_per_mm']['F.Cu']=float('nan')
        with self.assertRaises(ValueError):la.audit_path(b,e,s)
        with self.assertRaises(ValueError):finite_tree({'process':{'width':float('nan')}})
    def test_rotated_pad_long_axis_is_not_pitch_axis(self):
        a={'shape':'rect','pos':(0,0),'size':(2,.3),'angle':90}
        b={**a,'pos':(1,0)}
        self.assertGreater(signed_gap(a,b),0)
        self.assertLess(signed_gap({**a,'angle':0},{**b,'angle':0}),0)
    def test_missing_and_open_courtyard_block(self):
        for content in ['','(fp_line (start 0 0) (end 1 0) (layer "F.CrtYd"))']:
            f=self.p/'b.kicad_pcb';f.write_text('(kicad_pcb (footprint "F" (property "Reference" "U1") '+content+'))')
            r=Review({},'mass_production','pre_export');eg.inspect_courtyards(r,f,{},self.p)
            self.assertTrue(any(x['rule']=='ENG.COURTYARD' for x in r.findings))
    def bom(self):
        f=self.p/'bom.csv'
        f.write_text('Reference,MPN,Manufacturer,Footprint,Specification,Variant,DNP,Supplier,ApprovedAlternatives\nR1,PART-A,MFG,0402,10k 1%,default,no,SUP,NONE\nR2,PART-B,MFG,0402,10k 1%,default,no,SUP,NONE\nR3,PART-A,MFG,0402,10k 1%,default,yes,SUP,NONE\n')
        return f
    def test_bom_mpn_and_dnp_not_merged(self):
        self.assertEqual(len(grouped(read_bom(self.bom()))),3)
    def test_cpl_must_exactly_match_fitted_variant(self):
        c=self.p/'cpl.csv';c.write_text('Reference,PosX,PosY,Rotation,Side\nR1,1,2,0,Top\nR2,2,2,90,Bottom\n')
        self.assertEqual(check_cpl(read_bom(self.bom()),c,'default')['status'],'PASS')
        with c.open('a') as f:f.write('R3,3,2,0,Top\n')
        with self.assertRaises(ValueError):check_cpl(read_bom(self.bom()),c,'default')
    def test_freeze_preview_never_creates_or_changes_engineering_files(self):
        src=self.p/'src';src.mkdir();board=src/'b.kicad_pcb';board.write_text('fixture');digest=sha256(board)
        result=freeze(src,'b.kicad_pcb',self.p/'candidate')
        self.assertEqual(result['status'],'PREVIEW');self.assertFalse((self.p/'candidate').exists());self.assertEqual(sha256(board),digest)
    def test_stale_frozen_candidate_blocks_before_native_execution(self):
        p=self.p/'candidate';p.mkdir();(p/'b.kicad_pcb').write_text('new')
        c=p/'config.json';c.write_text(json.dumps({'inputs':{'board':'b.kicad_pcb'}}))
        (p/'freeze-log.json').write_text(json.dumps({'operations':['copy','refill','save','reload'],'candidate_sha256':'wrong'}))
        with self.assertRaises(ValueError):validate(p,c,self.p/'evidence')
        self.assertFalse((self.p/'evidence').exists())
    def build(self,gerber='not a Gerber'):
        candidate=self.p/'package';candidate.mkdir();(candidate/'a.gbr').write_text(gerber)
        auth={'reviewer':'fixture','date':'2026-10-17','factory':'F','order_scope':'TEST ONLY'}
        manifest={'level':'D2','production_authorization':auth,'source_sha256':{},'output_sha256':{'a.gbr':sha256(candidate/'a.gbr')}}
        (candidate/'build-manifest.json').write_text(json.dumps(manifest));return candidate,manifest
    def test_nonempty_fake_gerber_is_not_accepted(self):
        candidate,_=self.build();r=Review({},'mass_production','release')
        eg.inspect_production(r,self.p/'source',{'delivery_manifest':{'gerber':['a.gbr']}},{},candidate)
        self.assertTrue(any('Gerber结构' in x['description'] for x in r.findings))
    def test_d0_cannot_publish_as_d2(self):
        candidate,manifest=self.build();manifest['level']='D0';(candidate/'build-manifest.json').write_text(json.dumps(manifest))
        r=Review({},'mass_production','release');eg.inspect_production(r,self.p/'source',{}, {},candidate)
        self.assertTrue(any('D2' in x['description'] for x in r.findings))
    def test_tool_inventory_detects_changed_active_tool(self):
        clone=self.p/'clone';shutil.copytree(ROOT,clone,ignore=shutil.ignore_patterns('__pycache__'))
        tool=clone/'scripts/netlist_guard.py';tool.write_text(tool.read_text()+'\n# tampered\n')
        r=Review({},'mass_production','pre_export')
        with patch.object(eg,'__file__',str(clone/'scripts/engineering_gate.py')):eg.inspect_inventory(r)
        self.assertTrue(any(x['rule']=='TOOLS.INVENTORY' for x in r.findings))
    def test_all_25_findings_remain_traceable_and_not_falsely_closed(self):
        data=json.loads((ROOT.parent/'development/history/repair-status.json').read_text())
        self.assertEqual({x['id'] for x in data['items']},{f'R{x:02d}' for x in range(1,26)})
        self.assertFalse(data['production_ready'])

if __name__=='__main__':unittest.main()
