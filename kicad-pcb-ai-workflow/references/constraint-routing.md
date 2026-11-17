# Script-Planned Routing: Request Contract, Backend Acceptance and Safe Fallback

## Plan versus execution

`routing_policy.py` validates and structures routing requests and backend selections. It does not automatically lay final KiCad copper. `script_route_search.py` provides a bounded offline grid/A* path *proposal*, not a manufacturing-approved track. An externally routed Freerouting SES is also only a candidate until successfully imported, saved, reloaded and natively verified.

## Required request inputs

Specify current project/board identity and source hashes; factory-approved layer order, copper weight and trace/clearance/via limits; allowed net layers and NetClass assignments; protected components, objects, existing tracks, keepouts, board edge; net priorities and endpoints; accepted backend identity; engineer-supplied differential, timing, RF, power and return-path constraints; and operation budgets. Unknown nets, unknown source rules and unsupported geometric constraints cannot default to safe ordinary routing.

Execution must be confined to an authorized independent candidate or the explicitly authorized working project, respecting the single Konnect MCP writer. Record the command/plan revision, object identities, source/target geometry and whether the operation can be safely undone. A new external version, changed schema or broader net/geometry scope requires new relevant capability evidence.

## Failure and controlled recovery

Read back after each bounded routing batch; on timeout or unknown result do **not** replay the same non-idempotent action. If rules, protected objects, design intent or net identity conflict, stop. Do not disable DRC, relax manufacturer tolerances, remove required nets or silently switch to an unverified native script as a fallback. When a supported Freerouting adapter is used, treat DSN→SES→import→native save/DRC as distinct acceptance steps.

Intermediate routing may report explicitly approved incomplete connections; final pre-G4 routing must resolve all *required* unconnected items and applicable blockers. Always verify actual saved copper geometry, fill, via transitions, clearance, return/reference planes and full native DRC. See [PCB module](module-pcb.md) and [workflow node 10](latest-complete-workflow.md).
