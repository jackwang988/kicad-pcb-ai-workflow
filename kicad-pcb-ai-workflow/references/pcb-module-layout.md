# Rules-First PCB Module Placement Planner — R10 Preview

## Required engineering order

1. Finish native schematic/ERC and G2 symbol-pin → footprint-pad checks. KiCad 10 Update PCB from Schematic (F8) synchronizes footprints and nets; the XML netlist is for independent pad/net parity, not mandatory intermediate import.
2. Before G3 placement, agree on fabrication constraints, actual physical stack-up, board/connector/hole geometry, RF keepouts and fixed anchors. Apply KiCad Board Setup minima for trace/copper clearance, via diameter/drill, annular ring, copper-edge/hole clearance, NetClasses and design-specific power, high-speed, RF and custom rules. Pad geometry comes from approved footprints rather than generic global limits.
3. Run existing design_intent_audit.py native effective-rule checking in pre_route mode. The planner compares seven sourced fabrication minima against actual .kicad_pro settings in millimeters, and checks current native PCB versus schematic XML pad/net identities. A JSON policy alone does not prove rules are activated.
4. Determine whole-board fixed regions, then place critical and ordinary members of each source-defined functional module using actual front-side Courtyard polygons and bounded net-neighbor heuristics; finally test bounded whole-module translations for inter-module coordination.
5. The planner is read-only. Apply exact current-revision coordinates through the single Konnect writer in small batches, save and read back, then run real KiCad DRC and the original placement_review.py G3 checks.

## Input contracts and commands

Fill assets/pcb-module-layout.template.json, assets/pcb-fab-placement-rules.template.json and the existing assets/placement-plan.template.json with real project-specific data. The fab minimums_mm values must contain min_clearance_mm, min_track_width_mm, min_via_diameter_mm, min_via_drill_mm, min_annular_width_mm, min_copper_edge_clearance_mm and min_hole_to_hole_mm, plus courtyard_clearance_mm. The equivalent serialized KiCad rule keys include min_through_hole_diameter and min_via_annular_width. Never invent fabricator minima.

    python scripts/workflow.py run /project --task pcb.layout_preflight --layout-request 03_REPORTS/layout/request.json --layout-receipt /project/03_REPORTS/layout/rules-r1.json
    python scripts/workflow.py run /project --task pcb.layout_plan --layout-request 03_REPORTS/layout/request.json --layout-receipt /project/03_REPORTS/layout/rules-r1.json

RULES_VERIFIED_FOR_LAYOUT_PLANNING is a source-bound planning gate, not manufacturing approval. BOUNDED_MODULAR_PLACEMENT_PROPOSAL is a read-only candidate, not placed copper or DRC evidence. A saved placement change reuses rule preflight only when the native project, fab source, netlist, pad identities, stack-up, edge and RF/keepout anchors remain unchanged. Rule/footprint/net mutations require another native preflight.

## Limits

This preview supports rectangular native Edge.Cuts (gr_rect or four closed orthogonal gr_line segments) and existing supported rectilinear top-side F.CrtYd polygons from placement_review.metadata(). Unsupported polygon/arc/bottom/curved or 3D geometry requires actual native/manual evidence; never infer a fictitious bounding box. The bounded heuristic keeps footprint orientation fixed, does not rotate complete modules, and does not prove routability, signal/return integrity, thermal/RF behavior, assembly safety or fabrication suitability. Unknown geometry, missing rule evidence or unsynchronized nets stop the planner; search exhaustion means replan required, not impossible PCB. Live KiCad 10/Konnect end-to-end execution remains to be verified.
