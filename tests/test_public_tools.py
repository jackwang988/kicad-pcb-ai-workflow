"""Synthetic tests only; these do NOT emulate KiCad or validate real boards."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'
EX=ROOT/'examples/netlists'
sys.path.insert(0,str(SCRIPTS))
import _runtime
import diff_net

def run(name,*args):
    return subprocess.run([sys.executable,str(SCRIPTS/name),*map(str,args)],capture_output=True,text=True)

class NetlistTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(run('diff_net.py',EX/'baseline.xml',EX/'baseline.xml').returncode,0)
    def test_rename_strict_rejected(self):
        self.assertEqual(run('diff_net.py',EX/'baseline.xml',EX/'renamed.xml').returncode,1)
    def test_rename_topology_accepted(self):
        self.assertEqual(run('diff_net.py',EX/'baseline.xml',EX/'renamed.xml','--topo').returncode,0)
    def test_changed_topology_rejected(self):
        p=run('diff_net.py',EX/'baseline.xml',EX/'changed.xml','--topo','--json')
        self.assertEqual(p.returncode,1);self.assertFalse(json.loads(p.stdout)['equivalent'])
    def test_invalid_and_empty_not_green(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'bad.xml'
            for text in ['not xml','<export/>','<export><nets/></export>']:
                f.write_text(text)
                self.assertEqual(run('diff_net.py',f,EX/'baseline.xml').returncode,2)
    def test_unconnected_pin_changes_detected(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'nc.xml';g=Path(d)/'removed.xml'
            f.write_text('<export><nets><net name="unconnected-a"><node ref="U_A" pin="1"/></net></nets></export>')
            g.write_text('<export><nets><net name="unconnected-b"><node ref="U_A" pin="2"/></net></nets></export>')
            self.assertEqual(run('diff_net.py',f,g,'--topo').returncode,1)
    def test_duplicate_pin_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'duplicate.xml'
            f.write_text('<export><nets><net name="A"><node ref="U_A" pin="1"/></net><net name="B"><node ref="U_A" pin="1"/></net></nets></export>')
            self.assertEqual(run('diff_net.py',f,EX/'baseline.xml').returncode,2)
    def test_xml_attributes_and_escapes(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'escape.xml'
            f.write_text('<export><nets><net name="A&amp;B" code="1"><node pin="1" ref="U_A"/></net></nets></export>')
            self.assertEqual(diff_net.parse(f),{'A&B':frozenset({('U_A','1')})})

class OutputGuardTests(unittest.TestCase):
    def test_no_overwrite_source_or_existing(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.kicad_sch';source.write_text('synthetic')
            other=Path(d)/'existing.kicad_sch';other.write_text('keep')
            for target in [source,other]:
                with self.assertRaises(SystemExit):_runtime.new_output(source,target)
            self.assertEqual(source.read_text(),'synthetic');self.assertEqual(other.read_text(),'keep')
    def test_existing_directory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'src.kicad_sch';p.write_text('synthetic')
            with self.assertRaises(SystemExit):_runtime.new_output_directory(p,Path(d))
    def test_apply_required_before_transform(self):
        for name in ['route_v2.py','split_sheets.py']:
            p=run(name,'unused-source','unused-output')
            self.assertNotEqual(p.returncode,0);self.assertIn('--apply',p.stdout+p.stderr)
    def test_refill_preview_does_not_load_or_write(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.kicad_pcb';p.write_text('(synthetic-not-a-board)')
            out=Path(d)/'new.kicad_pcb';result=run('refill_zones.py',p,out)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(out.exists());self.assertEqual(p.read_text(),'(synthetic-not-a-board)')
    def test_missing_kicad_load_not_passed(self):
        spec=importlib.util.spec_from_file_location('page_check',SCRIPTS/'page_check.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        m.KICAD_CLI='/nonexistent-kicad-synthetic-fixture'
        with self.assertRaises(SystemExit):m.check_load('.',[])

class PackagingTests(unittest.TestCase):
    def test_all_python_syntax(self):
        for p in SCRIPTS.glob('*.py'):ast.parse(p.read_text())
    def test_doctor_core_is_not_board_claim(self):
        p=run('doctor.py','--require','core');self.assertEqual(p.returncode,0)
        value=json.loads(p.stdout);self.assertEqual(value['requested_profile'],'core')
        self.assertIn('pcbnew',value['modules'])
    def test_pdf_reorder_preserves_source(self):
        import fitz
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'in.pdf';out=Path(d)/'out.pdf'
            doc=fitz.open()
            for t in ['FIRST','SECOND']:
                page=doc.new_page();page.insert_text((72,72),t)
            doc.save(p);doc.close();before=p.read_bytes()
            result=run('pdf_reorder.py',p,out,'--move','2','1')
            self.assertEqual(result.returncode,0,result.stderr)
            with fitz.open(out) as result_doc:self.assertIn('SECOND',result_doc[0].get_text())
            self.assertEqual(p.read_bytes(),before)
            self.assertNotEqual(run('pdf_reorder.py',p,out,'--order','1,2').returncode,0)

if __name__=='__main__':unittest.main()
