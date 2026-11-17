# Environment, Connection and Workspace

**Smallest-first inspection:** For routine MCP health, use a supported protocol ping or one already exposed read-only call, such as `get_active_toolsets`. For KiCad connectivity, use a single `open_project` query (include the requested board path if supplied). A successful connection check is *not* an operation-capability acceptance and does not prove native file correctness.

Interpret the returned facts: `ipc_available=true` and an open matching board mean KiCad IPC connectivity; no open board is an ordinary not-open state; `ipc_available=false` requires examining the reported `ipc_failure`; a different board path is a target mismatch. Do not automatically start applications, change boards, capture the desktop, create test boards, run DRC or install plugins just to check a connection.

If a call fails, use its actual error to select **one** additional targeted read-only diagnostic. Do not run unbounded reinstall/reconnect loops or repeat whole-toolset discovery. First installation, a new Konnect binary, a new high-risk operation or native source verification may require the documented doctor/setup and scoped capability fixture.

The current working project is registered with `workflow.py workspace ...`; always inspect `CURRENT_PROJECT.json` before incremental editing. For full local acceptance see [Konnect backend](konnect-backend.md), [dynamic capabilities](konnect-capability-migration.md) and [environment setup](environment-onboarding.md). Use `--apply` only for an explicitly authorized write; never infer source-write permission from a read-only check.
