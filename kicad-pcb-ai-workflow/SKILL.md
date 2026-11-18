---
name: kicad-pcb-ai-workflow
description: KiCad PCB/schematic Skill: G1–G4 knowledge reuse, Konnect single writer, KiCad CLI verification, one working project, compact context.
---

# KiCad PCB AI Skill R10 — Single Workspace, Minimal Context

## Non-negotiable execution rules

1. **One authoritative working project.** If `CURRENT_PROJECT.json` exists, run `workflow.py workspace ROOT --action status` first. Continue ordinary symbol creation, net edits, placement, routing and silkscreen edits within the registered `01_WORKING/` project. **Do not run init/build or generate a new schematic candidate for every incremental edit.** Create separate candidates only for initial creation, high-risk tests, milestones or final freeze. Before a new schematic symbol batch, require the source-bound [pre-placement gate](references/schematic-preplacement.md): independent topology, occupied/keep-out/field/label/pin-space reservation, trial routes, and exact receipt revalidation. A feasible plan is not an actual native KiCad edit or verified ERC. Do not guess a legacy project’s latest copy. See [workspace and context policy](references/workspace-and-token-policy.md).
2. **Single EDA writer with first-use postchecks.** Konnect MCP performs active EDA writes, Python plans/audits and KiCad CLI checks saved results. Dynamically discover tools; L0 reads and bounded L1/L2 first-use edits do not require blanket fixture acceptance, but do require current target/schema, explicit authorization, save and immediate readback. Unknown changes stay unapproved until verified; L3 destructive tools require isolated acceptance. Never silently retry or switch to pcbnew.
3. **Manufacturer data cache first.** Node 3 looks up exact manufacturer, MPN and package before fetching external sources. Reuse frozen cards at G1/6, G2/7, G3/9 and G4/11; revisit only missing/stale/conflicting sources. Check every project independently. See [device knowledge](references/device-knowledge.md).
4. **Independent engineering gates.** Never invent electrical, SI/PI or fab parameters. Check each actual design and current rule. Native ERC/DRC, sourced AI review and engineer approval are independent; changed inputs invalidate affected evidence. Manufacturing output remains `EXPORTED_NOT_RELEASED`; CAM/factory EQ, prototype tests and ECO require separate external authority. Do not delete historical projects or evidence.
5. **Context-efficient reading without reduced checks.** Load only the current task's module. Start with `status --format compact`, knowledge `brief` or `report-brief`; expand relevant exceptions and cited figures only. Preserve full disk evidence; gates validate full files, never summaries.

## Schematic composition checks (new designs)

Before placing symbols, use `schematic_style.py --plan-input page-plan.json` to choose one sheet with functional frames or a hierarchical root plus child sheets. Reserve the actual worksheet title block and note regions. Use native KiCad power-library symbols for explicit positive/ground rails; do not replace these with ordinary rail labels. A new schematic's G1 style policy must opt into `composition.required=true` and bind actual rendered geometry and a complete object inventory. The `schematic_style.py` gate screens keep-outs, rail symbols and sheet hierarchy, but no geometry screen proves visual quality without a real page review. Do not generate unverified layout geometry or claim automatic placement. See [composition checks](references/schematic-composition-gates.md).

Before any new symbol-placement batch, prefer `geometry_mode=native_auto` and extract genuine KiCad symbol graphics, pins, fields and current instance positions via [`schematic_native_geometry.py`](references/schematic-native-geometry.md). Do not invent per-symbol rectangles. Worksheet title-block regions require project-specific source evidence and conservative font bounds still need KiCad render review. Reuse geometry/source SHA hashes at the fast second gate without rerunning A*.

## Task-based reference routing

| Requested task | Read first |
|---|---|
| Connection, environment, workspace | [module-environment](references/module-environment.md) |
| Requirements, architecture, manufacturer references | [module-requirements](references/module-requirements.md) |
| Symbols, pin maps, footprints | [module-resources](references/module-resources.md) |
| Schematic editing, actual nets, G1 | [module-schematic](references/module-schematic.md) |
| PCB constraints, placement, routing, copper | [module-pcb](references/module-pcb.md) |
| High-speed/PI only when applicable | [module-high-speed](references/module-high-speed.md) |
| DFX/NPI, review, manufacturing candidate | [module-manufacturing](references/module-manufacturing.md) |
| External prototype/ECO only if separately requested | [module-lifecycle](references/module-lifecycle.md) |

