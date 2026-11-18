"""Seven-stage routing plan/audit: synthetic software tests, no KiCad/Java."""
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parents[2] / "kicad-pcb-ai-workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
import routing_seven_stage as seven


def board(gpio="", gnd="", zone=False, footprint=""):
    fill = '(zone (net 1) (net_name "GND") (layer "B.Cu") (filled_polygon (layer "B.Cu") (pts (xy 0 0))))' if zone else ''
    return f'(kicad_pcb (version 20260101) (net 0 "") (net 1 "GND") (net 2 "GPIO") {footprint} {gnd} {gpio} {fill})'


def seg(name, x1, y1, x2, y2, width="0.2", net=2):
    return (f'(segment (start {x1} {y1}) (end {x2} {y2}) '
            f'(width {width}) (layer "F.Cu") (net {net}) (uuid "{name}"))')


class RoutingSevenStageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / 'before.kicad_pcb').write_text(board(), encoding='utf-8')
        (self.root / 'after.kicad_pcb').write_text(board(
            seg('new', 0, 0, 1, 1), zone=True), encoding='utf-8')
        (self.root / 'drc.json').write_text(json.dumps({
            'violations': [], 'unconnected_items': []}), encoding='utf-8')
        self.config = {
            'schema_version': 1, 'stage': 'import',
            'before_board': self.bind('before.kicad_pcb'),
            'after_board': self.bind('after.kicad_pcb'),
            'networks': {
                'GPIO': {
                    'minimum_width_mm': 0.2,
                    'allowed_layers': ['F.Cu', 'B.Cu'],
                    'min_via_diameter_mm': 0.3, 'min_via_drill_mm': 0.2,
                },
            },
            'protected_nets': ['GND'], 'gnd_nets': ['GND'],
            'protected_object_uuids': [], 'max_new_vias': 0,
        }

    def bind(self, name):
        p = self.root / name
        return {'file': name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}

    def write_cfg(self):
        (self.root / 'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        return 'config.json'

    def change_after(self, new):
        (self.root / 'after.kicad_pcb').write_text(new, encoding='utf-8')
        self.config['after_board'] = self.bind('after.kicad_pcb')

    def prepare_final(self):
        # Final DRC starts from a saved, already zone-filled candidate.
        # The synthetic ground report is bound to that exact checkpoint.
        (self.root / 'grounded.kicad_pcb').write_bytes(
            (self.root / 'after.kicad_pcb').read_bytes())
        self.config.update(
            stage='final', before_board=self.bind('grounded.kicad_pcb'),
            zone_refill_completed=True, native_drc_json=self.bind('drc.json'),
            native_drc_board_sha256=self.bind('after.kicad_pcb')['sha256'])
        (self.root / 'ground-report.json').write_text(json.dumps({
            'status': 'GROUND_FILLED_STITCHING_AUDITED_READY_FOR_NATIVE_DRC',
            'final_refilled_sha256': self.bind('grounded.kicad_pcb')['sha256'],
            'ground_zone_layers': {'GND': ['B.Cu']},
            'approved_stitching_via_uuids': [],
        }), encoding='utf-8')
        self.config['gnd_completion_report'] = self.bind('ground-report.json')


    def test_import_good_candidate_still_not_approved(self):
        out = seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(out['status'], 'IMPORTED_CANDIDATE_GEOMETRY_CHECKED_NOT_APPROVED')
        self.assertFalse(out['production_authorized'])
        self.assertEqual(out['added_segments'], 1)

    def test_gnd_route_would_change_protected_copper(self):
        self.change_after(board(seg('new', 0, 0, 1, 0),
                                seg('gnd', 0, 2, 0, 3, net=1), zone=True))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'PROTECTED_NET_COPPER_CHANGED')

    def test_non_45_degree_is_rejected(self):
        self.change_after(board(seg('new', 0, 0, 1.0, 0.5), zone=True))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'NON_45_SEGMENT')

    def test_underwidth_is_rejected(self):
        self.change_after(board(seg('new', 0, 0, 1, 1, '0.10'), zone=True))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'TRACK_WIDTH_UNDERSIZED')

    def test_existing_ordinary_copper_cannot_be_silently_removed(self):
        (self.root / 'before.kicad_pcb').write_text(board(
            seg('old', 0, 0, 0, 1)), encoding='utf-8')
        self.config['before_board'] = self.bind('before.kicad_pcb')
        self.change_after(board(seg('new', 0, 0, 1, 1), zone=True))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'UNAUTHORIZED_RIPUP')
        self.config['allowed_removed_track_uuids'] = ['old']
        out = seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(out['removed_prior_tracks'], 1)

    def test_footprints_cannot_move_during_ses_import(self):
        first = '(footprint "X:Y" (layer "F.Cu") (at 5 5) (uuid "fp1"))'
        moved = '(footprint "X:Y" (layer "F.Cu") (at 6 5) (uuid "fp1"))'
        (self.root / 'before.kicad_pcb').write_text(board(footprint=first), encoding='utf-8')
        self.config['before_board'] = self.bind('before.kicad_pcb')
        self.change_after(board(seg('new', 0, 0, 1, 1), zone=True, footprint=moved))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'FOOTPRINTS_CHANGED_BY_ROUTER')

    def test_stale_hash_is_rejected(self):
        self.config['after_board']['sha256'] = '0'*64
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'HASH_MISMATCH')

    def test_final_requires_real_filled_ground_zone(self):
        self.change_after(board(seg('new', 0, 0, 1, 1), zone=False))
        self.prepare_final()
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'GND_FILLED_ZONE_NOT_FOUND')

    def test_final_clean_drc_is_not_manufacturing_release(self):
        self.prepare_final()
        out = seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(out['status'], 'NATIVE_DRC_CLEAN_REQUIRES_G4_ENGINEER_REVIEW')
        self.assertFalse(out['production_authorized'])

    def test_final_unconnected_drc_is_rejected(self):
        (self.root / 'drc.json').write_text(json.dumps({
            'violations': [], 'unconnected_items': [{'type': 'unconnected'}]}))
        self.prepare_final()
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'NATIVE_DRC_NOT_CLEAN')

    def test_final_warning_drc_is_rejected(self):
        (self.root / 'drc.json').write_text(json.dumps({
            'violations': [{'severity': 'warning'}], 'unconnected_items': []}))
        self.prepare_final()
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'NATIVE_DRC_NOT_CLEAN')

    def test_unchanged_source_path_disallowed(self):
        self.config['after_board'] = self.config['before_board']
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'SAME_SOURCE_AND_CANDIDATE')


    def ground_fixture(self, add_stitch=True, initial_fill=True, final_fill=True):
        signal = seg('p3', 0, 0, 1, 1)
        def add_front_zone(raw, filled):
            return (raw[:-1] + ' (zone (net 1) (net_name "GND") (layer "F.Cu") '
                    + ('(filled_polygon (layer "F.Cu") (pts (xy 0 0)))' if filled else '')
                    + '))') if filled else raw
        initial = add_front_zone(board(gpio=signal, zone=initial_fill), initial_fill)
        # Via is GND, and only appears after initial fill.
        via = '(via (at 2 3) (size 0.6) (drill 0.3) ' \
              '(layers "F.Cu" "B.Cu") (net 1) (uuid "gnd-stitch-1"))'
        stitched = add_front_zone(board(gpio=signal, zone=initial_fill,
                                       gnd=via if add_stitch else ''), initial_fill)
        refilled = add_front_zone(board(gpio=signal, zone=final_fill,
                                       gnd=via if add_stitch else ''), final_fill)
        # Distinguish the second native fill receipt in fixture.
        if add_stitch and final_fill:
            refilled = refilled.replace('(pts (xy 0 0))',
                                        '(pts (xy 0 0) (xy 1 0) (xy 1 1))')
        files = {
            'post-route.kicad_pcb': board(gpio=signal),
            'first-fill.kicad_pcb': initial,
            'stitched.kicad_pcb': stitched,
            'last-fill.kicad_pcb': refilled,
        }
        for name, content in files.items():
            (self.root / name).write_text(content, encoding='utf-8')
        cfg = {
            'schema_version': 1, 'stage': 'ground',
            'pre_ground_board': self.bind('post-route.kicad_pcb'),
            'first_filled_board': self.bind('first-fill.kicad_pcb'),
            'stitched_board': self.bind('stitched.kicad_pcb'),
            'final_refilled_board': self.bind('last-fill.kicad_pcb'),
            'gnd_zone_layers': {'GND': ['F.Cu', 'B.Cu']},
            'approved_stitching_vias': [{
                'uuid': 'gnd-stitch-1', 'net': 'GND', 'at_mm': [2, 3],
                'layers': ['F.Cu', 'B.Cu'],
                'min_diameter_mm': 0.5, 'min_drill_mm': 0.25,
                'purpose': 'Connect isolated reference layers',
            }] if add_stitch else [],
        }
        (self.root / 'ground.json').write_text(json.dumps(cfg), encoding='utf-8')
        return cfg

    def test_ground_first_fill_stitch_and_final_refill_gate(self):
        self.ground_fixture()
        result = seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(result['status'],
                         'GROUND_FILLED_STITCHING_AUDITED_READY_FOR_NATIVE_DRC')
        self.assertEqual(result['approved_stitching_via_uuids'], ['gnd-stitch-1'])
        self.assertFalse(result['drc_executed'])

    def test_ground_no_stitch_via_required_is_allowed(self):
        self.ground_fixture(add_stitch=False)
        result = seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(result['approved_stitching_via_uuids'], [])

    def test_ground_missing_first_zone_definition_blocks(self):
        self.ground_fixture(initial_fill=False)
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(error.exception.code, 'GND_ZONE_NOT_DEFINED')

    def test_initial_unanchored_zone_allowed_when_stitched_and_finally_filled(self):
        self.ground_fixture()
        # Model an unanchored B.Cu pour: KiCad keeps its outline, but the
        # first fill removes the unconnected copper island before a GND via.
        for filename in ('first-fill.kicad_pcb', 'stitched.kicad_pcb'):
            p = self.root / filename
            source = p.read_text(encoding='utf-8')
            source = source.replace(
                '(filled_polygon (layer "B.Cu") (pts (xy 0 0)))', '')
            p.write_text(source, encoding='utf-8')
        cfg = json.loads((self.root / 'ground.json').read_text())
        cfg['first_filled_board'] = self.bind('first-fill.kicad_pcb')
        cfg['stitched_board'] = self.bind('stitched.kicad_pcb')
        (self.root / 'ground.json').write_text(json.dumps(cfg))
        out = seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(out['initial_unfilled_ground_layers']['GND'], ['B.Cu'])

    def test_initial_unanchored_zone_without_stitch_blocks(self):
        self.ground_fixture(add_stitch=False)
        p = self.root / 'first-fill.kicad_pcb'
        p.write_text(p.read_text().replace(
            '(filled_polygon (layer "B.Cu") (pts (xy 0 0)))', ''))
        cfg = json.loads((self.root / 'ground.json').read_text())
        cfg['first_filled_board'] = self.bind('first-fill.kicad_pcb')
        (self.root / 'ground.json').write_text(json.dumps(cfg))
        with self.assertRaises(seven.RoutingBlocked) as err:
            seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(err.exception.code, 'GND_FIRST_FILL_UNANCHORED')

    def test_ground_missing_final_refill_blocks(self):
        self.ground_fixture(final_fill=False)
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(error.exception.code, 'GND_LAYER_NOT_FILLED')

    def test_ground_requires_approved_via_whitelist(self):
        self.ground_fixture()
        cfg = json.loads((self.root / 'ground.json').read_text())
        cfg['approved_stitching_vias'] = []
        (self.root / 'ground.json').write_text(json.dumps(cfg))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(error.exception.code, 'UNAUTHORIZED_GND_STITCHING_VIA')

    def test_ground_rejects_wrong_via_size_or_net(self):
        self.ground_fixture()
        cfg = json.loads((self.root / 'ground.json').read_text())
        cfg['approved_stitching_vias'][0]['min_diameter_mm'] = 0.8
        (self.root / 'ground.json').write_text(json.dumps(cfg))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.ground_audit(self.root, 'ground.json')
        self.assertEqual(error.exception.code, 'STITCH_VIA_UNDERSIZED')

    def test_final_requires_ground_gate_not_just_refill_boolean(self):
        self.config.update(stage='final', zone_refill_completed=True,
                           native_drc_json=self.bind('drc.json'))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'INVALID_BINDING')

    def test_final_rejects_stale_ground_gate_board(self):
        self.prepare_final()
        report = json.loads((self.root / 'ground-report.json').read_text())
        report['final_refilled_sha256'] = '0' * 64
        (self.root / 'ground-report.json').write_text(json.dumps(report))
        self.config['gnd_completion_report'] = self.bind('ground-report.json')
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'GROUND_GATE_MISSING_OR_STALE')


if __name__ == '__main__':
    unittest.main()
