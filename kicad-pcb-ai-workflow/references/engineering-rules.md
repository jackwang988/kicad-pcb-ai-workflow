# Engineering Rules for Valid Electronic Products

## Authority and applicability

Use, in descending precedence, actual product safety/functional requirements, the **exact device manufacturer's** electrical/thermal/application guidance and errata, the chosen interface protocol standard, the *actual* fabricator and assembler's approved stack-up/process capabilities, and relevant IPC/industry recommendations. General examples are never universal defaults. Distinguish actual factory minimums from conservative recommended targets; do not infer controlled impedance from nominal trace width without stack-up and a verified field solve. If sources conflict, request an engineering disposition and keep dependent operations blocked.

## Pre-design and layout audit matrix

| Review domain | Required engineering evidence |
|---|---|
| Product and architecture | Quantitative functional acceptance, environmental conditions, interface map, fail states and power budget |
| Device source | Exact MPN/package, original revision, verified pinout/land pattern, source card and errata |
| Power | Continuous/peak current, voltage range, startup sequencing, protection, voltage drop, copper thermal rise, decoupling and ground return |
| Digital | Clock/reset/BOOT and unused pins, logic levels and power-off behavior, routing topology, termination, isolation and ESD |
| High-speed | Protocol/PHY, rise/fall times, impedance and tolerance from real stack-up, layer reference, differential mapping, skew and loss/crosstalk budget |
| RF/antenna | Feed/matching, reference plane, trace geometry, antenna keepout/ground and actual orientation |
| Mechanical | Outline, holes, mating connector datum, BBox/courtyard, clearances, enclosure and thermal areas |
| Fabrication | Copper/layer material, drills, annular rings, min trace/space, board edge, via fill, soldermask and paste |
| Assembly | Polarity, Pin 1, orientation, component side, DNP variants, BOM/CPL consistency and rework access |
| Test | Required test points, boundary-scan/JTAG when applicable, fixtures, diagnostics, safety and real external qualification |

Before drawing PCB, set actual KiCad layer mapping, routing width classes, via sizes, classes/custom DRC and manufacturing parameters; *read back* actual effective rules. Unknown constraints stay unresolved. Verify the board's copper geometry and return current, not just net count or colored airwire length. Each required problem must retain location, evidence/source, risk category, recommended repair and verification method.

## Risk classes and sign-off

- **Blocking:** Missing mandatory evidence, wrong pin/part identity, unproven safety/manufacturing rule, failed electrical/native check, unconnected required net or any other non-waivable fatal condition.
- **High:** Material design risk requiring explicit engineer disposition and correct project-specific evidence.
- **Medium:** Real project/assembly/process concern requiring tracked disposition before relevant production gate.
- **Recommendation:** Optimization or readability improvement that cannot override hard electrical/physical constraints.

A Python PREVIEW, an AI statement, a tool's successful return code and an empty DRC report do not independently establish production fitness. Preserve source-to-design-to-acceptance traceability. The principal AI workflow ends at reviewed **design candidates**; actual CAM/EQ, production authorization and prototype tests are external.

## Manufacturing candidate and immutable status

Only create or export in explicit new candidate directories, after real gating and source hash binding. The candidate status `EXPORTED_NOT_RELEASED` does not mean manufacturing approved. The selected factory, schematic variant, BOM/CPL, Gerber/drill and engineer approval must be consistent; actual CAM and factory EQ are needed for production release. Never delete historic source or weaken rules to produce an artificial PASS.
