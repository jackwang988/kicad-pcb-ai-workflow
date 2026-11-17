# KiCad Symbol, Footprint and Project Resource Integrity (G2)

Use locally trusted official KiCad libraries first. Lock exact symbol, footprint, optional 3D and project-specific library resources with hashes and source/provenance. Do not silently install an unknown vendor library. A stable file hash does not establish electrical correctness.

At G2, reuse the node 03 frozen device bundle. `resource_guard.py check --review-config` checks identity and produces the G2 knowledge-coverage brief. Independently compare current schematic pin numbers/electrical types to physical pad numbers, pin-1 orientation, exposed/thermal pad, polarity, optional/NC pins and actual manufacturer-recommended land pattern. Resolve missing pinout/footprint sources at node 03 and regenerate affected evidence. A missing or mismatched binding blocks G2; prior approval does not transfer to another project.

See [resource contracts](project-resources.md), [device knowledge](device-knowledge.md), and [schematic review](module-schematic.md).