Use `python scripts/workflow.py modules --intent schematic` only when needed. Escalation references: [16 nodes](references/latest-complete-workflow.md) · [Konnect capabilities](references/konnect-capability-migration.md).

## Workspace structure

```text
/project/
  01_WORKING/       Project.kicad_pro + .kicad_sch + .kicad_pcb
  02_CHECKPOINTS/   Immutable milestone/high-risk backups only
  03_REPORTS/       Full ERC, DRC, G1–G4 and other evidence
  04_RELEASE/       Isolated, never implicitly approved deliverables
  CURRENT_PROJECT.json  # Authoritative navigation index, never approval
```

```bash
# First place the complete project and relative library resources in 01_WORKING.
python scripts/workflow.py workspace /project --action init --project-file 01_WORKING/Project.kicad_pro --apply
python scripts/workflow.py workspace /project --action status
python scripts/workflow.py workspace /project --action inventory  # Classify only, preserve files
python scripts/workflow.py workspace /project --action checkpoint --label G1-approved --apply
python scripts/workflow.py status /project --bundle control-r1 --format compact
python scripts/workflow.py report-brief /project/03_REPORTS/G1/checks.json --limit 6
```

For connection checks, perform one sufficient read; no automatic test boards. Writes require authorization and target validation. For routing: fab rules → net classes → critical nets → Konnect batches → saved readback → native DRC → G4. Planning is not execution.

Manufacturing uses guarded `--mode mass_production` and [DFX/NPI](references/dfx-npi.md); `--mode prototype` cannot authorize release. `npi_release.py` requires current CAM/factory evidence and engineer sign-off; no context optimization bypasses release gates.

**Schematic two-stage workflow:** Check independent pin/net contracts, title-block exclusion, real object/text collisions and valid label/pin anchors before placement. Search declared legal orthogonal rotations and compare bounded candidate scores. Treat density, trial-route length/bends and solver budgets as *advisories*: uncertain routing allows symbol placement only, not wiring acceptance. Recheck plan/source SHA without repeating A*, then check actual saved geometry, native netlist/ERC and visual evidence after each Konnect edit. See [pre-placement](references/schematic-preplacement.md).

**Rules-before-PCB-placement:** After G2, synchronize the PCB from the schematic (KiCad F8); apply actual fab/stackup/netclass/Board Setup constraints before moving footprints. Run `pcb.layout_preflight` (native effective rules, current physical minima and PCB/XML net parity) before `pcb.layout_plan` (local module placement followed by whole-board coordination). Plans are read-only; use one Konnect writer, saved readback, native DRC and G3 review. See [PCB module layout](references/pcb-module-layout.md).

**Explicit JLCPCB fabrication confirmation before PCB placement:** For ordinary 2/4/6/8-layer rigid FR-4, first use `pcb.fab_preview` to show actual project layer count, conservative manufacturer-informed design rules, and the official capability limits side by side. STOP for the actual user's explicit approval before `pcb.fab_confirm --apply`. Do not fabricate user consent or treat the preview as applied rules. Konnect is the only KiCad writer: apply the selected real Board Setup/stackup, then require native readback and current `fab_approval` in `pcb.layout_preflight` before `pcb.layout_plan`. See [user-confirmed manufacturing baseline](references/jlcpcb-fab-confirmation.md).

**Courtyard-first geometry for G3:** The read-only `pcb.layout_plan` now screens supported actual courtyard polygons with the approved additional courtyard gap and recognized KiCad custom `courtyard_clearance`, fixed NPTH holes, footprint-disallow zones, fixed/connector/RF anchors, and declared pin-level decoupling/proximity limits before proposing positions. Unknown supported-scope geometry or mandatory electrical rules block instead of guessing. Its PASS is *not* a native DRC PASS; real Konnect save/readback, KiCad DRC and G3 still determine acceptance. See [courtyard hard-rule pre-screen](references/pcb-courtyard-hard-rules.md).
