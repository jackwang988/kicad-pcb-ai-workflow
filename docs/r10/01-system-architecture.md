# R10 · 系统总体架构

[返回R10导航](README.md) · [16节点](02-16-node-workflow.md) · [验收状态](05-release-readiness.md)

```mermaid
flowchart TB
  U["用户：需求 / KiCad工程"] --> AI["AI：工程决策与流程调度<br/>SKILL.md + workflow.py"]
  AI --> P["项目契约 / JSON约束 / 16节点 / G1–G4"]
  AI <--> KB[("器件知识库<br/>MPN + Package + 来源/版本")]
  AI <--> AB[("工具能力验收库<br/>Konnect版本 + 工具schema + 范围")]
  P --> PY["Python：算法 / 规则审计 / 证据管理"]
  P --> M["Konnect MCP：活动EDA唯一写入通道"]
  KB --> PY
  AB --> M
  PY -->|"计划与约束"| M
  M -->|"编辑独立候选"| CAD[("KiCad原理图/PCB工程")]
  CAD -->|"保存后的原生文件"| CLI["KiCad CLI：ERC / DRC / 网表 / 导出检查"]
  CAD -->|"只读快照"| PY
  PY --> G{"工程门禁与工程师确认"}
  CLI --> G
  G -->|"通过"| R["设计资料准备好<br/>待工程师/工厂进一步审核"]
  G -->|"失败"| X["BLOCKED：证据补齐 / 修复 / 重新验证"]
  X --> AI
  classDef plan fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
  classDef cache fill:#dcfce7,stroke:#16a34a,color:#14532d
  classDef write fill:#f3e8ff,stroke:#9333ea,color:#581c87
  classDef gate fill:#ffedd5,stroke:#ea580c,color:#9a3412
  class AI,P,PY plan
  class KB,AB cache
  class M,CAD write
  class CLI,G,R gate
```

## 四种职责不能混淆

| 主体 | 工作 | 不负责 |
|---|---|---|
| AI | 阅读需求、选择方案、解释风险、编排已登记的操作 | 伪造实验数据或自行替工程师批准 |
| Python | 知识卡索引、规则计算、布局/布线候选、哈希/证据审计 | 默认直接修改活动中的KiCad文件 |
| Konnect MCP | 动态发现工具、受控执行实时EDA写入、保存/回读 | 未验收就假定复杂任务一定可靠 |
| KiCad原生CLI | ERC/DRC、网表、制造文件和原生工程检查 | 代替信号/电源完整性工程判断 |

## 一份工程一个写入者

任何时候只授权一个活动EDA写入后端。旧 `pcbnew` 部分只读适配仍可能存在于迁移版里；只有完成等价验证，才可移除。离线冻结步骤需要先保存、交接、独立候选、原生复验；不能让GUI、MCP和其他脚本同时写同一个工程。

原厂知识卡和工具能力记录**可以跨项目复用**；所有项目中的**真实修改结果必须逐次验证**。
