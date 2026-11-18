# R10 main integration and native validation evidence — 2026-11-18

[Current full architecture and 16-node / 7-stage execution diagrams](06-current-skill-full-flow.md) · [Seven-stage routing runtime contract](../../kicad-pcb-ai-workflow/references/freerouting-seven-stage.md) · [Legacy R10 acceptance history](../../R10_RELEASE_NOTES.md)

## R10 正式验收记录（2026-11-18 · 维护者确认）

| 验收项目 | 版本 / 证据 | 结果与边界 |
|---|---|---|
| **R10 GND 铺铜阶段执行顺序** | 维护者于 2026-11-18 在对话中明确确认 Skill 验证通过；[PR #10](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/10) 合并提交 [`86b363f4408a`](https://github.com/jackwang988/kicad-pcb-ai-workflow/commit/86b363f4408af9b5cbd9a9eb7a972f9f65739555) | **维护者验收 PASS，源码已合并 main** |
| 受控 GND 流程 | P0–P3 路由 → 首次各批准地层 GND 填铜 → 连通/孤岛分析 → 必要且经批准的缝合过孔 → 再次填铜 → 保存回读 → ground audit → 全板原生 DRC → G4 | **流程规则已纳入 R10；G3 不执行最终全板 DRC** |
| 软件回归 | [PR #12 software CI #44331681880](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44331681880) | **PASS**（包含 KiCad 10 名称式网络、原生板几何规范化及拒绝冲突/未知网络测试） |
| 既有真实 Freerouting 路由验证 | [PR #10 native CI #44321220007](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44321220007)，路由子步骤 | **PASS_NOT_G4**（KiCad 10.0.8 / Freerouting 2.5.0，8 条普通网走线、0 条 GND 走线） |
| **首次 GND 填铜→批准缝合地孔→再次填铜→原生 DRC** | [PR #12](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/12) · [KiCad 10/Freerouting 2.5.0 原生 CI #44331681459](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44331681459) | **PASS_NOT_G4**：F.Cu/B.Cu 原生实际铺铜、1 颗批准 GND 地孔、二次填铜、保存回读、SHA 绑定的 ground gate 与原生 DRC 成功执行；该合成测试板 DRC 尚有 **13 项违规、3 项未连接**，不能放行制造 |
| 产品级 G4、制造审批 | 需实际 PCB 的完整覆铜后原生 DRC、未连接项、SI/PI/热与工程师批准、厂方 CAM/EQ | **未自动放行** |
| 版本分发 | 当前 main 已包含 PR #10、#12；历史 `R10.0.0` 标签早于这些变更 | **不声称旧 ZIP 已包含本次修复；要重新打包须创建新版本，勿改写历史标签** |

验收口径：这里的“R10 正式验收通过”含 **维护者对 Skill 流程的验收**与已独立通过的 **KiCad 10/Freerouting/GND 顺序互操作原生 CI**，但不代表合成样板 DRC 零违规或具体 PCB 可投产。旧版 CI 失败是 KiCad 10 名称式网络、空白属性、层排序与 `.6` 数值规范化误报，已由 [PR #12](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/12) 修复；R10 的软件/互操作/G4/量产授权证据必须分别披露。

## Acceptance status (do not combine tiers)

| Scope | Current evidence | Conclusion |
|---|---|---|
| Software runtime tool inventory, G1–G4 and seven-stage read-only audits | Current GitHub software CI [476 main + 37 R10 regression tests passed](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44287564161), plus new fixture tests | **Software contract only**; no live PCB routing certification |
| KiCad 10.0.8 native CLI + PCB load, effective rules, DRC, fill and CAM smoke | [Historical tested KiCad 10.0.8 run](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44015065144) | Previous **native toolchain subset** passed; does not demonstrate the new Freerouting workflow |
| Freerouting 2.5.0 pinned JAR, native KiCad DSN→SES→native import/save | [Fixed isolation run #44295612537](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44295612537) | **PASS_NOT_G4**: effective class GND, no newly routed GND, 8 ordinary signal tracks imported and saved. Native KiCad DRC still reports 9 violations / 2 unconnected: no G4 approval. |
| Windows KiCad/Konnect 本机验收 | 维护者于 2026-11-18 报告已在本机验收；尚无本次仓库可独立检查的现场日志 | **Maintainer-reported PASS; independent evidence pending** |
| Mixed critical/power/high-speed 2/4-layer samples, real manufacturing rule fidelity | No representative matrix of routed and independently approved native boards | **Not verified** |
| Factory CAM/EQ and prototype EVT/DVT/PVT | External engineering/factory steps | **Not performed by Skill** |

## Latest scope

The integrated main Skill source registers **54 SHA-pinned runtime Python tools**, with `routing_seven_stage.py` as a read-only plan/SES-candidate geometry audit and `freerouting_adapter.py` as a bounded external CLI candidate generator. Those code paths cannot by themselves perform native KiCad SES import, GND pour, complete DRC or engineering G4 signoff. PR #6, #7, #9, #10 and #12 have been merged into `main`. The historical `R10.0.0-rc.1` ZIP remains unchanged, and release packaging must use the merged source, not the old archive. This is a software integration milestone, not automatic production routing certification. R10.0.0 stable software publication uses separate gated [CI](../../.github/workflows/release-r10-stable.yml); verify the actual tag and published checksum before claiming a release.

## Before designating Freerouting as a production default

1. A real KiCad 10 saved project must have approved native NetClass membership and explicit GND/critical exclusions, with source+rules hashes.
2. Real Freerouting v2.5.0 must route and produce nonempty SES; the exact KiCad project must then import it, save/reload and show correct actual copper without unauthorized footprint moves or existing track loss.
3. Independent native DRC, post-fill required connectivity, return path, signal/thermal/factory constraints, plus live multi-board Konnect acceptance must pass.
4. Preserve every failure record and avoid automatic promotion if any essential capability is unavailable. **A software unit test or CI DSN/SES smoke is not proof of qualified 4-layer/high-speed PCB manufacturing.**

All manufacturer, external machine and engineering signatures remain independent.


## Regression chronology and corrected native scope — 2026-11-18

[Native run #44286105239](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44286105239) **failed** at the protected-net assertion. Actual KiCad 10.0.8 DSN export and pinned Freerouting 2.5.0 SES generation succeeded, but isolated KiCad import produced GND tracks despite `-inc GND`. The test correctly returns `BLOCKED` with `GND_AUTOROUTED_DESPITE_EXCLUSION`. The first correction restored real KiCad project NetClass membership, yet [run #44295196723](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44295196723) still imported 3 GND tracks because Freerouting fanout ran despite the excluded autorouter class. The second correction disables SMD fanout and optimizer for ordinary routing. [Run #44295612537](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44295612537) passes the genuine isolated KiCad roundtrip, importing 8 non-GND tracks with 0 GND tracks. The historical fixture reported 9 violations/2 unconnected **before any GND pour**; that result is not an appropriate final G4 verdict. The routing-only fixture no longer runs this premature DRC. A separate real KiCad native GND fill / approved via / refill / postfill DRC run is now required before claiming any GND-ready integration level. G4/production remain separate. The user's Windows/Konnect acceptance is a separate reported test tier.
