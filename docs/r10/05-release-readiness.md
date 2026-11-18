# R10 main integration and native validation evidence — 2026-11-18

[Current full architecture and 16-node / 7-stage execution diagrams](06-current-skill-full-flow.md) · [Seven-stage routing runtime contract](../../kicad-pcb-ai-workflow/references/freerouting-seven-stage.md) · [Legacy R10 acceptance history](../../R10_RELEASE_NOTES.md)

## Acceptance status (do not combine tiers)

| Scope | Current evidence | Conclusion |
|---|---|---|
| Software runtime tool inventory, G1–G4 and seven-stage read-only audits | Current GitHub software CI [476 main + 37 R10 regression tests passed](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44287564161), plus new fixture tests | **Software contract only**; no live PCB routing certification |
| KiCad 10.0.8 native CLI + PCB load, effective rules, DRC, fill and CAM smoke | [Historical tested KiCad 10.0.8 run](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44015065144) | Previous **native toolchain subset** passed; does not demonstrate the new Freerouting workflow |
| Freerouting 2.5.0 pinned JAR, native KiCad DSN→SES→native import/save | [Isolated interoperability action](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44286105239) | **FAILED — GND_AUTOROUTED_DESPITE_EXCLUSION**: real DSN and SES were produced, but KiCad SES import showed GND copper despite `-inc GND`; default ordinary-net routing remains BLOCKED. |
| Windows KiCad/Konnect 本机验收 | 维护者于 2026-11-18 报告已在本机验收；尚无本次仓库可独立检查的现场日志 | **Maintainer-reported PASS; independent evidence pending** |
| Mixed critical/power/high-speed 2/4-layer samples, real manufacturing rule fidelity | No representative matrix of routed and independently approved native boards | **Not verified** |
| Factory CAM/EQ and prototype EVT/DVT/PVT | External engineering/factory steps | **Not performed by Skill** |

## Latest scope

The integrated main Skill source registers **54 SHA-pinned runtime Python tools**, with `routing_seven_stage.py` as a read-only plan/SES-candidate geometry audit and `freerouting_adapter.py` as a bounded external CLI candidate generator. Those code paths cannot by themselves perform native KiCad SES import, GND pour, complete DRC or engineering G4 signoff. PR #6 and #7 have been merged into `main`. The historical `R10.0.0-rc.1` ZIP remains unchanged, and release packaging must use the merged source, not the old archive. This is an integration milestone, not automatic production routing certification.

## Before designating Freerouting as a production default

1. A real KiCad 10 saved project must have approved native NetClass membership and explicit GND/critical exclusions, with source+rules hashes.
2. Real Freerouting v2.5.0 must route and produce nonempty SES; the exact KiCad project must then import it, save/reload and show correct actual copper without unauthorized footprint moves or existing track loss.
3. Independent native DRC, post-fill required connectivity, return path, signal/thermal/factory constraints, plus live multi-board Konnect acceptance must pass.
4. Preserve every failure record and avoid automatic promotion if any essential capability is unavailable. **A software unit test or CI DSN/SES smoke is not proof of qualified 4-layer/high-speed PCB manufacturing.**

All manufacturer, external machine and engineering signatures remain independent.


## Native regression blocker discovered 2026-11-18

[Native run #44286105239](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44286105239) **failed** at the protected-net assertion. Actual KiCad 10.0.8 DSN export and pinned Freerouting 2.5.0 SES generation succeeded, but isolated KiCad import produced GND tracks despite `-inc GND`. The test correctly returns `BLOCKED` with `GND_AUTOROUTED_DESPITE_EXCLUSION`. Diagnose actual (possibly composite) NetClass membership and exclusion behavior, correct it and rerun native save/reload/protected-object audit before enabling Freerouting ordinary-net automatic routing as the default. The user's Windows/Konnect acceptance is a separate reported test tier.
