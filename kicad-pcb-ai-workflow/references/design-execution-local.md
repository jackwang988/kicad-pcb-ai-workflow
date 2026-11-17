# R10 Executable Design Policy and Planned Work

This reference describes the *current actual implementation* versus future engineering plans. It is not proof of a universal automatic placement, routing, electrical field-simulation or manufacturing system. The main AI design workflow stops after a verified *candidate package for review*; real CAM, EVT/DVT/PVT and ECO remain external lifecycle steps. For the complete 16-node input/output and gate matrix use [latest workflow](latest-complete-workflow.md).

## Before layout: two-level engineering rules

1. Define **manufacturing constraints** from the actual board-house stack-up and fabrication class: copper/dielectric, drills, via diameter/annular ring, trace width/clearance, copper-to-edge, mask and assembly.
2. Define **project-specific network constraints**: rated continuous/peak current, voltage drop, temperature rise, approved trace/via geometry, impedance, differential skew, allowed reference plane/layer, timing/length, protection objects and isolation/safety.
3. Map each requirement to a native KiCad field or custom rule and a specific net/object, write backend, read-back query and independent verification evidence. Unsupported rules are explicitly marked and block dependent work.
4. Apply the settings in an isolated valid KiCad candidate. Save/reload; verify real layer order, effective NetClass bindings, rule priorities and expected violations. An external JSON policy does not prove actual rule activation.
5. When the toolchain permits, make positive/negative manufacturing violation fixtures in a disposable test copy: width, gap, drill, ring and board edge. Confirm the expected DRC rule ID, object UUID and actual report location. No fixture artifact may enter a final project.
6. Bind all rule evidence to project/board/stack-up/tool versions by hash. Relevant modifications invalidate affected checks.

## Topology-first schematic

Build a pin/net model with exact electrical endpoints, including rotation, mirrors, hierarchical ports and off-page names. Plan global wiring corridors before final placement, then symbol/label geometry, net drawing, save/reload netlist parity, ERC and page-level visual audit. A project-specific real Konnect operation may draw/modify the schematic; the general custom geometry engine is not fully implemented. Never infer electrical connectivity from touching graphics, and never change the expected net contract to fit erroneous output.

## Placement: proposed eight-part control loop

P1 verify board outline and fixed mechanical objects. P2 classify modules and source-backed restrictions. P3 anchor connectors, mounting holes, antenna and test access. P4 optimize sensitive power loops, oscillators, filters and high-speed endpoints. P5 resolve actual courtyard/keepout and crossing/corridor conflicts. P6 trial-route tightly spaced fan-outs when available; the existence of fewer airwires is not proof of routability. P7 execute scoped Konnect moves/rotations in batches with UUID and pad read-back. P8 save/reload, run native DRC and G3 schematic/geometry/visual review.

`placement_review.py` remains a read-only quality checker; the additional `placement_extract`, `placement_candidates`, `placement_optimize`, `placement_apply`, and `placement_verify` interfaces are **proposed**, not yet existing callable tools.

## Routing: seven verified stages

Check effective constraints; classify every net; route electrical/routing critical signals first; plan and implement ordinary nets with accepted tools; verify high-current rails, ground zones and return paths; optimize geometry and timing; finally save/reload and native-connectivity/DRC-check. Offline A* and external SES are candidate data, not evidence that the KiCad board was edited. Do not assume GND is solved by a final all-layer pour. Preserve all protected objects and do not silently relax rules. For actual operations, use Konnect as the sole writer; older instructions mentioning a default `pcbnew` zone-fill writer are superseded by [Konnect single-writer policy](konnect-capability-migration.md).

## Reliability

Manufacturer source cards are frozen once per exact MPN/package/project and reused across G1–G4. Every stage rechecks actual project results. A failed capability fixture, missing source, rule conflict, GUI/disk mismatch or stale proof causes `BLOCKED`; do not automate engineer approval or factory authorization.

Primary references: [KiCad PCB editor](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html) and applicable manufacturer/interface/IPC publications. These are external engineering authorities; their applicability must be checked per project.
