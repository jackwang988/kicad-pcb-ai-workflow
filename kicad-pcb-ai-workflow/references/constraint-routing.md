# Script-Planned Routing: Request Contract, Backend Acceptance and Safe Fallback

## Plan versus execution

`routing_policy.py` validates and structures routing requests and backend selections. It does not automatically lay final KiCad copper. `script_route_search.py` provides a bounded offline grid/A* path *proposal*, not a manufacturing-approved track. An externally routed Freerouting SES is also only a candidate until successfully imported, saved, reloaded and natively verified.

## Required request inputs

Specify current project/board identity and source hashes; factory-approved layer order, copper weight and trace/clearance/via limits; allowed net layers and NetClass assignments; protected components, objects, existing tracks, keepouts, board edge; net priorities and endpoints; accepted backend identity; engineer-supplied differential, timing, RF, power and return-path constraints; and operation budgets. Unknown nets, unknown source rules and unsupported geometric constraints cannot default to safe ordinary routing.

Execution must be confined to an authorized independent candidate or the explicitly authorized working project, respecting the single Konnect MCP writer. Record the command/plan revision, object identities, source/target geometry and whether the operation can be safely undone. A new external version, changed schema or broader net/geometry scope requires new relevant capability evidence.

## Failure and controlled recovery

Read back after each bounded routing batch; on timeout or unknown result do **not** replay the same non-idempotent action. If rules, protected objects, design intent or net identity conflict, stop. Do not disable DRC, relax manufacturer tolerances, remove required nets or silently switch to an unverified native script as a fallback. When a supported Freerouting adapter is used, treat DSN→SES→import→native save/DRC as distinct acceptance steps.

Intermediate routing may report explicitly approved incomplete connections; final pre-G4 routing must resolve all *required* unconnected items and applicable blockers. Always verify actual saved copper geometry, fill, via transitions, clearance, return/reference planes and full native DRC. See [PCB module](module-pcb.md) and [workflow node 10](latest-complete-workflow.md).

## Exact request and source-binding contract

Use `assets/routing-request.template.json` (schema version 1). Required request fields include `request_id`, `strategy=script_planned`, `phase=incremental|final`, explicit `runtime` (`platform`, KiCad and API versions), hashed project-relative `inputs`, per-net engineering constraints, stable pending connection IDs and bounded resource budgets. A sample `null`/placeholder does not satisfy the contract. Each input must bind the board, actual XML netlist, stackup, native rules and protected-object file by `file/sha256` and must not follow project-escaping symlinks. Hash drift is a **blocker**, not an invitation to refresh hashes silently.

Each target net needs a documented class, manufacturer/project source locator and bounded allowed layers, width, copper clearance, edge/keepout clearance, vias and return requirements. Distinguish continuous voltage/current, high current and thermal, clock/reset, differential/high-speed, RF/analog/Kelvin, ordinary, ground and explicit manual-only. Unknown nets cannot be silently downgraded to ordinary signals. `parameters` must be explicit finite numeric engineering values with units and applicability. Differential/RF/timing/power classes need their corresponding additional constraints; this policy parser is not an impedance or SI/PI solver.

`pending_connections` are stable IDs bound to explicit `(ref,pin)` endpoints in actual schematic XML; `target_connection_ids` declares the batch. Preflight checks declared endpoints and net partition, not actual existing copper continuity or completeness of the pending list. `budgets` must bound time, iteration count, maximum via count and random seed. Zero vias may be allowed; if vias are allowed, specify per-net actual via geometry and hole clearance. An execution backend must enforce budgets, not merely echo them in a plan.

Declare actual copper layer order and roles in a hashed layer file. Only `signal` or explicitly permitted `mixed` copper supports signal routing; `reference_plane` and `power_plane` remain protected unless a justified project-specific rule explicitly allows something different. `allowed_signal_layers` cannot reference absent/forbidden layers. For four or more copper layers, require real fabricator stackup and adjacent reference/return review; layer names or nominal stackup count alone do not establish characteristic impedance.

