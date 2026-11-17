# R10 · 芯片知识库跨项目、跨G1–G4复用

![器件知识库跨G1-G4复用图](figures/03-device-knowledge.svg)

[返回导航](README.md) · [16节点](02-16-node-workflow.md)

```mermaid
flowchart TB
  R["新项目芯片需求<br/>Manufacturer + Exact MPN + Package"] --> Q{"先查共享知识库"}
  Q -->|"已有且来源/版本/适用条件有效"| CARD["复用已审核知识卡"]
  Q -->|"缺失、过期、冲突"| SRC["节点3补齐原厂资料<br/>Datasheet / 指南 / Errata"]
  SRC --> REVIEW["提炼条目并人工核对来源"]
  REVIEW --> REGISTER[("登记知识库<br/>来源+版本+哈希+审计日期")]
  REGISTER --> CARD
  CARD --> FREEZE["冻结本项目的器件资料快照<br/>项目版本与卡片哈希"]
  FREEZE --> G1["G1：电源/时钟/启动/推荐电路"]
  FREEZE --> G2["G2：引脚映射/封装/极性/EP"]
  FREEZE --> G3["G3：去耦/晶振/RF/布局禁区"]
  FREEZE --> G4["G4：关键走线/参考层/回流"]
  G1 --> VERIFY{"针对本项目独立验证"}
  G2 --> VERIFY
  G3 --> VERIFY
  G4 --> VERIFY
  VERIFY -->|"通过"| DONE["形成当次审查证据"]
  VERIFY -->|"资料缺失/不适用"| SRC
  VERIFY -->|"项目设计不通过"| FIX["修改当前工程并复验"]
  classDef cache fill:#dcfce7,stroke:#16a34a,color:#14532d
  classDef audit fill:#ffedd5,stroke:#ea580c,color:#9a3412
  class CARD,REGISTER,FREEZE cache
  class VERIFY,FIX audit
```

## 知识卡必须有什么

- 器件身份：制造商、**精确型号（MPN）**、封装和必要的子型号。
- 原厂来源：文档名称、修订版本、获取日期、SHA-256及章节/页码定位。
- 适用条件：电源范围、接口配置、温度等级、工作模式及板层/叠层前提。
- G1：供电、EN/RESET/BOOT、时钟、推荐外围电路。
- G2：引脚编号/功能/封装、land pattern、裸焊盘与装配提示。
- G3：去耦回路、晶振/RF布局、热与结构禁区。
- G4：回流/参考层/高速规则、关键电源和差分链路约束。
- 不确定项：仅存资料无法证明的条件，标注为“待查证”，绝不补猜。

**节省Token的正确方法**：AI默认读取本节点相关的精简卡片，而不是重复全文提取PDF；当遇到复杂图表、修订冲突、特殊工况或证据不足时，仍要打开已保存的原厂原文核对。缓存命中只证明知识可用，不代表新原理图/PCB合格。
