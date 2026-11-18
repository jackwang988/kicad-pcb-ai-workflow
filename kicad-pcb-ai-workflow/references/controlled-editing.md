# Historical Experimental KiCad IPC Editing Bridge (Disabled for Active Writes)

**Important:** The self-developed IPC `kicad_bridge` plugin/launch/serve/request write path is disabled in R10. This reference remains an English historical/diagnostic specification, not instructions to enable a second active EDA writer. Current active edits must use the accepted [Konnect single-writer workflow](konnect-capability-migration.md).

## Historical prototype contract

The experimental bridge used an IPC plugin, private session directory and preconfigured KiCad Python client for a constrained KiCad 10.0.8 board-edit demonstration. Its original install flow could include a plugin under KiCad's IPC plugin location, a connection action and `connection.json` session identity, with separate GUI/IPC state. **It is not installed or invoked by default.** A stale connection file is not evidence that a live board is connected.

The former operation sequence was: inspect the actual source board and UUID/pad coordinates; stage a new candidate with a `candidate-manifest.json` and source SHA; open the candidate as a separate board/session; preview the requested bounded footprint move/rotation; apply once; read actual footprint/pad positions; if cancelled or ambiguous, reconcile without blind replay; save an accepted candidate; independently run CLI DRC on the saved file.

The prototype used a private per-user sessions directory with OS-scoped locking. Such a lock did not exclude GUI manual actions, different sessions roots or independent third-party writers. A pre/post hash and read-back are not atomic transaction guarantees. A committed operation's compensating restore was a new operation, not a claim that a past commit never existed; state changes from other editors must not be overwritten.

The legacy plugin and bridge writer cannot be selected as automatic fallback if Konnect fails. Read-only diagnostics may still be used where explicitly supported. Future experimental reuse would require an independently accepted runtime, real GUI fault-injection testing, saved-board checks, recovery state validation and explicit separation from all live project writes.

Reference: [KiCad IPC API](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/). The exact client/API version must be independently validated on the target KiCad installation.
