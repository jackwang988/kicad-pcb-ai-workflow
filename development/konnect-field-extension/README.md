# Case-tested placed-field MCP extension (AGPL-3.0-only)

This companion adds `set_placed_footprint_fields` to **open Konnect 0.13.0**, exact base commit `6bbe3e4f890ba1d37c0e5d5f38ccd03d90958c9e`. It does not modify or redistribute commercial Konnect 0.14.1, and is not included in the minimal Skill ZIP. Source module SHA-256: see `manifest.json`; the module is byte-identical to revision 2 tested in the Windows LED case. No executable or personal host configuration is distributed.

The tool edits only placed fields through live KiCad IPC: board-space positions/angles, size/stroke, visibility/layer and custom/Datasheet/Description text. Reference and Value content cannot be renamed. Dry run is default; apply needs the current revision. Parent-footprint update is one undo commit; fresh field and protected non-field readback is required. It has no file fallback and does not expose arbitrary code execution.

**Scope:** tested on KiCad 10.0.8 and the 84-component LED board, whose footprints contain Reference, Value, Datasheet and Description. The three bundled Rust tests cover non-field preservation, forbidden renaming/size and field-only changes. They do not prove every possible field structure or board. A new executable hash/schema/project still needs relevant first-use acceptance and native saved-state checks. An MCP success alone is insufficient.

## Prepare and build

Requirements from the pinned upstream source: Rust 1.96.0, working C/C++ linker and SDK, CMake, protoc 23.4 plus protobuf includes. On Windows prefer a short **ASCII** source/toolchain/build path. Verify `link.exe`/SDK actually exist; installed Build Tools directory names alone did not prove a working MSVC installation in the local run.

```sh
python development/konnect-field-extension/prepare.py --destination /new/ascii/path/konnect-fields
# Source preparation only; then inspect source and build prerequisites.
# For a fresh destination and an already verified toolchain:
python development/konnect-field-extension/prepare.py --destination /another/new/path/konnect-fields --build
```

The preparer checks the upstream ZIP hash, target preimage hashes and module hash before applying unique source anchors. It changes package version to `0.13.0+led.fields.1`, runs the three tests when `--build` is requested, and builds a standalone **MCP server**, not a separate CAD application. It does not install Rust, modify PATH persistently, register MCP, replace an existing destination or edit a KiCad project.

Builds create `local-enrollment.review.json` with `approved_for_local_use: false`. Review license/source, executable hash, actual `get_installation_info`, KiCad version and the discovered tool schema; then explicitly enroll locally under the existing Skill policy. Do not change the distributed backend whitelist to trust arbitrary builds. Configure the server with the **actual local** KiCad CLI and IPC endpoint; never copy another workstation's socket/config. First inspect/dry-run one footprint, apply one approved change, save and independently verify geometry/full native DRC before batching. See the [runtime repair guide](../../kicad-pcb-ai-workflow/references/pcb-silkscreen-fields.md) and `konnect_capabilities.py --help` in the installed Skill.

The observed fallback build used a private portable GNU toolchain because MSVC linker/SDK files were missing. That required a matching Rust GNU **host** compiler and target libraries, GCC's Rust-distributed `libgcc_eh.a`, `MinGW Makefiles`, and `-Wno-error=incompatible-pointer-types` for old NNG with GCC 16. Unicode paths failed in GNU linker response files. These are recorded diagnostics, **not automatic global compiler/config changes or guaranteed instructions for every machine**. The public preparer uses the upstream's ordinary verified toolchain path and fails if prerequisites are unavailable.

## License

The companion Rust source is provided under **AGPL-3.0-only**, separate from the MIT Skill. `LICENSE` is included. Corresponding upstream source URL, exact commit and archive/file hashes are in `manifest.json`; `prepare.py` retrieves that source and applies this fully supplied module and registration edits. No claim is made that a source preparation/build is a native editor test or production authorization.
