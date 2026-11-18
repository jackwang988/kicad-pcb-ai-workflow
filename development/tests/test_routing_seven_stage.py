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
        self.config.update(stage='final', zone_refill_completed=True,
                           native_drc_json=self.bind('drc.json'))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'GND_FILLED_ZONE_NOT_FOUND')

    def test_final_clean_drc_is_not_manufacturing_release(self):
        self.config.update(stage='final', zone_refill_completed=True,
                           native_drc_json=self.bind('drc.json'))
        out = seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(out['status'], 'NATIVE_DRC_CLEAN_REQUIRES_G4_ENGINEER_REVIEW')
        self.assertFalse(out['production_authorized'])

    def test_final_unconnected_drc_is_rejected(self):
        (self.root / 'drc.json').write_text(json.dumps({
            'violations': [], 'unconnected_items': [{'type': 'unconnected'}]}))
        self.config.update(stage='final', zone_refill_completed=True,
                           native_drc_json=self.bind('drc.json'))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'NATIVE_DRC_NOT_CLEAN')

    def test_final_warning_drc_is_rejected(self):
        (self.root / 'drc.json').write_text(json.dumps({
            'violations': [{'severity': 'warning'}], 'unconnected_items': []}))
        self.config.update(stage='final', zone_refill_completed=True,
                           native_drc_json=self.bind('drc.json'))
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'final')
        self.assertEqual(error.exception.code, 'NATIVE_DRC_NOT_CLEAN')

    def test_unchanged_source_path_disallowed(self):
        self.config['after_board'] = self.config['before_board']
        with self.assertRaises(seven.RoutingBlocked) as error:
            seven.audit(self.root, self.write_cfg(), 'import')
        self.assertEqual(error.exception.code, 'SAME_SOURCE_AND_CANDIDATE')


if __name__ == '__main__':
    unittest.main()
