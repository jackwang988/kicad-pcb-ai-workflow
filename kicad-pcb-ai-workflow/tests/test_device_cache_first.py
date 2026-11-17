"""Offline tests for the device-card reuse flow; NOT an official source endorsement."""
import datetime as dt
import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import device_knowledge as dk
import static_review as review
from design_intent import digest


def h(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class CacheFirstTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        doc = self.root / 'example.txt'
        doc.write_text('VCC supply recommended operating voltage from 3.0 V to 3.6 V.\n', encoding='utf-8')
        meta = {'manufacturer':'DemoSemi','mpn':'DEMO-1234','package':'QFN-32',
                'document_id':'EX-DAT-1','revision':'A','title':'Example test document',
                'source_url':'https://www.example.com/docs/demo.txt','kind':'datasheet'}
        record_result = dk.ingest(self.cache,meta,['www.example.com'],source=str(doc),apply=True)
        record_path = Path(record_result['record'])
        card_path = self.cache / 'cards' / 'demo.json'
        card_path.parent.mkdir()
        card = dk.draft(self.cache,record_path,card_path,apply=True)['card']
        card['gaps'] = []
        card['status'] = 'verified'
        card['items'] = [{
            'id':'power-vcc','category':'power','requirement':'Check recommended supply voltage',
            'conditions':'Test fixture only; no real device applicability',
            'locator':'test-document line 1','quote':'VCC supply recommended operating voltage from 3.0 V to 3.6 V.',
            'strength':'recommended','verification_method':'Compare project supply against cited condition'}]
        evidence = self.cache / 'evidence' / 'review.txt'
        evidence.parent.mkdir()
        evidence.write_text('Synthetic test review. NOT real manufacturer validation.',encoding='utf-8')
        card['verification'] = {'reviewer':'fixture reviewer','date':dt.date.today().isoformat(),
                                'reason':'Synthetic test only','source_identity_reason':'Fixture matched',
                                'file':'evidence/review.txt','sha256':h(evidence),
                                'content_sha256':digest({k:card[k] for k in ('identity','record_sha256','items','gaps')})}
        write(card_path,card)
        check_file = self.cache / 'evidence' / 'latest.txt'
        check_file.write_text('Synthetic test check. NOT actual current version evidence.',encoding='utf-8')
        self.check = {'date':dt.date.today().isoformat(),'revision':'A',
                      'source_sha256':record_result['source_sha256'],
                      'file':'evidence/latest.txt','sha256':h(check_file),'checked_by':'fixture reviewer','result':'current'}
        self.base={'schema_version':1,'max_check_age_days':90,'devices':[{
                    'ref':'U1','manufacturer':'DemoSemi','mpn':'DEMO-1234','package':'QFN-32',
                    'application':'synthetic fixture','required_kinds':['datasheet'],
                    'cards':[],'latest_checks':{}}]}
        old={**self.base, 'devices':[{**self.base['devices'][0],
                'cards':['cards/demo.json'],'latest_checks':{'datasheet':self.check}}]}
        self.previous=self.root/'old-requirements.json'
        write(self.previous,old)
        self.new=self.root/'new-inventory.json'
        write(self.new,self.base)

    def test_register_resolve_audit_bundle_and_brief(self):
        self.assertEqual(dk.audit(self.cache,self.previous)['status'],'SOURCES_READY_FOR_PROJECT_REVIEW')
        self.assertEqual(dk.register(self.cache,self.previous,apply=True)['status'],'REGISTERED')
        self.assertEqual(dk.register(self.cache,self.previous,apply=True)['registered'],1)
        output=self.root/'new-resolved.json'
        result=dk.resolve(self.cache,self.new,output,apply=True)
        self.assertEqual(result['status'],'CACHE_HIT_READY_FOR_AUDIT')
        self.assertTrue(result['offline'] and not result['downloaded'])
        self.assertTrue(output.exists())
        self.assertEqual(dk.audit(self.cache,output)['status'],'SOURCES_READY_FOR_PROJECT_REVIEW')
        brief=dk.brief(self.cache,output,'U1')
        self.assertEqual(brief['total_matching'],1)
        self.assertEqual(brief['items'][0]['locator'],'test-document line 1')
        bundled=dk.bundle(self.cache,output,self.root/'frozen',apply=True)
        self.assertEqual(bundled['status'],'BUNDLED')

    def test_missing_identity_never_uses_near_match(self):
        dk.register(self.cache,self.previous,apply=True)
        q=json.loads(self.new.read_text())
        q['devices'][0]['package']='QFN-48'
        write(self.new,q)
        result=dk.resolve(self.cache,self.new)
        self.assertEqual(result['status'],'CACHE_INCOMPLETE_SOURCE_REVIEW_REQUIRED')
        self.assertEqual(result['entries'][0]['status'],'MISS')

    def test_stale_check_cannot_be_reused_as_current(self):
        dk.register(self.cache,self.previous,apply=True)
        q=json.loads(self.new.read_text())
        q['max_check_age_days']=0
        write(self.new,q)
        # Registry is current today, zero-day policy should pass.
        self.assertEqual(dk.resolve(self.cache,self.new)['status'],'CACHE_HIT_READY_FOR_AUDIT')
        # Place policy-sensitive check into the past while preserving evidence.
        old=json.loads(self.previous.read_text())
        old['devices'][0]['latest_checks']['datasheet']['date']=(dt.date.today()-dt.timedelta(days=4)).isoformat()
        old['max_check_age_days']=0
        write(self.previous,old)
        # Recreate registry with old record only.
        for entry in (self.cache/'registry').glob('*.json'): entry.unlink()
        self.assertEqual(dk.register(self.cache,self.previous)['status'],'BLOCKED')
        old['max_check_age_days']=30
        write(self.previous,old)
        self.assertEqual(dk.register(self.cache,self.previous,apply=True)['status'],'REGISTERED')
        result=dk.resolve(self.cache,self.new)
        self.assertEqual(result['entries'][0]['status'],'STALE')

    def test_modified_verified_card_fails_closed(self):
        dk.register(self.cache,self.previous,apply=True)
        p=self.cache/'cards'/'demo.json'
        data=json.loads(p.read_text());data['items'][0]['requirement']='tampered';write(p,data)
        result=dk.resolve(self.cache,self.new)
        self.assertEqual(result['entries'][0]['status'],'INVALID_CACHE_ENTRY')

    def test_no_unreviewed_card_registration(self):
        data=json.loads(self.previous.read_text())
        card=self.cache/'cards'/'demo.json'
        raw=json.loads(card.read_text());raw['status']='draft';write(card,raw)
        result=dk.register(self.cache,self.previous,apply=True)
        self.assertEqual(result['status'],'BLOCKED')

    def test_workflow_node3_uses_shared_cache_without_configuration_bundle(self):
        dk.register(self.cache,self.previous,apply=True)
        command=[sys.executable,'-B',str(SKILL/'scripts'/'workflow.py'),'run',str(self.root),
                 '--task','architecture.sources_resolve','--device-cache',str(self.cache),
                 '--device-inventory',self.new.name,'--device-output','workflow-resolved.json','--apply']
        cp=subprocess.run(command,capture_output=True,text=True,timeout=20)
        self.assertEqual(cp.returncode,0,cp.stdout+'\n'+cp.stderr)
        self.assertEqual(json.loads(cp.stdout)['status'],'CACHE_HIT_READY_FOR_AUDIT')
        self.assertTrue((self.root/'workflow-resolved.json').is_file())
        self.assertEqual(dk.audit(self.cache,self.root/'workflow-resolved.json')['status'],
                         'SOURCES_READY_FOR_PROJECT_REVIEW')

    def test_g1_uses_frozen_verified_card_and_original_text_without_network(self):
        original=dk.bundle(self.cache,self.previous,self.root/'g1-sources',apply=True)
        self.assertEqual(original['status'],'BUNDLED')
        manifest=self.root/'g1-sources'/'device-bundle.json'
        binding={'manifest':'g1-sources/device-bundle.json','sha256':h(manifest),
                 'required_refs':['U1']}
        brief,text_by_sha=dk.project_review_cache(self.root,binding)
        self.assertTrue(brief['offline'] and not brief['downloaded'])
        self.assertEqual(brief['status'],'VERIFIED_CACHED_CARDS_NOT_DESIGN_APPROVAL')
        self.assertEqual(brief['devices'][0]['ref'],'U1')
        self.assertEqual(brief['devices'][0]['items'][0]['item_id'],'power-vcc')
        self.assertEqual(len(text_by_sha),1)
        original_text=next(iter(text_by_sha.values()))
        self.assertTrue(original_text.is_file())
        self.assertIn('VCC supply',original_text.read_text(encoding='utf-8'))
        self.assertEqual(dk.project_review_cache(self.root,binding,max_items_per_device=1)[0]['devices'][0]['shown_count'],1)

    def test_g1_rejects_tampered_card_or_expired_check(self):
        dk.bundle(self.cache,self.previous,self.root/'g1-sources',apply=True)
        manifest=self.root/'g1-sources'/'device-bundle.json'
        binding={'manifest':'g1-sources/device-bundle.json','sha256':h(manifest)}
        card=self.root/'g1-sources'/'cards'/'demo.json'
        current=json.loads(card.read_text())
        current['items'][0]['requirement']='tampered review input'
        write(card,current)
        with self.assertRaises(ValueError):dk.project_review_cache(self.root,binding)

    def test_g1_requires_project_frozen_sources_not_shared_mutable_registry(self):
        with self.assertRaises((ValueError,FileNotFoundError)):
            dk.project_review_cache(self.root,{'manifest':'cache/registry/missing.json',
                                             'sha256':'0'*64})

    def test_g1_pdf_text_is_reused_without_pdf_extraction(self):
        doc=self.root/'manufacturer-original.pdf'
        doc.write_bytes(b'%PDF-1.4\nsynthetic fixture only')
        original_hash=h(doc)
        cached=self.root/'already-extracted.txt'
        cached.write_text('verified extracted text from frozen source',encoding='utf-8')
        output=self.root/'review-document.txt'
        with patch.object(review.shutil,'which',side_effect=AssertionError('pdftotext must not run')):
            origin=review.materialize_review_text(doc,output,original_hash,{original_hash:cached})
        self.assertEqual(origin,'verified_project_device_cache')
        self.assertEqual(output.read_text(),cached.read_text())
        with self.assertRaises(ValueError):
            review.materialize_review_text(doc,self.root/'wrong.txt','0'*64,{original_hash:cached})

    def test_g1_full_packet_preparation_reuses_project_frozen_knowledge(self):
        dk.bundle(self.cache,self.previous,self.root/'frozen',apply=True)
        manifest=self.root/'frozen'/'device-bundle.json'
        binding={'manifest':'frozen/device-bundle.json','sha256':h(manifest),
                 'required_refs':['U1']}
        source_path=next((self.root/'frozen'/'objects').iterdir())
        record=json.loads(next((self.root/'frozen'/'records').glob('*.json')).read_text())
        (self.root/'demo.kicad_sch').write_text('(kicad_sch (version 20250101))',encoding='utf-8')
        (self.root/'demo.kicad_pro').write_text('{}',encoding='utf-8')
        xml='''<export><components><comp ref="U1"><value>DEMO-1234</value>
  <fields><field name="Manufacturer">DemoSemi</field><field name="MPN">DEMO-1234</field>
  <field name="Package">QFN-32</field></fields></comp></components>
  <nets><net code="1" name="VCC"><node ref="U1" pin="1"/></net></nets></export>'''
        (self.root/'demo.xml').write_text(xml,encoding='utf-8')
        docid=record['document_id']
        tasks=[{'id':f'fixture.{cat}','category':cat,'level':'阻断级',
                'requirement':'Synthetic fixture only','strength':'mandatory',
                'targets':{'refs':['U1'],'nets':['VCC'],'layers':[],'footprints':[]},
                'source_refs':[{'document_id':docid,'locator':'test-document line 1'}],
                'check':{'kind':'semantic'}} for cat in review.CATEGORIES['schematic']]
        conf={'schema_version':1,'require_device_knowledge':True,
              'device_knowledge':binding,'documents':[{
                  'id':docid,'file':source_path.relative_to(self.root).as_posix(),
                  'sha256':h(source_path),'title':'Synthetic source','revision':'A',
                  'issuer':'DemoSemi','authority':'datasheet','applicability':'Synthetic only',
                  'approved_by':'Fixture reviewer'}],
              'stages':{'schematic':{'inputs':{'schematic':'demo.kicad_sch',
                    'project':'demo.kicad_pro','provided_netlist':'demo.xml'},
                    'critical_nets':['VCC'],'tasks':tasks,'component_sources':{'U1':[docid]},
                    'support_files':[]}}}
        write(self.root/'review.json',conf)
        outcome=review.prepare(self.root,self.root/'review.json','schematic',self.root/'g1-packet')
        self.assertEqual(outcome['status'],'PACKET_READY_FOR_AI')
        self.assertFalse(outcome['native_ready'])  # Synthetic netlist is NOT a native ERC pass.
        packet=json.loads((self.root/'g1-packet'/'packet.json').read_text())
        self.assertEqual(packet['device_knowledge_brief'],'device-knowledge-brief.json')
        self.assertEqual(packet['documents'][0]['text_origin'],'verified_project_device_cache')
        brief=json.loads((self.root/'g1-packet'/'device-knowledge-brief.json').read_text())
        self.assertEqual(brief['devices'][0]['items'][0]['item_id'],'power-vcc')
        self.assertIn('先读packet.json中的device_knowledge_brief',
                      (self.root/'g1-packet'/'review-request.md').read_text(encoding='utf-8'))

    def test_no_overwriting_resolved_file(self):
        dk.register(self.cache,self.previous,apply=True)
        with self.assertRaises(ValueError):dk.resolve(self.cache,self.new,self.new,apply=True)

if __name__=='__main__':unittest.main()
