"""Fail-closed tests for reviewed Freerouting 2.5.0 inputs; no Java required."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "kicad-pcb-ai-workflow" / "scripts" / "freerouting_adapter.py"
spec = importlib.util.spec_from_file_location("freerouting_strict_adapter", SCRIPT)
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


class FreeroutingProtectedInputsTests(unittest.TestCase):
    def test_exclusion_names_are_netclasses_not_net_names(self):
        self.assertEqual(router.class_exclusions("GND,RF,POWER"), ["GND", "RF", "POWER"])
        for bad in ("GND,GND", "GND,", "../GND", "GND;BAD"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                router.class_exclusions(bad)

    def test_dsn_netclass_names_are_read(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "board.dsn"
            p.write_text('(pcb demo (network (class GND GND) (class "RF" SIG) (class SIGNAL GPIO)))')
            self.assertEqual(router.specctra_netclasses(p), {"GND", "RF", "SIGNAL"})

    def run_adapter(self, folder, *extra):
        dsn = folder / "board.dsn"
        if not dsn.exists():
            dsn.write_text('(pcb demo (network (class GND GND) (class SIGNAL A B)))')
        out = folder / "result"
        cmd = [sys.executable, str(SCRIPT), "--dsn", str(dsn),
               "--output-dir", str(out), *extra]
        run = subprocess.run(cmd, capture_output=True, text=True)
        return run, json.loads(run.stdout), out

    def test_apply_requires_reviewed_dsn_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            run, result, out = self.run_adapter(Path(temp), "--apply", "--exclude-netclasses", "GND")
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "DSN_HASH_REQUIRED_FOR_EXECUTION")
            self.assertFalse(out.exists())

    def test_apply_requires_protected_netclass_exclusions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dsn = root / "board.dsn"
            dsn.write_text('(pcb demo (network (class GND GND)))')
            digest = hashlib.sha256(dsn.read_bytes()).hexdigest()
            run, result, out = self.run_adapter(root, "--apply", "--expected-dsn-sha256", digest)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "PROTECTED_NETCLASS_EXCLUSIONS_REQUIRED")
            self.assertFalse(out.exists())

    def test_class_must_exist_in_export(self):
        with tempfile.TemporaryDirectory() as temp:
            run, result, out = self.run_adapter(Path(temp), "--exclude-netclasses", "NO_SUCH_CLASS")
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "EXCLUDED_NETCLASS_NOT_IN_DSN")
            self.assertFalse(out.exists())

    def test_implicit_rules_file_cannot_be_silently_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "board.rules").write_text("(rules unknown)")
            run, result, out = self.run_adapter(root)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "UNAPPROVED_ADJACENT_RULES")
            self.assertFalse(out.exists())

    def test_dsn_checksum_drift_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            run, result, out = self.run_adapter(Path(temp), "--expected-dsn-sha256", "0"*64)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "DSN_SHA256_MISMATCH")
            self.assertFalse(out.exists())

    def test_approved_rules_require_hash_for_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rules = root / "verified.rules"
            rules.write_text("(rules verified)")
            dsn = root / "board.dsn"
            dsn.write_text('(pcb demo (network (class GND GND)))')
            digest = hashlib.sha256(dsn.read_bytes()).hexdigest()
            run, result, out = self.run_adapter(
                root, "--apply", "--expected-dsn-sha256", digest,
                "--exclude-netclasses", "GND", "--rules-file", str(rules))
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "RULES_HASH_REQUIRED_FOR_EXECUTION")
            self.assertFalse(out.exists())



    def test_declared_gnd_class_does_not_prove_actual_membership(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "board.dsn").write_text(
                '(pcb demo (network (net GND (pins J1-1)) '
                '(net GPIO (pins J1-2)) (class kicad_default GND GPIO (rule (width 200))) '
                '(class GND (rule (width 200)))))')
            self.assertEqual(router.specctra_netclass_members(root / "board.dsn")["GND"],
                             "kicad_default")
            run, result, out = self.run_adapter(root, "--exclude-netclasses", "GND")
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "GND_EFFECTIVE_CLASS_NOT_EXCLUDED")
            self.assertFalse(out.exists())

    def test_effective_gnd_and_signal_map_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "board.dsn").write_text(
                '(pcb demo (network (net GND (pins J1-1)) (net GPIO (pins J1-2)) '
                '(class GND GND (rule (width 200))) (class SIGNAL GPIO)))')
            self.assertEqual(router.specctra_netclass_members(root / "board.dsn"),
                             {"GND": "GND", "GPIO": "SIGNAL"})
            run, result, out = self.run_adapter(root, "--exclude-netclasses", "GND")
            self.assertEqual(run.returncode, 0)
            self.assertEqual(result["status"], "MANUAL_ROUTING_FALLBACK")

    def test_native_netclass_map_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dsn = root / "board.dsn"
            dsn.write_text('(pcb demo (network (net GND (pins J1-1)) '
                           '(net GPIO (pins J1-2)) (class GND GND) (class SIGNAL GPIO)))')
            native = root / "map.json"
            native.write_text(json.dumps({"dsn_sha256": hashlib.sha256(dsn.read_bytes()).hexdigest(),
                                         "net_to_class": {"GND": "GND", "GPIO": "Default"}}))
            mhash = hashlib.sha256(native.read_bytes()).hexdigest()
            run, result, _ = self.run_adapter(
                root, "--netclass-map", str(native),
                "--expected-netclass-map-sha256", mhash, "--exclude-netclasses", "GND")
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "NATIVE_NETCLASS_MAP_MEMBERSHIP_MISMATCH")

    def test_apply_requires_hash_bound_native_map(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dsn = root / "board.dsn"
            dsn.write_text('(pcb demo (network (class GND GND)))')
            digest = hashlib.sha256(dsn.read_bytes()).hexdigest()
            run, result, out = self.run_adapter(root, "--apply",
                                                "--expected-dsn-sha256", digest,
                                                "--exclude-netclasses", "GND")
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "NATIVE_NETCLASS_MAP_REQUIRED_FOR_EXECUTION")
            self.assertFalse(out.exists())

    def test_duplicate_dsn_membership_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "board.dsn").write_text(
                '(pcb demo (network (class kicad_default GND) (class GND GND)))')
            run, result, out = self.run_adapter(root, "--exclude-netclasses", "GND")
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["reason"], "DSN_NETCLASS_MEMBERSHIP_UNVERIFIABLE")
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
