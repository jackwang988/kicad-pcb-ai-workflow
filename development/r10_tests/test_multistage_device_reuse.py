"""Stage G2/G3/G4 offline reuse regression tests; synthetic documents only."""
import contextlib, io, json, sys
from pathlib import Path
from unittest.mock import patch
import test_device_cache_first as fixture
from test_device_cache_first import h, write
import unittest
import device_knowledge as dk
import resource_guard as rg
import placement_review as pl
import static_review as sr
from design_intent import digest

class StageReuseTests(unittest.TestCase):
    # Synthetic fixtures only; do not duplicate all previous-release tests.
    def setUp(self):
        fx=fixture.CacheFirstTests(methodName='test_g1_uses_frozen_verified_card_and_original_text_without_network')
        fx.setUp()
        self.addCleanup(fx.t.cleanup)
        self.root,self.cache,self.previous,self.new,self.check=fx.root,fx.cache,fx.previous,fx.new,fx.check
    def _recategorize(self, categories):
        card_path=self.cache/'cards'/'demo.json'
        card=json.loads(card_path.read_text(encoding='utf-8'))
        template=card['items'][0]
        card['items']=[{**template,'id':'rule-'+str(i),'category':cat} for i,cat in enumerate(categories)]
        card['verification']['content_sha256']=digest({k:card[k] for k in ('identity','record_sha256','items','gaps')})
        write(card_path,card)
        return card
    def _bundle(self, sub='frozen'):
        result=dk.bundle(self.cache,self.previous,self.root/sub,apply=True)
        self.assertEqual(result['status'],'BUNDLED')
        path=self.root/sub/'device-bundle.json'
        return {'manifest':sub+'/device-bundle.json','sha256':h(path),'required_refs':['U1']}
    def _config(self,binding,docs=True):
        record=json.loads(next((self.root/'frozen'/'records').glob('*.json')).read_text(encoding="utf-8"))
        source=next((self.root/'frozen'/'objects').iterdir())
        doc={'id':record['document_id'],'file':source.relative_to(self.root).as_posix(),
             'sha256':h(source),'title':'synthetic','revision':'A','issuer':'DemoSemi',
             'authority':'datasheet','applicability':'synthetic','approved_by':'fixture'}
        config={'schema_version':1,'require_device_knowledge':True,'device_knowledge':binding,
                'documents':[doc], 'stages':{'pcb':{'component_sources':{'U1':[doc['id']]}}}}
        return config
    def _graph(self):
        return {'components':{'U1':{'fields':{'Manufacturer':'DemoSemi','MPN':'DEMO-1234','Package':'QFN-32'}}}}
    def test_multistage_uses_only_relevant_items(self):
        self._recategorize(['footprint_pinmap_variants','decoupling','critical_signal_paths','power'])
        binding=self._bundle()
        for stage,expected in [('g2','footprint_pinmap_variants'),('g3','decoupling'),('g4','critical_signal_paths')]:
            brief,txt=dk.project_stage_brief(self.root,binding,stage)
            self.assertEqual(brief['status'],'VERIFIED_FROZEN_STAGE_CARDS_NOT_DESIGN_APPROVAL')
            self.assertTrue(brief['offline'] and not brief['downloaded'])
            self.assertIn(expected,{x['category'] for x in brief['devices'][0]['items']})
            self.assertEqual(len(txt),1)
            self.assertFalse(brief['production_authorized'])
    def test_missing_stage_category_explicit_gap(self):
        binding=self._bundle()
        for stage in ('g2','g3','g4'):
            brief,_=dk.project_stage_brief(self.root,binding,stage)
            self.assertEqual(brief['status'],'STAGE_CARD_COVERAGE_INCOMPLETE')
            self.assertEqual(brief['coverage_gaps'][0]['ref'],'U1')
    def test_stage_detects_after_bundle_change(self):
        self._recategorize(['land_pattern'])
        binding=self._bundle()
        card=self.root/'frozen'/'cards'/'demo.json';j=json.loads(card.read_text(encoding="utf-8"));j['items'][0]['quote']='invalid override';write(card,j)
        with self.assertRaises(ValueError):dk.project_stage_brief(self.root,binding,'g2')
    def test_g2_resource_check_integrates_exact_identity_and_card(self):
        self._recategorize(['land_pattern']);binding=self._bundle()
        config=self._config(binding);write(self.root/'review.json',config)
        current={'schema_version':1,'kind':'project-resource-lock','scope':rg.SCOPE,
                 'project_id':'SYNTHETIC','manifest':'resources.json','manifest_sha256':'a'*64,
                 'inputs_sha256':{},'resources':[{'manufacturer':'DemoSemi','mpn':'DEMO-1234','package':'QFN-32'}],
                 'limitations':rg.LIMITATIONS,'production_authorized':False}
        write(self.root/'lock.json',current)
        with patch.object(rg,'audit',return_value=current):
            result=rg.check(self.root,'lock.json',review_config=str(self.root/'review.json'))
            self.assertEqual(result['g2_device_knowledge']['stage'],'g2')
            self.assertIn('NOT_APPROVED',result['status'])
            wrong={**current,'resources':[{'manufacturer':'DemoSemi','mpn':'DEMO-1234','package':'QFN-48'}]}
            write(self.root/'lock.json',wrong)
            with patch.object(rg,'audit',return_value=wrong):
                with self.assertRaises(ValueError):rg.check(self.root,'lock.json',review_config=str(self.root/'review.json'))
    def test_g3_cli_preview_reuses_frozen_card_current_pcb(self):
        self._recategorize(['decoupling']);binding=self._bundle()
        config=self._config(binding);write(self.root/'review.json',config)
        for name in ('board.kicad_pcb','net.xml','layout.json'):
            (self.root/name).write_text('fixture only',encoding='utf-8')
        result={'status':'DECLARED_LAYOUT_CHECKS_COMPLETE','inputs_sha256':{},'production_authorized':False}
        board={'footprints':[{'ref':'U1'}]}
        argv=['placement_review.py',str(self.root),'--policy','layout.json','--netlist','net.xml',
              '--board','board.kicad_pcb','--review-config',str(self.root/'review.json'), '--static-preview']
        with patch.object(sys,'argv',argv),patch.object(pl,'primitives',return_value=(board,[])), \
             patch.object(pl,'read_netlist',return_value=self._graph()),patch.object(pl,'audit',return_value=result.copy()), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(pl.main(),0)
        data=json.loads(output.getvalue())
        self.assertEqual(data['g3_device_knowledge']['stage'],'g3')
        self.assertEqual(data['g3_device_knowledge']['devices'][0]['items'][0]['category'],'decoupling')
        self.assertEqual(data['g3_state'],'VERIFIED_CACHED_LAYOUT_CANDIDATES_CURRENT_BOARD_VALIDATION_REQUIRED')
    def test_g3_cli_blocks_board_missing_core_footprint(self):
        self._recategorize(['decoupling']);binding=self._bundle()
        config=self._config(binding);write(self.root/'review.json',config)
        for name in ('board.kicad_pcb','net.xml','layout.json'):
            (self.root/name).write_text('fixture only',encoding='utf-8')
        result={'status':'DECLARED_LAYOUT_CHECKS_COMPLETE','inputs_sha256':{},'production_authorized':False}
        argv=['placement_review.py',str(self.root),'--policy','layout.json','--netlist','net.xml',
              '--board','board.kicad_pcb','--review-config',str(self.root/'review.json'),'--static-preview']
        with patch.object(sys,'argv',argv),patch.object(pl,'primitives',return_value=({'footprints':[]},[])), \
             patch.object(pl,'read_netlist',return_value=self._graph()),patch.object(pl,'audit',return_value=result.copy()), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(pl.main(),2)
        self.assertIn('missing on PCB',output.getvalue())
    def test_g4_static_review_packet_reuses_frozen_text(self):
        self._recategorize(['critical_signal_paths']);binding=self._bundle()
        config=self._config(binding)
        (self.root/'demo.kicad_sch').write_text('(kicad_sch (version 20250101))',encoding='utf-8')
        (self.root/'demo.kicad_pro').write_text('{}',encoding='utf-8')
        (self.root/'board.kicad_pcb').write_text('(kicad_pcb (version 20250101))',encoding='utf-8')
        xml='''<export><components><comp ref="U1"><value>DEMO-1234</value>
          <fields><field name="Manufacturer">DemoSemi</field><field name="MPN">DEMO-1234</field>
          <field name="Package">QFN-32</field></fields></comp></components>
          <nets><net code="1" name="VCC"><node ref="U1" pin="1"/></net></nets></export>'''
        (self.root/'demo.xml').write_text(xml,encoding='utf-8')
        config['stages']['pcb'].update({'inputs':{'schematic':'demo.kicad_sch','board':'board.kicad_pcb',
                'project':'demo.kicad_pro','provided_netlist':'demo.xml'}, 'critical_nets':['VCC'],
                'tasks':[{'id':'pcb.'+cat,'category':cat,'level':'阻断级',
                'requirement':'Synthetic only','strength':'mandatory',
                'targets':{'refs':['U1'],'nets':['VCC'],'layers':[],'footprints':[]},
                'source_refs':[{'document_id':config['documents'][0]['id'],'locator':'line 1'}],
                'check':{'kind':'semantic'}} for cat in sr.CATEGORIES['pcb']], 'support_files':[]})
        write(self.root/'pcb-config.json',config)
        fake_board={'footprints':[{'ref':'U1','pads':[]}], 'copper_layers':['F.Cu'], 'engine':'static_preview'}
        with patch.object(sr,'primitives',return_value=(fake_board,[])):
            outcome=sr.prepare(self.root,self.root/'pcb-config.json','pcb',self.root/'g4-packet')
        self.assertEqual(outcome['status'],'PACKET_READY_FOR_AI')
        brief=json.loads((self.root/'g4-packet'/'device-knowledge-brief.json').read_text(encoding="utf-8"))
        self.assertEqual(brief['stage'],'g4')
        packet=json.loads((self.root/'g4-packet'/'packet.json').read_text(encoding="utf-8"))
        self.assertEqual(packet['documents'][0]['text_origin'],'verified_project_device_cache')
        self.assertFalse(packet['native_ready'])

if __name__ == '__main__':
    import unittest
    unittest.main()
