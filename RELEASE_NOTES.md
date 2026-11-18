# R10.0.0 stable Skill software — 2026-11-18 — real protected Freerouting native roundtrip

- [R10.0.0 正式软件版说明](R10_STABLE_RELEASE_NOTES.md) · [正式 Release 和 SHA-256 核对](https://github.com/jackwang988/kicad-pcb-ai-workflow/releases) · [完整架构](docs/r10/06-current-skill-full-flow.md)。
- [PR #9](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/9) 修复 headless DSN 的有效NetClass成员校验并用独立哈希映射阻断漂移；普通网 Freerouting 2.5.0 禁用可能绕过 GND 排除的 Fanout/Optimizer 阶段。
- [真实 KiCad 10.0.8 / Freerouting 2.5.0 回导测试](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44295612537)：**PASS_NOT_G4**，8条普通走线、0新增GND；示例项目尚有9项原生DRC违规和2项未连接，**G4并未通过**。
- 稳定发行仅代表受测试软件功能与受控失败阻断逻辑，**不代表所有 PCB 可自动布通或制造授权**。发布前 [CI](.github/workflows/release-r10-stable.yml) 必须在 main 上复核测试并生成全新ZIP/SHA；旧 RC 和 R9.4 不变。

---

# R10 main source integration · 2026-11-18 · Freerouting 2.5.0 七阶段布线

- 维护者指示下，依次合并 [PR #6](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/6) 与 [PR #7](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/7) 到 `main`。工作区保护、原理图预布局、英文版模块化Skill、关键网保护、NetClass排除、Freerouting DSN/SES候选、保存板审计及G3/G4分界已纳入源码。
- [最新版 README](README.md) · [七阶段布线说明](kicad-pcb-ai-workflow/references/freerouting-seven-stage.md) · [16节点/七阶段架构图](docs/r10/06-current-skill-full-flow.md) · [更新版R10说明](R10_RELEASE_NOTES.md)。
- [PR #6 软件CI](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44278478257) 与 [PR #7 软件CI](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44287952061) 均成功。用户报告Windows/Konnect本机验收通过；新Freerouting原生往返CI与跨项目投产级验证单独计算，未得到最终PASS不得宣称。
- **原生阻断（2026-11-18）**：[Freerouting回导CI](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44286105239) 失败；真实导入后GND仍被布线，错误 `GND_AUTOROUTED_DESPITE_EXCLUSION`。R10.0.0-rc.2为预发布，不能默认开启该自动布线路径。
- 历史 `R10.0.0-rc.1` ZIP不随 `main` 的代码合并而改变；发布R10新版安装包时必须重新构建、独立测试并生成新的SHA-256。R9.4原稳定包继续保留。

---

# R10.0.0-rc.1 · 2026-11-17 · Konnect单写入与G1–G4知识库复用（预发布）

- [完整版本说明](R10_RELEASE_NOTES.md) · [安装包](dist/kicad-pcb-ai-workflow-R10.0.0-rc.1.zip) · [系统架构及5张流程图](docs/r10/README.md)
- 319项旧版回归＋33项R10测试及KiCad10.0.8原生验证通过；Konnect实时MCP端到端验收仍待完成。**R9.4稳定版继续保留。**

---

# R9.4 · 2026-11-04 · KiCad 10 向前兼容及原生验证

- **版本策略**：10.0.7继续为推荐基线，不再是安装上限；稳定KiCad 10.x逐项检测CLI和pcbnew同版本、真实项目烟雾记录及生产门禁。混合版本/开发版不可直接授权。
- **KiCad 10.0.8 真实测试**：在GitHub Actions Ubuntu 24.04上通过KiCad官方10.0 PPA实装10.0.8，验证版本匹配、原理图PDF/XML、ERC/DRC JSON、PCB读取、铜皮区域填充、保存重载、Gerber/Excellon/CPL/BOM/装配PDF等工具链操作；[测试定义](.github/workflows/native-kicad-10.0.8.yml)、[原生成功记录](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/41748194225)。
- **工程副本保护**：原生CLI可能写出`*.kicad_prl`设置文件。R9.4制造导出在独立临时工程副本上运行并核对原工程哈希；增加真实工具链检测与软件防回归测试。
- **未来KiCad 11+**：提供CLI-only候选检测和受控原生报告验证通道；旧SWIG `pcbnew`未适配IPC前，PCB原生写入及制造放行继续阻断。
- **KiCad 9**：离线工作流可用，未实际验证的原生KiCad 9 API/CLI不做兼容承诺。
- **质量保障**：GitHub Actions Python软件测试覆盖319项，发布前还需跑真实10.0.8原生测试；工具完整性SHA-256保持强制校验。
- **工程边界**：本版验证的是示例项目上的真实工具链功能，不是产品项目的原厂电路、NetClass设计值、制造CAM/DFM或工程师签核通过；所有G1–G6及NPI/工厂门禁均保留。其他操作系统和KiCad补丁需本地验证。

安装[最新R9.4 ZIP](https://github.com/jackwang988/kicad-pcb-ai-workflow/raw/refs/heads/main/dist/kicad-pcb-ai-workflow-R9.4.zip)，使用[SHA256SUMS](dist/SHA256SUMS)核对完整性。升级请在干净Skills目录重装，不叠加旧脚本。

---

# R9.3 · 2026-10-20

- 目标版本KiCad 10.0.7；维护者确认本机CLI与pcbnew基础调用已接通。
- 六组入口组织16个工程节点，保留G1–G6、原生ERC/DRC、AI与工程师确认、DFX/NPI、CAM/EQ及授权流程。
- 原厂资料检查与项目化缓存、架构首页和跨模块接口契约、差分/电源/RF设计意图、模块化布局及备用方案评审。
- 单一主配置共享路径、资料、策略与装配变体，编译为不可覆盖的新配置快照。
- 安装包64文件，包含31个有效工具和18份通用模板；核心库存强制验证完整集合、哈希及工具合同。
- 当前仓库286项软件测试全部通过，含ZIP独立运行、工具缺失/篡改、证据过期和生产阻断反例。

安装[当前ZIP](https://github.com/jackwang988/kicad-pcb-ai-workflow/raw/refs/heads/main/dist/kicad-pcb-ai-workflow-R9.3.zip)，或从仓库的kicad-pcb-ai-workflow子目录安装。升级使用干净目录，不合并旧scripts；配置与环境证据按当前版本复验。

CLI/API基础连通和软件测试不授予产品制造许可。真实产品仍需完成原生工程、工程师确认、CAM/目标工厂及实测验收。
