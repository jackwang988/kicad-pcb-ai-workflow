"""Behavioral tests. Native CLI/API calls are NOT integration-tested by mocks."""
import ast
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'
sys.path.insert(0,str(ROOT/'scripts'))
import mass_production_review as review
import npi_release
from npi_common import sha256,parse_sexpr

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.project=self.base/'project'
        shutil.copytree(ROOT.parent/'development/fixtures/npi-demo',self.project)
        self.config=self.project/'review-config.json'
    def tearDown(self): self.temp.cleanup()
    def run_static(self):
        return review.evaluate(self.project,self.config,'mass_production','release',static_preview=True)
    def test_skill_entrypoint_exposes_mass_production_gate(self):
        text=(ROOT/'SKILL.md').read_text()
        self.assertIn('--mode mass_production',text)
        self.assertIn('references/dfx-npi.md',text)
        self.assertIn('npi_release.py',text)
    def test_all_python_sources_parse_without_running_legacy_top_level_code(self):
        for p in ROOT.rglob('*.py'): ast.parse(p.read_bytes(),filename=str(p))
    def test_demo_blocks_production_and_finds_actual_dimensional_and_bom_risks(self):
        report=self.run_static()
        codes={f['rule'] for f in report['findings']}
        self.assertTrue({'BOM.FIELD','DFM.TRACK','DFM.VIA','DFM.ASPECT','PI.DECOUPLING'}.issubset(codes))
        self.assertTrue(report['blocked']); self.assertFalse(report['release_allowed'])
    def test_review_does_not_modify_any_project_file(self):
        before={str(p):sha256(p) for p in self.project.rglob('*') if p.is_file()}
        self.run_static()
        after={str(p):sha256(p) for p in self.project.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
    def test_blocked_publish_never_creates_destination(self):
        candidate=self.base/'candidate'; candidate.mkdir()
        destination=self.base/'release'
        # Real evaluation with absent native dependencies must fail closed.
        result=npi_release.release(self.project,self.config,candidate,destination,apply=True)
        self.assertTrue(result['blocked']); self.assertFalse(destination.exists())
    def test_report_cannot_overwrite_old_evidence(self):
        report=self.run_static(); output=self.base/'report'
        review.write_report(report,output)
        with self.assertRaises(ValueError): review.write_report(report,output)
    def test_bom_duplicate_is_blocking(self):
        bom=self.project/'review-bom.csv'
        with bom.open('a') as f: f.write('U1,PART,MFG,FOOTPRINT,VALUE\n')
        self.assertTrue(any(x['rule']=='BOM.DUPLICATE' and x['level']=='阻断级' for x in self.run_static()['findings']))
    def test_input_path_escape_is_rejected(self):
        data=json.loads(self.config.read_text()); data['inputs']['board']='../../outside.kicad_pcb'
        self.config.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.run_static()
    def test_prototype_does_not_grant_mass_production_release(self):
        report=review.evaluate(self.project,self.config,'prototype','release')
        self.assertFalse(report['release_allowed'])
    def test_unknown_native_report_schema_blocks_instead_of_passing(self):
        r=review.Review({},'mass_production','pre_export')
        def fake_run(command):
            path=Path(command[command.index('--output')+1]); path.write_text('{"unexpected": []}')
            return {'returncode':0}
        with patch.object(review,'run',side_effect=fake_run):
            review.native_checks(r,{'cli_version':'10.0.7','cli_exact_target':True,'kicad_cli':'fake-cli'},self.project/'npi-demo.kicad_sch',self.project/'npi-demo.kicad_pcb')
        self.assertEqual(sum(x['rule']=='NATIVE.SCHEMA' for x in r.findings),2)
    def test_preview_no_write_and_apply_freshness_guard(self):
        # Stub only the review verdict to isolate publication behavior.
        candidate=self.base/'candidate'; candidate.mkdir(); (candidate/'file.gbr').write_text('fixture'); (candidate/'build-manifest.json').write_text('{}')
        destination=self.base/'release'; cfg=self.base/'release-config.json'
        cfg.write_text(json.dumps({'delivery_manifest':{'gerber':['file.gbr']}}))
        verdict={'release_allowed':True,'counts':{},'inputs_sha256':{str(candidate/'file.gbr'):sha256(candidate/'file.gbr')}}
        with patch.object(npi_release,'evaluate',return_value=verdict):
            result=npi_release.release(self.project,cfg,candidate,destination)
            self.assertTrue(result['preview']); self.assertFalse(destination.exists())
            (candidate/'file.gbr').write_text('changed')
            with self.assertRaises(ValueError): npi_release.release(self.project,cfg,candidate,destination,True)
        self.assertFalse(destination.exists())
    def test_apply_copies_only_manifest_to_new_directory(self):
        candidate=self.base/'candidate'; candidate.mkdir()
        (candidate/'file.gbr').write_text('fixture'); (candidate/'build-manifest.json').write_text('{}'); (candidate/'unlisted.txt').write_text('not for release')
        cfg=self.base/'release-config.json'; cfg.write_text(json.dumps({'delivery_manifest':{'gerber':['file.gbr']}}))
        verdict={'release_allowed':True,'counts':{},'inputs_sha256':{str(candidate/'file.gbr'):sha256(candidate/'file.gbr')}}
        destination=self.base/'release'
        with patch.object(npi_release,'evaluate',return_value=verdict):
            result=npi_release.release(self.project,cfg,candidate,destination,True)
            self.assertTrue(result['released']); self.assertEqual(sorted(p.name for p in destination.iterdir()),['build-manifest.json','file.gbr'])
            with self.assertRaises(ValueError): npi_release.release(self.project,cfg,candidate,destination,True)

if __name__=='__main__': unittest.main()
