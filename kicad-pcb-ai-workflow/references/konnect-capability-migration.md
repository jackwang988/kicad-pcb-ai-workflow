# R10 Konnect MCP Migration: Dynamic Discovery and a Single Active EDA Writer

## Policy

Do not hard-code a permanent whitelist of 228 or 235 tool names. Discover the tools actually exposed by the installed Konnect version with `list_toolboxes`, `load_toolset` and MCP `tools/list`; use task-focused discovery by default and an explicit `--all-toolsets` only for inventory. **Discovery is not acceptance.** Capabilities are accepted for specified build, input schema, project scope, KiCad version and validated object types, then can be reused under those exact conditions.

Konnect MCP is the sole active KiCad **writer**. The experimental `kicad_bridge` plugin, server and request writing paths have been disabled; native `pcbnew` zone-fill/save is not an automatic fallback. Python remains responsible for calculations, cached knowledge, deterministic audit and isolated offline generation; KiCad CLI is the independent ERC/DRC/checking path. During transition, a small number of `pcbnew` **read-only** geometry/NetClass audits remain available where verified; missing native-equivalent information blocks relevant manufacturing assertions.

## Risk and reusable acceptance

| Risk | Example | Acceptance boundary |
|---|---|---|
| L0 | Version, list/read/get, board metadata | Verify identity and intended target; no project source write |
| L1 | Single object move/rotate, simple field or silkscreen change | First bounded use with explicit authorization, save and readback; no blanket fixture prerequisite |
| L2 | Group placement, routing, vias, zone fill, net mutation | First authorized small batch on protected working candidate; save, read back and review real state |
| L3 | Deletion/rebuild, whole-board autorouting, high-risk reconstruction | Isolated candidate plus dedicated fault/recovery and engineering evidence; human authorization as applicable |

Persist an acceptance registry **outside** the public Skill, candidate and project (e.g., a private workstation location). An accepted item binds: executable SHA-256; backend release/server version and build commit; KiCad version; actual MCP tool name and input schema SHA; tested parameters/geometry/object scope; source fixture and resulting candidate hashes; independent native DRC proof; and failure/recovery conditions. New executable builds or changed input schema require new relevant acceptance. Project edits still require independent project-specific results and gate review.

## Operating sequence

```bash
# Read-only inventory. Use --all-toolsets only when full audit is requested.
python scripts/konnect_capabilities.py discover --executable /real/konnect --config /real/config.json --all-toolsets --output-dir /new/reports/discovery
# Inspect a specific capability's identity and scope before performing writes.
python scripts/konnect_capabilities.py assess --help
# Use a *separate*, genuine KiCad fixture for first acceptance.
python scripts/konnect_capabilities.py fixture --help
# Only after actual scope acceptance, invoke a candidate operation with --apply.
python scripts/konnect_capabilities.py invoke --help
```

Before starting a version not already enrolled, verify the actual installer source and legal authorization; register its executable build and allowed KiCad targets locally. Do not inherit a 0.13.0 test result as proof that commercial 0.14.1 or a future release behaves identically. Do not assume every newly discovered tool is safe simply because its help text exists.

## Candidate operation and freeze handoff

1. Verify one current target project and candidate source hash, check object UUIDs, protected geometry and existing accepted tool scope.
2. Use direct bounded first-use execution for ordinary L1/L2 operations; reserve an independent fixture for L3 or specialized acceptance. `fixture` currently has bounded acceptance checkers for designated footprint positioning and zone-fill changes; an unknown operation class needs its own deterministic validator, not auto-PASS.
3. Execute a small batch via Konnect and read back real changes; a timeout leaves uncertain state until read back. Save after an accepted operation when requested, and bind the receipt to the exact source/candidate hashes.
4. For freeze, use `freeze_candidate.py` only to stage an independent copy; open the *candidate*, perform accepted Konnect zone fill and save; call `freeze_candidate.py --finalize --operation-report ...` to verify the receipt, filled copper and independent KiCad CLI native reload/DRC. Source project must remain unchanged.
5. Store operation receipts and native output in separate, immutable report directories. Native DRC and human PCB reviews still use the current saved candidate; a successful MCP response alone is insufficient.

## Migration limitations

`konnect_backend.py` verifies backend identity, board and resource protection. Other scripts still require selected native geometry, rule and manufacturing semantics not yet proven equivalent through MCP; preserve read-only adapters or block when absent. Do not claim full replacement of `pcbnew` reads, complete auto placement/route, EMC/PI validation or final production approval. `manufacturing_export.py` uses KiCad CLI to generate separate outputs; DFX/NPI and source-provenance gates remain mandatory.

Related: [backend installation](konnect-backend.md), [workflow](latest-complete-workflow.md), [independent static review](static-ai-review.md).

## Current first-use policy

The available Konnect tool list is not artificially cropped. After current executable, tool schema and target checks, L0 reads run normally. L1/L2 may attempt one authorized operation in the protected working candidate without a prior fixture registry entry; the tool must save and be checked immediately. Known footprint placement and zone fill have optional exact saved-state verifiers; unfamiliar operations return `OPERATION_EXECUTED_NEEDS_POSTCHECK` and cannot auto-pass subsequent engineering gates. A no-op returns `NO_SAVED_CHANGE_REVIEW_REQUIRED`. A timeout, failed save or unexpected change must stop; inspect the real editor before retry. L3 deletion, rebuild and script execution remain isolated-fixture-only. This backend's general `invoke` remains **PCB-file oriented**; it is not yet verified as a universal schematic GUI dispatcher. KiCad ERC/DRC and engineer review remain independent.
