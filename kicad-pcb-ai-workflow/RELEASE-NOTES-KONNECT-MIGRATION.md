# R10 Konnect Single-Writer Migration — Release Candidate Notes

## Implemented software changes

Konnect MCP dynamically discovers all actual loaded tools and checks build/schema/operation scope. Writes are risk-classified L0–L3 with separate fixture acceptance and reusable records; an accepted tool does not imply an automatically accepted design. Legacy self-developed IPC live writing and default `pcbnew` zone-fill saving are disabled, avoiding an accidental second active KiCad writer. The freeze handoff now requires a source-protected candidate, a genuine accepted Konnect zone-fill/save receipt, independent KiCad CLI reload/DRC and immutable evidence.

Python still handles manufacturer-cache reuse, algorithm planning and deterministic analysis. Select read-only `pcbnew` geometry/NetClass audits remain transitional until equivalent native-compatible MCP data have been tested. No missing manufacturing predicate or current project G1–G4 finding may be bypassed by a simplified model response.

## Testing and unverified areas

R10 offline software tests cover interface identity, risk/scope checks, failed fixture behavior, hash tampering, single-writer safety and device-card stage reuse. They do not establish complete live Windows/KiCad GUI compatibility, all newly discovered Konnect tools, complex schematic hierarchies, full PCB autorouting, engineering SI/PI or factory-release acceptance. Test these areas on real, source-backed candidate projects and retain reports before stating production readiness.

## How to operate

Use task-scoped module loading, exact project index, verified device card briefs, dynamic Konnect acceptance and native ERC/DRC. Do not download manufacturer source again for each gate, duplicate a full KiCad project after ordinary edits or read every tool schema into AI context. A new version requires fresh relevant binding tests; failure is `BLOCKED`, not silent fallback. See `references/konnect-capability-migration.md` and `references/latest-complete-workflow.md`.
