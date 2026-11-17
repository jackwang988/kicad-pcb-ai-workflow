---
name: kicad-pcb-ai-workflow
description: KiCad原理图与PCB工程设计、受控评审；R10知识库跨G1–G4复用、Konnect动态工具及唯一EDA写入、KiCad CLI独立复验、单一工作工程和按需摘要。
---

# KiCad PCB AI Skill R10 · 精简上下文与唯一工作区

## 所有任务都必须遵守
1. **唯一工作工程**：已有 `CURRENT_PROJECT.json` 时先执行 `workflow.py workspace ROOT --action status`。日常添加器件、连接网络、修改丝印/布局必须在 `01_WORKING/` 当前工程内增量编辑；不要为每次普通修改反复执行 `workflow init/build` 或 `schematic_candidate`。新建项目/高风险测试/里程碑/最终冻结才建立新候选。没有工作区索引的旧项目继续现有保护流程，不猜测哪个副本最新。参见 [工程目录与Token策略](references/workspace-and-token-policy.md)。
2. **工具职责**：AI决策；Python处理知识、几何算法和规则审计；Konnect MCP是唯一活动EDA写入后端；KiCad CLI独立ERC/DRC复验。不得同时由旧pcbnew、GUI与Konnect修改同一工程；MCP失败不可静默回退到未验证的写入接口。按当前机器实际发现的工具、L0–L3风险和专项能力记录执行。
3. **器件知识库优先**：节点3先按厂家＋精确MPN＋封装查共享库。有效知识卡在G1节点6、G2节点7、G3节点9、G4节点11按类别复用；只对缺失/版本变化的资料按需核原厂。资料卡不代替真实项目审核。见 [知识库](references/device-knowledge.md)。
4. **独立门禁**：原厂/制造条件缺失不猜参数；真实原理图、网表、封装、叠层和铜层各阶段独立核验。ERC/DRC、AI工程评审及工程师批准不可互相替代；哈希或输入变更使受影响证据失效。制造导出仅 `EXPORTED_NOT_RELEASED`；CAM/工厂EQ、样机/ECO在AI设计主线之外。不得删除旧项目/证据。
5. **节约上下文不牺牲安全**：当前任务只打开对应模块文档；不要重复载入整本PDF、全部16节点规则、所有Konnect工具schema或完整报告。先读 `workflow status --format compact`、知识卡 `brief`、`workflow report-brief`；如发现阻断项、特殊工况、图表和脚注，再精准展开原文和相应证据。完整证据仍保存在磁盘，工程门禁永远使用原文件。

## 按需模块
| 任务 | 推荐文档 |
|---|---|
| 连接、环境、工程目录 | [module-environment](references/module-environment.md) |
| 需求与原厂资料 | [module-requirements](references/module-requirements.md) |
| 符号封装 | [module-resources](references/module-resources.md) |
| 原理图/网络/G1 | [module-schematic](references/module-schematic.md) |
| PCB规则、布局和布线 | [module-pcb](references/module-pcb.md) |
| 仅适用时的高速/PI专题 | [module-high-speed](references/module-high-speed.md) |
| DFX/NPI与制造候选 | [module-manufacturing](references/module-manufacturing.md) |
| 外部样机/ECO | [module-lifecycle](references/module-lifecycle.md) |

只在首次调用意图时使用 `python scripts/workflow.py modules --intent schematic` 等命令选择模块，不逐次全量扫描。完整16节点和G1–G4规则见 [完整流程](references/latest-complete-workflow.md)，实机Konnect能力见 [动态验收](references/konnect-capability-migration.md)。

## 工作区示例
```text
/project/
  01_WORKING/   Project.kicad_pro / .kicad_sch / .kicad_pcb （唯一活动工程）
  02_CHECKPOINTS/    仅高风险/里程碑检查点
  03_REPORTS/        审核、ERC/DRC详细证据
  04_RELEASE/        独立冻结制造候选
  CURRENT_PROJECT.json （权威路径索引，不是工程授权）
```

```bash
# 首次应由用户或Agent先把完整工程及相对库资源整理进01_WORKING
python scripts/workflow.py workspace /project --action init --project-file 01_WORKING/Project.kicad_pro --apply
python scripts/workflow.py workspace /project --action status
# 分类历史目录，保留全部原文件
python scripts/workflow.py workspace /project --action inventory
# 重要里程碑才创建一次不可覆盖的检查点
python scripts/workflow.py workspace /project --action checkpoint --label G1-approved --apply
# 使用同一个有效的配置bundle，不因普通编辑重新init/build
python scripts/workflow.py status /project --bundle control-r1 --format compact
# 只读有界报告，失效/缺证据时打开完整原文
python scripts/workflow.py report-brief /project/03_REPORTS/G1/checks.json --limit 6
```

日常检查连接成功即止，不创建测试板、不默认截图、不自动执行全部工程检查。所有写入遵循预览和实际授权。PCB布线必须先检查工艺、网络分类、关键网，再通过已验收Konnect执行、保存重载、原生DRC、G4确认。布线算法规划、布局检查器和参数推测都不能冒充已写入、已检查或可投产。
制造预检与导出仍必须显式使用 `--mode mass_production`，该模式不会绕过NPI、工程签核或工厂授权；`--mode prototype` 只允许非量产诊断。

DFX/NPI流程细则：[制造评审规范](references/dfx-npi.md)。最终生产放行仍由 `npi_release.py` 依据真实工程证据和独立工厂授权执行，不因精简上下文而减少检查。
