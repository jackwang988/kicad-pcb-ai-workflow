# System Architecture and Cross-Module Interface Gate

The project must explicitly describe system blocks, each source-backed power domain, interface endpoints, module ownership, expected pin-to-net graph, voltage/logic levels, clock/reset/enable direction and operating/safety assumptions. An architecture image is explanatory but is not a netlist. Every declared requirement needs a documented source and a validation task or genuine external test plan.

`system_integration.py` compares current KiCad XML netlist endpoints against the declared module boundary and source contract. Missing nets, wrong pin endpoint topology, an interface that does not actually cross the declared modules, or unknown source identity must create evidence-linked findings. Never edit the expected interface specification simply to make an erroneous schematic appear correct.

Inspect overview and hierarchy visually, verify port names and module roles, and run actual native ERC. The verifier does not design or wire the schematic and does not grant G1 approval. See [requirements module](module-requirements.md), [schematic module](module-schematic.md) and [static review](static-ai-review.md).
