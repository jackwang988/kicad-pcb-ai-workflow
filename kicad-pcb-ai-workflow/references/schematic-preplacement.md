# Schematic Pre-placement: Topology → Space Reservation → Trial Routes → Gate

**Scope:** read-only candidate planning for new components on an existing KiCad sheet, anchored to the current immutable native-file hashes. This implements a conservative, *bounded* pre-placement feasibility screen. It **does not** extract arbitrary symbol fonts/worksheet geometry from KiCad, calculate exact real-world component positions for every complex schematic, edit `.kicad_sch`, or guarantee a perfect orthogonal route in a dense design. If required geometry is missing, the preflight **blocks rather than inventing coordinates**.

## Required order before any new symbol placement

1. Independently establish the **expected exact pin-to-net graph** from approved requirements and manufacturer guidance. Provide a design-basis file, SHA-256, and precise locator; do not derive expected connections from the generated schematic.
2. Select the current authoritative `01_WORKING/` schematic and target hierarchy sheet. Run the existing sheet planner first (`schematic_style.py --plan-input`) and split an overcrowded module into a real reachable child sheet before attempting placement.
3. Extract/check *current* schematic UUID inventory and visual object bounds into a `geometry.json` manifest bound to the saved `.kicad_sch` and exported rendered view. Include all visible symbol fields, labels, existing wires, annotations, true page/worksheet keep-outs and title block. **Source hashes do not prove geometry was measured correctly.** Custom `.kicad_wks` and fonts require independently verified bounds; absent a trusted measurement, no autonomous placement.
4. Supply every new symbol's real library-body bounds, visible `Reference`/`Value` field bounds, pin attachment coordinates and transformed exit directions, with a SHA-pinned geometric-source document. List each legal candidate anchor or an admissible placement-zone grid. Reserve a field box, label box and pin escape corridor for each required endpoint. Power/GND connections need a planned native power symbol, not arbitrary textual replacement.
5. Provide complete explicit `connections` (expected net + source/target `[ref,pin]`) and label reservations for all new non-NC pins. Existing endpoints must be declared `fixed_ports` tied to an object UUID in the *current* schematic. Reject pin/net mismatch or a missing connection/label.
6. Run the bounded collision/clearance preflight and orthogonal A* **trial routing**. It checks existing objects, field/label collisions, title-block/notes keep-outs, per-pin escape and reserved routing corridors. Candidate search stops at explicit budgets. This also checks conservative page occupancy and optional maximum trial-wire length/bend limits, preventing objectively too-dense or overly dispersed candidate layouts. A `BLOCKED` response means that **this declared candidate set has not been shown feasible**, not that a valid schematic is impossible.
7. When geometry is verified and status is `PREPLACEMENT_FEASIBLE_FOR_DECLARED_GEOMETRY` or `PREPLACEMENT_GEOMETRY_READY_ROUTE_REVIEW_REQUIRED`, save the immutable receipt in the existing **`03_REPORTS/`** directory or outside the working project and revalidate SHA-bound inputs without rerunning A* immediately before the Konnect write. The verified route path is a *plan*, not an electrical wire. The host must compare actual Konnect call arguments with exact planned coordinates and connections; if the chosen tool cannot honor them, do not execute. **This Skill cannot intercept arbitrary direct MCP tool calls from another agent.**
8. Execute **small batches** via the authorized Konnect backend; immediately read back actual UUID, pin/net, fields and saved geometry; run native XML/ ERC and existing G1 geometric/visual review. Every successful batch changes schematic SHA and invalidates the prior receipt. Replan the next batch from the fresh native file and rendered bounds. Do not replay a failed/unknown write without investigating state. No silent pcbnew fallback.

## Read-only CLI / workflow commands

```bash
# Request, bound evidence, and receipt are inside the existing project reports area.
python scripts/workflow.py run /project --task schematic.preplacement_plan \
  --preplacement-request 03_REPORTS/preplacement/batch-01.json \
  --preplacement-receipt /project/03_REPORTS/preplacement/batch-01.receipt.json
# Run again just before the MCP call; catches stale geometry, plan or topology.
python scripts/workflow.py run /project --task schematic.preplacement_check \
  --preplacement-request 03_REPORTS/preplacement/batch-01.json \
  --preplacement-receipt /project/03_REPORTS/preplacement/batch-01.receipt.json
```

The preflight must not be run with `--apply`; it performs **no EDA modifications**. The original request and referenced source files are read-only. The receipt file must not exist already, and its parent folder must already exist. If trial routing fails or its budget is exhausted, the planner may report `PREPLACEMENT_GEOMETRY_READY_ROUTE_REVIEW_REQUIRED`: only bounded symbol placement is permitted, never unverified wiring. Try alternate anchors/rotations before splitting the sheet; search exhaustion is not proof the page is full.

## Request v1 contract (abbreviated, illustrative only)

