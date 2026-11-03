"""Pure-Python compatibility policy tests; NOT evidence of native KiCad 9/10 execution."""
import pathlib
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'kicad-pcb-ai-workflow/scripts'))
import npi_common as n
from native_report import extract


class PatchCompatibilityTests(unittest.TestCase):
    def probe(self, cli_version, pcb_version):
        pcb = MagicMock()
        pcb.GetBuildVersion.return_value = pcb_version
        with patch.object(n, 'run', return_value={'returncode': 0, 'stdout': cli_version + '\n', 'stderr': ''}), \
             patch.dict(sys.modules, {'pcbnew': pcb}):
            return n.environment('/trusted/kicad-cli')

    def test_recommended_baseline_remains_supported(self):
        e = self.probe('10.0.7', '10.0.7')
        self.assertTrue(n.pair_compatible(e))
        self.assertTrue(e['cli_exact_target'])
        self.assertEqual(e['compatibility_tier'], 'RECOMMENDED_BASELINE')

    def test_new_patch_is_candidate_not_manufacturing_authorization(self):
        e = self.probe('10.0.8', '10.0.8')
        self.assertTrue(n.pair_compatible(e))
        self.assertFalse(e['cli_exact_target'])
        self.assertEqual(e['compatibility_tier'], 'PATCH_CANDIDATE_NATIVE_SMOKE_REQUIRED')

    def test_other_10_0_patches_need_native_verification(self):
        e = self.probe('10.0.6', '10.0.6')
        self.assertTrue(n.pair_compatible(e))
        self.assertEqual(e['compatibility_tier'], 'PATCH_CANDIDATE_NATIVE_SMOKE_REQUIRED')

    def test_mixed_patch_versions_fail(self):
        e = self.probe('10.0.8', '10.0.7')
        self.assertTrue(n.cli_compatible(e))
        self.assertTrue(n.pcbnew_compatible(e))
        self.assertFalse(n.pair_compatible(e))

    def test_kicad_9_is_offline_only_not_native_approved(self):
        e = self.probe('9.0.9', '9.0.9')
        self.assertFalse(n.pair_compatible(e))
        self.assertEqual(e['compatibility_tier'], 'OFFLINE_ONLY_OR_UNVERIFIED')
        self.assertEqual(e['kicad9_native_status'], 'UNVERIFIED_NOT_ENABLED')

    def test_patch_requires_current_native_setup_record(self):
        e = self.probe('10.0.8', '10.0.8')
        with patch.dict(n.os.environ, {}, clear=True):
            self.assertFalse(n.patch_native_ready(e))
        with patch.dict(n.os.environ, {'KICAD_PATCH_STARTUP_STATE': '/trusted/setup/startup-state.json'}):
            with patch('environment_start.check', return_value={'status': 'ENVIRONMENT_READY'}) as check:
                self.assertTrue(n.patch_native_ready(e))
                self.assertEqual(check.call_args.kwargs['cli'], '/trusted/kicad-cli')
            with patch('environment_start.check', return_value={'status': 'FULL_SETUP_REQUIRED'}):
                self.assertFalse(n.patch_native_ready(e))

    def test_baseline_patch_does_not_require_new_environment_setting(self):
        e = self.probe('10.0.7', '10.0.7')
        with patch.dict(n.os.environ, {}, clear=True):
            self.assertTrue(n.patch_native_ready(e))

    def test_future_10_minor_is_candidate_not_automatically_production_ready(self):
        e = self.probe('10.1.0', '10.1.0')
        self.assertTrue(n.pair_compatible(e))
        self.assertEqual(e['compatibility_tier'], 'PATCH_CANDIDATE_NATIVE_SMOKE_REQUIRED')
        with patch.dict(n.os.environ, {}, clear=True):
            self.assertFalse(n.patch_native_ready(e))

    def test_kicad_11_cli_is_detected_but_pcbnew_stays_blocked(self):
        e = self.probe('11.0.0', '11.0.0')
        self.assertTrue(n.cli_compatible(e))
        self.assertFalse(n.pcbnew_compatible(e))
        self.assertFalse(n.pair_compatible(e))
        self.assertEqual(e['compatibility_tier'], 'FUTURE_CLI_CANDIDATE_SMOKE_REQUIRED')
        self.assertEqual(e['capabilities']['pcb_native'], 'IPC_ADAPTER_REQUIRED')
        self.assertEqual(e['capabilities']['manufacturing'], 'BLOCKED')
        with patch.dict(n.os.environ, {}, clear=True):
            self.assertFalse(n.cli_native_ready(e))
        with patch.dict(n.os.environ, {'KICAD_CLI_STARTUP_STATE': '/trusted/cli-only/startup-state.json'}):
            with patch('environment_start.check', return_value={'status': 'ENVIRONMENT_CLI_READY'}):
                self.assertTrue(n.cli_native_ready(e))
            with patch('environment_start.check', return_value={'status': 'ENVIRONMENT_READY'}):
                self.assertFalse(n.cli_native_ready(e))

    def test_future_major_without_pcbnew_is_cli_only_not_installation_failure(self):
        with patch.object(n, 'run', return_value={'returncode': 0, 'stdout': '11.0.0\n', 'stderr': ''}), \
             patch.dict(sys.modules, {'pcbnew': None}):
            e = n.environment('/trusted/kicad-cli')
        self.assertTrue(n.cli_compatible(e))
        self.assertFalse(n.pair_compatible(e))

    def test_future_major_development_build_is_not_silently_enabled(self):
        self.assertIsNone(n.stable_kicad_version('11.0.0-rc1'))
        self.assertIsNone(n.stable_kicad_version('11.0.0-dev'))
        e = self.probe('11.0.0-rc1', '11.0.0-rc1')
        self.assertFalse(n.cli_compatible(e))

    def test_release_candidate_not_treated_as_stable_patch(self):
        self.assertIsNone(n.kicad10_patch_version('10.0.8-rc1'))
        self.assertIsNone(n.kicad10_patch_version('10.0.8-dev'))
        self.assertEqual(n.kicad10_patch_version('KiCad 10.0.8'), '10.0.8')

    def test_untrusted_cli_version_output_does_not_pass(self):
        pcb = MagicMock()
        pcb.GetBuildVersion.return_value = '10.0.8'
        with patch.object(n, 'run', return_value={'returncode': 0, 'stdout': '10.0.8 debug extra\\n', 'stderr': ''}), \
             patch.dict(sys.modules, {'pcbnew': pcb}):
            e = n.environment('/trusted/kicad-cli')
        self.assertFalse(n.pair_compatible(e))


