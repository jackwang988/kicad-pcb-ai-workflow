# Schematic Design and PCB Synchronization

Use the [topology-first drawing contract](schematic-ai-layout-rules.md), [visual schematic style](schematic-style.md) and [system integration](system-integration.md) as needed. Solve net topology, global routing corridors and off-page connections before placing all symbols. A visible line crossing is not proof of a KiCad electrical connection. Verify hierarchical labels, pin endpoints, reference designators, NC behavior, supply direction and electrical/ERC semantics.

For a first candidate, `schematic_candidate.py` accepts an explicit source-bound design and native expected network contract. For ordinary later changes, edit the **same** authorized workspace project with scoped Konnect tools. KiCad 10 PCB IPC does not automatically provide schematic IPC editing; Konnect schematic tools may use file-backed operations. Never edit an unsaved schematic simultaneously from two writers.

At G1, reuse the project-frozen device-card brief from node 03; `static_review.py --stage schematic` prepares native XML/netlist, PDF/graph review material and verified cached source text. Read only current-relevant card items first. Inspect original source figures, notes, corner conditions and manufacturer's recommended circuits as required. Native ERC, pin-level netlist, graphical reading, actual project values and engineer confirmation are separate mandatory checks.

Schematic-to-PCB synchronization: use a verified `update_pcb_from_schematic` equivalent. First `dry_run` and record `plan_revision`; check locked objects, footprint provenance, protected copper and the exact proposed actions; then apply only the same `expected_plan_revision`. On mismatch, timeout or rollback failure, inspect state before any retry. Verify UUID/reference/pad-net mapping, saved schematic/PCB correspondence and current DRC afterwards. Complex hierarchical, multi-unit and replacement scenarios require independent acceptance beyond small fixture tests.

Read [static AI review](static-ai-review.md) and [design intent](design-intent.md) for full gates; dynamic MCP tools are not additional `workflow.py` commands.

## Executable composition screening

For a newly authored schematic, first obtain a read-only page plan from `schematic_style.py /project --plan-input page-plan.json`. Follow the plan with Konnect writes only in the registered working project. Bind actual title-block/notes keep-outs, native power symbols for explicit supply and ground rails, and the existing functional single-sheet frames or verified hierarchical subsheets. After saving and exporting, enable `composition.required=true` in the project schematic style policy and run the existing G1 static review: it invokes `schematic_style.audit()`. A missing or stale rendered-bounds manifest blocks the composition screen; visual/native ERC review remains independent. Details: [schematic composition gates](schematic-composition-gates.md).


## Mandatory new-symbol batch pre-placement (read-only candidate gate)

Before calling Konnect for symbol insertion, verify independent pin-to-net topology and current fully measured page geometry via [pre-placement policy](schematic-preplacement.md). Run `workflow.py run /project --task schematic.preplacement_plan --preplacement-request REPORT_PATH --preplacement-receipt RECEIPT_PATH`, then immediately `schematic.preplacement_check` with the same request and receipt. Reject any `BLOCKED`, stale/modified receipt, unreserved label/power symbol, congested pin exit or failed trial route. These tools perform no KiCad writes; the host must map its actual MCP operations to the exact planned batch, then read back native netlist/ERC, fields and rendered pages. Direct MCP calls outside the Skill remain un-intercepted, and unmeasured worksheet/font geometry forbids automatic clearance acceptance.

## Two-stage planning and execution

Preflight hard electrical, title-block, collision and pin/label constraints. Automatically test declared legal 0/90/180/270-degree rotations and score candidate layouts. Occupancy, trial wire length/bends and A* resource limits are soft: unresolved routes require review and prohibit unverified wiring, but should not block a geometrically safe symbol-only batch. Validate existing plan receipt hashes without rerunning A*. L1/L2 Konnect tools may execute first-use bounded writes on protected candidates followed by saved-state checks; L3 destructive operations need isolated acceptance. Unknown outcomes stop for inspection, never automatic retry. Avoid new project copies for ordinary editing.

**Native pre-placement geometry:** read real KiCad symbol graphics, pins and existing instance transforms with `schematic_native_geometry.py` and `geometry_mode=native_auto`. Do not hand-author symbol rectangles. Actual text glyphs and worksheet title regions still need render/worksheet evidence. See [native geometry](schematic-native-geometry.md).

**Do not reserve a text box for `lib_id`.** This is a non-rendered KiCad library lookup key. Reserve only native symbol graphics/pins and properties actually shown on the schematic: visible Reference, Value, additional visible fields, labels and notes. When `value` is omitted, use the native library Value property, not the `lib_id` suffix. See [native geometry](schematic-native-geometry.md).
