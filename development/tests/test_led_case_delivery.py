"""Semantic counterexamples for the public saved case and BOM checks."""
import csv,importlib.util,json,pathlib,shutil,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('native_led_case',ROOT/'development/native_led_8x8_e2e.py')
case=importlib.util.module_from_spec(spec);spec.loader.exec_module(case)

class LedCaseDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=pathlib.Path(self.tmp.name)
        self.rows=[]
        for name in ['BOM.csv','PCB-solder-pad-features.csv']:
            with (case.CASE/'evidence'/name).open(encoding='utf-8-sig',newline='') as f:self.rows+=list(csv.DictReader(f))
    def bom(self):
        p=self.base/'BOM.csv'
        with p.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(self.rows[0]));w.writeheader();w.writerows(self.rows)
        return p
    def test_native_bom_versus_purchase_features(self):
        result=case.audit_bom(self.bom());self.assertEqual(result['references'],84);self.assertEqual(result['purchasable_components'],80);self.assertEqual(result['PCB_pad_pairs'],4)
    def test_duplicate_reference_cannot_be_hidden_in_correct_groups(self):
        row=next(r for r in self.rows if r['References'].startswith('D'));row['References']+=',D1';row['Quantity']='65'
        with self.assertRaisesRegex(ValueError,'Duplicate/missing/extra'):case.audit_bom(self.bom())
    def test_missing_resistor_and_mismatched_quantity_fail(self):
        row=next(r for r in self.rows if r['References'].startswith('R'));row['References']='R1-R15';row['Quantity']='15'
        with self.assertRaises(ValueError):case.audit_bom(self.bom())
        row['References']='R1-R16'
        with self.assertRaisesRegex(ValueError,'quantity'):case.audit_bom(self.bom())
    def test_wrong_LED_identity_is_not_a_valid_2835_substitute(self):
        next(r for r in self.rows if r['References'].startswith('D'))['MPN']='OTHER_2835'
        with self.assertRaisesRegex(ValueError,'manufacturer/MPN'):case.audit_bom(self.bom())
    def test_source_rule_change_blocks_before_native_subprocess(self):
        clone=self.base/'case';shutil.copytree(case.CASE,clone)
        p=clone/'source'/('LED_Matrix_8x8_12V.kicad_pro');data=json.loads(p.read_text(encoding="utf-8"));data['board']['design_settings']['rule_severities']['silk_over_copper']='ignore';p.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(case.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'Published case source changed'):case.verify('must-not-run',self.base/'out',clone)
            run.assert_not_called()
    def test_closed_contour_equivalence_preserves_vertices(self):
        square=[(0,0),(2,0),(2,2),(0,2)];self.assertEqual(case.canonical_contour(square),case.canonical_contour(square[2:]+square[:2]+[square[2]]))
        self.assertEqual(case.canonical_contour(square),case.canonical_contour(square[::-1]))
        self.assertNotEqual(case.canonical_contour(square),case.canonical_contour([(0,0),(2,0),(2,1),(0,2)]))

if __name__=='__main__':unittest.main()
