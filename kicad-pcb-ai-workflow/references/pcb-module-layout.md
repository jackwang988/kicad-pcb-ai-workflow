# Rules-First PCB Module Placement Planner — R10 Preview

## Required engineering order

1. Finish native schematic/ERC and G2 symbol-pin → footprint-pad checks. KiCad 10 Update PCB from Schematic (F8) synchronizes footprints and nets; the XML netlist is for independent pad/net parity, not mandatory intermediate import.
2. Before G3 placement, agree on fabrication constraints, actual physical stack-up, board/connector/hole geometry, RF keepouts and fixed anchors. Apply KiCad Board Setup minima for trace/copper clearance, via diameter/drill, annular ring, copper-edge/hole clearance, NetClasses and design-specific power, high-speed, RF and custom rules. Pad geometry comes from approved footprints rather than generic global limits.
3. Run existing design_intent_audit.py native effective-rule checking in pre_route mode. The planner compares seven sourced fabrication minima against actual .kicad_pro settings in millimeters, and checks current native PCB versus schematic XML pad/net identities. A JSON policy alone does not prove rules are activated.
4. Determine whole-board fixed regions, then place critical and ordinary members of each source-defined functional module using actual front-side Courtyard polygons and bounded net-neighbor heuristics; finally test bounded whole-module translations for inter-module coordination.
5. The planner is read-only. Apply exact current-revision coordinates through the single Konnect writer in small batches, save and read back, then run `pcb.placement_pre` (`placement_review.py --phase pre_route`) as the **G3 layout-only review, without full-board DRC or a zero-unconnected requirement**. After G3, complete routing and refill copper zones, then run full native DRC and G4 review.

## Input contracts and commands

Fill assets/pcb-module-layout.template.json, assets/pcb-fab-placement-rules.template.json and the existing assets/placement-plan.template.json with real project-specific data. The fab minimums_mm values must contain min_clearance_mm, min_track_width_mm, min_via_diameter_mm, min_via_drill_mm, min_annular_width_mm, min_copper_edge_clearance_mm and min_hole_to_hole_mm, plus courtyard_clearance_mm. The equivalent serialized KiCad rule keys include min_through_hole_diameter and min_via_annular_width. Never invent fabricator minima.

    python scripts/workflow.py run /project --task pcb.layout_preflight --layout-request 03_REPORTS/layout/request.json --layout-receipt /project/03_REPORTS/layout/rules-r1.json
    python scripts/workflow.py run /project --task pcb.layout_plan --layout-request 03_REPORTS/layout/request.json --layout-receipt /project/03_REPORTS/layout/rules-r1.json

RULES_VERIFIED_FOR_LAYOUT_PLANNING is a source-bound planning gate, not manufacturing approval. BOUNDED_MODULAR_PLACEMENT_PROPOSAL is a read-only candidate, not placed copper or DRC evidence. A saved placement change reuses rule preflight only when the native project, fab source, netlist, pad identities, stack-up, edge and RF/keepout anchors remain unchanged. Rule/footprint/net mutations require another native preflight.

## Limits

This preview supports rectangular native Edge.Cuts (gr_rect or four closed orthogonal gr_line segments) and existing supported rectilinear top-side F.CrtYd polygons from placement_review.metadata(). Unsupported polygon/arc/bottom/curved or 3D geometry requires actual native/manual evidence; never infer a fictitious bounding box. The bounded heuristic keeps footprint orientation fixed, does not rotate complete modules, and does not prove routability, signal/return integrity, thermal/RF behavior, assembly safety or fabrication suitability. Unknown geometry, missing rule evidence or unsynchronized nets stop the planner; search exhaustion means replan required, not impossible PCB. Live KiCad 10/Konnect end-to-end execution remains to be verified.


## Mandatory JLCPCB user approval before any G3 layout plan

For ordinary FR-4 2/4/6/8-layer boards, preview conservative factory-informed values with `pcb.fab_preview`. Show actual layer count and all suggested dimensions **alongside** manufacturer capability limits. Wait for the user's explicit approval, then `pcb.fab_confirm --apply` creates two immutable project report files: `fab_approval` and matching `fab_rules`. Only the authorized Konnect writer applies actual KiCad Board Setup and stackup. The layout request must reference the approval (`fab_approval`) and the corresponding `fab_rules`; `pcb.layout_preflight` refuses missing/stale/changed human approval **before** expensive native NetClass audit. After Konnect saves, read back the real stackup (including correct finished copper weights) and effective rules before planning module placement; movement-only planning reuses current acceptance. Source, layer count or recommended-rule changes invalidate authorization. See [JLCPCB confirmation process](jlcpcb-fab-confirmation.md).

## Native Courtyard collision and placement-safe DRC pre-screen

The current planner now uses supported real Courtyard polygons rather than only their axis-aligned bounding rectangles. It conservatively takes the maximum of user-approved Courtyard gap and recognized KiCad custom `courtyard_clearance` minima, and screens footprint-disallow Keepout zones, fixed NPTH holes, locked/connectors/RF anchors, source-declared fixed/corridor and supported pin-level decoupling and proximity rules. Candidate grids are lazily generated with a search cap, and existing legal footprint positions are preserved first. Unsupported geometry and unknown hard rules block instead of guessing. This remains a **read-only pre-screen**, not a substitute for native KiCad DRC; real Konnect batch execution/save/position readback and G3 layout-only review are still required. Full-board KiCad DRC is deferred until after routing and zone refill at G4. See [Courtyard-first geometry and DRC semantics](pcb-courtyard-hard-rules.md).

## Mandatory stage boundary — G3 does NOT run full-board DRC

- **Layout:** `pcb.layout_preflight` (effective rules/network identities, not DRC) → `pcb.layout_plan` (coordinates only) → authorized Konnect placement move → save and read back actual footprint positions → `pcb.placement_pre` (`placement_review.py --phase pre_route`). G3 checks Courtyard, assembly/mechanical keepouts, module bounds, source-bound pin-level decoupling/proximity and anticipated routing access. Unconnected nets/airwires are normal at this stage and **must not be treated as G3 layout errors**.
- **Routing and copper:** after G3, route critical/ordinary nets, power and GND; fill/refill copper zones and verify saved-state connectivity.
- **G4:** only after routing and zone refill, use `pcb.prepare` / `pcb.gate` for independent native full-board KiCad DRC (including unconnected items) and AI/engineer review. `pcb.placement_final` is a separate post-route placement recheck, not a substitute for full DRC.
- **Do not** invoke `pcb.prepare`, `pcb.gate` or `kicad-cli pcb drc` as part of G3, lower manufacturing rules, suppress violations or fabricate a native DRC PASS. General Konnect batch-placement rollback is still a pending capability, not an implemented engine.
