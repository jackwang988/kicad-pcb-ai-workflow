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

## Mandatory source and task contracts

`assets/static-review.template.json` is a schema example, not a valid current engineering approval. Each approved `documents` entry needs a real, locally frozen file, SHA-256, issuer, title, revision, applicability and source approval; `authority` categories distinguish `product_spec`, `datasheet`, `manufacturer_guide`, `industry_standard`, `factory_spec`. Each task must state its `id/category/requirement/strength/level/targets/source_refs/check`, where `strength` separates mandatory constraints, recommendations and typical examples. Do not promote a typical diagram or absolute maximum rating into an unconditional design limit.

`component_sources` binds each critical device to the matching exact manufacturer, MPN, package and revision; `critical_nets` explicitly covers power/ground, bootstrap/straps/reset, clocks, differential/high-speed, RF/analog and external interfaces. `support_files` must bind BOM, stackup, library, calculations, design intent and relevant drawings as used. Schematic hierarchical sheets and imported original documents must all be included in review baselines; screenshots cannot prove invisible wires or cross-sheet connectivity.

| Check type | Deterministic scope | Insufficient for |
|---|---|---|
| `pin_net`, `same_net`, `different_nets` | Actual KiCad XML pin/net membership | Connector semantics, device behavior or crossing lines not linked by netlist |
| `component_field` | Exact value, footprint, datasheet or declared part field | Trusting similar package/MPN descriptions |
| `voltage_levels` | Explicit VOH/VOL, VIH/VIL, absolute operating boundaries | Current load, power-off injection, rise/fall, timing and fault behavior |
| `resistor_divider` | Actual 3-net circuit and worst-case *unloaded* DC ratio under tolerance | Closed-loop stability, load, leakage, transients |
| `track_geometry`, `via_count` | Named track segments/arcs, layers, width and via count | Characteristic impedance, return continuity or via-stub effects |
| `pad_distance` | Real pad-center separation | Current loop geometry/ground inductance |
| `endpoint_path` | Declared point-to-point path and supported delay model | Undeclared branches or complete channel SI analysis |
| `semantic` | AI must examine source documents, graph and real views | Python returns `AI_REQUIRED`; never silently PASS |

Manufacturer PDF text extraction (`pdftotext` where available) is only an indexed *text source*, not proof that diagrams, table layout, waveform conditions or captions have been viewed. For a scanned PDF or key manufacturer drawing, the reviewing Agent must inspect the original figures (and identify gaps when unavailable). Under the cache-first path, compare file hashes and reuse frozen device-card text rather than re-extracting every PDF or re-searching the public internet.

## G1: schematic review obligations

1. Verify the actual source versions, MPNs, packages, voltage/temperature/operating conditions, original manufacturer recommended circuits and errata; reject inappropriate reference-board assumptions.
2. View the actual KiCad-exported schematic PDF and original manufacturer diagrams; cross-check all named pins against actual exported XML. A visual line crossing is not an electrical junction, and two hierarchical labels do not prove same net without exported evidence.
3. Cover power input/output/enable/feedback and startup, clock sources and loading, reset/strap behavior, interface polarity/logic levels, termination/AC coupling/ESD, power-fault handling, analog input/feedback, thermal/exposed-pad requirements and every populated/unpopulated BOM variant as applicable. Not every product requires the same watchdog, reset or protection architecture; document applicability.
4. Distinguish real deterministic FAIL from semantic uncertainty. AI must record `additional_findings` for risks not listed in preset tasks and `NEEDS_EVIDENCE` for missing drawings, unreadable sources or untested dynamic behavior.
5. Native ERC/netlist parity + AI source-grounded reasoning + actual engineer approval are **three independent** approvals. A correct netlist does not prove visual readability or safe power behavior.

## G4: PCB review obligations

1. Read saved board and current stackup, actual footprint/pad/net geometry, tracks/arcs/vias/zones and **all copper layer views**, not a single attractive screenshot. An SVG view is not Gerber CAM inspection.
2. Trace critical channels from actual endpoints, honoring serial components and reference/return layers; check layer transitions, voids, splits, differential routing, grounding/return and application-dependent timing. If impedance or delay models are unavailable, retain `NEEDS_EVIDENCE` rather than assert SI success.
3. Check supply trunks, neck-downs, current and via/thermal limits, switching loops, feedback routes, oscillator and RF feed/antenna clearances, pad-to-device return geometry and manufacturer layout requirements. Short Euclidean distance does not prove a low-inductance loop.
4. Check fab rules, outline, holes, courtyard, assembly polarity and variants, DNP and test access. Native DRC, signal-quality engineering judgment and factory CAM review remain independent.
5. Capture all required footprint, critical net and copper-layer observations with correct object identity and source location. A diagram that does not show a region is not evidence of that region's correctness.

## AI report, dispositions and engineer evidence

The running Agent must read `packet.json`, `facts.json`, `checks.json`, G1/G4 stage-specific `device-knowledge-brief.json`, relevant source citations and genuine views, then produce a separate `ai-review.json` and readable engineering report. It cannot mark itself an actual human reviewer. Per-task AI status is `PASS|FAIL|NEEDS_EVIDENCE|NOT_APPLICABLE`; retain original engineering severity and record real observations (`ref/pin/net/layer/view` or precise facts JSON pointer), applicability conditions, short verified source citations, reasoning and an executable fix/verification plan. `additional_findings` must include structured discovered issues, even when no preset task covers them. Full component, critical-net and layer `coverage` cannot be replaced with an assertion saying "all covered."

Dispositions such as `not_applicable`/`accept_deviation` need evidence, reason and binding to each current item SHA; they cannot nullify active blockers or missing sources. A human `engineer-review.json` binds real reviewer, date, scope, decision and packet/AI SHA hashes; no AI-generated signature or manufactured test result. The gate checks this binding and current files but cannot authenticate a person or guarantee the reasoning is technically correct. `APPROVED_STATIC` is *static review only*; it does not authorize production. Changes to files or source applicability invalidate affected review evidence. A PCB copper edit does not necessarily invalidate unchanged schematic knowledge, but it invalidates affected PCB G4 and later manufacturing files.

```bash
python scripts/static_review.py /project --config /project/static-review.json --stage schematic --output-dir /project/03_REPORTS/G1-r1
python scripts/static_review_gate.py /project --packet /project/03_REPORTS/G1-r1 --ai-review /project/03_REPORTS/G1-r1/ai-review.json
# After a real engineer review, supply an actual engineer-review.json for the same packet:
python scripts/static_review_gate.py /project --packet /project/03_REPORTS/G1-r1 --ai-review /project/03_REPORTS/G1-r1/ai-review.json --engineer-review /project/03_REPORTS/G1-r1/engineer-review.json
python scripts/static_review.py /project --config /project/static-review.json --stage pcb --output-dir /project/03_REPORTS/G4-r1
```

A successful `prepare` only proves packet creation; without an independently valid current KiCad CLI/netlist/Drc evidence it is a *preview*, not an approved board. The gate can refuse missing ERC/DRC, unchanged/bad evidence, AI-only approval or an out-of-date human review. Product performance, thermal, EMC, eyes/USB compliance, simulation and prototype tests still require external actual evidence. Under R10, Konnect is the single live EDA writer; optional legacy pcbnew is limited to independently isolated read-only compatibility, not an automatic save/fill fallback.
