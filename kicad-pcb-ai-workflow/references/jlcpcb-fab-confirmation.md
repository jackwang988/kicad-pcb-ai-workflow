# JLCPCB Rigid FR-4: Explicit Manufacturer Profile Review and User Confirmation

## Scope, sources and distinction

This Skill bundles `references/jlcpcb-rigid-fr4-presets.json`, a dated, **Skill-authored conservative recommendation** derived from JLCPCB's public rigid-PCB capability and finished-copper documentation (as checked 2026-11-18). It is **not JLCPCB's own default order configuration** and must not be presented as a factory quotation, actual stackup, capacity guarantee, or manufacturing authorization. Each source URL is in the catalog. Factory availability, cost and exact stacking must be reviewed for the actual order.

- 1 oz copper: JLCPCB's published capability minima are approximately 0.10/0.10 mm trace/space for 1–2 layer rigid PCBs and 0.09/0.09 mm for multilayer. The Skill instead suggests 0.20/0.20 mm (2-layer) or 0.15/0.15 mm (4/6/8-layer) design minima. Wider nets for actual current, voltage and thermal conditions must still be calculated; these profiles are not a universal power-width rule.
- Published small-via capability (0.15 mm hole/0.25 mm pad) is an **advanced/possibly extra-fee limit**, not the Skill's default. The Skill proposes 0.30 mm drill/0.70 mm outer diameter, giving a 0.20 mm nominal radial annular ring. It also proposes 0.30 mm copper-to-routed-edge and via hole-to-hole margins and 0.25 mm courtyard separation (the last is a project assembly-planning suggestion, not a universal JLCPCB minimum).
- JLCPCB publishes 0.5 oz finished inner copper as the common default for multilayers; the profiles suggest 1 oz outer / 0.5 oz inner and 1.6 mm overall thickness. Actual KiCad stackup must contain exactly the approved copper-layer count and matching finished copper thickness before G3. **Neither a generic 4/6/8-layer count nor 1.6 mm thickness implies a valid impedance stackup.** Choose a specific JLCPCB stackup and use manufacturer impedance calculator where needed.
- For rigid FR-4 6 layers or more JLCPCB's capability chart excludes HASL; the profile suggests a compatible non-HASL finish such as ENIG. Actual order finish is still independently confirmed. V-cut edges require different copper clearance (0.4 mm), as do castellated holes, edge plating and special panelization.
- Board fabrication minima cannot approve arbitrary component courtyard/3D, PTH pad-to-hole and pad diameter, annular rings in custom footprints, solder-mask bridges, controlled impedance, RF return, SI/PI or assembly. Run independent DRC and factory DFM checks.

## Human-in-the-loop sequence (do not auto-confirm)

**Step A: Discover selected board and show one proposal** (no KiCad mutation):

```bash
python scripts/workflow.py run /project --task pcb.fab_preview \
  --fab-board 01_WORKING/main.kicad_pcb --fab-layers 4 \
  --fab-proposal /project/03_REPORTS/pcb-fab/proposal-v1.json
```

The agent **must show the user** the selected manufacturer, copper layers, thickness, outer/inner copper, suggested minimum track width/spacing, recommended via drill/diameter/radial ring, copper-to-edge, drill-hole separation, courtyard, finish and the distinction between factory limits and design suggestions. Explicitly disclose unknown actual stackup ID, high-speed impedance and special manufacturing. Status is `FAB_USER_CONFIRMATION_REQUIRED`. If the user changes layer count or settings, revise the proposal / use an appropriate separately sourced custom profile; do not treat the old receipt as approval.

**Step B: STOP until the user explicitly confirms the displayed proposal.** Never infer approval from silence or previous chat statements. Only after confirmation may the agent use:

```bash
python scripts/workflow.py run /project --task pcb.fab_confirm --apply \
  --fab-proposal 03_REPORTS/pcb-fab/proposal-v1.json \
  --fab-decision CONFIRM --fab-confirmed-by '<actual approving user or engineer>' \
  --fab-approval 03_REPORTS/pcb-fab/approval-v1.json \
  --fab-rule-output 03_REPORTS/pcb-fab/fab-rules-v1.json
```

These files are **new, immutable, project-scoped receipts** only. CLI acknowledgement cannot authenticate a person: the host must preserve the actual conversation/user action. The script cannot itself click, configure or save the KiCad editor. Successful confirmation means `FAB_PROFILE_USER_CONFIRMED`, **not** the rule-application step or engineering sign-off. Repeated calls refuse overwrites rather than silently renewing an approval.

**Step C: Apply actual rules through the configured Konnect MCP writer** in the same protected working project; configure board layer count, 1.6mm nominal overall thickness, actual finished outer/inner copper stackup, Board Setup constraints, NetClasses and applicable special rules. After saving, independently read back the current `.kicad_pro`, `.kicad_pcb` native stackup and effective NetClasses. Manufacturer's exact laminate/dielectric thickness and stackup ID must be explicitly selected where impedance is relevant. No second native writer fallback.

**Step D: Only after C succeeds, run native layout preflight and module layout planning:**

```bash
# Request must include both approved `fab_rules` and immutable `fab_approval`.
python scripts/workflow.py run /project --task pcb.layout_preflight \
  --layout-request 03_REPORTS/pcb-layout/request.json \
  --layout-receipt /project/03_REPORTS/pcb-layout/rules-v1.json
python scripts/workflow.py run /project --task pcb.layout_plan \
  --layout-request 03_REPORTS/pcb-layout/request.json \
  --layout-receipt /project/03_REPORTS/pcb-layout/rules-v1.json
```

The layout preflight first validates an explicit user-approved, hash-bound profile matching the board identity and layer count. It also verifies current exact copper layer thicknesses (1 oz outer, 0.5 oz inner in this catalog) and that active KiCad minimum rules meet every approved design floor, then calls the existing **native** effective NetClass audit and schematic-to-PCB pad-net parity check. If approval is absent, it blocks before expensive KiCad audit, with `FAB_USER_CONFIRMATION_REQUIRED`. The two-level planner reuses a verified immutable preflight for subsequent movement-only planning, avoiding repeated approval/audit. Source, layer count, selection, stackup, or rule changes invalidate matching approval/readback and require user review as appropriate. Existing DRC, G3 and manufacturing release gates remain independent.

## Hard failure cases

- A 4-layer selection presented for a 2-layer board, changed catalog/profile, changed stored proposal/fab JSON, missing approval or missing real user confirmation: **BLOCKED**.
- Actual Board Setup doesn't include the selected copper-layer stackup, or finished copper weight differs: **BLOCKED** before G3.
- Actual KiCad minimum constraints are less conservative than the user-approved proposed minima, or native NetClass data cannot be read back: **BLOCKED**.
- Special needs (impedance, RF, copper weight other than catalog, unusual thickness, blind/buried vias, V-cut etc.) cannot be silently treated as a standard case: obtain a separate sourced and reviewed specification; these four presets are not universal.

Only 2/4/6/8-layer 1.6mm nominal rigid FR4 profiles are included in this catalog; unrelated fabricators and special processes must use a separate scoped workflow, never forged JLCPCB proof.
