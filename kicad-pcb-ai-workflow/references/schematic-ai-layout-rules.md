# Topology-Driven Schematic Drawing and Verifiable Page Geometry

**Scope:** KiCad schematic generation, rearrangement, hierarchical sheets, and visual review. This is an engineering design and acceptance specification, **not** a claim that the current Skill implements a general geometric schematic solver. Apply together with [schematic-style](schematic-style.md), [system-integration](system-integration.md), and [engineering rules](engineering-rules.md).

## 0. Design goal, required inputs, and prohibited shortcuts

The reader must be able to reconstruct the **actual electrical topology, device roles, and design intent** from the 2D drawing. Optimize **topology first, relative layout second, absolute coordinates last**. Never derive pin exit directions from page center or reuse another project's coordinates, sheet size, or power-page layout as an assumed template.

Before drawing, obtain: approved product requirements and system/interface contract; exact device MPN, package, datasheet and errata; actual KiCad symbol definitions including units, hidden pins, rotation and mirroring; an **independently authored expected component/pin/net graph**; power-domain and safety constraints; and project sheet/text conventions. Missing critical facts are **BLOCKED**. The generated image or netlist must not be used to invent the expected electrical graph against which it will be checked.

## 1. L0–L5 precedence and disposition

| Layer | Subject | Required interpretation |
|---|---|---|
| **L0 electrical truth** | Pin numbers, MPN/values, pin-to-net relations, series/parallel topology, supply domains, polarity, NC/DNP, manufacturer conditions | Hard blocking; aesthetics never justify a connection change |
| **L1 geometric invariants** | Real pin attachment point, transformed exit vector, wires through bodies, label anchors, collisions, sheet regions | Verified hard violations block; unsupported automatic detection requires an explicit review path |
| **L2 circuit roles** | Main series paths, parallel protection/bias/decoupling branches, feedback, buses/differential signals, connectors, functional blocks | Express genuine function with a documented reason for exceptions |
| **L3 sheet archetypes** | Conversion/power, MCU/SoC, connectors, memory buses, analog/audio, discrete I/O, architecture overview | Classify the page and select local composition rules |
| **L4 soft objectives** | Readable wire paths, crossings, bends, labels, grouping, whitespace, alignment and density | Optimize only after L0–L3, never overrule hard constraints |
| **L5 evidence and acceptance** | Independent expected-vs-native netlist, ERC, geometric screening, full-page and local views, engineer review | Report **AUTO**, **REVIEW** or **UNAVAILABLE** honestly |

Priority for conflicting requirements: **applicable law/safety standards > manufacturer datasheet and errata > approved product/engineering requirements > independently established topology > page constraints > appearance**. Stop and obtain an engineering decision for unresolved conflicts; an approved circuit change requires re-approval of the expected graph.

## 2. Convert topology into a readable page

1. Construct a functional block graph by feature, supply domain, interface, reuse, and hierarchy. Identify every block's inputs, outputs, power, ground/reference, and cross-boundary ports.
2. From real component-pin-net connections classify series paths, parallel protection/bias/decoupling, feedback loops, differential pairs, buses, branches, and boundaries. **Visual alignment does not prove electrical series/parallel topology.**
3. Read actual symbol unit, center, rotation/mirror and each library pin's local position, attachment point, orientation, and length. Transform coordinates and outward vectors to the page. Never infer exit direction from which side of the page a pin appears on.
4. Solve relative block order and symbol anchors, then quantize coordinates to the schematic grid. Reserve wire/text corridors; prioritize feedback and protection branches before cross-block connectors.
5. Use short direct wiring locally. For cross-block, hierarchical, high-fanout or unavoidable long links, use named local/global/hierarchical labels as allowed by KiCad scoping and the system interface contract. Do not draw half-page wires merely to reduce label count.
6. Place reference/value text, pin names/numbers, labels and notes independently. Check rendered bounding boxes. Apply any final page offset to the **combined bounding box of all pertinent visible objects**, excluding title/border/reserved regions from the usable page area.
7. Verify both electrical and visual channels. Locally reroute/reposition failures; never remove a required component, silently declare NC, hide necessary text, or mutate a pin net to make a report pass.

## 3. L1 exact geometric definitions