```json
{
  "schema_version": 1,
  "schematic": "01_WORKING/main.kicad_sch",
  "schematic_sha256": "<current SHA-256>",
  "page": "01_WORKING/main.kicad_sch",
  "geometry_manifest": "03_REPORTS/current/geometry.json",
  "geometry_sha256": "<SHA-256>",
  "render_file": "03_REPORTS/current/schematic.svg",
  "render_sha256": "<SHA-256>",
  "topology_file": "03_REPORTS/expected/pin-net.json",
  "topology_sha256": "<SHA-256>",
  "grid_mm": 2.54,
  "clearance_mm": 1,
  "pin_escape_mm": 5.08,
  "wire_corridor_width_mm": 1,
  "max_candidate_positions": 120,
  "search_budget": 1000,
  "max_occupancy": 0.75,
  "max_trial_wire_length_mm": 100,
  "max_trial_wire_bends": 4,
  "power_rails": ["+3V3", "GND"],
  "symbols": [{
    "ref": "R1",
    "candidate_positions_mm": [[40.64, 53.34], [45.72, 53.34]],
    "rotations_deg": [0, 90],
    "geometry": {
      "source": {"file":"03_REPORTS/symbol-source.txt","sha256":"<SHA-256>","locator":"symbol reference & verified measurement"},
      "body_bbox_mm": [-4, -2, 4, 2],
      "fields": [{"name":"Reference","bbox_mm":[-2,-9,5,-6]}, {"name":"Value","bbox_mm":[-2,6,5,9]}],
      "pins": [{"number":"1","xy_mm":[-5,0],"outward":[-1,0],"net":"GND"},
               {"number":"2","xy_mm":[5,0],"outward":[1,0],"net":"SIG"}],
      "labels": [{"pin":"1","net":"GND","text":"GND","kind":"power","anchor_local_mm":[-10.08,0],"bbox_mm":[-23,-3,-10.08,3]}]
    }
  }],
  "fixed_ports": [{"id":"U1.3","net":"SIG","at_mm":[100,53.34],"source_uuid":"<current native UUID>"}],
  "connections": [{"net":"SIG","from":["R1","2"],"to":["@fixed","U1.3"]}]
}
```

`topology_file` is an independently authored JSON with `schema_version:1`, `pins` entries `{"ref":"R1","pin":"1","net":"GND"}`, and `source:{"file":"...","sha256":"...","locator":"..."}`. Every new symbol pin must appear **exactly once**. Each electrical pin must have either an explicit connection or a space-reserved local/hierarchical/global/power label; `NC` requires deliberate declaration. Non-power label text must equal net identity. Other pages remain unchanged; arbitrary direct EDA writes remain outside this planning tool's reach.

## Engineering limitations and acceptance

- **No automatic font metrics / worksheet parser:** Verified complete measurement manifests are mandatory. The algorithm works on declared, hashed geometry, not raw KiCad drawing semantics alone.
- **No false routing proof:** This A* plan is restricted to orthogonal paths on one sheet; it is conservative about crossing, bus semantics and shared same-net junctions. Complex hierarchy, multiunit symbols, true net-ties, pin stacking, partial routing and arbitrary mirrored text require focused acceptance or manual engineering decisions.
- **No hidden MCU-pin changes:** Rotating a symbol changes only its declared geometry, never source pin number or expected net. Verify all transformed pins and actual electrical connection after applying.
- **No simultaneous writers:** Continue in the same registered `01_WORKING` project; only one Konnect write path per current revision. Keep receipt and full checks separately; do not create a new KiCad project for every placement.
- **Mandatory back-end work:** Actual trusted symbol and worksheet geometry extraction, real per-tool Konnect `args ↔ planned placements` enforcement and live batch/rollback acceptance are **not implemented** by this read-only planner. They must be implemented and validated on Windows before claiming completely autonomous pre-placement and editing.

[Existing composition/visual gate](schematic-composition-gates.md) · [Topology-first rules](schematic-ai-layout-rules.md) · [Schematic module](module-schematic.md).

## Two-stage update: hard vs. soft

Hard constraints: independent pin-to-net contract, actual title block/border, verified symbol and text collision, legal pin exits, correct power/label anchors. The bounded solver now tries all four orthogonal rotations unless a symbol restricts `rotations_deg`; it compares multiple results (default `max_scored_solutions=12`). Project `role=vertical_branch|decoupling|pullup|pulldown` and `preferred_rotations_deg` may prioritize useful orientations. Soft goals: occupancy, trial-route existence/length/bends, solver budget and whitespace. Occupancy is estimated from the union of declared occupied rectangles, not a sum that double-counts reserved labels. When only routing is unproven, allow a bounded symbol-placement batch but **never** auto-accept wiring. The receipt check only rehashes current inputs; post-write native XML/ERC and visual review are mandatory. Trusted worksheet/text geometry is still supplied, not autonomously extracted.
