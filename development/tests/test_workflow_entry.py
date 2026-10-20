"""Unified-entry safety contracts. TEST fixtures are not approved hardware."""
import copy
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2] / 'kicad-pcb-ai-workflow'
sys.path.insert(0, str(ROOT / 'scripts'))
import workflow as entry
from npi_common import sha256


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name) / 'project'
        self.root.mkdir()
        self.master = entry.template()
        self.master.update(project_id='TEST', revision='A')
        self.master['shared']['inputs'].update(schematic='main.kicad_sch', board='main.kicad_pcb', project='main.kicad_pro')
        self.master['shared']['variant'] = 'default'
        self.write_master()

    def write_master(self):
        (self.root / 'workflow.json').write_text(entry.encoded(self.master))

    def build(self):
        return entry.compile_bundle(self.root, 'workflow.json', 'control-r1', True)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/workflow.py'), *args], capture_output=True, text=True)

    def test_shared_input_and_variant_propagate_without_engineering_defaults(self):
        self.master['shared']['inputs']['schematic'] = 'new-name.kicad_sch'
        self.master['shared']['variant'] = 'production-A'
        self.write_master()
        self.build()
        c = entry.load_bundle(self.root, 'workflow.json', 'control-r1')
        self.assertEqual(c['static']['stages']['schematic']['inputs']['schematic'], 'new-name.kicad_sch')
        self.assertEqual(c['npi']['inputs'], c['flow']['inputs'])
        self.assertEqual(c['npi']['variants'], ['production-A'])
        self.assertEqual(c['npi']['delivery_export']['variant'], 'production-A')
        self.assertIsNone(c['npi']['process']['min_track_width_mm'])
        self.assertEqual(c['npi']['workflow_contract'], 'control-r1/flow.json')

    def test_build_preview_writes_nothing(self):
        before = {p.name: sha256(p) for p in self.root.iterdir()}
        self.assertEqual(entry.compile_bundle(self.root, 'workflow.json', 'control-r1')['status'], 'PREVIEW')
        self.assertEqual(before, {p.name: sha256(p) for p in self.root.iterdir()})

    def test_init_preview_and_apply_never_overwrite(self):
        for args, code in [((), 0), (('--apply',), 0), (('--apply',), 2)]:
            r = self.cli('init', str(self.root), '--config', 'new.json', *args)
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
            if not args:
                self.assertFalse((self.root / 'new.json').exists())

    def test_existing_bundle_is_preserved(self):
        self.build()
        before = sha256(self.root / 'control-r1/flow.json')
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(before, sha256(self.root / 'control-r1/flow.json'))

    def test_stage_removal_cannot_simplify_gate_away(self):
        del self.master['configs']['flow']['stages']['cam_release']
        self.write_master()
        with self.assertRaisesRegex(ValueError, '16 workflow nodes'):
            self.build()
        self.assertFalse((self.root / 'control-r1').exists())

    def test_all_mandatory_flags_remain_enforced(self):
        for flag in entry.FLAGS:
            q = copy.deepcopy(self.master)
            q['configs']['static'][flag] = False
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'cannot be disabled'):
                entry.render(q, pathlib.Path('control-r1'))

    def test_semantic_category_cannot_be_removed(self):
        tasks = self.master['configs']['static']['stages']['schematic']['tasks']
        tasks[:] = [t for t in tasks if t['category'] != 'system_integration']
        self.write_master()
        with self.assertRaisesRegex(ValueError, 'category removed'):
            self.build()

    def test_shared_policy_divergence_blocks(self):
        self.master['configs']['npi']['system_integration'] = {'contract': 'different.json'}
        self.write_master()
        with self.assertRaisesRegex(ValueError, 'Conflicting shared'):
            self.build()

    def test_master_change_invalidates_bundle(self):
        self.build()
        self.master['revision'] = 'B'
        self.write_master()
        with self.assertRaisesRegex(ValueError, 'Master changed'):
            entry.load_bundle(self.root, 'workflow.json', 'control-r1')

    def test_bundle_change_even_with_rehashed_manifest_blocks(self):
        self.build()
        p = self.root / 'control-r1/static.json'
        c = json.loads(p.read_text())
        c['require_system_integration'] = False
        p.write_text(entry.encoded(c))
        m = self.root / 'control-r1/bundle.json'
        q = json.loads(m.read_text())
        q['files'][p.name] = sha256(p)
        m.write_text(entry.encoded(q))
        with self.assertRaisesRegex(ValueError, 'Generated config changed'):
            entry.load_bundle(self.root, 'workflow.json', 'control-r1')

    def test_toolchain_change_invalidates_snapshot(self):
        self.build()
        original = entry.sha256
        def changed(p):
            return '0' * 64 if pathlib.Path(p).name == 'tool-manifest.json' else original(p)
        with patch.object(entry, 'sha256', side_effect=changed), self.assertRaisesRegex(ValueError, 'Toolchain changed'):
            entry.load_bundle(self.root, 'workflow.json', 'control-r1')

    def test_cycles_remote_refs_and_mixed_tokens_rejected(self):
        for value in ({'$ref': '/shared/cycle'}, {'$ref': 'https://example.com/config'}, {'$ref': '/revision', 'extra': True}):
            q = copy.deepcopy(self.master)
            q['shared']['cycle'] = value
            q['configs']['flow']['revision'] = value
            with self.subTest(value=value), self.assertRaises((ValueError, KeyError)):
                entry.render(q, pathlib.Path('control-r1'))

    def test_path_escape_or_symlink_cannot_write_config(self):
        with self.assertRaises(ValueError):
            entry.compile_bundle(self.root, 'workflow.json', '../outside', True)
        target = pathlib.Path(self.temp.name) / 'elsewhere'
        target.mkdir()
        (self.root / 'link').symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            entry.compile_bundle(self.root, 'workflow.json', 'link/bundle', True)
        self.assertFalse((target / 'bundle').exists())

    def test_navigation_never_claims_gates_passed(self):
        self.build()
        r = entry.status(self.root, 'workflow.json', 'control-r1')
        self.assertFalse(r['production_authorized'])
        self.assertEqual(r['status'], 'NEEDS_INPUT')
        self.assertEqual(len(r['groups']), 6)
        self.assertEqual([s for g in r['groups'] for s in g['nodes']], list(entry.flow.STAGES))
        self.assertTrue(all(g['gate_status'] == 'NOT_EVALUATED_BY_NAVIGATION' for g in r['groups']))
        self.assertTrue(any(f['rule'] == 'FLOW.APPLICABILITY' for f in r['findings']))

    def test_no_legacy_or_arbitrary_tool_entry(self):
        self.build()
        for task in ('route_p2p', 'bash', 'workflow', 'manufacturing.jobset'):
            with self.subTest(task=task), self.assertRaisesRegex(ValueError, 'Unknown task'):
                entry.command(self.root, 'workflow.json', 'control-r1', task, {})

    def test_prototype_cannot_export_or_release(self):
        self.build()
        for task in ('manufacturing.export', 'manufacturing.release'):
            with self.subTest(task=task), self.assertRaisesRegex(ValueError, 'Prototype mode cannot'):
                entry.command(self.root, 'workflow.json', 'control-r1', task, {'mode': 'prototype'})

    def test_export_keeps_original_guarded_entry_and_explicit_apply(self):
        self.build()
        opts = {'destination': str(pathlib.Path(self.temp.name) / 'candidate')}
        tool, args = entry.command(self.root, 'workflow.json', 'control-r1', 'manufacturing.export', opts)
        self.assertEqual(tool, 'manufacturing_export')
        self.assertNotIn('--apply', args)
        self.assertIn(str(self.root / 'control-r1/npi.json'), args)
        opts['apply'] = True
        self.assertIn('--apply', entry.command(self.root, 'workflow.json', 'control-r1', 'manufacturing.export', opts)[1])

    def test_readonly_gate_does_not_accept_apply(self):
        self.build()
        with self.assertRaisesRegex(ValueError, 'only valid'):
            entry.command(self.root, 'workflow.json', 'control-r1', 'schematic.gate', {'apply': True})

    def test_explicit_actual_ai_and_engineer_files_required(self):
        self.build()
        with self.assertRaisesRegex(ValueError, 'engineer-review'):
            entry.command(self.root, 'workflow.json', 'control-r1', 'pcb.gate', {'packet': 'packet', 'ai_review': 'ai.json'})
        packet = self.root / 'packet'
        packet.mkdir()
        (packet / 'packet.json').write_text('{"stage":"schematic"}')
        _, args = entry.command(self.root, 'workflow.json', 'control-r1', 'schematic.gate', {'packet': str(packet), 'ai_review': 'ai.json', 'engineer_review': 'human.json'})
        self.assertIn('human.json', args)

    def test_wrong_stage_packet_cannot_satisfy_named_gate(self):
        self.build()
        packet = self.root / 'packet'
        packet.mkdir()
        (packet / 'packet.json').write_text('{"stage":"pcb"}')
        with self.assertRaisesRegex(ValueError, 'different stage'):
            entry.command(self.root, 'workflow.json', 'control-r1', 'schematic.gate', {'packet': str(packet), 'ai_review': 'ai.json', 'engineer_review': 'human.json'})

    def test_missing_inputs_propagate_real_child_failure(self):
        self.build()
        r = self.cli('run', str(self.root), '--bundle', 'control-r1', '--task', 'architecture.check')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'], 'BLOCKED')
        self.assertFalse(json.loads(r.stdout)['production_authorized'])

    def test_actual_schematic_prepare_rejects_unfilled_sources(self):
        self.build()
        out = pathlib.Path(self.temp.name) / 'review'
        r = self.cli('run', str(self.root), '--bundle', 'control-r1', '--task', 'schematic.prepare', '--output-dir', str(out))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(out.exists())

    def test_plan_does_not_execute_child(self):
        self.build()
        before = {str(p.relative_to(self.root)): sha256(p) for p in self.root.rglob('*') if p.is_file()}
        r = self.cli('plan', str(self.root), '--bundle', 'control-r1', '--task', 'environment.doctor')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'], 'PREVIEW')
        after = {str(p.relative_to(self.root)): sha256(p) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_environment_diagnostic_needs_no_project_configuration(self):
        (self.root / 'workflow.json').unlink()
        r = self.cli('plan', str(self.root), '--task', 'environment.doctor')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('doctor.py', json.loads(r.stdout)['command'][2])
        r = self.cli('plan', str(self.root), '--task', 'manufacturing.export', '--destination', '/tmp/never-created')
        self.assertEqual(r.returncode, 2)
        self.assertFalse(list(self.root.iterdir()))


if __name__ == '__main__':
    unittest.main()
