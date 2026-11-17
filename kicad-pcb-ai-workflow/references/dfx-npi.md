# DFX/NPI: Implementation Matrix, Evidence and Controlled Release

This reference specifies the **real scope and limits** of design-for-manufacture, assembly, test, reliability, and handoff checks. It is not a claim that KiCad or this Skill automatically verifies every mechanical, SI/PI, safety, CAM or product-performance property. **R10 precedence:** Konnect MCP is the only authorized active EDA writer; KiCad CLI performs independent native checks; `pcbnew` may remain a read-only compatibility dependency. Node 13 produces a candidate with `EXPORTED_NOT_RELEASED`, not an automated production authorization. Actual CAM/EQ, prototypes and ECO are separate external steps. Any older R9.x instructions implying a mandatory `pcbnew` editing backend or automatic G5/G6 execution are historical, not R10 permission.

## 1. Lifecycle and ownership mapping

The original engineering process used an eight-stage baseline with a separate stackup pre-stage; some older NPI guides used ten **management checkpoints**. Neither is a replacement for the current [16-node contract](latest-complete-workflow.md). The effective R10 mainline ends after design-package review readiness at node 13.

| Current area | Work | Independent acceptance |
|---|---|---|
| Nodes 1–4 | Requirements, AVL, MPN/manufacturer sources, protection options, variants | Source validity, explicit acceptance conditions and constraints |
| Nodes 5–7 | Schematic, ERC, complete pin/footprint mapping | **G1** schematic/semantic/engineer, **G2** symbol-footprint/manufacturer |
| Nodes 8–9 | Approved stackup, native rules, placement | Actual rule application, **G3** placement, returns and assemblies |
| Nodes 10–11 | Tracks, zones, critical nets, native DRC, design review | Connectivity, zone-fill/readback, **G4** PCB/engineer |
| Nodes 12–13 | DFX/NPI and immutable manufacturing candidate | Source/evidence hashes, variant parity, Gerber/drill/BOM/CPL/drawings, `EXPORTED_NOT_RELEASED` |
| Nodes 14–16 | CAM/EQ, actual EVT/DVT/PVT and ECO | **External** factory and engineer authority, physical measured outcomes |

A `pre_export` report checks design inputs; it does **not** authorize manufacturing. Historical `release` checks examine an existing candidate's integrity and authorized dispositions. No gate is satisfied just because a file exists.

## 2. Comprehensive engineering check matrix

Use three implementation categories: **NATIVE** (real KiCad CLI result or a specifically accepted equivalent), **SCREEN** (bounded Python geometric/data heuristic), and **EXTERNAL** (actual engineer, factory, lab or specialist tool). When only SCREEN exists, record its limitations and do not promote it to NATIVE or final manufacturing acceptance.

