# Schematic Page Hierarchy and Visual Style

Keep functional signal flow legible. Use modular sheets based on actual system architecture (power, MCU, RF, interfaces, protection and sensors as applicable), with explicit net connectivity, hierarchical ports and label scopes. Draw actual connectivity first and choose consistent symbol orientation, signal/power flow, reference/value labels and section notes afterward. Avoid crossing through symbols, dangling/mirrored labels, overlapping text, ambiguous junctions, accidental power-pin shorts and nonfunctional ornaments.

A visually organized page is not an electrically correct circuit. Independently export and check real KiCad XML netlist/ERC, inspect page PDF and compare manufacturer recommendations and current project requirements. Verifier scripts cover only explicitly supported structural/geometry predicates; human visual inspection and G1 approval remain mandatory. Preserve original symbol UUID/net identity across authorized incremental edits and ensure the current engineering revision is correctly bound to all review evidence.

See [topology-first rules](schematic-ai-layout-rules.md) and [schematic review](static-ai-review.md).
