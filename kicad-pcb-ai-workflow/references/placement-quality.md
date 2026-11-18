# Modular, Pin-Level and Visual PCB Placement Review

## Execution order

First derive the actual board outline, mounting holes, connector positions, mechanical keepouts and manufacturability/courtyard restrictions. Then assign functional modules and anchor critical locations: power loops, oscillators, resets, analog filters, RF feed/antenna, high-speed connectors and escape paths. Solve physical routing corridors and pin-level current return before seeking aesthetic symmetry.

The model plans component placement based on actual schematic net topology, verified G3 device cards and board-house rules. Accepted Konnect MCP tools apply real moves/rotations in bounded batches to the *current authorized working project*; Python `placement_review.py` reads and assesses the resulting geometry. It is not an implemented auto-placement optimizer. Check actual pad centers and pin identities, footprint orientation/side, courtyard BBox, module occupancy, shortest critical return loops, antenna/mounting restrictions, thermal airflow and assembly/test accessibility.

## Four evidence classes

1. **Mechanical geometry:** Board and mounting constraints, courtyard footprints, connector mating clearances, edge/keepout and assembly height limitations.
2. **Electrical local geometry:** Actual decoupling pin-to-cap pad connections, oscillator/clock loop geometry, RF matching/antenna positions, sensitive analog and power loop interactions; pad-center distance is not the full return path.
3. **Routing feasibility:** Access/escape channels, real narrow-pitch geometry, net classification, protected paths and current/thermal widths. An approximate airwire count is not proof of completed routing.
4. **Human visual quality:** Functional grouping, reference/value readability, silkscreen orientation, drawing legibility and service access, without weakening hard rules.

## G3 pre-route layout-only versus G4 post-route DRC

**G3:** `pcb.layout_plan` → Konnect accepted placement moves → save/position readback → `pcb.placement_pre` / `placement_review.py --phase pre_route`. Check supported Courtyard/collision, mechanical keepouts, module ownership, source-bound pin proximity/decoupling, corridor and anticipated routing access. **No full-board KiCad DRC is run and unconnected nets are never a G3 failure.** Do not call `pcb.prepare`/`pcb.gate` during G3.

**After G3:** complete signal and power/GND routing → zone fill/refill → save/reload. **G4:** `pcb.prepare` invokes native full-board KiCad DRC (including unconnected items and schematic parity); `pcb.gate` requires AI and engineer review. `pcb.placement_final` may recheck final placement but cannot replace G4 DRC.

Run phase-specific placement reviews before routing and again after saved final copper/zone fill whenever relevant placement changed. Retain per-stage reports with current board SHA, source-card basis, actual component IDs/coords, observed violations and independent engineer decision. Fail/unknown/missing knowledge cannot become PASS to optimize appearance. See [schematic source](module-schematic.md), [G3/G4 workflow](latest-complete-workflow.md), [PCB rules](module-pcb.md).

```bash
# Read-only G3 report, always into a new immutable report directory.
python scripts/placement_review.py /project --policy placement-plan.json --netlist actual-netlist.xml --board actual-board.kicad_pcb --phase pre_route --review-config /project/static-review.json --output-dir /project/03_REPORTS/layout-r1
```

## Exact policy inputs and implementation boundaries

Use `assets/placement-plan.template.json` (schema version 1), binding every policy source by project-local file SHA-256 and document locator. Every actual PCB footprint, including DNP, mechanical and test parts, must belong to exactly one module; module regions may overlap but component ownership cannot. Assign anchors, members, real `refs`, roles and allowed `bounds_mm`. Typical roles are controller, decoupling, clock, power, connector, protection, termination, filter, feedback, RF, analog, passive, test, mechanical, reserve and other. Roles follow pin/net application, never a C/R prefix. Schematic-only symbols need an explicit ref/reason/evidence exception; mechanical footprints need not appear in the schematic. Use `other` only after reviewing electrical applicability.

`critical_subcircuits` must explicitly list `id/type/reason/refs/check_ids/source`. Types include decoupling, power_loop, crystal, termination, protection, filter, feedback, rf, reserve and other. Each known decoupling capacitor must have a dedicated pin-level decoupling rule; do not treat arbitrary nearby pads as an effective decoupling circuit.