- **Native connection point:** Only a real pin attachment point or other legal KiCad electrical node qualifies. A contact anywhere along a drawn pin line is not automatically a connection. Use a native exported netlist to distinguish junctions from nonconnecting crossings.
- **Pin exit:** For the first nonzero wire segment leaving a pin attachment, compare its direction against the **transformed library-defined outward pin vector**, considering rotation and mirroring. Handle off-axis symbols, composite nodes, and power symbols using verified geometry or explicit review. “The pin is on the left” is not a valid direction algorithm.
- **Wire through a symbol:** The wire must not cross another symbol's real body or prohibited region. A rectangular bounding box is only a conservative broad-phase test; permit legal near-edge/nonrectangular cases after actual geometry review. A line contacting a bounding box near a pin does not automatically legalize a body crossing.
- **Label connection:** The label attachment anchor must coincide with a real wire end or legal node and have native netlist evidence. The text should extend into readable free space and follow neighboring wire direction. Horizontal 0°/180° and vertical 90°/270° are **initial screening only**; verify actual KiCad label type, mirror, transform and rendered text orientation. Do not treat angle alone as proof.
- **Text collision:** Use actual visible text geometry, including font, size, angle and field visibility. Screen illegal overlap with bodies, wires, labels and other text. Hidden fields and legitimate notes follow explicit exceptions; character-count approximations cannot grant PASS.
- **Page boundaries:** Functional objects must remain inside the usable canvas, outside title block, border and reserved annotations. Page frame/title elements themselves are excluded from object violations.
- **Topology versus appearance:** Series and parallel relationships are **L0 netlist predicates**; collinearity is an **L2 readability default**. A parallel TVS/decoupler must not appear as a series main-path element, or vice versa.
- **Long-wire trigger:** Intra-block path length beyond the available block width, more than **two bends**, or crossing another function block triggers **REVIEW/re-layout**. Prefer boundary labels/ports for cross-block links. Relative length is a heuristic, not an electrical acceptance gate.
- **Collinear series path:** Prefer components lying between their actual connected nodes along the primary flow where the symbol geometry permits. **Center offset ≤1 grid** may be a configurable soft target, not a universal electrical requirement.
- **Parallel branches:** TVS, decoupling and pull-up/down components normally form short orthogonal branches to the correct rail/reference. Actual topology controls orientation; “power up, ground down” is not an inflexible rule.
- **Visual center/density:** The overall bounding box includes symbols, wires, junctions, labels, visible reference/value, notes and hierarchy. Exclude the frame/title/reserved region. Offset within **5% of the usable span** is a soft recommendation; intentional whitespace is allowed. Select A3/A4/other sheet size by genuine legibility and project requirements, not a fixed template.

## 4. L2 semantic layout by circuit role

| Role | Default visual expression | Verify |
|---|---|---|
| Series resistor, ferrite bead or fuse | Short aligned entrance/exit on main path | It is truly series; no unintended bypass |
| Bypass/decoupling | Short rail-to-reference branch | Correct supply domain, count, values and device guidance |
| TVS/clamp/filter | Parallel branch from protected node to reference | Polarity, voltage, ground and placement context |
| Pull-up/down | Node → resistor → proper reference rail | Power-up levels, enable/boot behavior |
| Feedback/compensation | Local loop near controlling device | Sense node, loop polarity and complete network |
| Differential pair | Adjacent, aligned, unambiguous P/N names | Physical pin/net polarity; drawing symmetry is **not** PCB length matching |
| Shared pins/nets | Merge locally when actually allowed | Never short isolated pins simply because their function names match |
| Multipin connector | Functional face inward; short labeled fanout | Pin 1, case/shield, NC and full pin map |

## 5. L3 per-sheet archetypes

- **Power conversion:** Input → protection → conversion → energy storage/filter → output; place feedback/enable near the controller.
- **MCU/SoC:** Group by actual pin functions and modules; use proper cross-module hierarchy. Do not change physical pin numbers or manufacturer symbol semantics to improve appearance.
- **USB/multipin interface:** Short connector fanout; CC/VBUS/ESD placed by actual connectivity; clearly distinguish differential polarity.
- **SD/memory/bus:** Controller → optional series/matching → connector or target; pull-ups are actual branches, and labels must not conceal direction.
- **Analog/audio:** Input → conditioning → output; keep feedback and decoupling local; distinguish analog/digital supply and references.
- **Debug/port expansion:** Short labeled branches, grouped nets, visible references; avoid artificial series-chain presentation.
- **User I/O:** Button, LED, buzzer, actuator etc. grouped as independent functions.
- **Hierarchy overview:** Show real flow, modules, supply domains and explicitly bound interfaces; not merely decorative blocks.

One sheet may contain multiple archetypes; partition regions instead of imposing one global POWER page pattern.

## 6. Deterministic conflict resolution

Apply in this order: **(1)** preserve L0; **(2)** reposition peripheral devices; **(3)** legal rotation/mirror; **(4)** only approved alternate symbol or multiunit presentation, never altered pin numbering/net identity; **(5)** short orthogonal wires; **(6)** local/global/hierarchical boundary labels; **(7)** increase spacing; **(8)** resize or split sheets.