Protected-object contract example:

```json
{"schema_version":1,"locked_policy":"preserve_all","object_uuids":[],"plane_layers":["B.Cu"],"nets":["GND"]}
```

Existing locked footprints and copper are inherently protected. Only explicitly identified, previously reviewed `reroutable_uuids` of eligible segment/arc/via objects may be modified. They cannot include locked objects, excluded nets, plane layers or nonrouting geometry. Every actual edit delta must be reconciled against the protection set.

## Backend registration and acceptance

`routing_policy.py` supports *planning-only* backend kinds `native_script|freerouting`; this is a **historical backend-acceptance contract**, not an authorization for a second active KiCad writer. Under R10 the final real KiCad write still goes through the supported Konnect MCP tool with its separate per-build/schema/scope acceptance. Never blindly execute an offline router's script against the active GUI project.

Backend records bind `id`, `kind`, version, artifact SHA and acceptance SHA. Acceptance must specify `record_type=routing_backend_acceptance`, `decision=accepted`, `scope=kicad_end_to_end`, checked and expiry dates, actual reviewer/reason, exact runtime platform/KiCad/API versions, supported constraints, geometry/capabilities and independent evidence for `native_drc`, `netlist_parity`, `save_reload`, `protected_object_diff`, `rule_hits`, `connectivity`. Merely producing DSN or SES, placing `passed=true` in JSON, or running synthetic fixtures is not manufacturing/physical qualification. If the exact required capability lacks current acceptance, choose `PENDING_BACKEND_ACCEPTANCE` rather than fabricate a plan to execute it.

For the current constrained policy, prefer accepted native script planning to equally qualified Freerouting only when *all* hard constraints are supported; same-kind alternatives sort deterministically. The external `freerouting_adapter.py` currently handles limited DSN→SES staging; it does not establish successful KiCad import, rule fidelity, layer mapping, zone fill, save/reload or DRC without separate evidence. This remains a reason to block the unsupported operation rather than silently switch an unverified writer.

| Planning status | Meaning |
|---|---|
| `PREFLIGHT_READY_NOT_EXECUTED` | Inputs, declared policy and acceptance records are eligible, **no copper written** |
| `PLAN_READY_NOT_EXECUTED` | Bounded planning information produced, **no copper written** |
| `PENDING_BACKEND_ACCEPTANCE` | Missing/expired/insufficient backend proof; not ready to execute |
| `BLOCKED` | Missing source/rules, changed hash, unsupported feature, protected-object conflict or malformed request |

Use:

```bash
python scripts/routing_policy.py preflight /project --request routing-request.json
python scripts/routing_policy.py plan /project --request routing-request.json --output-dir /project/03_REPORTS/route-plan-r1
python scripts/routing_policy.py plan /project --request routing-request.json --after-attempt failed-attempt.json
```

### Failure handling and fallback

Only a real, source-bound `NO_ROUTE_WITHIN_BUDGET` may trigger planning for another **equally accepted** backend. It must carry `schema_version=1`, current request SHA, initial board SHA, failed backend ID, real log evidence hashes and a nonempty list of remaining connection IDs. An attempt that violates rules, moves protected objects, loses source identity or lacks a supported capability cannot be rescued by changing backend or increasing constraints without reapproval. Budget exhaustion does not prove the connection impossible.

A fallback is planned from the original checkpoint; do not reuse unverified partial copper from a failed execution. To retain completed segments, independently validate and save the partial candidate, then create a **new** request anchored to its actual board, netlist, protection and rule hashes. For intermediate routing, explicitly track only approved remaining connection IDs; do not waive an entire DRC category. For final routing, independently rescan *all* required connections, including ground, after final fill. A green plan never means a routed board; connection, DRC, pin-to-pad parity, protected-object integrity, stackup/return path and project-specific timing/SI/PI still need separate verification. G1–G4 and `EXPORTED_NOT_RELEASED` remain unaffected.
