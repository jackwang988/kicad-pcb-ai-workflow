import copy
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'kicad-pcb-ai-workflow/scripts'))
import device_knowledge as d

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.cache=self.root/'cache'
        self.src=self.root/'source.md';self.src.write_text('TEST ONLY. Supply must be 3.0 to 3.6 V. No clock is required.\n')
        self.meta=dict(manufacturer='TEST',mpn='IC1',package='QFN',document_id='DS1',revision='A',title='TEST ONLY',source_url='https://example.com/source.pdf',kind='datasheet')
    def tearDown(self):self.tmp.cleanup()
    def setup_card(self):
        r=d.ingest(self.cache,self.meta,['example.com'],self.src,True);self.record=pathlib.Path(r['record'])
        p=self.cache/'card.json';d.draft(self.cache,self.record,p,True);c=d.read(p)
        c['items']=[dict(id='supply',category='power_domains',requirement='Supply 3.0–3.6 V',conditions='Normal operation, TEST fixture',locator='§1',quote='Supply must be 3.0 to 3.6 V.',strength='mandatory',verification_method='Compare actual supply')]
        c['gaps']=[];c['status']='verified';e=self.cache/'test-evidence.txt';e.write_text('TEST DOUBLE ONLY, no real person approval')
        c['verification']=dict(reviewer='TEST_NOT_A_PERSON',date=d.today().isoformat(),reason='Synthetic test',source_identity_reason='Synthetic fixture',file=e.name,sha256=d.sha256(e),content_sha256=d.digest({k:c[k] for k in ('identity','record_sha256','items','gaps')}))
        d.write(p,c);self.card=p
        rec=d.read(self.record);self.q=dict(schema_version=1,max_check_age_days=30,devices=[dict(ref='U1',manufacturer='TEST',mpn='IC1',package='QFN',application='TEST',required_kinds=['datasheet'],cards=['card.json'],latest_checks={'datasheet':dict(date=d.today().isoformat(),revision='A',source_sha256=rec['source_sha256'],file=e.name,sha256=d.sha256(e),checked_by='TEST',result='current')})])
    def test_preview_no_write(self):
        r=d.ingest(self.cache,self.meta,['example.com'],self.src);self.assertEqual(r['status'],'PREVIEW');self.assertFalse(self.cache.exists())
    def test_same_bytes_reuse(self):
        a=d.ingest(self.cache,self.meta,['example.com'],self.src,True);b=d.ingest(self.cache,self.meta,['example.com'],self.src,True)
        self.assertEqual(b['status'],'REUSED');self.assertEqual(a['record'],b['record']);self.assertEqual(len(list((self.cache/'objects').iterdir())),1)
    def test_revision_retained(self):
        d.ingest(self.cache,self.meta,['example.com'],self.src,True);self.meta['revision']='B';d.ingest(self.cache,self.meta,['example.com'],self.src,True)
        self.assertEqual(len(list((self.cache/'records').iterdir())),2);self.assertEqual(len(list((self.cache/'objects').iterdir())),1)
    def test_bad_host(self):
        with self.assertRaises(ValueError):d.ingest(self.cache,self.meta,['ti.com'],self.src)
    def test_private_and_insecure_urls(self):
        for url in ['http://example.com/x','https://localhost/x','https://example.com:888/x','https://user@example.com/x']:
            with self.assertRaises(ValueError):d.public_url(url,['example.com'])
    def test_download_transport_and_extraction(self):
        class Response:
            url='https://example.com/source.pdf'
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return b'%PDF-1.4 SYNTHETIC TRANSPORT TEST'
        from unittest.mock import MagicMock
        opener=MagicMock();opener.open.return_value=Response()
        with patch.object(d,'public_url',side_effect=lambda url,hosts:url),patch.object(d.urllib.request,'build_opener',return_value=opener),patch.object(d,'extract',return_value='TEST extracted text'):
            r=d.ingest(self.cache,self.meta,['example.com'],None,True)
        rec=d.read(r['record']);self.assertEqual(rec['acquisition'],'https_download');self.assertEqual(d.local(self.cache,rec['text_file']).read_text(),'TEST extracted text')
    def test_download_html_response_rejected(self):
        class Response:
            url='https://example.com/source.pdf'
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return b'<html>login wall</html>'
        from unittest.mock import MagicMock
        opener=MagicMock();opener.open.return_value=Response()
        with patch.object(d,'public_url',side_effect=lambda url,hosts:url),patch.object(d.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(ValueError):d.ingest(self.cache,self.meta,['example.com'],None,True)
        self.assertFalse(self.cache.exists())
    def test_html_not_pdf(self):
        self.src=self.root/'source.pdf';self.src.write_text('<html>login</html>')
        with self.assertRaises(ValueError):d.ingest(self.cache,self.meta,['example.com'],self.src)
    def test_draft_not_trusted(self):
        r=d.ingest(self.cache,self.meta,['example.com'],self.src,True);p=self.cache/'draft.json';d.draft(self.cache,r['record'],p,True)
        with self.assertRaises(ValueError):d.validate_card(self.cache,p,True)
    def test_grounded_card(self):
        self.setup_card();self.assertEqual(d.audit(self.cache,self.q)['status'],'SOURCES_READY_FOR_PROJECT_REVIEW')
    def test_fake_quote(self):
        self.setup_card();c=d.read(self.card);c['items'][0]['quote']='There is no need for protection.';d.write(self.card,c)
        self.assertEqual(d.audit(self.cache,self.q)['status'],'BLOCKED')
    def test_edit_invalidates_verification(self):
        self.setup_card();c=d.read(self.card);c['items'][0]['requirement']='Changed';d.write(self.card,c)
        self.assertEqual(d.audit(self.cache,self.q)['status'],'BLOCKED')
    def test_source_corruption(self):
        self.setup_card();r=d.read(self.record);d.local(self.cache,r['source_file']).write_text('tampered')
        self.assertEqual(d.audit(self.cache,self.q)['status'],'BLOCKED')
    def test_missing_errata(self):
        self.setup_card();self.q['devices'][0]['required_kinds'].append('errata');self.assertEqual(d.audit(self.cache,self.q)['status'],'BLOCKED')
    def test_draft_issue_not_misattributed_to_errata(self):
        self.setup_card();c=d.read(self.card);c['status']='draft';d.write(self.card,c)
        self.q['devices'][0]['required_kinds'].append('errata')
        r=d.audit(self.cache,self.q)
        self.assertFalse(any(f['kind']=='errata' and 'Incomplete/draft' in f['description'] for f in r['findings']))
        self.assertTrue(any(f['kind']=='errata' and 'latest-version' in f['description'] for f in r['findings']))
    def test_wrong_package(self):
        self.setup_card();self.q['devices'][0]['package']='BGA';self.assertEqual(d.audit(self.cache,self.q)['status'],'BLOCKED')
    def test_expired_check(self):
        self.setup_card();self.q['devices'][0]['latest_checks']['datasheet']['date']=(d.today()-dt.timedelta(days=31)).isoformat();self.assertEqual(d.audit(self.cache,self.q)['status'],'BLOCKED')
    def test_new_version_not_silent_replace(self):
        self.setup_card();self.q['devices'][0]['latest_checks']['datasheet']['revision']='B';self.assertEqual(d.audit(self.cache,self.q)['status'],'BLOCKED')
    def test_bundle_preview_and_hash(self):
        self.setup_card();q=self.root/'q.json';d.write(q,self.q);out=self.root/'project'/'sources'
        d.bundle(self.cache,q,out);self.assertFalse(out.exists());d.bundle(self.cache,q,out,True)
        rec={'manifest':'sources/device-bundle.json','sha256':d.sha256(out/'device-bundle.json')}
        self.assertTrue(d.validate_bundle(out.parent,rec));(out/'card.json').write_text('{}')
        with self.assertRaises(ValueError):d.validate_bundle(out.parent,rec)
    def test_no_overwrite(self):
        self.setup_card();q=self.root/'q.json';d.write(q,self.q);out=self.root/'out';out.mkdir()
        with self.assertRaises(ValueError):d.bundle(self.cache,q,out,True)
    def test_static_packet_binds_bundle(self):
        from test_static_review import fixture
        from static_review import prepare
        from static_review_gate import validate
        self.setup_card();project=self.root/'project';cfg=fixture(project)
        q=self.root/'q.json';d.write(q,self.q);out=project/'device-sources';d.bundle(self.cache,q,out,True)
        source=d.read(self.record)
        cfg['documents'].append(dict(id='DEVICE',file='device-sources/'+source['source_file'],sha256=source['source_sha256'],title='TEST',revision='A',issuer='TEST',authority='datasheet',applicability='TEST ONLY',approved_by='TEST'))
        cfg['device_knowledge']={'manifest':'device-sources/device-bundle.json','sha256':d.sha256(out/'device-bundle.json'),'required_refs':['U1']}
        for spec in cfg['stages'].values():spec['component_sources']['U1'].append('DEVICE')
        p=project/'provided.xml';p.write_text(p.read_text().replace('<field name="MPN">TEST_ONLY</field>','<field name="MPN">IC1</field><field name="Manufacturer">TEST</field><field name="Package">QFN</field>'))
        d.write(project/'review-config.json',cfg);packet=self.root/'packet'
        prepare(project,project/'review-config.json','schematic',packet)
        manifest=d.read(packet/'packet.json');self.assertIn('device-sources/card.json',manifest['baseline'])
        (out/'card.json').write_text('{}');r=validate(project,packet)
        self.assertEqual(r['status'],'BLOCKED');self.assertTrue(any('device' in f['description'].lower() for f in r['findings']))
    def test_new_policy_missing_bundle_blocks(self):
        from test_static_review import fixture
        from static_review import validate_config
        cfg=fixture(self.root/'project');cfg['require_device_knowledge']=True
        with self.assertRaises(ValueError):validate_config(cfg,'schematic')
    def test_actual_project_identity(self):
        self.setup_card();q=self.root/'q.json';d.write(q,self.q);out=self.root/'project'/'sources';d.bundle(self.cache,q,out,True)
        source=d.read(self.record);cfg={'device_knowledge':{'manifest':'sources/device-bundle.json','required_refs':['U1']},'documents':[{'id':'DS','sha256':source['source_sha256']}],'stages':{'schematic':{'component_sources':{'U1':['DS']}}}}
        graph={'components':{'U1':{'fields':{'Manufacturer':'TEST','MPN':'IC1','Package':'QFN'}}}}
        self.assertTrue(d.validate_project_binding(out.parent,cfg,'schematic',graph));graph['components']['U1']['fields']['MPN']='IC2'
        with self.assertRaises(ValueError):d.validate_project_binding(out.parent,cfg,'schematic',graph)
if __name__=='__main__':unittest.main()
