import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow/scripts'))
import environment_start as e

class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.project=self.root/'source';self.project.mkdir();self.out=self.root/'report'
        for n in ('demo.kicad_sch','demo.kicad_pcb','demo.kicad_pro'):(self.project/n).write_text('TEST ONLY')
        self.sig={'TEST':'TEST_ONLY'};self.env={'cli_exact_target':True,'pcbnew_exact_target':True,'kicad_cli':'TEST_CLI'}
        self.probe=patch.object(e,'signature',return_value=(self.sig,self.env));self.probe.start();self.addCleanup(self.probe.stop)
    def tearDown(self):self.tmp.cleanup()
    def setup(self,apply=False):return e.setup(self.project,'demo.kicad_sch','demo.kicad_pcb','demo.kicad_pro',self.out,apply=apply)
    def fake_run(self,args):
        p=pathlib.Path(args[args.index('--output')+1]);p.write_text('%PDF-TEST' if p.suffix=='.pdf' else '<export/>' if p.suffix=='.xml' else '{}');return {'returncode':0,'command':args}
    def ready(self):
        with patch.object(e,'run',side_effect=self.fake_run),patch.object(e,'read_netlist',return_value={'TEST':True}),patch('native_report.extract',return_value=[]),patch.object(e.importlib,'import_module',return_value=MagicMock()):
            return self.setup(True)
    def test_preview_no_write(self):
        self.assertEqual(self.setup()['status'],'PREVIEW');self.assertFalse(self.out.exists())
    def test_missing_tools_blocks_without_write(self):
        self.env['cli_exact_target']=False;self.assertEqual(self.setup(True)['status'],'BLOCKED');self.assertFalse(self.out.exists())
    def test_native_test_double_preserves_source(self):
        before=e.inventory(self.project);r=self.ready();self.assertEqual(r['status'],'ENVIRONMENT_READY');self.assertFalse(r['production_authorized']);self.assertEqual(before,e.inventory(self.project))
    def test_daily_read_only_reuse(self):
        self.ready();before=e.inventory(self.out);r=e.check(self.out/'startup-state.json');self.assertEqual(r['status'],'ENVIRONMENT_READY');self.assertEqual(before,e.inventory(self.out))
    def test_changed_signature_requires_full(self):
        self.ready();self.sig['TEST']='CHANGED';self.assertEqual(e.check(self.out/'startup-state.json')['status'],'FULL_SETUP_REQUIRED')
    def test_changed_evidence_requires_full(self):
        self.ready();(self.out/'pcb.pdf').write_text('CHANGED');self.assertEqual(e.check(self.out/'startup-state.json')['status'],'FULL_SETUP_REQUIRED')
    def test_expired_record_requires_full(self):
        self.ready();p=self.out/'startup-state.json';s=json.loads(p.read_text());s['checked_at']=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=8)).isoformat();p.write_text(json.dumps(s));self.assertEqual(e.check(p)['status'],'FULL_SETUP_REQUIRED')
    def test_design_violations_not_environment_failure(self):
        with patch.object(e,'run',side_effect=self.fake_run),patch.object(e,'read_netlist',return_value={'TEST':True}),patch('native_report.extract',return_value=[{'severity':'error'}]),patch.object(e.importlib,'import_module',return_value=MagicMock()):r=self.setup(True)
        self.assertEqual(r['status'],'ENVIRONMENT_READY');self.assertEqual(r['design_issue_counts']['drc'],1);self.assertFalse(r['production_authorized'])
    def test_failed_export_no_ready_record(self):
        with patch.object(e,'run',return_value={'returncode':-1}):r=self.setup(True)
        self.assertEqual(r['status'],'BLOCKED');self.assertFalse((self.out/'startup-state.json').exists())
    def test_existing_report_refused(self):
        self.out.mkdir()
        with self.assertRaises(ValueError):self.setup(True)
    def test_in_project_report_refused(self):
        with self.assertRaises(ValueError):e.setup(self.project,'demo.kicad_sch','demo.kicad_pcb','demo.kicad_pro',self.project/'report',apply=True)
    def test_missing_state(self):
        self.assertEqual(e.check(self.root/'missing.json')['status'],'FULL_SETUP_REQUIRED')
    def test_wrong_project_names(self):
        with self.assertRaises(ValueError):e.setup(self.project,'demo.kicad_sch','different.kicad_pcb','demo.kicad_pro',self.out)
if __name__=='__main__':unittest.main()
