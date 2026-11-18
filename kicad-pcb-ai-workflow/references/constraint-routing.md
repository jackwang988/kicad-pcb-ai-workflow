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

**Current R10 seven-stage policy supersedes the old native-script-first prose:** use verified Freerouting 2.5.0 as the **offline candidate generator for eligible ordinary nets** after actual critical-net routing/protection, with GND and critical classes excluded. The `routing_policy.py` backend acceptance contract itself authorizes only a qualified `konnect_mcp` *active EDA writer*; legacy `native_script` and `freerouting` backend kinds are not live writers. `freerouting_adapter.py` handles bounded DSN→SES staging, and `routing_seven_stage.py` adds read-only plan/import/final geometry checks. Neither can prove native SES import, rule fidelity, layer mapping, zone fill, save/reload or DRC without separate evidence. Missing native capabilities must BLOCK rather than silently switch to an unverified writer.

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


## Power traces: tabulated main width, +0.254 mm, and controlled pad escapes

**Current R10 software guard:** `routing_policy.py` now requires the complete named XML-net inventory to be categorized, rejects ordinary-router targets classified `GND` or `REFERENCE_PLANE`, and sizes declared **power trunk** `track_width` from the user-supplied 1/1.5/2 oz current table **plus 0.254 mm minimum additional copper width**, then compares approved thermal and voltage-drop width floors. This chart is **experience data with unspecified temperature rise, inner/outer placement and source provenance**; it does not certify IPC-2152 ampacity. A copper thickness absent from the chart (for example 0.5 oz inner copper), too-high current, or missing thermal/drop evidence **blocks**, instead of extrapolating a false safe width. Select an actual available KiCad routing width **rounded upward**, not downward. Width margin is not clearance.

**Important exception: a fine-pitch power pad is not the wide trunk.** A narrowly scoped, short **pad-escape/neckdown** can join a small pad to a wider trunk; the trunk's +0.254 mm margin must not be imposed as the **global Board Setup minimum trace width** or as an unconditional every-segment absolute minimum. Global Board Setup minimum remains the verified board-house absolute fabrication floor; KiCad netclass/custom rules should maintain the wide trunk away from a tightly scoped pad escape. **No blanket rule relaxation:** a neckdown must be permitted only for its named net, exact `reference/pad`, layer, source-backed region and length. A footprint-wide courtyard alone may be too permissive; use the smallest independently verified scoped rule area. KiCad's official custom-rule example supports localized `track_width` using `intersectsCourtyard`, but the actual rule priority/effective scope must be read back and tested with a deliberately failing fixture before use.

**Required proposed neckdown contract (NOT YET AUTOMATICALLY ENFORCED):** exact `net`, `ref`, `pad`, approved `layer`, actual pad and adjacent-pad copper geometry, `escape_width_mm`, source-backed `max_escape_length_mm`, allowable exception count, region polygon/UUID, trunk `main_width_mm`, design current carried by that branch, copper thickness, estimated/reviewed drop and temperature rise, reference-plane/return requirements, approved native rule scope and authoritative source/evidence hashes. The width must not drop below actual fab minima, violate neighboring pad clearances, or exceed local heat/current/voltage-drop limits; a short escape is **not automatically current-safe**. Consider parallel power pins, multiple stitching vias or copper zones when necessary, and verify connector/pad/via ratings. If any required evidence is missing, use `NEEDS_NECKDOWN_ENGINEERING_REVIEW` / `BLOCKED`, not an invented default.

**Execution target:** parse actual footprint pads/neighbors → calculate feasible escape width and shortest legal exit path → bind exact source-backed local native rules → reserve escape zone → create short narrow section, then widen as soon as legal (optional verified teardrops between pad/track/track) → Konnect save and independently read back actual object UUIDs/widths/lengths/clearances → bound the actual width exceptions to their approved areas → complete routing/zone fill → full G4 native KiCad DRC, connectivity and electrical/thermal review. An effective minimum clearance/track-width rule cannot be overridden below KiCad's global fabrication minimum. KiCad teardrops improve transition geometry; **they do not establish a narrow segment's thermal safety**.

The current generic `script_route_search.py` uses **one width per simple ordinary connection** and has no mixed-width pad-escape solver, automatic native per-segment DRC-rule application or acceptance receipt. Do **not** claim it currently executes power-neckdown routing just because the above contract is documented. For signal classes with a wide default width, the same short-escape geometry principle may apply; for differential, clock or RF, independently verify discontinuity, symmetry, impedance and timing, never silently change width.

**Fallback:** first use supported/current-version accepted Konnect interactive or dedicated routing operations, with saved-state readback. A bounded A* budget failure may retry on the same approved constraints; an externally generated Freerouting SES is a *candidate* only until independently imported into a protected KiCad candidate and validated. If neither tool can preserve the scoped rules/geometry, stop and ask for a deliberate engineering/manual route, never auto-waive safety constraints.

## R10 staged Freerouting-primary candidate

For the normal-net batch, the recommended engineering direction is an externally routed **Freerouting DSN/SES candidate**, not a new LLM-owned multi-net A* production router. This is **not enabled as a production default** until the adapter, native import and rule-fidelity acceptance have passed. The v2.5.0 adapter now supports reviewed DSN hash, explicit approved `.rules` hash and class exclusions through `-inc`; it still cannot prove source NetClass membership or imported copper. Critical power, controlled impedance, differential, RF, Kelvin and GND-return geometry remain with independently verified KiCad/Konnect critical routing and validation. No weakening of the 0.254 mm power trunk margin, scoped pad escapes, H/V/45 expectation, object protection or G4 gate is permitted. See [complete Freerouting-first candidate contract](freerouting-primary-routing.md).
