"""Workspace and compact output regressions (no real KiCad edits)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow'/'scripts'))
import workflow

class WorkspaceTokenTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'01_WORKING').mkdir()
        (self.root/'01_WORKING/demo.kicad_pro').write_text('{}')

    def args(self,action,**kw):
        defaults=dict(project=str(self.root),action=action,apply=False,
                      project_file=None,label=None,stage=None,artifact=None,
                      limit=12,detailed=False)
        defaults.update(kw)
        return Mock(**defaults)

    def prepare(self):
        return workflow.workspace_action(self.args('init',project_file='01_WORKING/demo.kicad_pro',apply=True))

    def test_init_preview_and_one_authoritative_project(self):
        self.assertEqual(workflow.workspace_action(self.args('init',project_file='01_WORKING/demo.kicad_pro'))['status'],'PREVIEW')
        self.assertFalse((self.root/'CURRENT_PROJECT.json').exists())
        self.prepare()
        for _ in range(10):
            self.assertEqual(workflow.workspace_action(self.args('status'))['project'],'01_WORKING/demo.kicad_pro')
        self.assertEqual(len(list(self.root.rglob('*.kicad_pro'))),1)

    def test_duplicate_index_does_not_overwrite(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_immutable_checkpoint(self):
        self.prepare()
        workflow.workspace_action(self.args('checkpoint',label='G1',apply=True))
        self.assertTrue((self.root/'02_CHECKPOINTS/G1/demo.kicad_pro').exists())
        with self.assertRaises(ValueError):
            workflow.workspace_action(self.args('checkpoint',label='G1',apply=True))

    def test_history_classification_does_not_delete(self):
        self.prepare()
        (self.root/'candidate-r1').mkdir()
        (self.root/'control-r1').mkdir()
        old=self.root/'old.kicad_pro';old.write_text('old')
        result=workflow.workspace_action(self.args('inventory'))
        self.assertEqual(result['total'],3)
        self.assertTrue(old.exists())
        self.assertFalse(result['history_deleted'])

    def test_symlinked_checkpoint_and_evidence_index_refused(self):
        self.prepare()
        external=self.root/'outside'
        external.mkdir()
        target=self.root/'02_CHECKPOINTS'
        target.rmdir()
        try:target.symlink_to(external,target_is_directory=True)
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:self.skipTest('Host lacks Windows symlink privilege; capable CI must exercise this case')
            raise
        with self.assertRaisesRegex(ValueError,'Symlinked'):
            workflow.workspace_action(self.args('checkpoint',label='X',apply=True))
        target.unlink()
        target.mkdir()
        (self.root/'03_REPORTS'/'index').symlink_to(external,target_is_directory=True)
        report=self.root/'03_REPORTS'/'g1.json'
        report.write_text('{}')
        with self.assertRaisesRegex(ValueError,'Symlinked'):
            workflow.workspace_action(self.args('register',stage='G1',artifact='03_REPORTS/g1.json',apply=True))

    def test_bounded_report_prioritizes_failures(self):
        source=self.root/'report.json'
        source.write_text(json.dumps({'status':'NEEDS_EVIDENCE','checks':
            [{'status':'PASS','task_id':str(i)} for i in range(50)]+
            [{'status':'BLOCKED','detail':'Missing reference'}]}))
        digest=workflow.report_brief(source,limit=2)
        self.assertEqual(digest['issue_count'],51)
        self.assertEqual(digest['by_status']['BLOCKED'],1)
        self.assertEqual(digest['issues'][0]['status'],'BLOCKED')
        self.assertTrue(digest['truncated'])
        self.assertFalse(digest['production_authorized'])

    def test_compact_status_keeps_full_error_count(self):
        report={'status':'BLOCKED','findings':[{'description':'missing'} for _ in range(15)],
                'unfilled_config_fields':[1,2],
                'groups':[{'group':'schematic','confirmation_status':'PENDING'}]}
        short=workflow.compact_navigation(report)
        self.assertEqual(short['findings_count'],15)
        self.assertTrue(short['findings_truncated'])
        self.assertFalse(short['production_authorized'])

if __name__=='__main__':
    unittest.main()
