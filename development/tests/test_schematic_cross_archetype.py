"""Evidence presence and cross-archetype coverage do not imply a visual PASS."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2] / "kicad-pcb-ai-workflow"
sys.path.insert(0, str(ROOT / "scripts"))
import schematic_style as style
from npi_common import sha256


class CrossArchetypeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.trees = {}
        for name in ("power.kicad_sch", "mcu.kicad_sch", "audio.kicad_sch"):
            (self.root / name).write_text("(kicad_sch)")
            self.trees[name] = ["kicad_sch", ["paper", "A4"]]
        for name in ("power", "mcu", "audio"):
            (self.root / (name + "-review.txt")).write_text("human-reviewed evidence for " + name)

    def run_audit(self, cases):
        policy = {"schema_version": 1, "pages": {}, "require_sheet_pin_wire": False,
                  "prototype_validation": {"required": True, "cases": cases}}
        (self.root / "style.json").write_text(json.dumps(policy))
        with patch.object(style, "sheets", return_value=self.trees):
            return style.audit(self.root, "power.kicad_sch", "style.json")

    def case(self, name, kind, tamper=False):
        f = self.root / (name + "-review.txt")
        return {"page": name + ".kicad_sch", "archetype": kind,
                "evidence": {"file": f.name, "sha256": "0" * 64 if tamper else sha256(f),
                             "locator": "page 1 full-view and zoomed details"}}

    def test_power_and_mcu_pass_declared_evidence(self):
        result = self.run_audit([self.case("power", "power_conversion"),
                                 self.case("mcu", "mcu_soc")])
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["status"], "DECLARED_STRUCTURE_CHECKS_COMPLETE")
        self.assertIn("manual_remaining", result)

    def test_power_and_audio_cannot_generalize(self):
        result = self.run_audit([self.case("power", "power_conversion"),
                                 self.case("audio", "analog_audio")])
        self.assertIn("STYLE.PROTOTYPE_GENERALIZE", {f["rule"] for f in result["findings"]})

    def test_tampered_evidence_blocks(self):
        result = self.run_audit([self.case("power", "power_conversion", tamper=True),
                                 self.case("mcu", "mcu_soc")])
        self.assertIn("STYLE.PROTOTYPE_EVIDENCE", {f["rule"] for f in result["findings"]})

    def test_single_archetype_blocks(self):
        result = self.run_audit([self.case("power", "power_conversion")])
        self.assertIn("STYLE.PROTOTYPE_DIVERSITY", {f["rule"] for f in result["findings"]})


if __name__ == "__main__":
    unittest.main()
