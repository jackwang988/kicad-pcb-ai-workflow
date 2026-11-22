"""Offline tests only: fake MCP/board/CLI; do not claim live KiCad acceptance."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL=Path(__file__).resolve().parents[2] / 'kicad-pcb-ai-workflow'
sys.path.insert(0,str(SKILL/'scripts'))
import konnect_capabilities as kc
import konnect_backend as kb
import freeze_candidate as fr
import workflow


def board(x=10,y=20,locked=False):
    return f'''(kicad_pcb (version 20240108)
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (footprint "R_0603" (layer "F.Cu") {'locked' if locked else ''}
    (at {x} {y} 0) (property "Reference" "U1"))
  (footprint "R_0603" (layer "F.Cu") (at 50 60 90)
    (property "Reference" "R1")))'''


class FakeDiscover:
    def __init__(self):self.called=[]
    def call(self,name,arguments=None):
        self.called.append((name,arguments))
        if name=='list_toolboxes':return {'structuredContent':{'toolboxes':[{'name':'pcb_board'},{'name':'pcb_components'}]}}
        if name=='load_toolset':return {'structuredContent':{'ok':True}}
        raise ValueError('Unexpected tool invocation: '+name)
    def tools(self):
        return [{'name':'get_board_info','inputSchema':{'type':'object'}},
                {'name':'move_component','inputSchema':{'type':'object','properties':{'reference':{'type':'string'}}}},
                {'name':'autoroute_board','inputSchema':{'type':'object'}}]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.src=self.root/'source';self.src.mkdir()
        self.can=self.root/'candidate';self.can.mkdir()
        self.src_board=self.src/'main.kicad_pcb';self.can_board=self.can/'main.kicad_pcb'
        for p in (self.src_board,self.can_board):p.write_text(board(),encoding='utf-8')
        self.identity={'version':'0.14.1','build_commit':'testcommit','executable_sha256':'a'*64,
                       'server_name':'konnect','profile':'test','eligible_kicad_versions':['10.0.8'],'toolchain_verified':True}
        self.move={'name':'move_component','inputSchema':{'type':'object','properties':{'reference':{'type':'string'}},'required':['reference']}}

    def test_dynamically_discover_all_toolsets_without_mutating_tools(self):
        session=FakeDiscover()
        result=kc.discover(session,all_toolsets=True)
        self.assertEqual(result['tools_count'],3)
        self.assertEqual(result['toolsets_loaded'],['pcb_board','pcb_components'])
        self.assertEqual(result['status'],'DISCOVERED_NOT_ACCEPTED')
        self.assertEqual(kc.risk(self.move),'L1')
        self.assertEqual(kc.risk({'name':'autoroute_board'}),'L3')
        self.assertTrue(all(method in ('list_toolboxes','load_toolset') for method,_ in session.called))

    def test_unknown_tool_appears_but_high_risk(self):
        self.assertEqual(kc.risk({'name':'new_future_tool'}),'L3')
        self.assertEqual(kc.risk({'name':'get_editor_state'}),'L0')
        self.assertEqual(kc.risk({'name':'get_schematic_info'}),'L0')
        self.assertEqual(kc.assessment(kc.empty_registry(),self.identity,{'name':'new_future_tool'},'10.0.8','new')['status'],'FIXTURE_REQUIRED')

    def test_matching_acceptance_requires_exact_build_schema_kicad_scope(self):
        record={'status':'FIXTURE_PASSED_ACCEPTANCE_RECORDED','backend':self.identity,'tool':self.move['name'],
                'tool_schema_sha256':kc.tool_schema_hash(self.move),'kicad_version':'10.0.8',
                'scope':'placement:QFN32:v1','risk':'L1'}
        drc_path=self.root/'fixture-native-drc.txt'
        drc_path.write_text('No violations',encoding='utf-8')
        record.update({'production_authorized':False,'source_sha256':'b'*64,
                       'fixture_before_sha256':'c'*64,'fixture_after_sha256':'d'*64,
                       'fixture':{'kind':'placement','expected_moved':['U1']},
                       'native_drc':{'returncode':0,'report_sha256':kc.sha(drc_path),'report_path':str(drc_path)}})
        registry={'schema_version':1,'kind':'konnect_capability_acceptance','records':[record]}
        self.assertEqual(kc.assessment(registry,self.identity,self.move,'10.0.8','placement:QFN32:v1')['status'],'ACCEPTED_WITHIN_RECORDED_SCOPE')
        self.assertEqual(kc.assessment(registry,self.identity,self.move,'10.0.8','placement:QFN48:v1')['status'],'FIRST_USE_POSTCHECK_REQUIRED')
        altered={**self.move,'inputSchema':{'type':'object','required':['other']}}
        self.assertEqual(kc.assessment(registry,self.identity,altered,'10.0.8','placement:QFN32:v1')['status'],'FIRST_USE_POSTCHECK_REQUIRED')
        self.assertEqual(kc.assessment(registry,{**self.identity,'version':'0.15'},self.move,'10.0.8','placement:QFN32:v1')['status'],'FIRST_USE_POSTCHECK_REQUIRED')
        self.assertEqual(kc.assessment(registry,self.identity,self.move,'10.0.9','placement:QFN32:v1')['status'],'FIRST_USE_POSTCHECK_REQUIRED')

    def test_workflow_konnect_write_requires_explicit_apply(self):
        options={'konnect_executable':'/verified/konnect.exe',
                 'konnect_config':'/verified/config.json',
                 'output_dir':'/independent/report',
                 'board':'candidate/main.kicad_pcb'}
        # The mutation is blocked before a tool or configuration can be read.
        with self.assertRaisesRegex(ValueError,'explicit --apply'):
            workflow.command(self.root,'workflow.json',None,'environment.konnect_invoke',options)

    def test_registry_drc_evidence_tamper_invalidates_acceptance(self):
        drc_path=self.root/'fixture-native-drc.txt'
        drc_path.write_text('Zero violations',encoding='utf-8')
        record={'status':'FIXTURE_PASSED_ACCEPTANCE_RECORDED',
                'backend':self.identity,'tool':self.move['name'],
                'tool_schema_sha256':kc.tool_schema_hash(self.move),
                'kicad_version':'10.0.8','scope':'placement:unit:v1','risk':'L1',
                'production_authorized':False,'source_sha256':'b'*64,
                'fixture_before_sha256':'c'*64,'fixture_after_sha256':'d'*64,
                'fixture':{'kind':'placement','expected_moved':['U1']},
                'native_drc':{'returncode':0,'report_sha256':kc.sha(drc_path),
                              'report_path':str(drc_path)}}
        registry={'schema_version':1,'kind':'konnect_capability_acceptance','records':[record]}
        self.assertEqual(kc.assessment(registry,self.identity,self.move,'10.0.8','placement:unit:v1')['status'],
                         'ACCEPTED_WITHIN_RECORDED_SCOPE')
        drc_path.write_text('Changed evidence',encoding='utf-8')
        self.assertEqual(kc.assessment(registry,self.identity,self.move,'10.0.8','placement:unit:v1')['status'],
                         'FIRST_USE_POSTCHECK_REQUIRED')

    def test_saved_footprint_lock_and_position_without_pcbnew(self):
        self.assertEqual(kc.inspect_saved_board(self.can_board)['U1']['x'],10)
        self.can_board.write_text(board(locked=True), encoding="utf-8")
        self.assertTrue(kc.inspect_saved_board(self.can_board)['U1']['locked'])

    def test_placement_only_expected_change_and_other_refs_protected(self):
        before=kc.inspect_saved_board(self.can_board)
        self.can_board.write_text(board(x=25,y=30), encoding="utf-8")
        after=kc.inspect_saved_board(self.can_board)
        self.assertEqual(kc.verify_fixture_change(before,after,{'kind':'placement','placements':{'U1':{'x':25,'y':30,'rotation':0}}})['expected_moved'],['U1'])
        with self.assertRaisesRegex(ValueError,'not reached'):
            kc.verify_fixture_change(before,after,{'kind':'placement','placements':{'U1':{'x':20,'y':30,'rotation':0}}})
        with self.assertRaisesRegex(ValueError,'Only placement'):
            kc.verify_fixture_change(before,after,{'kind':'routing','placements':{'U1':{'x':25,'y':30,'rotation':0}}})

    def test_first_use_without_prior_fixture_saves_and_checks_expected_state(self):
        class FakeCall:
            def __init__(self,target):self.target=target;self.calls=[]
            def call(self,name,args=None):
                self.calls.append(name)
                if name=='save_project':self.target.write_text(board(x=25,y=30), encoding="utf-8")
                return {'structuredContent':{'ok':True}}
            def tools(self):return [{'name':'save_project'}]
        fake=FakeCall(self.can_board)
        with patch.object(kc,'require_live_board',return_value={'editor_state':{'kicad_version':{'full_version':'10.0.8'}}}):
            r=kc.invoke(fake,self.move,{'reference':'U1'},self.identity,self.can_board,
                        self.src_board,'placement:test',kc.empty_registry(),save_after=True,
                        expected={'kind':'placement','placements':{'U1':{'x':25,'y':30,'rotation':0}}})
        self.assertEqual(r['capability_status'],'FIRST_USE_POSTCHECK_REQUIRED')
        self.assertEqual(r['status'],'OPERATION_EXECUTED_REQUIRES_PROJECT_REVIEW')
        self.assertEqual(r['verified_change']['expected_moved'],['U1'])
        self.assertEqual(fake.calls,['move_component','save_project'])

    def test_unknown_edit_is_not_auto_accepted_or_retried(self):
        class FakeCall:
            def __init__(self,target):self.target=target
            def call(self,name,args=None):
                if name=='save_project':self.target.write_text(board(x=25,y=30), encoding="utf-8")
                return {'structuredContent':{'ok':True}}
            def tools(self):return [{'name':'save_project'}]
        with patch.object(kc,'require_live_board',return_value={'editor_state':{'kicad_version':{'full_version':'10.0.8'}}}):
            r=kc.invoke(FakeCall(self.can_board),self.move,{'reference':'U1'},self.identity,
                        self.can_board,self.src_board,'placement:unknown',kc.empty_registry(),save_after=True)
        self.assertEqual(r['status'],'OPERATION_EXECUTED_NEEDS_POSTCHECK')
        self.assertIsNone(r['verified_change'])

    def test_L3_destructive_still_requires_isolated_fixture(self):
        class Fail:
            def call(self,*a,**kw):raise AssertionError('No destructive tool invocation')
        with patch.object(kc,'require_live_board',return_value={'editor_state':{'kicad_version':{'full_version':'10.0.8'}}}):
            with self.assertRaisesRegex(ValueError,'L3 destructive'):
                kc.invoke(Fail(),{'name':'delete_all_components'}, {},self.identity,
                          self.can_board,self.src_board,'L3:delete',kc.empty_registry(),save_after=True)

    def test_edit_without_save_is_rejected_before_call(self):
        class Fail:
            def call(self,*a,**kw):raise AssertionError('No edit before save authorization')
        with patch.object(kc,'require_live_board',return_value={'editor_state':{'kicad_version':{'full_version':'10.0.8'}}}):
            with self.assertRaisesRegex(ValueError,'save-after'):
                kc.invoke(Fail(),self.move,{'reference':'U1'},self.identity,self.can_board,
                          self.src_board,'placement:test',kc.empty_registry())

    def test_first_use_zone_fill_verifies_saved_polygons(self):
        before='(kicad_pcb (zone (net 1) (name "GND")))'
        after='(kicad_pcb (zone (net 1) (name "GND") (filled_polygon (pts (xy 0 0)))))'
        self.src_board.write_text(before, encoding="utf-8");self.can_board.write_text(before, encoding="utf-8")
        class Fake:
            def __init__(self,target):self.target=target
            def call(self,name,args=None):
                if name=='save_project':self.target.write_text(after, encoding="utf-8")
                return {'structuredContent':{'ok':True}}
            def tools(self):return [{'name':'save_project'}]
        with patch.object(kc,'require_live_board',return_value={'editor_state':{'kicad_version':{'full_version':'10.0.8'}}}):
            r=kc.invoke(Fake(self.can_board),{'name':'fill_zones'}, {'board':str(self.can_board)},self.identity,
                        self.can_board,self.src_board,'zone:GND',kc.empty_registry(),save_after=True,
                        expected={'kind':'zone_fill','min_filled_polygons':1})
        self.assertEqual(r['status'],'OPERATION_EXECUTED_REQUIRES_PROJECT_REVIEW')
        self.assertEqual(r['verified_change']['kind'],'zone_fill')

    def test_legacy_workflow_edit_blocked_without_bundle(self):
        with self.assertRaisesRegex(ValueError,'LEGACY_WRITE_DISABLED'):
            workflow.command(self.root,'workflow.json',None,'pcb.edit',{'apply':True})
        with self.assertRaisesRegex(ValueError,'LEGACY_WRITE_DISABLED'):
            workflow.command(self.root,'workflow.json',None,'environment.bridge_plugin',{'apply':True})

    def test_freeze_prepare_creates_copy_only_no_zone_fill(self):
        dest=self.root/'new-freeze'
        result=fr.prepare(self.src,'main.kicad_pcb',dest,apply=True)
        self.assertEqual(result['status'],'KONNECT_HANDOFF_PENDING')
        self.assertEqual((dest/'main.kicad_pcb').read_bytes(),self.src_board.read_bytes())
        self.assertEqual(result['candidate_sha256_before'],kc.sha(self.src_board))
        self.assertFalse((dest/'freeze-log.json').exists())

    def test_freeze_requires_real_matching_operation_receipt(self):
        dest=self.root/'new-freeze';fr.prepare(self.src,'main.kicad_pcb',dest,apply=True)
        receipt=self.root/'fake.json';receipt.write_text(json.dumps({'status':'OPERATION_EXECUTED_REQUIRES_PROJECT_REVIEW','tool':'foo'}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'No exact matching Konnect'):
            fr.finalize(dest,'main.kicad_pcb',receipt)
        self.assertFalse((dest/'freeze-log.json').exists())

    def test_freeze_rejects_source_change(self):
        dest=self.root/'new-freeze';fr.prepare(self.src,'main.kicad_pcb',dest,apply=True)
        self.src_board.write_text(board(x=34), encoding="utf-8")
        receipt=self.root/'fake.json';receipt.write_text('{}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'Source/candidate'):
            fr.finalize(dest,'main.kicad_pcb',receipt)

    def test_local_enrollment_does_not_auto_trust_binary(self):
        binary=self.root/'konnect.exe';binary.write_bytes(b'fixture')
        with self.assertRaisesRegex(ValueError,'explicit local enrollment'):
            kc.pin_binary_before_launch(binary)
        enrollment=self.root/'pin.json'
        enrollment.write_text(json.dumps({'schema_version':1,'approved_for_local_use':False,
             'executable_sha256':kc.sha(binary),'version':'0.15.0','build_commit':'abcdef','eligible_kicad_versions':['10.0.9']}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'Invalid or mismatching'):
            kc.pin_binary_before_launch(binary,enrollment)
        data=json.loads(enrollment.read_text(encoding="utf-8"));data['approved_for_local_use']=True
        enrollment.write_text(json.dumps(data), encoding="utf-8")
        digest,profile=kc.pin_binary_before_launch(binary,enrollment)
        self.assertEqual(digest,kc.sha(binary))
        self.assertEqual(profile['eligible_kicad_versions'],['10.0.9'])

    def test_registry_invalid_does_not_silently_pass(self):
        reg=self.root/'bad.json';reg.write_text('{"schema_version":1,"records":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,'Invalid capability registry'):
            kc.load_registry(reg)


if __name__=='__main__':unittest.main()
