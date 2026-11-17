# Electronic Product Engineering Rules — Safety, Applicability and 25 Controlled Repairs

**Current R10 precedence:** applicable laws/safety requirements → product specification and manufacturer datasheet/errata → approved PCB/PCBA fabrication and project constraints → general engineering heuristics → appearance. If sources conflict, stop for a recorded engineering decision and ECO. Never silently loosen hard constraints. The table below preserves the historical R9.x repair IDs as a compatibility reference; see [current 16-node workflow](latest-complete-workflow.md) for authoritative R10 stage ownership and Konnect single-writer policy.

An implemented checker or zero exit code does **not** mean a product is production-approved. A source-grounded PCB rule, actual project-specific data, independent KiCad ERC/DRC, native-equivalent geometry, CAM/factory EQ and human sign-off may each be independently necessary.

## 1. Twenty-five rule repairs and their validation boundaries

| ID | Risk | Engineering rule / change | Implemented control and remaining evidence |
|---|---|---|---|
| **R01** | P0 | Netlist changes are not universally forbidden; distinguish exact preserve from authorized ECO | `netlist_guard.py` preserve/eco; ECO hashes and exact expected differences. Real ECO still requires approval |
| **R02** | P0 | A lower violation count is not a pass criterion | `engineering_gate.py` compares violation identity; native errors and unreviewed exclusions block; high risks need per-item evidence |
| **R03** | P0 | No blanket unconnected warning suppression | Native excluded errors block; neither pad position nor missing pad-to-zone error proves actual connectivity |
| **R04** | P0 | Hole technology, span, and fabrication intent must agree | Need stackup, drill layer pairs and real CAM; contradictions in blind/buried holes cannot be waived by a convenient note |
| **R05** | P0 | Do not infer copper shorts from pitch/pad long edge or a generic 45° geometry trick | `pad_audit.py` supports rotated rectangles and circles; unsupported pad shapes require native DRC/land-pattern inspection |
| **R06** | P0 | Empty or badly parsed XML must not pass by exit code 0 | Strict component/net/pin XML validation with preserved singleton/unconnected semantics; FAIL=1, BLOCKED=2 |
| **R07** | P0 | Differential audits must include arcs and distinguish vias | `link_audit.py` checks unique endpoint paths, tracks/arcs/vias, delay in ps, spans and layer changes; complex native board validation remains specific |
| **R08** | P1 | Old project-probe tools are diagnostic, not release gates | Missing, open or malformed courtyards are not approved; project-specific geometry/profile required |
| **R09** | P1 | A missing tool is not an active protection | SHA-256 tool manifest binds build, commands, versions and evidence scope; excluded legacy helpers do not become default dependencies |
| **R10** | P1 | Fixed eight-layer names are not a real stackup | Record physical order, dielectric/Dk/Df at frequency, copper thickness, reference planes and fab approval for each signal path |
| **R11** | P1 | AGND/DGND are not always connected at one point | Follow the silicon, isolation scheme and actual return current; function regions do not imply a split ground plane |
| **R12** | P1 | No default capacitor across every plane split | Avoid split crossings, distinguish ground-to-ground from reference transitions, and protect safety isolation |
| **R13** | P1 | Do not apply one differential length tolerance to every protocol | Separate USB2/USB3, D-PHY/C-PHY, HDMI modes, RGMII single-ended timing and Ethernet MDI, and DDR-specific lanes/timing; include package delay |
| **R14** | P1 | Never disguise skew by renaming nets or globally lowering thresholds | Preserve pair identity across series components; track stubs/branches and endpoint mapping, block unsupported topology |
| **R15** | P1 | 3W/20H/90° are contextual heuristics, not pass/fail electrical laws | Specify actual trace edge/center spacing, stackup and crosstalk budget; 45°/arcs do not prove SI |
| **R16** | P1 | No fixed A/mm, half-width internal layers, or “1 A per via” rule | Calculate steady/peak current, IR drop, I²R, temperature and actual copper/plating/thermal environment; solder buildup is not a universal fix |
| **R17** | P1 | Do not mandate backdrill by data rate or use arbitrary via-in-pad | Decide from stub and channel model; approve capped/filled via planarity jointly with fab and assembler |
| **R18** | P1 | Smallest capacitor is not universally nearest; do not clear all thermal-relief warnings | Follow PDN/DC-bias/ESR/ESL/anti-resonance/load-transient evidence; solderability and current paths determine pad connections |
| **R19** | P1 | No mandatory layer switch after 2 mm or universal via-to-pad 0.8 mm | Direction is preference; breakout, return path, timing, fab process govern dogbone/laser/microvia details |
| **R20** | P1 | BOM grouping by only Value+Footprint is invalid | `assembly_guard.py` groups all necessary manufacturing fields; DNP and variants separated; CPL fitted list verified; polarity/rotation require review |
| **R21** | P1 | KiCad SVG is not a Gerber acceptance test | Verify actual Gerber/Excellon structure, complete hashes and independent CAM bound to all current outputs; fake-file/old-CAM tests exist |
| **R22** | P1 | Final source must be frozen, refilled, saved and natively revalidated | R10 `freeze_candidate.py` stages an independent copy, accepts a **Konnect** fill/save receipt and native CLI DRC; it does not use pcbnew to silently write the active board |
| **R23** | P2 | Do not impose 30 devices/page, A4 or absolute routing ratio by default | Functional readability controls pagination. If a product specifies A4 landscape, three-sheet architecture or centering, that **explicit project contract** is binding |
| **R24** | P2 | Clearly distinguish design, CAM, fab EQ and release authority | Historical 0–7 + stackup 2.5 and G1–G6 records are compatible background; R10 active design mainline 01–13, G1–G4, external 14–16 |
| **R25** | P1 | No universal voltage, ripple, temperature, reliability or certification number | Quantify every rail and use case with product/market-specific applicability; D2 fabrication candidate is not D3 product qualification |

