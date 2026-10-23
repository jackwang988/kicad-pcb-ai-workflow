"""Unit tests for optional freerouting adapter; no Freerouting/Java required."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "kicad-pcb-ai-workflow" / "scripts" / "freerouting_adapter.py"
spec = importlib.util.spec_from_file_location("freerouting_adapter", SCRIPT)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class FreeroutingAdapterTests(unittest.TestCase):
    def test_version_metadata_required(self):
        with tempfile.TemporaryDirectory() as temp:
            jar = Path(temp) / "freerouting-2.5.0.jar"
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("META-INF/MANIFEST.MF", "Implementation-Title: Freerouting\nImplementation-Version: 2.5.0\n")
            self.assertTrue(adapter.inspect_jar(jar)[0])
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("META-INF/MANIFEST.MF", "Implementation-Title: Freerouting\nImplementation-Version: 2.4.0\n")
            self.assertFalse(adapter.inspect_jar(jar)[0])

    def test_missing_jar_uses_manual_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            dsn = base / "board.dsn"
            dsn.write_text("(pcb test)", encoding="utf-8")
            output = base / "out"
            run = subprocess.run([sys.executable, str(SCRIPT), "--dsn", str(dsn),
                                  "--output-dir", str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["status"], "MANUAL_ROUTING_FALLBACK")
            self.assertFalse(output.exists())

    def test_existing_result_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            dsn = base / "board.dsn"
            dsn.write_text("(pcb test)", encoding="utf-8")
            output = base / "out"
            output.mkdir()
            run = subprocess.run([sys.executable, str(SCRIPT), "--dsn", str(dsn),
                                  "--output-dir", str(output), "--apply"], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertTrue(output.is_dir())


if __name__ == "__main__":
    unittest.main()