| Domain/check | Evidence and implementation | Limits and mandatory escalation |
|---|---|---|
| ERC and severity | `kicad-cli sch erc --format json --severity-all --exit-code-violations`; parse native report | Errors block; warnings require a documented engineering disposition, not silent ignore |
| Hierarchy, sheet names and cross-page electrical identity | Native XML netlist, ERC, sheet parser/graph cycle checks and `netlist_guard.py` | Textual sheet parsing alone cannot prove electrical topology or modular correctness |
| Variant identification | Explicit `variants`, variant BOMs and approved variant baseline | Never infer missing variants; native ERC need not expose a `--variant` switch |
| Reference, MPN, maker, package, field completeness | Actual BOM CSV with reference splitting, field mapping and duplication check | Missing fields and duplicate designators block; CSV parse does not approve sourcing |
| Same-MPN conflicts and cross-variant parity | Compare exact MPN, maker/package/spec and only declared invariant variant fields | Approved substitutes must have documented ECO or variant policy |
| Power-domain and protection presence | Configured domains plus roles for reverse polarity, TVS, fuse, watchdog, reset etc. | A matching designator never proves correct protection topology; manual schematic review mandatory |
| Creepage/clearance and safety insulation | Reviewer supplies actual voltage, pollution degree, material group, altitude, working insulation category | No universal numbers, no automatic safety acceptance without applicable standard/approval |
| EOL/NRND availability | Export candidate MPN list with `not_queried` status for external lookup | The Skill does not silently contact supply-chain services |
| Electrical/thermal derating | Manufacturer ratings and qualified reviewer or external part database | Do not calculate pass/fail without appropriate part parameters and conditions |
| PCB geometry source | Saved board data, accepted native-equivalent reader, optional read-only pcbnew | Static-text fallback is **preview only**, not manufacturing-grade geometry authority |
| NetClass assignments | Actual KiCad project rules and exposed native-class data | Presence alone is not proof correct net assignment, rule priority or applicability |
| Heat sources, thermal vias and temperature-sensitive devices | Declared sources, nearby via candidates and 2D distances | Does not establish thermal resistance, copper connection or temperatures |
| Power-loop area | Footprint-center bounding-box estimate | Not the true power or return-current loop area |
| Test point access | Probe contact dimensions, neighboring pad envelopes, expected access | 2D obstruction is not physical fixture/height access; check real enclosure/fixture |
| JTAG/other debug exposure | Declared JTAG nets on declared connector pads | Chain order, levels, connector polarity and usability need actual review |
| Part-to-edge and mounting-hole copper | Pad geometry and straight-outline screening | Curved edges, 3D parts, screws/washers, exact copper require native/MCAD review |
| Component height interference | Explicit mechanical reviewer/template or 3D/MCAD | Do not infer Z height from 2D footprint |
| Decoupling capacitor to IC supply pin | Explicit refs and pad numbers, approved max distance, real pad center readback | Straight-line distance is not loop inductance, return path or adequate capacitance |
| Plane splits, return continuity and PI | Approved stackup, classes, copper, source-grounded analysis | No implicit field solver or automatic current-return proof |
| Differential pairs and critical link paths | Actual segments/arcs/vias, endpoint uniqueness, layer timing models, link audit | Missing paths/branches/duplicate copper/unknown models block; no automatic coupled impedance or S-parameters |
| Functional partition and noise coupling | Declared regions and center position; 2D noisy-vs-sensitive net spacing | A 2D distance is not electromagnetic-coupling proof |
| Width, spacing, drills, annular rings | Fab-approved bounds, native DRC plus track/pad/via pre-screen | All object types and custom rules require native full DRC; no guessed limits |
| Hole aspect ratio | Nominal through-hole board thickness/drill | Blind/buried/microvias require actual traversed-layer thickness and fab confirmation |
| Impedance precheck | Approved stackup, dielectric thickness, Er and target tolerance | **No claimed impedance solve** without validated field calculator/coupon process |
| Acute angles, necks and solder-mask bridges | Segment angles and pad envelopes, DRC and factory checks | Exact filled-neck geometry and all mask openings are not fully automated; CAM review |
| Layer copper balance/board warp | Sparse grid estimate of fills/tracks/pad envelopes for simple rectangles | Not exact CAM copper area; cannot predict warpage or laminate behavior |
| Zone overlap, islands and actual fill | Filled polygon presence, native DRC and visual checks | A zone outline alone is not filled copper; independent precise island detection may be unavailable |
| SMT spacing and BGA edge risk | Pad-box clearance and board-edge screening | Must inspect component bodies, courtyard, rework and depanel stresses |
| Panel V-Cut, mouse bites | Explicit factory/assembly review | Labels or graphics alone do not prove panel cut geometry/copper clearances |
| Fiducials | Name/footprint and count screening | Panel-level positions, non-collinearity, copper and solder-mask keepouts require assembly review |
| SPICE | Explicit schematic export and optional independent ngspice | Models, stimuli and analyses are supplied/approved by engineer; non-running demo is not a test |
| Thermal simulation | Source-coordinate handoff to external solver | No claimed thermal simulation without external result |
| EMC | Ground/filter/shield screening with external test evidence | Static screening is not EMC compliance or field solution |
| Baseline, revisions and variants | SHA-256 across schematic, hierarchy, PCB, project, BOM and variant BOMs | Missing current revision/approver/variant set blocks; hashes cannot be rewritten to hide change |
| ECO | Change ID, reason, scope, affected files, verification, owner and approval | Changed inputs invalidate related engineering signatures |
| Gerber/drill/CPL/BOM/drawings | Explicit, no-wildcard per-layer/per-category output list with file hashes | Nonempty files alone never prove CAM, assembly or D2 authorization |
| Jobset | Restricted, verified tool/command profile | Generic jobset output cannot bypass per-file export and destination-contract verification |
| EVT/DVT/PVT | Real quantity/conditions/acceptance/evidence/owner | Lab and manufacturing measurements cannot be claimed from static review |
| CCC/CE/product regulation | Explicit product/market applicability decision by responsible engineer | No implied certification or legal conclusion |

