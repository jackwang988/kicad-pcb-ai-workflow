# R10 Unified CLI and Task Routing

## Start with the smallest relevant interface

Do not read every reference, compile every configuration or discover every Konnect toolset for a simple edit. Determine current project identity first, reuse its existing configuration snapshot when valid, and choose exactly one declared task. `workflow.py modules` selects module instructions; `workflow.py plan` previews an operation; `workflow.py run` dispatches an authorized, manifest-bound tool; a Konnect MCP edit is a separately accepted real EDA action.

## Six compatibility groups and the active design stages

| Group | Nodes and intent | Main checks |
|---|---|---|
| Environment | Node 01: connection, workspace and tool identity | Real KiCad/CLI/verified Konnect target |
| Architecture | Nodes 02–04: quantitative requirements, cached sources, reserves | Exact part evidence and source-backed constraints |
| Schematic | Nodes 05–07: topology/netlist, G1, G2 | Native ERC and symbol-pin/footprint mapping |
| PCB | Nodes 08–11: stack-up/rules, G3, route, G4 | Actual saved board, full native DRC and AI review |
| Manufacturing | Nodes 12–14: NPI, export; factory review external | `EXPORTED_NOT_RELEASED`, verified artifacts |
| Lifecycle | Nodes 15–16: real tests and ECO, externally authorized | Physical evidence and engineer signature |

## Core commands

```bash
# Discover module-level task reading requirements without creating a new project.
python scripts/workflow.py modules --intent schematic
# Register a known working project ONCE. Do not create a second project for ordinary edits.
python scripts/workflow.py workspace /project --action status
# First-time master config only; an existing config must be reused or intentionally versioned.
python scripts/workflow.py init /project
python scripts/workflow.py init /project --apply
# Generate a new immutable configuration bundle only if the original source/rules changed.
python scripts/workflow.py build /project --bundle control-r1
python scripts/workflow.py build /project --bundle control-r1 --apply
# Use compact status, and obtain full JSON only for specific diagnosis.
python scripts/workflow.py status /project --bundle control-r1 --format compact
python scripts/workflow.py status /project --bundle control-r1 --format json
# Ordinary task: preview first, then run with required exact options.
python scripts/workflow.py plan /project --bundle control-r1 --task schematic.prepare --output-dir /project/03_REPORTS/G1-r1
python scripts/workflow.py run /project --bundle control-r1 --task schematic.prepare --output-dir /project/03_REPORTS/G1-r1
```

For a new installation run `environment.doctor`; native setup requires actual valid input and explicit write authorization where appropriate. Schematic AI review uses node 03 project device cards, actual netlist/XML, native ERC and G1 engineer disposition. PCB independently reviews actual copper/DRC at G4. Manufacturing output must use an isolated candidate and must not be authorized merely because a report looks clean. A configured feature being not applicable does not silently disable a mandatory gate.

## State, safety and evolution

Configuration bundles are immutable and hash-bound to source master, tools and component rules. Tool, component or source changes can require a *new* bundle; do not overwrite old signed packets to save disk. Externally supplied scripts/commands are not automatically executable. Python script routing uses the approved tool manifest and explicit argv. Konnect dynamic MCP tools are discovered separately with build/schema/scope acceptance; only Konnect writes the active EDA project. A 10.x sample acceptance does not automatically extend to future KiCad 11+, nonbaseline installation, or complex manufacturing.

See [entry](../SKILL.md), [workspace policy](workspace-and-token-policy.md), [latest 16-node process](latest-complete-workflow.md) and [Konnect capabilities](konnect-capability-migration.md).