| Local circuit | Locate relative to | What the geometry does not prove |
|---|---|---|
| Bypass capacitors | Named IC power pin, capacitor power/ground pads and explicit return anchor | Pad-center proximity cannot establish return-loop inductance or copper continuity |
| Switching regulator | Manufacturer-identified high-di/dt loop and quiet sense/feedback point | Courtyard envelope does not define the actual current loop |
| Oscillator/clock | Specified pins, load capacitance path and noise-sensitive neighbors | No universal copper cutout or blanket ground-fence rule |
| Series/parallel termination | Actual driver or receiver as required by topology | Do not place every resistor next to the IC by default |
| Interface protection/ESD | Connector entry, upstream/downstream nets and low-inductance discharge path | Short path to controller is not the same as effective ESD return |
| RF feed/matching/antenna | Device-specific topology, reference plane and radiating keepout | Do not remove copper beneath all RF circuitry by default |
| Feedback/analog filtering | Specific sense point, source impedance and return/reference requirements | Track length alone does not establish accuracy or stability |
| Optional/DNP branches | Installed variant and physical stub/pad parasitics | Unpopulated pads may still affect the RF/high-speed topology |

### Supported constraints and verification limits

`placement_review.py` is **read-only**, not an automatic placer. Every constraint has unique `id`, `kind`, risk `level` and source. Physical units and thresholds must come from the current design or a relevant manufacturer/fabricator source, never a generic hard-coded distance.

- `fixed`: actual footprint reference position and angle against `position_mm`, `angle_deg`, `position_tolerance_mm` and `angle_tolerance_deg`; does not prove 3D fit.
- `pad_proximity`: exact `(ref,pad,net)` endpoints, maximum distance and optional same-side rule; cross-check real XML netlist and actual pad identities.
- `decoupling`: `ic_power`, `cap_power`, `cap_ground`, `return_anchor`, `max_power_mm`, `max_return_mm` and side rule. The capacitor's power and ground endpoints must be distinct, with a named return pad or validated via UUID. Even a passing geometry result does not prove reference-plane continuity.
- `corridor`: protected rectangle, margin and explicit allowed footprint refs. Only conservative supported courtyard AABB intrusion is checked; routing capacity is not computed.
- `alignment`, `uniform_spacing` (three or more refs) and `orientation`: aesthetic constraints only, never grounds to override electrical or manufacturing violations.

Courtyard/physical boundary checks require supported real vertices rather than footprint center only. Supported static geometry is limited to simple same-side rectilinear closed outlines; rotated, bottom-side, curved/multi-outline or missing-courtyard cases may require native or manual evidence. If the exact pad transform cannot be independently established, return `manual_required` / blocked instead of computing a guessed position. For `manual_geometry[ref]`, require a current board SHA-256, reason and actual native/mechanical evidence. This records a human-supplied exception, not an automatic PASS.

Only aesthetic rules may declare an `exception={reason,evidence:{file,sha256}}`; hard rules never inherit such a waiver. Silkscreen obscuration, polarity, pin 1, 3D interference, thermal access, placement height and repairability require actual design/assembly review beyond the basic geometric checker.

### Pre-route, final review and invalidation

`reviews.pre_route` must bind `placement_sha256`, `netlist_sha256`, `policy_sha256` (excluding the review record), reviewer, date, reason and evidence. Review routability/escape, return paths, manufacturer source layouts and mechanical constraints for **every** declared critical subcircuit. It does not prove automatic routability. `reviews.final` must correspond to the same actual placement and final `board_sha256`, and cover final visual quality and all `moves_rechecked` after routing/fill. Board changes can invalidate final review even when the pre-route placement remains unchanged; changes to pads, constraints, source data or component position require the affected pre-route review again. Never reconstruct or backdate a missing earlier review.

For PCB static AI review, set `require_placement_review=true`, bind `placement_review.policy`, and add a `placement_quality` semantic task. Cover all physical footprints and critical nets; mechanical objects are observed as footprints, electrical pins as `(ref,pin,net)`. Native layer views and source layouts are separate evidence. Missing pre-route/final evidence or hard-constraint failure blocks the relevant G3/G4 and manufacturing gates; **unrouted nets alone never block G3**. Human/AI review is required even when the visual plot looks tidy.

Deliver four classes of *read-only* artifacts: `module-map.svg`, `local-N.svg` local circuit views, `placement-report.json/.md`, and `visual-review.md`. They are coordinate illustrations, not KiCad native copper/CAM/3D proof. Where native PCB extraction is unavailable, `--static-preview` is screening only; unsupported geometry remains a reported gap. Strict reports use new immutable report directories; do not clone a fresh KiCad engineering project merely for another report.

## Placement prerequisite: effective rules and module zoning

Use the [rules-first module layout](pcb-module-layout.md) preflight before generating new candidate positions. It checks actual KiCad source/effective rules and source-backed fabrication minima instead of duplicating G3's post-write electrical and mechanical review. The modular heuristic is read-only; no proposal is a placed PCB, routed copper, verified SI/PI or G3 approval. Read back current Konnect moves and continue with this original G3 reviewer.
