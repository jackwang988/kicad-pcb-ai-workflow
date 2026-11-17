# Project Library Resources and File Integrity

Prefer verified official KiCad symbols and footprints where suitable. For external parts, check actual origin/license, manufacturer's recommended land pattern, exact MPN/package, version and applicability before project use. Keep exact symbol/footprint files and 3D models accessible under known, safely resolved project paths; avoid external scripts or unknown shell commands supplied by a component library.

A resource lock should bind each approved library file and relevant project-relative path by SHA-256. `resource_guard.py lock` creates new explicit locks; `check` verifies current files against them and can consume the G2 project source cards through `--review-config`. Any missing, symlink-escaped or changed file blocks dependent review. Pin-to-pad electrical correctness, EP, polarity, NC pins and real assembly variant require separate manufacturer-source and engineer validation.

When synchronizing schematic to PCB, preserve UUIDs, physical pad net mapping, protected layout and native design rules. Resource hash consistency cannot bypass G1/G2, actual netlist parity, native ERC/DRC or final manufacturing sign-off. See [G2 module](module-resources.md) and [device source](device-knowledge.md).
