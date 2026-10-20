import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow';sys.path.insert(0,str(ROOT/'scripts'))
from native_report import extract
from mass_production_review import Review,bom_checks
from production_contract import records,cam_checks,CAM_CHECKS
from npi_common import sha256
import npi_release

class EvidenceTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.p=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def native(self,kind):
        d={'$schema':'https://schemas.kicad.org/'+kind+'.v1.json','kicad_version':'10.0.7','coordinate_units':'mm',
           'source':'board.'+('kicad_pcb' if kind=='drc' else 'kicad_sch'),'included_severities':['error','warning','exclusion'],'ignored_checks':[]}
        if kind=='drc':d.update(violations=[],unconnected_items=[],schematic_parity=[])
        else:d['sheets']=[{'path':'/','violations':[]}]
        return d
    def test_incomplete_native_report_never_becomes_zero_violations(self):
        for report in [{'violations':[]},{'violations':''}]:
            with self.assertRaises(ValueError):extract('drc',report,'board.kicad_pcb')
    def test_complete_supported_native_shape_and_all_coverage(self):
        data=self.native('drc');self.assertEqual(extract('drc',data,'board.kicad_pcb'),[])
        for key in ('unconnected_items','schematic_parity','included_severities','ignored_checks'):
            broken=dict(data);broken.pop(key)
            with self.assertRaises(ValueError):extract('drc',broken,'board.kicad_pcb')
    def test_wrong_list_types_and_ignored_tests_block(self):
        data=self.native('drc');data['violations']=''
        with self.assertRaises(ValueError):extract('drc',data,'board.kicad_pcb')
        data=self.native('drc');data['ignored_checks']=['clearance']
        with self.assertRaises(ValueError):extract('drc',data,'board.kicad_pcb')
    def test_empty_bom_is_blocking(self):
        f=self.p/'bom.csv';f.write_text('Reference,MPN,Manufacturer,Footprint,Value\n')
        r=Review({},'mass_production','pre_export');bom_checks(r,f)
        self.assertTrue(any(x['rule']=='BOM.EMPTY' and x['level']=='阻断级' for x in r.findings))
    def test_prose_signoffs_and_invalid_dates_are_not_evidence(self):
        from mass_production_review import MANUAL
        signs={code:{'status':'approved','reviewer':'fixture','date':'not-a-date','reason':'test','evidence':'nonexistent.txt'} for code,*rest in MANUAL}
        r=Review({'manual_reviews':signs},'mass_production','release');r.project=self.p;r.signoffs()
        self.assertEqual(len(r.findings),len(MANUAL))
    def test_real_hashed_manual_evidence_is_accepted_for_its_item(self):
        f=self.p/'review.txt';f.write_text('TEST FIXTURE ONLY')
        record={'status':'approved','reviewer':'fixture','date':'2026-10-17','reason':'test','evidence':[{'file':'review.txt','sha256':sha256(f)}]}
        r=Review({'manual_reviews':{'SCH.PROTECTION':record}},'mass_production','release');r.project=self.p;r.signoffs()
        self.assertFalse(any(x['rule']=='SCH.PROTECTION' for x in r.findings))
        f.write_text('CHANGED');r=Review({'manual_reviews':{'SCH.PROTECTION':record}},'mass_production','release');r.project=self.p;r.signoffs()
        self.assertTrue(any(x['rule']=='SCH.PROTECTION' for x in r.findings))
    def contract(self):
        source={'board.kicad_pcb':'a'*64};output={'a.gbr':'b'*64}
        config={'inputs':{'board':'board.kicad_pcb'},'delivery_manifest':{'gerber':['a.gbr']}}
        tool={'id':'cli','name':'kicad-cli','version':'10.0.7','executable_sha256':'c'*64}
        command={'tool_id':'cli','argv':['/test/kicad-cli','pcb','export','gerbers','--output','/candidate','/design/board.kicad_pcb'],'cwd':'/design','source_root':'/design','output_root':'/candidate','returncode':0,'log':'export.log','source_basis_sha256':source,'output_sha256':output}
        auth={'reviewer':'fixture','date':'2026-10-17','factory':'F','order_scope':'TEST','source_basis_sha256':source,'output_sha256':output}
        return {'tools':[tool],'commands':[command],'logs':[{'file':'export.log','sha256':'d'*64}], 'source_sha256':source,'output_sha256':output,'production_authorization':auth},config
    def test_empty_truthy_tool_and_command_records_are_rejected(self):
        data,cfg=self.contract();self.assertEqual(records(data,cfg,{}),({'board.kicad_pcb':'a'*64},{'a.gbr':'b'*64}))
        data['tools']=[{}]
        with self.assertRaises(ValueError):records(data,cfg,{})
        data,cfg=self.contract();data['commands']=[{}]
        with self.assertRaises(ValueError):records(data,cfg,{})
    def test_non_export_wrong_source_category_and_output_are_rejected(self):
        for argv in (
            ['kicad-cli','--version'],
            ['kicad-cli','pcb','export','gerbers','-o','/elsewhere','/design/board.kicad_pcb'],
            ['kicad-cli','pcb','export','gerbers','-o','/candidate','/design/other.kicad_pcb'],
            ['kicad-cli','pcb','export','drill','-o','/candidate','/design/board.kicad_pcb'],
        ):
            data,cfg=self.contract();data['commands'][0]['argv']=argv
            with self.assertRaises(ValueError):records(data,cfg,{})
    def test_stale_source_or_authorization_binding_blocks(self):
        data,cfg=self.contract();data['production_authorization']['output_sha256']={'a.gbr':'wrong'}
        with self.assertRaises(ValueError):records(data,cfg,{})
        data,cfg=self.contract();data['commands'][0]['source_basis_sha256']={}
        with self.assertRaises(ValueError):records(data,cfg,{})
    def test_failed_cam_check_is_not_truthy_pass(self):
        good={'date':'2026-10-17','checks':{k:'PASS' for k in CAM_CHECKS}};cam_checks(good)
        good['checks']['all_copper_layers']=False
        with self.assertRaises(ValueError):cam_checks(good)
    def test_publication_preserves_validated_evidence_dependencies(self):
        candidate=self.p/'candidate';candidate.mkdir();(candidate/'a.gbr').write_text('fixture')
        (candidate/'build-manifest.json').write_text('{}');proof=candidate/'evidence/review.json';proof.parent.mkdir();proof.write_text('fixture proof')
        cfg=self.p/'config.json';cfg.write_text(json.dumps({'delivery_manifest':{'gerber':['a.gbr']}}))
        verdict={'release_allowed':True,'counts':{},'inputs_sha256':{str(f):sha256(f) for f in (candidate/'a.gbr',candidate/'build-manifest.json',proof)}}
        with patch.object(npi_release,'evaluate',return_value=verdict):
            result=npi_release.release(self.p/'source',cfg,candidate,self.p/'release',True)
        self.assertTrue(result['released']);self.assertEqual((self.p/'release/evidence/review.json').read_text(),'fixture proof')

if __name__=='__main__':unittest.main()
