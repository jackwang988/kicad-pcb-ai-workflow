# KiCad PCB AI Skill R10.0.1

This patch packages the current R10 source including PR #10's GND-first-fill / approved-stitch / refill sequence and PR #12's KiCad 10 saved-geometry normalization fixes. The historical R10.0.0 ZIP predates those changes and is preserved unchanged.

## Included fixes

- Ground connectivity is evaluated after actual GND fill; approved stitching, when needed, is followed by refill, save/readback and complete native DRC.
- KiCad 10 name-based nets, default empty properties, mask-layer ordering and equivalent decimal representations are normalized without accepting unknown or conflicting nets.
- Release packaging validates the runtime tool manifest, checks every ZIP member against the exact checked-out source, and publishes source-commit / workflow-run provenance alongside SHA-256.

## Release verification and limits

The release workflow runs both complete software suites on the exact main commit and reruns actual KiCad 10.0.8 / pinned Freerouting 2.5.0 DSN -> SES -> native KiCad import/save/readback plus the ground first-fill/stitch/refill interoperability test. The GitHub Release is created only after these checks succeed.

Native fixture success means PASS_NOT_G4. The existing ground fixture has 13 DRC violations and 3 unconnected items; it is not a DRC-clean product or manufacturing approval. Windows/Konnect local operation and real-board electrical/thermal verification remain separate evidence. The requested 60 mm 8x8 single-sided LED board is a subsequent project test and is not claimed as verified by this release.

## Installation

Verify kicad-pcb-ai-workflow-R10.0.1.zip using SHA256SUMS-R10.0.1, then install the inner kicad-pcb-ai-workflow directory with a recoverable backup of the previous installation. Konnect, KiCad, Java and Freerouting are separate dependencies; no backend or host configuration is replaced by this Skill package.

Assets: Skill ZIP, SHA-256 checksum, and release-provenance-R10.0.1.json identifying the exact source commit and run. Existing tags/assets are never overwritten.
