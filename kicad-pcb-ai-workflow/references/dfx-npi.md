# DFX and NPI: Implementation, Manufacturing Evidence and Release Gates

## Scope and distinct decision stages

Design for manufacture (DFM), assembly (DFA), test (DFT), reliability and early production integration (NPI) are reviewed after actual schematic/PCB design gates. A programmatically generated report is a screening instrument, not proof of an approved factory process or real hardware qualification. Node 12 prepares pre-export review; node 13 produces an isolated manufacturing candidate. Real factory CAM/EQ and production authorization belong to external node 14, followed by physical prototypes and ECO.

## Inputs and checks

Require **current project files and hashes**: saved KiCad schematic, actual PCB and stack-up, complete BOM and assembly variant, CPL/placement when applicable, validated NetClasses/custom DRC, source-based requirement profiles, G1/G2/G3/G4 evidence, recent native ERC/DRC and factory documentation. Check fabrication minimums (trace/space, drill, ring, edge/mask/paste), copper balance estimates with known limitations, PCB connectivity, courtyard closure, netlist parity, component polarity, correct pad mapping, DNP/0-ohm safety, test interfaces, connector and mechanical clearance, layer references and special high-speed/PI requirements. Real test observations are external evidence, not script outputs.

The current implementation may use static approximations: a rectangular board envelope, rounded pad outlines, straight-line capsule clearance and sparse copper sampling. These can both miss small objects and flag false positives. Do **not** use them as a substitute for native KiCad DRC, actual CAM copper geometry, full 3D mechanical clearance, field-solved impedance, thermal measurements or a panelization acceptance.

## Factory/process contract

Factory capabilities depend on laminate, layer count, copper weight, hole technology, selected line/space class, temperature and assembly sequence. Record the *approved* actual values and source/version; examples are not defaults. The manufacturer must determine stack-up and impedance geometry where applicable. Interface protocol timing/skew budgets and current-bearing widths must be justified from real project data, not from a universal number.

Any planned exclusion, unsupported check, BOM variant or non-applicability must have a specific rationale. Unknown DRC schema, absent source files, altered hashes, missing human review, or pending factory questions block any production-ready claim.

## Execution and evidence order

1. Validate environment and current project; retrieve complete approved G1–G4 state, not cached shortcuts.
2. Review manufacturing and assembly policy, selected variant, resource hashes and real board geometry. `mass_production_review.py` records checks and open issues.
3. Plan an independent candidate and preserve source version. `freeze_candidate.py` now uses a Konnect single-writer handoff: copy only needed project files to an isolated candidate; the *fixture-accepted* Konnect tool fills and saves copper; a real operation receipt and independent KiCad CLI reload/DRC are required. Old `pcbnew` write instructions do not apply to this migration.
4. Recheck native ERC/DRC, final netlist parity, effective rules, layer/zone files and critical sources. Generate Gerber, Excellon drill, BOM, CPL and drawings with actual CLI if all relevant pre-export checks pass. Build a file hash manifest; do not edit or reuse an old approved manifest.
5. Keep `EXPORTED_NOT_RELEASED` until real factory CAM, engineering queries, assembly data and authorized approvals are closed. Final production release tools must revalidate exact source/output hashes and evidence before claiming authorization; AI does not create missing signatures.

## Special review domains

**Source-backed schematic intent:** Validate power/protection, startup, interface integrity and approved alternatives before evaluating only board geometry. **High-speed and RF:** Verify current layout, actual reference plane/return and applicable solver/routing evidence; an impedance target is not a field solve. **Reserve/DNP:** Variant and mutex constraints, installed parts, zero-ohm current rating, branches/stubs and production BOM all agree. **Placement:** Evaluate local loops, pads, routing channels, mechanics and human visual quality both before routing and after final copper. **Thermal and EMC:** Screen for risks, but actual compliance must be measured using a real test plan and hardware.

## CLI and audit output

Use `workflow.py` to plan before any mutation and execute only with explicit `--apply` on authorized candidate destinations. All non-releasable states, findings, source files, tool/firmware versions and hashes remain in the immutable report directory; the model may read a short report summary but the gate reads complete raw evidence.

See [manufacturing module](module-manufacturing.md), [full workflow](latest-complete-workflow.md), [stage sign-off](stage-approvals.md), and [Konnect zone fill](konnect-capability-migration.md).