The existence of code or fixtures in the third column does not mean live KiCad, field geometry, production CAM or physical validation was completed for the current board. Any relevant missing evidence must remain blocked or pending.

## 2. Quantified product-level acceptance profile

Use `assets/engineering-profile.template.json`. Every requirement must identify its **ID, source document and revision/locator, design rule, acceptance condition, method, real evidence file SHA-256 and disposition**. `null` is unresolved, not a default. `not_applicable` needs actual rationale, reviewer and evidence. Missing manufacturer guidance, fab limits or project constraints blocks affected stages.

### Stackup and impedance

Record actual physical layer order; dielectric material, finished thickness and Dk/Df at relevant frequency; copper thickness; continuous reference planes; symmetry/copper balance; and target fabricator confirmation. An impedance target **cannot** be converted directly to trace width. Archive solver/coupon assumptions, nominal and corner tolerance results, differential/stackup reference and board-house approval. A NetClass setting alone does not prove that all rules are active or apply to the intended nets.

### High-speed and differential links

For each link specify source/destination pins; protocol, bit rate and fastest signal edge; series-device cross-net mapping; branches/stubs; permitted layers and return reference; delay per layer plus package/connector/via budget; skew, eye/timing/loss/crosstalk target, and required external model/test. **USB 2/3, MIPI D-PHY/C-PHY, HDMI TMDS/FRL and RGMII** require separate profiles. RGMII is checked as single-ended timing; its physical Ethernet MDI is differential. DDR must use the actual controller/memory manufacturer lane/CK/CA/DQS constraints rather than a universal millimeter tolerance.

### Power, thermal and safety

For each supply record continuous, peak and fault current; allowable IR drop/I²R; load transient and target impedance ΔV/ΔI; capacitor ESR/ESL/DC bias; actual thermal and copper conditions. Safety separation needs working voltage, overvoltage category, pollution degree, material group, altitude, insulation class and applicable standard—do **not** generalize a numeric clearance from one unrelated board.

## 3. Legacy release classes versus R10 workflow