All checks above retain their names and failure semantics. Where a tool cannot obtain native-equivalent geometry, keep `BLOCKED` or `NEEDS_EVIDENCE`; do not downgrade the gate to a text-only estimate to make a report green.

## 3. Dependencies, setup and optional external tools

- **Required according to actual task:** Supported KiCad CLI for native schematic/PCB checks and exports, accessible project sources, target factory-approved process limits, device manufacturer documents and review evidence. Test the current binary version and report schema in the target environment.
- **Konnect:** When active EDA write is needed, discover and accept the current binary/build/tool schema and operation scope; old public/commercial version acceptance is not transferable. The Skill package does not bundle Konnect.
- **Legacy read-only compatibility:** An installation-specific pcbnew reader may still be required for certain detailed geometry checks until proven native-equivalent Konnect snapshot coverage exists. This does **not** authorize pcbnew to write the active project.
- **Optional:** Independent ngspice with valid SPICE models; supply-chain APIs used only when explicitly supplied and authorized; specialist SI/PI, thermal, EMC, 3D/MCAD, fab CAM and fixture systems.
- **Python:** Core tools use the standard library for many tasks; per-tool external dependencies must be checked rather than guessed. Do not install an arbitrary `pcbnew` package from pip to bypass version compatibility.

First use [environment onboarding](environment-onboarding.md) and the actual Skill's `doctor`/Konnect capability check. Fill an actual project copy of `assets/review-config.template.json`, engineering profile and process source approvals. An incomplete template is never an approved design. All new report outputs go to explicit fresh directories; **ordinary editing remains in the one registered working project**.

## 4. Example guarded review and release workflow

```bash
# Read-only pre-export design review; source reports remain immutable.
python scripts/mass_production_review.py /project \
  --config /project/review-config.json --mode mass_production \
  --phase pre_export --output-dir /project/03_REPORTS/npi-pre-export-r1

# Candidate package must already exist and match the reviewed source.
python scripts/mass_production_review.py /project \
  --config /project/review-config.json --mode mass_production \
  --phase release --candidate-dir /separate/manufacturing-candidate \
  --output-dir /project/03_REPORTS/npi-release-check-r1

# Explicitly preview publication first; --apply only after real authorization.
python scripts/npi_release.py /project --config /project/review-config.json \
  --candidate-dir /separate/manufacturing-candidate --destination /separate/new-release
```

All commands above are illustrative contract patterns. Use actual supported option names, version checks, relative file paths and file existence in the installed build. `--mode prototype` is a non-production diagnostic; it cannot export or release a production package.

### Manufacturer reference and safe freeze handoff (R10)

1. Review real source data and applications; ensure G1–G4 reports apply to **this** schematic and PCB hash.
2. Finish routing and current zone-fill state in a controlled candidate through a **fixture-accepted Konnect** operation; perform independent readback and CLI DRC. Do not let a static route-plan output stand for actual saved copper.
3. `freeze_candidate.py` creates an isolated candidate and Konnect handoff. Its explicit `--apply` stages a copy **without automatically refilling**. `--finalize` requires an actual Konnect operation receipt and independent native DRC. A returned `FROZEN_NOT_VALIDATED` still needs the other project gates.
4. Do not recursively include `02_CHECKPOINTS/`, `03_REPORTS/`, `04_RELEASE/` and historical snapshots in the new candidate. Preserve all history externally; do not delete it. Ensure actual design dependency files stay present.
5. Bind the resulting baseline to exact revision, authorized reviewer, assembly variant, hierarchy and source hashes. Changing any relevant input requires re-freeze and re-evaluation, not a hash edit.
6. Export Gerber, drill, BOM, CPL and required assembly layers through verified direct KiCad CLI commands into a new candidate directory. Capture CLI version/build, command arguments, logs, return code, source/target paths, and output hashes. PDF or other printed drawings still need human content review.
7. Independently open Gerber/drill in CAM, close factory EQ, verify D2 delivery manifest and obtain factory/order-scope and human authorization. Package the **complete** validated delivery, not Gerber files alone.
8. Keep actual physical prototype/reliability approval separate from static design and manufacturing candidate readiness.