For “direct wire versus crossing,” move objects before introducing labels. For “few labels versus long wire,” favor accurate labels. For “center versus signal flow,” preserve flow and shift the combined drawing. For “ground down versus excessive bends,” consider legal symbol rotation. For “label orientation versus anchoring,” preserve the electrical anchor and adjust text. Do **not** resolve layout conflicts by blindly extending wires.

## 7. L4 optimization without changing the circuit

Use lexicographic priorities: achieve L0–L3 feasibility; then optimize readable length, illegal crossings, bend count, redundant labels, alignment, balance and usable area. Store thresholds/weights in project policies rather than global magic constants. Different sheet roles may require explicit exceptions; “minimum labels” and “minimum wire length” are not equal-weight objectives if they conflict.

## 8. L5 evidence matrix and implementation honesty

| Check | Evidence | Current implementation boundary |
|---|---|---|
| Component set, values/footprints, pin-net mapping, NC/DNP and one-pin nets | Independently specified expected graph versus KiCad native netlist plus source properties not exported in XML | Partial `schematic_candidate.py` and native commands; NC/DNP need separate inspection |
| ERC | Actual native ERC report with disposition of exemptions | Supported pathway; ERC alone does not prove electrical application correctness |
| Sheet/hierarchy/frame and pin scope | `schematic_style.py`, system interface pin endpoints | Limited static screening |
| Pin outward vectors, body crossing, label transform and actual anchor | Symbol-instance geometry with transformed pins | **Geometric auto-checker not yet fully implemented**; review every sheet manually |
| All text collision, combined bounding box and page edges | Actual font/rendered geometry plus exact rule calculation | **Not fully implemented**; PDF/SVG visual review required |
| Series/parallel role, feedback, long wires and crossings | Explicit functional block and topology review | AI plus engineer review, with independent actual netlist |
| Full page and ~200% local views | Actual KiCad export/GUI views with sheet and object locations | AI/engineer acceptance; no self-signature |

An automatic checker may declare PASS **only for the part it actually measures**. Unsupported mandatory checks become `UNAVAILABLE` with manual evidence; if the project explicitly requires a fully automatic gate, absence of an implementation means **BLOCKED**. Every violation should include sheet/object, net, severity, source rule, reproduction, before/after hashes and retest. Do not bypass a hard geometry violation because a script returned zero.

For independent archetype tests and three-pass drawing evidence, see [cross-archetype validation](schematic-cross-archetype.md). A prototype_validation record is evidence of what was tested, not evidence of an implemented general geometry engine.

## 9. Execution, rollback and completion

```text
Manufacturer data + independent expected topology + system interface contract
  → function graph / page archetypes
  → series/parallel/feedback roles and cross-block ports
  → exact symbol pin transforms and outward vectors
  → relative anchors and grid coordinates
  → short local wires + legal labels/hierarchy
  → independent visible text layout + combined-bounds centering
  → native export + expected-netlist equivalence + ERC
  → bounded geometry screening + full-page and ~200% view
  → sourced AI review + actual engineer approval
```

A verified L0/L1 hard violation blocks the current candidate; fix locally and rerun native checks. Any net change returns to L0 validation. Soft objectives produce improvement recommendations, not fictional electrical failures. Repeated layout failures warrant page partition or explicit engineering review, not infinite retry loops.

Completion requires independently established topology equal to native export, dispositions for all relevant ERC findings, actual available hard checks, full visual review for unsupported geometry, recorded AI issues and approval by the engineer for the **current** version. This does not replace manufacturer application validation or real hardware performance.

## 10. Integration and adversarial test requirements

Read this specification for new schematic drawing, rearrangement and static visual review. Existing `schematic_style.py` and `schematic_candidate.py` do not acquire new capability merely because this document exists. New geometry engines need positive and negative fixtures covering: shorting inside a symbol, mirrored label anchor, body-crossing wires, long cross-block links, reference/value overlap, title-block incursion, false series/parallel depiction, off-center drawing, and post-edit netlist changes. Include legal counterexamples to avoid false positives.

## Executable R10 composition extension

[Professional schematic composition checks](schematic-composition-gates.md) implement evidence-bound title-block/notes collision screening, native power-symbol policy and read-only page planning/partition screening. Use them on new projects, while preserving existing L0–L5 priorities. These checks require a verified rendered-bounds manifest and **do not** implement a complete autonomous KiCad symbol placement, wire routing, worksheet geometry extractor or automated text collision solver. Unavailable measurements must remain unapproved.
