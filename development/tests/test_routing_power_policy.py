"""R10 routing power-width guard; chart is NOT an IPC-2152 thermal proof."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2] / 'kicad-pcb-ai-workflow'
sys.path.insert(0, str(ROOT / 'scripts'))
import routing_policy as rp


class RoutingPowerPolicyTests(unittest.TestCase):
    def make_rule(self, *, current=1.0, copper=1.0, width=0.70, route_layer='F.Cu'):
        info = {'route_layer': route_layer}
        rules = [{
            'kind': 'track_width', 'nets': ['VDD'],
            'parameters': {
                'design_current_a': current, 'copper_oz': copper,
                'min_mm': width, 'max_mm': max(width, 1.4),
                'thermal_min_width_mm': 0.50,
                'voltage_drop_min_width_mm': 0.60,
            },
        }]
        layers = [{'name': 'F.Cu', 'role': 'signal', 'signal_enabled': True,
                   'finished_copper_oz': copper}]
        return info, rules, layers

    def test_reference_chart_first_capacity_at_or_above_current(self):
        self.assertEqual(rp.power_reference_width(1.0, 1.0), 0.4)
        self.assertEqual(rp.power_reference_width(2.0, 1.0), 0.8)
        self.assertEqual(rp.power_reference_width(1.0, 1.5), 0.3)
        self.assertEqual(rp.power_reference_width(2.0, 2.0), 0.5)

    def test_power_extra_width_0_254mm_not_copper_clearance(self):
        info, rules, layers = self.make_rule()
        r = rp.validate_power_width('VDD', info, rules, layers, {'F.Cu'})
        self.assertAlmostEqual(r['chart_width_mm'], 0.4)
        self.assertAlmostEqual(r['minimum_required_width_mm'], 0.654)
        self.assertAlmostEqual(r['extra_width_mm'], 0.254)

    def test_narrow_trunk_is_blocked_not_silently_necked_down(self):
        info, rules, layers = self.make_rule(width=0.64)
        with self.assertRaises(rp.PolicyError) as raised:
            rp.validate_power_width('VDD', info, rules, layers, {'F.Cu'})
        self.assertEqual(raised.exception.code, 'POWER_WIDTH_UNDERSIZED')

    def test_thermal_or_drop_width_floor_may_dominate_chart(self):
        info, rules, layers = self.make_rule()
        rules[0]['parameters']['thermal_min_width_mm'] = 1.2
        rules[0]['parameters']['min_mm'] = 1.3
        r = rp.validate_power_width('VDD', info, rules, layers, {'F.Cu'})
        self.assertEqual(r['minimum_required_width_mm'], 1.2)

    def test_no_copper_weight_guess_for_half_oz(self):
        info, rules, layers = self.make_rule(copper=0.5)
        with self.assertRaises(rp.PolicyError) as raised:
            rp.validate_power_width('VDD', info, rules, layers, {'F.Cu'})
        self.assertEqual(raised.exception.code, 'POWER_COPPER_UNSUPPORTED')

    def test_current_beyond_chart_must_not_extrapolate(self):
        with self.assertRaises(rp.PolicyError) as raised:
            rp.power_reference_width(5.0, 1.0)
        self.assertEqual(raised.exception.code, 'POWER_CURRENT_OUT_OF_CHART')

    def test_copper_weight_must_match_real_route_layer(self):
        info, rules, layers = self.make_rule(copper=1.0)
        layers[0]['finished_copper_oz'] = 2.0
        with self.assertRaises(rp.PolicyError) as raised:
            rp.validate_power_width('VDD', info, rules, layers, {'F.Cu'})
        self.assertEqual(raised.exception.code, 'POWER_COPPER_MISMATCH')

    def test_missing_thermal_or_voltage_drop_evidence_blocks(self):
        info, rules, layers = self.make_rule()
        del rules[0]['parameters']['thermal_min_width_mm']
        with self.assertRaises(rp.PolicyError) as raised:
            rp.validate_power_width('VDD', info, rules, layers, {'F.Cu'})
        self.assertEqual(raised.exception.code, 'POWER_WIDTH_EVIDENCE_MISSING')

    def test_generic_gnd_routing_is_not_an_ordinary_category(self):
        self.assertIn('GND', rp.CATEGORIES)
        self.assertIn('return_path', rp.CATEGORY_RULES['GND'])
        self.assertIn('POWER_DISTRIBUTION', rp.POWER_CLASSES)


if __name__ == '__main__':
    unittest.main()
