# Read-Only KiCad IPC Connection and Board Snapshot

IPC is a technical read bridge to a *running* PCB editor, not automatic approval of another write backend. The current Skill may probe KiCad editor availability, selected board path, board state and read-only footprints/pads where supported. The saved disk project and live in-memory board may legitimately differ before a user saves; record both identities and do not overwrite either from stale snapshots.

Use the specific `kicad_ipc_probe.py` command/help or the `workflow.py` environment IPC tasks only for an explicitly requested live diagnostic. A routine connection question is cheaper via one lightweight Konnect request, without capturing a full board dump. If IPC cannot connect, record the returned error and perform limited diagnosis, never silently install an experimental plugin or create a test board.

IPC compatibility is version-scoped; older KiCad SWIG bindings may be deprecated/absent. Do not infer that an available read-only IPC probe authorizes `pcbnew` or self-developed bridge writes. All active KiCad modification belongs to Konnect MCP under the approved single-writer policy; final native validation uses the saved project and KiCad CLI.

See [historical controlled editing](controlled-editing.md), [current Konnect backend](konnect-backend.md) and [environment setup](environment-onboarding.md).