Historical R9.x stages: requirements (0); schematic/G1 (1); package/G2 (2); stackup (2.5); placement/G3 (3); routing/G4 (4); manufacturing/fab EQ/G5 (5); prototype (6); ECO/G6 (7). R10's active AI design scope is [nodes 01–13](latest-complete-workflow.md), with G1–G4 and **design package awaiting review**; factory authorization and physical tests remain external.

- **D0:** Internal unapproved candidate; no production.
- **D1:** Verified design plus independent CAM may be offered for factory engineering questions only, subject to authorization; unresolved EQ means no manufacturing order.
- **D2:** Target-factory EQ/stackup/drill/impedance/assembly documents closed, exact source/output hashes and production authorization valid for the identified fab/order. A D2 field is not itself evidence of those checks.
- **D3:** Actual product qualification, applicable reliability/certification, ECO and line/process evidence; cannot be produced by static Skill scripts alone.

Default: preview only; no automatic vendor upload or order. Creating `build-manifest.json` does not grant ChatGPT permission to send manufacturing files to third parties. Require an explicit user-approved handoff.

## 4. Final copper, manufacturing evidence and risk closure

Use controlled candidates: approved source → Konnect zone fill/save with actual receipt → independent native reload/DRC → parity/constraints review → immutable export and CAM. Do not approve a board while old and new copper states are mixed, then silently remove old copper and ship Gerbers. Never overwrite the original source, and keep failures traceable.

```bash
python scripts/netlist_guard.py base.xml candidate.xml --mode preserve --topology
python scripts/netlist_guard.py base.xml candidate.xml --mode eco --eco approved-eco.json
python scripts/link_audit.py candidate.kicad_pcb --profile link-profile.json
python scripts/assembly_guard.py production-bom.csv --cpl cpl.csv --variant default
python scripts/freeze_candidate.py /project --board board.kicad_pcb --destination /new-candidate
# Preview above; --apply stages a new candidate and Konnect handoff, NOT automatic fill.
python scripts/validate_frozen_candidate.py /new-candidate --config /new-candidate/review-config.json --output-dir /new-final-evidence
```

Treat any path-graph audit with unsupported pad-edge entry, branches or middle-layer via endpoints as `BLOCKED`, not as “total track length approximately acceptable.” Link checks do not establish characteristic impedance, return-plane continuity or signal eye quality.

A manufacturing handoff requires per-layer Gerbers, Excellon including PTH/NPTH/slots/layer pairs, fab and assembly drawings, variant BOM/CPL, and applicable stencil/paste files. **Inspect actual Gerber/Excellon, not an SVG exported from the PCB.** Verify legal internal slots/holes individually rather than imposing one-outline-only assumptions. Do not manually mirror bottom fabrication outputs; review placement rotations, origin, polarity, DNP and pin 1 with the assembler.

`build-manifest.json` must bind D2, current sources and output hashes, actual tool versions/commands/logs, final state, independently reviewed CAM JSON matching **all** current copper/drill output hashes, closed EQ, and factory/order-scoped authorization. File structure markers alone are a sanity check, not a complete Gerber parser or CAM approval.

High-risk findings require **per-finding, content-bound approval** (rule/location/description fingerprint); do not waive a whole warning category. Native errors and unreviewed exclusions always block. Never escape a failed check by renaming nets, lowering global skew/unconnected rules, deleting objects or editing reports.

## 5. Manufacturer and official technical basis

- [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html) and [KiCad PCB Editor](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html).
- [Analog Devices mixed-signal board layout](https://www.analog.com/en/resources/analog-dialogue/articles/what-are-the-basic-guidelines-for-layout-design-of-mixed-signal-pcbs.html).
- [Texas Instruments SLLA414](https://www.ti.com/lit/an/slla414/slla414.pdf).
- [Espressif ESP32-S3 PCB layout guidance](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/pcb-layout-design.html).

These sources inform engineering methods and capabilities; they do not certify the current design. For IPC/IEC standards and manufacturer/fabricator rules, bind the actual applicable edition and license. Never fabricate source verification or compliance.
