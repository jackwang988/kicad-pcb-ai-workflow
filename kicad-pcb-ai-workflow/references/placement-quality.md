# Modular, Pin-Level and Visual PCB Placement Review

## Execution order

First derive the actual board outline, mounting holes, connector positions, mechanical keepouts and manufacturability/courtyard restrictions. Then assign functional modules and anchor critical locations: power loops, oscillators, resets, analog filters, RF feed/antenna, high-speed connectors and escape paths. Solve physical routing corridors and pin-level current return before seeking aesthetic symmetry.

The model plans component placement based on actual schematic net topology, verified G3 device cards and board-house rules. Accepted Konnect MCP tools apply real moves/rotations in bounded batches to the *current authorized working project*; Python `placement_review.py` reads and assesses the resulting geometry. It is not an implemented auto-placement optimizer. Check actual pad centers and pin identities, footprint orientation/side, courtyard BBox, module occupancy, shortest critical return loops, antenna/mounting restrictions, thermal airflow and assembly/test accessibility.

## Four evidence classes

1. **Mechanical geometry:** Board and mounting constraints, courtyard footprints, connector mating clearances, edge/keepout and assembly height limitations.
2. **Electrical local geometry:** Actual decoupling pin-to-cap pad connections, oscillator/clock loop geometry, RF matching/antenna positions, sensitive analog and power loop interactions; pad-center distance is not the full return path.
3. **Routing feasibility:** Access/escape channels, real narrow-pitch geometry, net classification, protected paths and current/thermal widths. An approximate airwire count is not proof of completed routing.
4. **Human visual quality:** Functional grouping, reference/value readability, silkscreen orientation, drawing legibility and service access, without weakening hard rules.

## Pre-route and final checks

Run the phase-specific review before routing and again after saved final copper/zone fill whenever relevant placement changed. Retain per-stage reports with current board SHA, source-card basis, actual component IDs/coords, observed violations and independent engineer decision. Fail/unknown/missing knowledge cannot become PASS to optimize appearance. See [schematic source](module-schematic.md), [G3/G4 workflow](latest-complete-workflow.md), [PCB rules](module-pcb.md).

```bash
# Read-only G3 report, always into a new immutable report directory.
python scripts/placement_review.py /project --policy placement-plan.json --netlist actual-netlist.xml --board actual-board.kicad_pcb --phase pre_route --review-config /project/static-review.json --output-dir /project/03_REPORTS/layout-r1
```
