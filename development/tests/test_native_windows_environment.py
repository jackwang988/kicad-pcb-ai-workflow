"""Regressions for the observed Windows version-output and startup contract."""
import copy
import pathlib
import sys
import unittest
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow/scripts'))
import npi_common as n
from native_report import extract

class WindowsVersionTests(unittest.TestCase):
    def probe(self,stdout='',stderr='',code=0,resource='10.0.7'):
        binding=MagicMock();binding.GetBuildVersion.return_value='10.0.7'
        record=None if resource is None else {'product_version':resource,'executable_sha256':'a'*64}
        with patch.object(n.os,'name','nt'),patch.object(n,'run',return_value={'returncode':code,'stdout':stdout,'stderr':stderr}),patch.object(n,'windows_cli_version_resource',return_value=record) as getter,patch.dict(sys.modules,{'pcbnew':binding}):
            result=n.environment('explicit-kicad-cli.exe')
        return result,getter.call_count
    def test_empty_success_reads_real_resource_not_binding(self):
        r,calls=self.probe();self.assertTrue(r['cli_exact_target']);self.assertEqual(calls,1)
        self.assertEqual(r['cli_version_source'],'windows_executable_version_resource');self.assertEqual(r['cli_probe']['stdout'],'')
    def test_resource_old_version_cannot_pass_with_matching_binding(self):
        r,_=self.probe(resource='9.0.8');self.assertFalse(r['cli_exact_target']);self.assertTrue(r['pcbnew_exact_target'])
    def test_missing_resource_remains_blocked(self):
        r,_=self.probe(resource=None);self.assertFalse(r['cli_exact_target'])
    def test_stderr_error_is_not_hidden_by_metadata(self):
        r,calls=self.probe(stderr='Access denied');self.assertFalse(r['cli_exact_target']);self.assertEqual(calls,0)
    def test_failed_process_is_not_hidden_by_metadata(self):
        r,calls=self.probe(code=1);self.assertFalse(r['cli_exact_target']);self.assertEqual(calls,0)
    def test_nonempty_wrong_stdout_is_not_overridden(self):
        r,calls=self.probe(stdout='9.0.8');self.assertFalse(r['cli_exact_target']);self.assertEqual(calls,0)
    def test_correct_stdout_keeps_original_contract(self):
        r,calls=self.probe(stdout='10.0.7\n');self.assertTrue(r['cli_exact_target']);self.assertEqual(calls,0)

class StartupReportTests(unittest.TestCase):
    def report(self):
        return {'$schema':'https://schemas.kicad.org/erc.v1.json','kicad_version':'10.0.7','coordinate_units':'mm','source':'demo.kicad_sch',
                'included_severities':['error','warning','exclusion'],'ignored_checks':[{'key':'single_global_label','description':'TEST ONLY'}],
                'sheets':[{'path':'/','violations':[]}]}
    def test_production_default_still_rejects_ignored_checks(self):
        with self.assertRaises(ValueError):extract('erc',self.report(),'demo.kicad_sch')
    def test_environment_can_parse_declared_ignored_checks(self):
        self.assertEqual(extract('erc',self.report(),'demo.kicad_sch',allow_ignored=True),[])
    def test_environment_still_rejects_malformed_ignored_checks(self):
        doc=self.report();doc['ignored_checks']=['ambiguous']
        with self.assertRaises(ValueError):extract('erc',doc,'demo.kicad_sch',allow_ignored=True)
    def test_environment_still_requires_schema_and_severity_coverage(self):
        for field in ('$schema','included_severities','ignored_checks'):
            doc=self.report();del doc[field]
            with self.assertRaises(ValueError):extract('erc',doc,'demo.kicad_sch',allow_ignored=True)

if __name__=='__main__':unittest.main()
