# KiCad PCB AI Skill R10.0.2 — case-verified maintenance release

R10.0.1 is preserved. This patch records the Windows/KiCad 10.0.8 single-copper LED CAD/export case, adds reusable placed-field and engineering-export guidance, and publishes a separate reproducible **source-only AGPL companion** for the missing field MCP capability.

## Verified evidence

- Windows software regressions exposed two existing portability bugs: containment compared an unresolved 8.3 root to a resolved long path; immutable fab-rule receipts hashed LF text but wrote CRLF bytes. R10.0.2 canonicalizes both containment operands and writes the exact hashed UTF-8/LF payload. Escape/tamper gates remain enforced. One path-argument test now compares canonical identity rather than raw alias spelling. Runtime files have explicit LF checkout rules to preserve manifest digests across operating systems.
- The Skill description contained an unquoted YAML colon. It is now quoted, verified with the Skill validator, and the release packager rejects this previously missed malformed metadata case. Symlink tests report an explicit skip only for Windows error 1314 (host lacks creation privilege); other errors still fail, and capable CI exercises the real symlink gates.

- One 60×60 mm / 8×8 red 2835 design: native ERC/DRC 0 errors, 0 warnings, 0 unconnected; 84 references, 66 independently checked net partitions, 168 pads, 205 tracks, no vias, one filled GND zone.
- 135 silk/mask collisions, 64 silk overlaps and 80 footprint/symbol-field warnings resolved through MCP. All 84 references remained visible; 376 field values were checked; physical placement/copper/rules/exclusions were preserved.
- Actual Gerber/BOM engineering exports: explicit top-only layers, 60 mm closed profile centerline, purchasing BOM 64 LED + 16 R, four integral pad pairs separately identified. Native two-logical-layer job metadata and empty drill files were kept outside the single-copper fabrication ZIP.
- A new native CLI regression rechecks the published saved design and exports on an independent copy. The release workflow also retains the existing software suites and pinned KiCad/Freerouting interoperability tests. Each result retains its own scope.

## Required dependency and limits

Stock Konnect 0.13.0/official 0.14.1 does not expose the placed-field editing used here. The optional companion is pinned to the **open** 0.13.0 source; its Rust module is exactly the one tested locally. The source preparer verifies archive/file hashes and can build with an already configured toolchain. No binary, compiler, IPC socket, credentials or automatic backend replacement is shipped. New builds require explicit local enrollment and relevant native first-use checks. The minimal Skill ZIP does not make official 0.14.1 support this feature automatically.

This is a scoped software maintenance release with one native CAD case, not universal full-flow certification. The saved-case regression is not an all-operation live MCP replay. Formal freeze handoff/G1–G4 signatures, CPL delivery, this LED board's Freerouting route, multi-board/multilayer/high-speed/thermal generality, factory CAM/EQ and real electrical/brightness/thermal measurements remain separate or unverified. Resistors still have specification-only sourcing. Engineering files remain `EXPORTED_NOT_RELEASED`.

## Share/install

Verify every release asset against `SHA256SUMS-R10.0.2`. Install the inner `kicad-pcb-ai-workflow` directory from the Skill ZIP, retaining a rollback copy. The separate validation ZIP contains the saved native case, evidence, verifier and source-only MCP companion; extract it beside the Skill directory or use the full repository. Existing host configuration and backend selection are not changed by installation.

See [the full case account](docs/r10/07-led-e2e-and-silkscreen.md) for failures, successful repairs and exact boundaries. Release assets are created from the checked main commit only after the required software/native checks pass; provenance binds the commit, run and asset hashes. No existing tag/asset is overwritten.
