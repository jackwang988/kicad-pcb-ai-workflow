# Capability Matrix and Engineering Limitations (R10)

## Implemented and bounded functions

- A manifest-bound `workflow.py` front end dispatches task-specific Python scripts, with module-level reference loading and separate immutable G1–G4 evidence.
- `device_knowledge.py` supports official-source ingestion, card validation, exact-MPN cache-first resolution, verification/freshness checks, project-frozen bundles and stage-specific briefs.
- G1 current schematic evidence preparation and AI/engineer review; G2 actual symbol/footprint lock and device-card mapping; G3 current board placement assessment; G4 saved board copper/static review and evidence gate.
- Python offers selected deterministic high-speed/PI checks, design-intent audits, source/network consistency, offline route search and manufacturing preflight. Each has a declared scope and does not automatically modify the PCB.
- Konnect MCP dynamic discovery and scope-bound fixture acceptance permit **specific** real operations. The accepted capability must match executable/build, KiCad version, tool schema and tested object/geometry parameters.
- Workspace index, immutable checkpoints and bounded report summaries reduce duplicate projects and unnecessary AI-context ingestion; neither changes KiCad's design database without a separate accepted operation.

## Not automatically proven

No universal schematic generator, general autorouter, auto-placer, guaranteed 3D collision/thermal/SI/EMC solver or automatic factory approval is provided. A clean ERC/DRC, a simulated A* route, a drawn keepout, a cached device card or a programmatically assembled Gerber archive does not prove product fitness. Complex multiboard/hierarchical, RF/high-speed and production cases require appropriate actual device/vendor/factory and engineering evidence.

## Version policy

KiCad 10.0.7 is a historical recommendation, not a maximum version. Stable KiCad 10.x may be considered after matching actual native tests; KiCad 11+ should be evaluated with CLI-only scope and a separately validated Konnect/IPC capability, not a blanket assumption of `pcbnew` SWIG compatibility. KiCad 9 and RC/nightly require separate verification. Historic KiCad 10.0.8 integration evidence or R10 software-unit tests are **not** blanket acceptance of a new installed Konnect binary, arbitrary board or manufacturing release.

Independent design review, manufacturing data and physical hardware tests remain required. See [latest workflow](latest-complete-workflow.md), [Konnect acceptance](konnect-capability-migration.md) and [engineering rules](engineering-rules.md).
