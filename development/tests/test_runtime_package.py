"""Actual standalone-package behavior and core inventory counterexamples."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOT = REPO/'kicad-pcb-ai-workflow'
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(REPO/'development'))
from npi_common import runtime_inventory, RUNTIME_TOOLS
import engineering_gate as gate
from mass_production_review import Review
import environment_start
import build_release


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.clone = self.base/'kicad-pcb-ai-workflow'
        shutil.copytree(ROOT, self.clone, ignore=shutil.ignore_patterns('__pycache__'))

    def test_standalone_core_has_no_archive_dependency(self):
        self.assertFalse((self.base/'archive').exists())
        r = Review({}, 'mass_production', 'pre_export')
        with patch.object(gate, '__file__', str(self.clone/'scripts/engineering_gate.py')):
            gate.inspect_inventory(r)
        self.assertEqual(r.findings, [])
        self.assertEqual(set(runtime_inventory(self.clone)), RUNTIME_TOOLS)

    def test_removing_any_required_tool_blocks_inventory_gate(self):
        for name in sorted(RUNTIME_TOOLS):
            p = self.clone/'scripts'/(name+'.py')
            held = self.base/(name+'.held')
            p.rename(held)
            try:
                r = Review({}, 'mass_production', 'pre_export')
                with patch.object(gate, '__file__', str(self.clone/'scripts/engineering_gate.py')):
                    gate.inspect_inventory(r)
                self.assertTrue(any(f['rule'] == 'TOOLS.INVENTORY' and f['level'] == '阻断级' for f in r.findings), name)
            finally:
                held.rename(p)

    def test_removing_gate_from_manifest_cannot_disable_requirement(self):
        p = self.clone/'references/tool-manifest.json'
        data = json.loads(p.read_text())
        data['active'] = [r for r in data['active'] if r['file'] != 'scripts/npi_release.py']
        p.write_text(json.dumps(data))
        (self.clone/'scripts/npi_release.py').unlink()
        with self.assertRaisesRegex(ValueError, 'Required runtime tool set'):
            runtime_inventory(self.clone)

    def test_duplicate_manifest_entry_blocks(self):
        p = self.clone/'references/tool-manifest.json'
        data = json.loads(p.read_text())
        data['active'].append(data['active'][0])
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            runtime_inventory(self.clone)

    def test_project_script_cannot_be_mixed_into_runtime(self):
        for relative in ('scripts/route_usb.py', 'scripts/old-project/route_usb.py'):
            p = self.clone/relative
            p.parent.mkdir(exist_ok=True)
            p.write_text('# Inert TEST project script\n')
            try:
                with self.assertRaisesRegex(ValueError, 'Unexpected/missing'):
                    runtime_inventory(self.clone)
            finally:
                p.unlink()

    def test_symlinked_tool_is_rejected_even_with_identical_bytes(self):
        p = self.clone/'scripts/doctor.py'
        p.unlink()
        p.symlink_to(ROOT/'scripts/doctor.py')
        with self.assertRaisesRegex(ValueError, 'Missing/changed'):
            runtime_inventory(self.clone)

    def test_external_archive_changes_do_not_change_environment_signature(self):
        archive = self.base/'archive'
        archive.mkdir()
        marker = archive/'old-project.py'
        marker.write_text('TEST historical artifact')
        env = {'cli_exact_target': False, 'pcbnew_exact_target': False, 'cli_version': None, 'pcbnew_version': None}
        with patch.object(environment_start, 'ROOT', self.clone), patch.object(environment_start, 'environment', return_value=env), patch.object(environment_start.importlib, 'import_module', side_effect=ImportError):
            before, _ = environment_start.signature()
            marker.write_text('Changed TEST history')
            after, _ = environment_start.signature()
        self.assertEqual(before, after)
        self.assertTrue(any(p.endswith('tool-manifest.json') for p in before['files_sha256']))
        self.assertFalse(any('/archive/' in p for p in before['files_sha256']))

    def test_corrupt_core_is_rejected_before_environment_state_reuse(self):
        p = self.clone/'scripts/static_review_gate.py'
        p.write_text(p.read_text()+'\n# changed\n')
        with patch.object(environment_start, 'ROOT', self.clone), self.assertRaisesRegex(ValueError, 'Missing/changed'):
            environment_start.signature()

    def test_runtime_docs_links_are_self_contained(self):
        (self.clone/'references/capabilities.md').write_text('[TEST link](../../development/DEVELOPMENT.md)')
        with self.assertRaisesRegex(ValueError, 'Broken/external'):
            build_release.validate(self.clone)

    def test_project_specific_template_is_rejected_by_builder(self):
        p = self.clone/'assets/schematic-style.template.json'
        data = json.loads(p.read_text())
        data['TEST_note'] = 'PROJECT_SPECIFIC_BOARD'
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Project/machine-specific'):
            build_release.validate(self.clone)

    def test_build_preview_preserves_destination(self):
        out = self.base/'release'
        result = build_release.build(out)
        self.assertEqual(result['status'], 'PREVIEW')
        self.assertFalse(out.exists())

    def test_real_zip_runs_without_source_archive_or_development(self):
        out = self.base/'release'
        result = build_release.build(out, True)
        self.assertFalse(result['production_authorized'])
        self.assertEqual(result['archived_original_scripts'], 70 if (REPO/'archive/legacy-project').is_dir() else 0)
        unpack = self.base/'isolated'
        with zipfile.ZipFile(out/'kicad-pcb-ai-workflow.zip') as z:
            names = z.namelist()
            self.assertTrue(all(n.startswith('kicad-pcb-ai-workflow/') for n in names))
            self.assertFalse(any('/fixtures/' in n or '/validation/' in n or 'original-script-sha256' in n for n in names))
            z.extractall(unpack)
        core = unpack/'kicad-pcb-ai-workflow'
        self.assertEqual(build_release.validate(core)['runtime_tools'], 31)
        project = self.base/'new-project'
        project.mkdir()
        p = subprocess.run([sys.executable, '-B', str(core/'scripts/workflow.py'), 'run', str(project), '--task', 'environment.doctor'], cwd=project, capture_output=True, text=True)
        self.assertIn(p.returncode, (0, 2), p.stdout+p.stderr)
        actual = json.loads(p.stdout)
        self.assertEqual(actual['target'], '10.0.7')
        self.assertEqual(p.returncode == 0, actual['required_ok'])
        self.assertFalse((unpack/'archive').exists())
        self.assertFalse((unpack/'development').exists())

    def test_existing_release_directory_never_overwritten(self):
        out = self.base/'release'
        out.mkdir()
        (out/'keep').write_text('original')
        with self.assertRaises(ValueError):
            build_release.build(out, True)
        self.assertEqual((out/'keep').read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
