# Schematic Design Intent and Effective PCB Constraints

## Intent is not the implemented board

A design-intent profile records requirements before physical routing. The actual KiCad project must be independently synchronized and read back. `design_intent.py` creates native rule/NetClass candidates; `design_intent_audit.py` checks real effective assignments where supported. An input JSON existing on disk is **not** proof that a rule was activated in KiCad.

## Signals, power and RF constraints

- **Differential or controlled single-ended links:** Exact net/pin endpoints, P/N pairing, signal protocol/PHY, target characteristic/differential impedance and tolerance from an authoritative interface/factory source; allowed layers, reference plane, topology, via constraints and skew/length budget. Do not require every differential bus to use the same impedance or matching length.
- **Power:** Nominal/min/max rail, continuous/peak transient current, allowable drop/temperature, copper thickness and current paths including return. Determine geometries from approved manufacturing conditions and thermal estimation; investigate neckdowns and via arrays, not merely the widest segment.
- **RF/antenna:** Frequency, reference ground, feed and matching arrangement, approved electrical geometry, power/return loop, physical antenna keepout with actually matching orientation and manufacturer instructions. Never remove all ground under RF indiscriminately or confuse a declared keepout outline with enforced native copper restrictions.
- **Spare options:** 0-ohm/DNP/selector value, default fit state, mutex groups, possible stubs and BOM/CPL variant implications.

## Apply/read-back steps

```bash
# Generate candidate rules: preview first, then explicit --apply into a new isolated destination.
python scripts/design_intent.py --help
# Verify the current synchronized project's real effective rules/geometry.
python scripts/design_intent_audit.py --help
```

Only write native project source with the accepted EDA writer. Confirm actual netlist and effective NetClasses/rule constraints, stack-up, layer mapping, project version and DRC on a saved candidate. Test native rule activation with isolated negative fixtures where possible. Any unsupported mapping, unbound net or mismatch is a blocking unresolved design constraint; do not lower the rule to obtain a clean report.

## Limits

Width/spacing cannot independently certify impedance, reference plane continuity, SI/PI or emissions. Native board DRC, detailed device guidance, validated field solver, factory process and engineer review are separate evidence classes. Changes to a source, project contract, net identity, rule file or geometry invalidate affected checks. Always bind proof to the exact design revision and avoid experimental tool writes to a live project.
