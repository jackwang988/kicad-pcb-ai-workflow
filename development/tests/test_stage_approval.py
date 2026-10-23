"""Stage approvals: require real human review and invalidate changed evidence."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2] / "kicad-pcb-ai-workflow"
sys.path.insert(0, str(ROOT / "scripts"))
import workflow
from npi_common import sha256


class StageApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.bundle = "control-r1"
        (self.root / self.bundle).mkdir()
        self.master = self.root / "workflow.json"
        self.master.write_text('{"test": true}')
        (self.root / self.bundle / "flow.json").write_text("{}")
        self.evidence = self.root / "env.txt"
        self.evidence.write_text("environment checked")
        self.configs = {'flow': {'confirmation_mode': 'formal_engineering', 'inputs': {}}}
        self.patch_load = patch.object(workflow, 'load_bundle', return_value=self.configs)
        self.patch_master = patch.object(workflow, 'master_path', return_value=self.master)
        self.patch_load.start()
        self.patch_master.start()
        self.addCleanup(self.patch_load.stop)
        self.addCleanup(self.patch_master.stop)

    def approve(self):
        result = workflow.stage_prepare(self.root, "workflow.json", self.bundle, "environment", ["env.txt"])
        self.assertEqual(result['status'], 'ENGINEER_REVIEW_PENDING')
        review = {
            "role": "hardware_engineer", "name": "Test Engineer",
            "date": "2026-10-23", "group": "environment",
            "decision": "approve", "reason": "Checked actual environment evidence",
            "packet_sha256": result["packet_sha256"]
        }
        (self.root / "review.json").write_text(json.dumps(review))
        return workflow.stage_confirm(self.root, "workflow.json", self.bundle, "environment", "review.json")

    def test_human_record_is_required(self):
        result = workflow.stage_prepare(self.root, "workflow.json", self.bundle, "environment", ["env.txt"])
        self.assertEqual(result["status"], "ENGINEER_REVIEW_PENDING")
        with self.assertRaises(ValueError):
            workflow.validate_stage(self.root, "workflow.json", self.bundle, "environment")

    def test_confirm_and_invalidate_evidence(self):
        self.assertEqual(self.approve()["status"], "ENGINEER_APPROVED_CURRENT")
        self.evidence.write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            workflow.validate_stage(self.root, "workflow.json", self.bundle, "environment")

    def test_dialogue_has_no_fake_engineer_approval(self):
        self.configs['flow']['confirmation_mode'] = 'dialogue'
        with self.assertRaisesRegex(ValueError, "formal_engineering"):
            workflow.stage_prepare(self.root, "workflow.json", self.bundle, "environment", ["env.txt"])

    def test_malformed_review_fails_closed(self):
        result = workflow.stage_prepare(self.root, "workflow.json", self.bundle, "environment", ["env.txt"])
        bad = {"role": "ai", "name": "bot", "date": "2026-10-23", "group": "environment",
               "decision": "approve", "reason": "automatic", "packet_sha256": result["packet_sha256"]}
        (self.root / "review.json").write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            workflow.stage_confirm(self.root, "workflow.json", self.bundle, "environment", "review.json")

    def test_prevent_approval_self_evidence(self):
        (self.root / self.bundle / "stage-approvals").mkdir()
        (self.root / self.bundle / "stage-approvals" / "self.txt").write_text("self")
        with self.assertRaisesRegex(ValueError, "approval"):
            workflow.stage_prepare(self.root, "workflow.json", self.bundle, "environment",
                                   [self.bundle + "/stage-approvals/self.txt"])


if __name__ == "__main__":
    unittest.main()
