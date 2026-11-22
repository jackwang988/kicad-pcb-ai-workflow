"""Preparation refusals are checked without network/build/editor side effects."""
import importlib.util,pathlib,shutil,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('field_companion',ROOT/'development/konnect-field-extension/prepare.py')
companion=importlib.util.module_from_spec(spec);spec.loader.exec_module(companion)
class CompanionPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=pathlib.Path(self.tmp.name)
    def test_existing_destination_is_never_overwritten(self):
        dest=self.base/'existing';dest.mkdir();sentinel=dest/'operator-file';sentinel.write_text('keep', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'NEW'):companion.prepare(dest)
        self.assertEqual(sentinel.read_text(encoding="utf-8"),'keep')
    def test_bad_archive_is_rejected_before_source_extraction(self):
        archive=self.base/'wrong.zip';archive.write_bytes(b'not the pinned upstream')
        with patch.object(companion.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'archive hash'):companion.prepare(self.base/'dest',archive)
            run.assert_not_called()
        self.assertFalse((self.base/'dest/source').exists())
    def test_changed_module_blocks_before_destination_creation(self):
        here=self.base/'payload';shutil.copytree(companion.HERE,here);(here/'pcb_fields.rs').write_text('// changed', encoding="utf-8")
        with patch.object(companion,'HERE',here):
            with self.assertRaisesRegex(ValueError,'source hash'):companion.prepare(self.base/'dest')
        self.assertFalse((self.base/'dest').exists())
if __name__=='__main__':unittest.main()
