# KiCad PCB AI Skill R10.0.0 — stable software release (2026-11-18)

## 2026-11-18 · PR #10 正式验收补记（main 更新，不修改既有 R10.0.0 标签）

- **合并结果**：[PR #10](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/10) 已合并至 `main`，合并提交 [`86b363f4408af9b5cbd9a9eb7a972f9f65739555`](https://github.com/jackwang988/kicad-pcb-ai-workflow/commit/86b363f4408af9b5cbd9a9eb7a972f9f65739555)。
- **维护者验收**：2026-11-18 维护者确认本次 Skill 验证通过并明确批准合并、计入 R10 正式验收；作为 **R10 维护者验收 PASS** 记录。
- **工程流程**：非 GND 走线和回导审核 → 首次 GND 分层铺铜 → 检查孤岛、焊盘和跨层回流 → 有需要才添加经批准的地孔 → 二次铺铜保存重载 → SHA 绑定的 `pcb.ground_plane_audit` → 原生全板 DRC/未连接检查 → G4 工程师审核。不允许将铺铜前的 GND 飞线当成最终 DRC 故障。
- **软件 CI**：[2026-11-18 PR #10 软件回归 PASS](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44321219956)。
- **独立原生互操作 CI 已修复并 PASS_NOT_G4**：[PR #12](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/12) 修复 KiCad 10 名称式网络、默认空白属性、掩膜层排序及小数表示的读回误报；[原生测试 #44331681459](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44331681459) 证明真实 KiCad 10.0.8 / Freerouting 2.5.0 路由回导、F.Cu/B.Cu 首次铺铜、批准 GND 缝合过孔、再次铺铜、保存校验、原生 DRC **全链路执行通过**。合成板最终 DRC 仍有 **13 项违规、3 项未连接**，不可据此称 G4 或量产审批通过。
- **发布标签边界**：已有的 `R10.0.0` Tag / Release 对应 PR #10/#12 合并之前的源码快照；它**不自动包含本次 `main` 的补丁**。禁止直接改写历史标签/复用旧 ZIP；若要重新发布，须在 CI 通过后单独发布新版本与 SHA-256。

详细验收口径见 [R10 验收矩阵](docs/r10/05-release-readiness.md)、[GND 先铺铜再 DRC 工程规范](kicad-pcb-ai-workflow/references/gnd-before-drc.md)。

---



**Release scope:** Stable release of the R10 Skill *software source and validated orchestration contracts*. It does **not** certify a given PCB layout as routable, electrically correct, G4 approved, manufacturable or factory-released. Freerouting is used only on explicitly approved ordinary NetClasses and only within protected, isolated candidate workflow; GND and critical nets remain protected.

## What's new since R9.4 / R10 RC1

- PR [#6](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/6): one authoritative working KiCad project, immutable checkpoints, source-bound workspace status, compact context without skipping checks, English modular Skill, schematic topology-first constraints and review.
- PR [#7](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/7): real-net inventory and rules-first routing, critical nets before ordinary nets, bounded Freerouting 2.5.0 DSN→SES candidate, native import/save/reload, protected copper audit, limited repair, GND fills then independent full KiCad DRC/G4.
- PR [#9](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/9): hardened actual DSN net-to-NetClass membership verification, hash-bound independent native `net_to_class` map mandatory for autoexecution; fixed headless KiCad native test to restore `.kicad_pro` classes into exported board; disabled Freerouting 2.5.0 SMD fanout and optimizer on the protected ordinary-net pass to prevent their addition of GND tracks.

[Mandatory GND first-fill/stitch/refill/full-DRC sequence](kicad-pcb-ai-workflow/references/gnd-before-drc.md) now has a real native two-layer integration test; verify its separate GitHub Actions result before asserting success.

## Seven-stage constrained routing

1. Extract actual native networks, pad endpoints, class/current/priority/critical attributes.
2. Set and read back real manufacturer-approved stackup and NetClasses, widths, clearances, layers, vias and local approved neckdown rules.
3. Route critical/high-speed/power networks with qualified Konnect/KiCad and lock/read back their copper.
4. Generate a reviewed, hash-bound DSN and NetClass map; run **Freerouting v2.5.0** on eligible ordinary nets only, excluding GND/protected classes, disabling fanout and optimizer. Produced SES is a candidate, not copper approval.
5. Import only in isolated project via approved KiCad/Konnect, save/reload and audit net, footprint and copper deltas against source hashes.
6. Perform only bounded, explicitly authorized repair without violating rules.
7. Fill real GND zones, verify return connectivity and run full native KiCad DRC including unconnected items, then G4 design/engineer review.

**G3 is layout-only and does not require all nets connected. Full native DRC/G4 is after routing and actual zone refill.**

## Actual verification evidence and remaining limits

| Tier | Evidence | Result |
|---|---|---|
| R10 corrected software regressions | [PR #9 software Actions](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44295612517) | PASS (branch software contracts) |
| KiCad→Freerouting→SES→KiCad actual native roundtrip | [Native Actions](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44295612537) | **PASS_NOT_G4**: KiCad 10.0.8, pinned Freerouting 2.5.0, 8 +3V3 tracks imported, **0 added GND tracks**, saved/reloaded |
| Independent native KiCad DRC on that synthetic test fixture | Same native Actions | **historical pre-GND-fill route-only fixture** reported 9 violations / 2 unconnected, not a valid final-G4 verdict; route fixture now defers full DRC until an independent actual GND zone/stitch/refill gate. This is **NOT** manufacturing approval |
| Windows/Konnect machine operation | Maintainer reported local acceptance | User-reported; independent Windows GUI capture not in this repository evidence |
| 2/4-layer mixed high-speed, RF and power production cases | Not fully represented by the minimal isolated native fixture | Still must validate each real board; not blanket production approval |
| Factory CAM/EQ/physical prototype | External process | Not performed by this Skill |

**Release automation:** [R10.0.0 stable workflow](.github/workflows/release-r10-stable.yml) must re-run complete software and native roundtrip checks on the exact `main` commit before creating the tag and packaging. This page is not evidence a GitHub Release already exists. Check [Releases](https://github.com/jackwang988/kicad-pcb-ai-workflow/releases) for the published `R10.0.0` tag and the exact ZIP/SHA-256 assets.

## Installation, compatibility and risk controls

- Stable package (only after actual successful workflow): `kicad-pcb-ai-workflow-R10.0.0.zip` and `SHA256SUMS-R10.0.0`. Install the inner `kicad-pcb-ai-workflow/` Skill directory; do not overlay old scripts.
- For working from source, use [main Skill directory](kicad-pcb-ai-workflow/) with [README](README.md). R10 RC1 ZIP does not contain the new seven-stage fix; keep historical releases untouched.
- KiCad 10.0.8 was tested in Linux native CI. Newer KiCad 10.x, KiCad 9 and 11+ require version-specific feature acceptance; cannot assume automatic parity.
- Konnect is a separate MCP/backend; real KiCad write/import/save/zone-fill capabilities require verification per environment. Freerouting 2.5.0 JAR and Java 25 must be independently installed/verified.
- `freerouting_adapter.py --apply` requires exact DSN hash, full effective DSN class membership, independent native `net_to_class` map plus its SHA-256, exclusion NetClasses and pinned router. If the exported GND class is merely declared but GND belongs to `kicad_default`, the route is **BLOCKED**.
- The external router cannot be assumed to enforce full KiCad custom DRC, impedance, differential length, power/thermal or every clearance rule. Native route import, board readback, G4 and engineer acceptance remain compulsory. GND default policy is via/zone return rather than ordinary trace routing.
- Gerber/BOM/CPL/Excellon output is a controlled manufacturing **candidate** with state `EXPORTED_NOT_RELEASED` until separate CAM/EQ and signoff.

[Latest R10 architecture and full 16-node diagrams](docs/r10/06-current-skill-full-flow.md) · [Seven-stage engineering contract](kicad-pcb-ai-workflow/references/freerouting-seven-stage.md) · [Release readiness](docs/r10/05-release-readiness.md) · [GND exclusion blocker history](https://github.com/jackwang988/kicad-pcb-ai-workflow/issues/8)