class NativeReportProvenanceTests(unittest.TestCase):
    @staticmethod
    def report(version='10.0.8'):
        return {'$schema': 'https://schemas.kicad.org/erc.v1.json',
                'kicad_version': version, 'coordinate_units': 'mm',
                'source': 'demo.kicad_sch',
                'included_severities': ['error', 'warning', 'exclusion'],
                'ignored_checks': [],
                'sheets': [{'path': '/', 'violations': []}]}

    def test_matching_patch_10_0_8_report_is_accepted(self):
        self.assertEqual(extract('erc', self.report(), 'demo.kicad_sch', expected_version='10.0.8'), [])

    def test_wrong_patch_report_is_rejected(self):
        with self.assertRaises(ValueError):
            extract('erc', self.report('10.0.7'), 'demo.kicad_sch', expected_version='10.0.8')

    def test_future_major_cli_report_is_parsed_only_if_schema_and_version_match(self):
        self.assertEqual(extract('erc', self.report('11.0.0'), 'demo.kicad_sch', expected_version='11.0.0'), [])
        with self.assertRaises(ValueError):
            extract('erc', self.report('11.0.0'), 'demo.kicad_sch', expected_version='10.0.8')
        r = self.report('11.0.0')
        r['$schema'] = 'https://schemas.kicad.org/erc.v2.json'
        with self.assertRaises(ValueError):
            extract('erc', r, 'demo.kicad_sch', expected_version='11.0.0')

    def test_kicad9_report_not_accepted_as_kicad10(self):
        with self.assertRaises(ValueError):
            extract('erc', self.report('9.0.9'), 'demo.kicad_sch', expected_version='9.0.9')

    def test_ignored_checks_still_block_production(self):
        r = self.report()
        r['ignored_checks'] = [{'key': 'TEST', 'description': 'ignored by user'}]
        with self.assertRaises(ValueError):
            extract('erc', r, 'demo.kicad_sch', expected_version='10.0.8')


if __name__ == '__main__':
    unittest.main()
