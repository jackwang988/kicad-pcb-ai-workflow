# Topology-First AI Schematic Drawing and Verifiable Page Geometry

## Highest priority and known limits

Electrical topology, actual KiCad pin/node semantics, manufacturer application guidance and unambiguous page readability take priority over symmetry or visual decoration. The current Skill contains review rules, candidates and bounded real Konnect operations; **it does not claim a universal implemented geometric auto-schematic solver**. Any proposed algorithm in this reference must be treated as a design objective until an actual implementation and native verification exist.

## L0–L5 drawing and review hierarchy

| Layer | Concern | Requirement |
|---|---|---|
| **L0 electrical** | Correct graph and sources | Solve intended pin-to-net topology, requirements and hierarchical interfaces independently of drawn line geometry; don't change the expected graph to match output |
| **L1 geometry** | Pin anchors and wiring corridors | Use real symbol pin coordinates after orientation and mirror; reserve corridors and wire stubs before bulk placement, route orthogonally when applicable; avoid overlaps with symbols, values and junctions |
| **L2 role and direction** | Interpretability | Power generally top-to-bottom and function/signal flow generally left-to-right when suitable; group upstream sources, protection, conversion, processing, connectors and returns |
| **L3 page archetypes** | Modular design | Choose explicit templates per page (power, RF/analog, MCU, high-speed, interface, mixed-signal) rather than forcing one global layout; verify the choice across varied circuit archetypes |
| **L4 optimization** | Soft readability | Minimize unnecessary crossings/long stubs and clutter, preserve clear labels, whitespace, component orientation and source notes without violating electrical/hard constraints |
| **L5 verification** | Native/semantic evidence | Export current KiCad netlist, run ERC, inspect every sheet and component label, compare expected nets/pin endpoints; engineer signs current version only |

## Exact geometric semantics

Design with explicit transformed pin/stub coordinates, wire endpoints, true KiCad junctions and hierarchical ports. A geometric crossing without a junction does not imply connected pins; a text label near a wire does not prove a valid net anchor. Check mirrored and rotated symbol pins, power-pin direction, hidden power pins, NC pins, multi-unit symbols, differential pairs, clocks, resets and cross-sheet label scopes. Do not let arrow glyphs or pictures substitute for electrical network declarations.

Plan corridors globally first, then solve symbol bounding boxes and connector/port locations, then labels/values/designators, section frames and title block. Hard mechanical/page boundaries and source-derived electrical requirements outrank soft aesthetics. If the requested fanout, page size and symbol density cannot coexist, create a documented page or hierarchical partition rather than accepting overlaps.

## Three-pass execution and conflict resolution

**Pass 1:** Validate net graph and pin identity with a manufacturer-backed expectation. **Pass 2:** Place modules/symbols and reserve actual corridors, including cross-sheet boundaries. **Pass 3:** Draw native wires/ports/labels and perform visual/ERC checks. On a conflict use this priority: physical/electrical correctness > manufacturing/library semantics > distinct net endpoints > page legibility > visual alignment. Never silently delete required components or short distinct nets to improve appearance.

For model evaluation, use representative page archetypes (not only one easy demo), and verify complex hierarchical/rotated/multi-unit cases with native exports and engineer review. Generate a blocker or explicit unsupported-feature record when an operation is not actually implemented. For detail, see [schematic module](module-schematic.md), [cross-archetype checks](schematic-cross-archetype.md), [source-backed review](static-ai-review.md).