### External evidence and review contract

Approval or not-applicable decisions must include `reviewer`, ISO date, `reason`, and an actual nonempty `evidence` array with existing paths and SHA-256. A manual JSON review declaration does not verify a person's signature; the organization must manage authority independently. A human review cannot override a demonstrated native/ERC/DRC blocker.

```json
{
  "baseline": {
    "revision": "R1",
    "approved_by": "engineer-name",
    "variants": ["default"],
    "sha256": {"board.kicad_pcb": "CURRENT_64_CHARACTER_SHA256_REQUIRED"}
  },
  "manual_reviews": {
    "SCH.CREEPAGE": {
      "status": "not_applicable",
      "reviewer": "responsible-engineer",
      "date": "2026-11-17",
      "reason": "Documented product-specific applicability decision",
      "evidence": [{"file": "reviews/safety.pdf", "sha256": "CURRENT_64_CHARACTER_SHA256_REQUIRED"}]
    }
  }
}
```

The JSON is only an explanatory **template**, not valid production evidence. It is not intended to be pasted as an approval. Export receipts, external test results and the actual current board hash are mandatory for their applicable stages. Do not leak secrets or contact supplier APIs unless explicitly authorized.

### ECO and prototype traceability

For ECO: record ID, old/new revision, affected schematics/PCB/BOM/firmware/fixtures, failure reason, risk, test evidence, owner and actual approval date. For EVT: functional/power/interface/DFT tests under a quantified plan; DVT: applicable thermal/humidity/vibration/aging and safety; PVT: yield, test coverage, traceability and process robustness. None can be approved solely from this Skill's software fixtures.

## 5. Rules for release gating and failure recovery

- No source EDA mutation during read-only reviews, and no overwrite of existing report directories or signed evidence.
- `--static-preview` never authorizes production even when it finds no other violation.
- A release decision recomputes relevant actual-file hashes and current gates; hand-edited historical reports are not authority.
- Never overwrite existing source/candidates, accept traversal/symlink escapes, or use wildcard categories as file-level proof.
- Enforce **design preflight → isolated manufacturing candidate → candidate integrity/CAM/EQ → explicit release**, avoiding a circular requirement to validate ungenerated files during preflight.
- If source constraints, native geometry, silicon application requirements or actual tool capabilities are missing, report **BLOCKED/NEEDS_EVIDENCE**, not an invented safe value.
- Engineering and factory standards are applied by **actual product and process applicability**. IPC/IEC references do not imply universal numbers or product certification.

## 6. Cross-references and authority

- [Design intent and NetClasses](design-intent.md): source-backed differential, current and RF constraints before PCB routing.
- [G1/G4 static AI review](static-ai-review.md): real drawing/netlist/board and current engineer review.
- [Reserve and debug options](reserve-options.md): variants, 0 Ω, DNP, test points and no-reserve rationale.
- [Placement quality](placement-quality.md): G3 pre-route and final layout/return-path evidence.
- [Engineering rules](engineering-rules.md): product-level safety, scope, quantified acceptance and risk disposition.
- [Full current design workflow](latest-complete-workflow.md): precedence over older R9.x stage numbering.
- [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html), [KiCad PCB Editor](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html), [KiCad IPC API](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/).

**Boundary:** Software contract tests and native example toolchain smoke tests are not manufacturing release, signal integrity or actual product validation. Record every unimplemented exact-geometry or specialist analysis check explicitly; do not hide it by selecting a permissive mode.
