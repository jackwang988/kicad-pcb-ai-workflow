# Independent G1 Schematic and G4 PCB AI Review

## Responsibilities and evidence

`static_review.py` creates a *new, immutable evidence packet* from the current saved project. It includes native netlist/exports when available, existing document/source hashes, project inputs, selected PDF/text evidence, review tasks, parsed checks and visual views. It does not silently edit the schematic or PCB. The model reads the current task packet, cited source sections and actual network/geometry, then writes an explicit `ai-review.json` with each required task's status and findings. `static_review_gate.py` checks packet integrity, native readiness, risks, AI report, project revision and actual engineer review. AI may never approve itself.

`AI_REQUIRED`, missing facts, unsupported native outputs or inconsistent source versions are *not* PASS. The gate must process the **complete** original packet and evidence even if the model initially sees only a small bounded summary. All additional discovered issues must be recorded in structured `additional_findings`, not only in narrative prose. Engineer approval binds the exact packet and current project hashes.

## G1 review procedure

1. Confirm current schematic `.kicad_sch/.kicad_pro`, project source bundle, requirements, actual KiCad export and ERC. An independently provided XML preview is not equivalent to native current netlist export.
2. Read `packet.json` and `device_knowledge_brief` first; select power, startup, clock, reset, boot, interfaces and recommended circuits matching actual MPN, package and application.
3. Examine current pin-to-net facts, supply tree, unused/NC pins, reference voltages, divider/tolerance and current-path calculations. Compare each relevant requirement to the original manufacturer's cited document locator; consult figures/footnotes where necessary.
4. Read actual schematic pages/visual exports. Inspect hierarchy, off-page labels, junctions, wiring ambiguity, symbol value/designator/polarity and module legibility. Native ERC cannot prove intended electrical operation.
5. Record one `PASS`, `FAIL`, `NEEDS_EVIDENCE` or applicable report value for every mandatory task, with measured actual values, source locator and exact repair/retest steps. Complete separate human engineer confirmation.

## G4 review procedure

1. Require the **saved, routed, zone-filled board** and actual schematic parity, approved stack-up/NetClasses and native DRC. Retrieve G4-specific verified cards via `project_stage_brief`.
2. Inspect every actual copper layer and relevant view. Evaluate critical signal paths, differential pairing/length budgets, vias, reference-plane crossings, RF antenna region, power/return current, filtering, decoupling, connector signals, mechanics, assembly and test access.
3. Track real UUID/reference/net/layer/coordinates; avoid reporting an unobserved net as routed, mistaking a pad-center distance for return-loop area, or inferring SI/PI/EMC from DRC alone.
4. Produce the structured AI review and the independent engineer disposition. Modified PCB geometry, rules, source card or evidence hashes invalidate the affected old G4 packet.

## Stage preparation and on-demand model context

```bash
# Always target distinct, explicit review directories; do not overwrite signed evidence.
python scripts/static_review.py /project --config /project/static-review.json --stage schematic --output-dir /project/03_REPORTS/G1-r1
python scripts/static_review.py /project --config /project/static-review.json --stage pcb --output-dir /project/03_REPORTS/G4-r1
# Show a bounded initial summary while preserving full report files.
python scripts/token_budget.py --input /project/03_REPORTS/G1-r1/checks.json --limit 6
```

The preparation stage may copy actual source files and create local PDF text for **audit retention**, not to inject all bytes into model context. Source text is reused if its SHA matches the project-frozen cache. For daily review, the model first reads the brief and actual current checks. Expand only the exact location needed to resolve a discrepancy, with full source when high-risk context requires it.

## Gate safety and current-version binding

- The original and reviewed source/board must match input hashes recorded in the packet. The native CLI environment and report schema must be accepted. An unresolved hard-risk item cannot be waived merely by a signature.
- AI review content and engineer confirmation are distinct. A specific reviewer must record the packet identity, decision, date, current problem disposition and reason. The model must not manufacture this record.
- Project variants, resource locks, reserve options, interface contracts and G3 placement are checked when configured; a missing required policy makes the packet incomplete.
- A static review is not a hardware bench, impedance field solver, thermal analysis, EMC test or factory CAM acceptance. Report unsupported claims as external tests with owners and proof requirements.

See [requirements and risk categories](engineering-rules.md), [stage approvals](stage-approvals.md) and [latest 16-node workflow](latest-complete-workflow.md).
