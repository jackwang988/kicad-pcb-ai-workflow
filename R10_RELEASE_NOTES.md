# KiCad PCB AI Skill · R10.0.0-rc.2（2026-11-18）

> **R10 最新源码预发布；不是生产验证或硬件设计放行声明。** 本次从已合并的 `main` 构建独立安装包；若 GitHub Release 尚未实际产生，以主分支源码和构建状态为准。旧 `R10.0.0-rc.1` 安装包**不包含**本次的七阶段布线改动。R9.4历史稳定版保留。

## 合并与版本

- [PR #6](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/6)：单一 `01_WORKING` 权威工程、`CURRENT_PROJECT.json`、受控里程碑/历史保留、摘要上下文、英文模块化Skill、原理图拓扑预布局与页面几何审查。
- [PR #7](https://github.com/jackwang988/kicad-pcb-ai-workflow/pull/7)：Freerouting 2.5.0 普通网络受约束候选布线，DSN/JAR/`.rules` SHA绑定、NetClass保护、SES导入后真实板审计、无越权拆线/封装移动、有界修复、GND Zone和原生G4验证契约。
- 合并提交：`237d3b0695f03d830528efa2466724096ac4e4e8`（#6），`9e0a604d0fcf86ba06af4255a6851268648ccc5f`（#7）。文档/发布文件随后的提交单独记录。

## 当前全流程

01 环境/工作工程 → 02 需求架构 → 03 原厂器件资料卡 → 04 备用方案 → 05 先拓扑、通道、引脚空间再绘制原理图 → 06 G1/ERC → 07 G2封装 → 08 叠层/NetClass/制造规则真实应用 → 09 Konnect布局、位置回读、G3（**布局阶段不跑未完成布线的全板DRC**） → 10 七阶段布线 → 11 覆铜后原生DRC/G4 → 12 DFX/NPI → 13 冻结导出候选。14 工厂CAM/EQ、15 EVT/DVT/PVT、16 ECO归档是后续的外部人工/实体流程。

**节点10七阶段**：完整网络分类 → 规则生效及回读 → 专项布线关键网络并保护 → Freerouting仅对普通NetClass产生`.ses`候选 → 独立KiCad回导、保存重载和真实铜审核 → 有界修复 → GND Zone覆铜与全板原生DRC/G4。`-inc`排除的是NetClass而非Net名称，且不能假设路由器自动满足局部颈缩、真实阻抗、所有自定义DRC或最终45°走线。

- [最新R10系统架构及16节点/七阶段 Mermaid](docs/r10/06-current-skill-full-flow.md)
- [七阶段执行/命令/审计边界](kicad-pcb-ai-workflow/references/freerouting-seven-stage.md)
- [原厂资料/工作区/单写入约束](kicad-pcb-ai-workflow/references/latest-complete-workflow.md)
- [README安装与验收](README.md)

## 验证证据（分层，禁止合并称作“量产通过”）

| 验证项目 | 状态 / 证据 |
|---|---|
| PR #6 软件回归/包预览 | [通过](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44278478257) |
| PR #7 软件回归/包预览 | [通过](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44287952061) |
| 历史 KiCad 10.0.8 原生工具链烟测 | [通过](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44015065144)，**不涵盖此新七阶段全链** |
| Windows/Konnect 实机 | 维护者报告于2026-11-18验收通过；本次仓库无独立现场记录，范围不能自动扩大到Freerouting各种工程 |
| 新 Freerouting 2.5.0 DSN→SES→KiCad 保存回读专用CI | [独立工作流](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44286105239)，截至记录时无已确认的最终PASS，需查看最新状态 |
| 多块实际2/4层混合高速/电源/锁铜PCB、生产CAM/EQ | 没有通用制造资格认定，逐项目G1–G4和外部签核仍必须执行 |

## 安装包、兼容与保留

- 发布工作流 [publish-r10-rc2.yml](.github/workflows/publish-r10-rc2.yml) 在`main`上执行软件回归，重新从 `kicad-pcb-ai-workflow/` 生成独立ZIP及SHA-256，只有测试通过才尝试创建 **R10.0.0-rc.2 GitHub Pre-release**。绝不把旧RC1 ZIP重命名为新版本。
- [GitHub Release 页面](https://github.com/jackwang988/kicad-pcb-ai-workflow/releases)可核对新资产是否真正发布。发布成功后应下载 `kicad-pcb-ai-workflow-R10.0.0-rc.2.zip`，按配套 `SHA256SUMS-R10.0.0-rc.2` 验证，而非从旧RC1压缩包安装。
- 也可直接从`main`的 [Skill子目录](kicad-pcb-ai-workflow/) 获取最新源文件。不要把仓库根目录当作Skill安装；旧目录不要与新脚本混合。
- KiCad 10.0.7是历史推荐基线，10.0.8有历史原生工具链烟测，其他版本按当前项目检测兼容能力。Freerouting CLI依赖真实2.5.0 JAR/Java与受控NetClass；Konnect为独立MCP服务，不包含在Skill包内。

## 安全与交付边界

**生成SES不等于KiCad铜线已导入；DRC为零不等于高速SI/PI、温升、PCB机械、工厂CAM或样机通过。** 本Skill不代替工程师签核、工厂EQ、产品真实测量。成功导出 Gerber/钻孔/BOM/CPL 时仍为 `EXPORTED_NOT_RELEASED`，不得自行升级成量产授权。