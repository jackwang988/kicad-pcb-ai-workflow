# Konnect MCP Backend: Connection, Operation and Verification Contract

## Distinguish four requests

1. **MCP online?** Use a protocol ping or one exposed lightweight read; stop on success.
2. **KiCad active board connected?** Call `open_project` with the expected board path when available. Confirm IPC, open board identity and actual path. Do not create a project to answer a connection question.
3. **Which tools are available?** Dynamically discover the current toolset(s) and relevant MCP schemas, avoiding an all-tool dump unless explicitly auditing the backend.
4. **May this tool edit the board?** Check local build/schema/version and operation-scope fixture acceptance. Discovery is not authorization; high-risk writes require a protected candidate and independent verification.

## Installation and identity

Konnect-EDA is an externally installed third-party executable, with its own terms and version-specific behavior; it is **not bundled in the public Skill ZIP**. The historical local profile recorded commercial 0.14.1 on Windows/KiCad 10.0.8 and older open-source 0.13.0 on a distinct basis. Those small fixture results are not universal operating guarantees. Verify installer provenance, actual executable SHA-256, server build, connection identity, KiCad version and target PCB on every relevant environment change. No silent downgrade to a different backend or hidden second writer is permitted.

## Board operation loop

- Create or select the exact authorized working candidate. Protect board outline, locks, reference/footprint identities, netlist, already accepted routes and rules.
- AI generates a scoped plan; Python checks deterministic constraints and relevant device cards. Prefer `dry_run` for complex schematic-to-PCB synchronization, and bind the returned plan revision to the corresponding actual call.
- Use a verified task-specific Konnect tool to apply a bounded operation. Return UUID/network/geometry object identities and actual changed values. On timeout or uncertain response, **read actual state** before retrying; do not replay relative transforms blindly.
- Save current KiCad source, release writer ownership, reload independent native files with KiCad CLI, evaluate ERC/DRC and verify project/board hashes. AI and the hardware engineer separately evaluate engineering correctness and current evidence.
- Preserve raw operation receipt in the report folder; the model can initially see only status, affected-object count, changed UUIDs and evidence path, then expand if issues arise.

## Special conditions

- A file-backed schematic tool may conflict with unsaved schematic-editor state. Confirm the editor has saved the current source before edit and inspect the exported native netlist afterward.
- `update_pcb_from_schematic` is a stateful operation: run dry-run first, inspect created/updated/removed/locked objects, and apply the exact recorded plan revision. A successful return does not prove parity until a native re-export and audit.
- Moving a footprint may detach old tracks, change impedance, short protected objects or violate geometric constraints. Read back actual pads and rerun relevant DRC and G3/G4.
- Freerouting DSN/SES interchange is not the same as verified copper in KiCad. Confirm SES import, actual board state, manufacturing rules and saved DRC.
- If the backend lacks the operation, fail only the dependent task with a specific `BLOCKED` reason; never invent tool names or treat higher version numbers as automatic compatibility proof.

See [dynamic capability policy](konnect-capability-migration.md), [module environment](module-environment.md) and [full process](latest-complete-workflow.md).
