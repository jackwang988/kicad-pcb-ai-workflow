# Historical 16-Node Workflow Compatibility (R9)

For current R10 behavior use **[the authoritative, full 16-node engineering contract](latest-complete-workflow.md)**. This older workflow name remains as a compatibility entry point for existing links, checklists and code that expects it. Do not treat historical G5/G6 labels as requirements for the present AI design mainline.

## Stage mapping retained for compatibility

| Group | Nodes | Current control |
|---|---|---|
| Environment | 01 | Real version, project and Konnect target check |
| Requirements/architecture | 02–04 | Quantitative architecture, verified component cache, option/DNP rationale |
| Schematic | 05–07 | Topology-first schematic and native ERC; G1 review; G2 physical pin/pad resources |
| PCB | 08–11 | Stack-up/rule effectiveness; G3 placement; real routing and copper; G4 final review |
| Manufacturing | 12–14 | DFX/NPI and isolated export; factory CAM/EQ is external |
| Prototype/ECO | 15–16 | Physical prototype and revision archive are external |

**Current stop condition:** Design documents and source-linked evidence may be ready for external review. Successful Gerber export only produces `EXPORTED_NOT_RELEASED` and does not imply factory approval.

Never rewrite earlier G1–G4 or engineer signature records to make changed designs appear valid. A new design revision requires a new affected evidence packet. See [stage approvals](stage-approvals.md), [native review](static-ai-review.md) and [R10 execution policy](design-execution-local.md).
