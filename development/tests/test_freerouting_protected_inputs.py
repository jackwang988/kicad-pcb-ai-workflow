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


if __name__ == "__main__":
    unittest.main()
