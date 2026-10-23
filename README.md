# KiCad PCB AI 工作流 · R9.3

**从器件原厂手册的推荐电路出发，让 AI 按工程流程设计与评审，用 KiCad 检查、版本证据和工程师确认推进每一步。**

这是一套面向 **KiCad 10.0.7** 的电子设计 Skill，覆盖需求、系统架构、器件资料、原理图、封装、叠层、PCB布局布线、DFX/NPI、制造交付与ECO。日常操作分成 **6组入口**，完整流程展开为 **16个节点、G1–G6六道工程门禁**。

作者：[Jack](https://github.com/jackwang988) · 版本 **R9.3** · [MIT](LICENSE)

👉 [下载 R9.3 Skill 安装包](https://github.com/jackwang988/kicad-pcb-ai-workflow/raw/refs/heads/main/dist/kicad-pcb-ai-workflow-R9.3.zip) · [SHA-256校验](dist/SHA256SUMS) · [完整流程](kicad-pcb-ai-workflow/references/full-workflow.md) · [安装与配置教程](kicad-pcb-ai-workflow/references/environment-onboarding.md) · [更新记录](RELEASE_NOTES.md)

适合希望用AI辅助KiCad开发的硬件工程师、嵌入式开发者与电子爱好者。你需要提供真实需求、器件资料、工程与制造条件；关键电气判断和生产放行仍由工程师、工厂及实际验证共同完成。

## 重点：对照原厂推荐电路进行设计与检查

原理图评审会结合实际网络连接和图纸，逐项核对对应型号、封装及应用条件下的原厂资料：

- 电源域、推荐工作范围、去耦、反馈与上电顺序。
- 复位、启动配置、使能、时钟和未使用引脚处理。
- 接口电平、方向、偏置、终端、保护及外围器件。
- 封装尺寸、引脚编号、极性、裸露焊盘及推荐land pattern。
- 跨模块电平、供电、复位、时钟、启动及故障行为。

每项结论应说明“依据哪份资料、哪一节、实际连接是什么、是否适用、如何修复和复验”。资料缺失或型号不清时列为待补证据，不能套用其他型号参数。

资料阶段先检查已有缓存，缺少时补齐原厂datasheet、设计指南及勘误。资料卡保留来源、版本、适用条件与原文定位；复用前检查当前版本并冻结项目依据，评审时仍须实际查看相关原文和图表。

## 原理图、PCB怎样衔接

| 设计要求 | 在原理图/项目阶段记录 | 到PCB后核对 |
|---|---|---|
| 系统架构 | 架构首页、功能模块、分层方案、跨模块接口与完整引脚端点 | 实际层级、模块归属和网络是否符合契约 |
| USB、MIPI等差分链路 | P/N、协议/PHY、端点、串联器件分段及目标规则 | 原生更新PCB后核对实际NetClass归属、规则覆盖和支持范围内的路径 |
| 电源 | 持续/峰值电流、压降、铜厚、温升和批准的导体几何 | 实际线宽、过孔、颈缩、供电与返回路径；复杂电流分布另行评估 |
| RF | 频率、功率、馈线参考地、匹配网络和天线净空 | 馈线参考平面和天线辐射区分别核对，避免把所有RF底层一律挖空 |
| 备用方案 | 默认装配、DNP、0Ω、替代方案、互斥关系和有/无预留理由 | 焊盘与支线风险、实际BOM/CPL、所选装配变体 |
| 布局 | 模块、锚点、局部电路、准确电源/地端子与来源 | 去耦/关键回路/时钟/RF/结构/装配/测试约束，再做视觉整理 |

目标阻抗数值本身不能推出可靠线宽。W/S、参考平面和过孔方案需要真实叠层、器件要求及工程师或工厂批准。原理图到PCB的同步须由真实KiCad操作或已验证适配器完成，脚本不虚构后台同步与通用自动布线能力。

## 6组入口，16个节点

| 操作组 | 完整节点 | 核心交付与门禁 |
|---|---|---|
| 环境 | 1 环境检测与工程保护 | 目标CLI/pcbnew、库及工程资源可用；首次验证与日常记录复用 |
| 需求架构 | 2 需求与架构；3 器件资料；4 备用决策 | 量化要求、来源、电源树、接口及装配决策明确 |
| 原理图 | 5 原理图与设计意图；6 原理图评审；7 封装 | 架构首页/接口契约/候选、ERC、AI与工程师确认 **G1**；封装核对 **G2** |
| PCB | 8 叠层与规则；9 布局；10 布线覆铜；11 PCB评审 | 规则生效、布局 **G3**、最终保存状态、全部铜层及关键网络评审 **G4** |
| 制造 | 12 DFX/NPI预检；13 制造候选；14 CAM/EQ与授权 | 阻断关闭后隔离导出；实际CAM/工厂EQ/装配确认及 **G5** 放行 |
| 试产/ECO | 15 EVT/DVT/PVT；16 ECO与归档 | 真实功能/性能/环境等验收；变更影响复验与 **G6** 归档 |

机器检查、AI内容评审、工程师确认各有职责。ERC/DRC不能独立证明产品逻辑正确；AI需真实读图、网络和资料；工程师本人确认当前版本。修改工程、规则或资料后，受影响的评审证据需要重新确认。

完整输入、输出、执行者与失败回退见[系统流程](kicad-pcb-ai-workflow/references/full-workflow.md)。

## 仓库目录说明：请认准 Skill 安装目录

> **实际 Skill 安装目录：[`kicad-pcb-ai-workflow/`](kicad-pcb-ai-workflow/)**（仓库内部子目录，包含 `SKILL.md`、`scripts/`、`references/`、`assets/`）。
>
> GitHub 仓库根目录也叫 `kicad-pcb-ai-workflow`，用于存放 README、开发测试、发布包等；**不要把整个仓库根目录当作一个 Skill 安装**。两个目录同名是预期的项目组织方式，并非重复安装。

```text
kicad-pcb-ai-workflow/             # GitHub 仓库根目录（开发、文档、发布）
├── README.md
├── development/                  # 开发与测试
├── dist/                         # 发布安装包
└── kicad-pcb-ai-workflow/        # ★ Skill 安装目录：只安装这一层
    ├── SKILL.md                  # Skill 入口
    ├── scripts/
    ├── references/
    └── assets/
```

分享仓库首页链接仍然可以；让 Agent 安装时请明确指定上述子目录。仅提供仓库首页 URL 是否能自动安装，取决于 Agent/安装器是否支持发现子目录下的 `SKILL.md`。仓库目录名保持不变。

## 安装：只安装Skill目录

### 方法一：让Agent协助安装

将下面这段话交给支持本地Skills、文件与命令执行的Agent：

```text
请帮我安装这个Skill：
https://github.com/jackwang988/kicad-pcb-ai-workflow

先阅读仓库README和kicad-pcb-ai-workflow/SKILL.md。
实际Skill位于仓库的kicad-pcb-ai-workflow子目录，只安装这个目录。
检查KiCad 10.0.7、kicad-cli及匹配的pcbnew Python绑定。
告诉我实际检测结果、缺失依赖和下一步配置方法。
按预览和--apply规则操作，在新的独立目录验证工程。
```

### 方法二：下载安装包

下载上方ZIP，解压得到`kicad-pcb-ai-workflow/`，将该目录放入当前Agent支持的Skills目录并按宿主要求启用。保留`SKILL.md`、`scripts/`、`references/`、`assets/`的相对结构。

升级时使用干净的新目录，避免与旧`scripts`合并。实际项目保持原位，按路径迁移项目配置并重建快照。环境与工程师确认记录不能直接当作另一台电脑或另一版工程的通过记录。

也可克隆仓库，安装其中的同名子目录：

```bash
git clone https://github.com/jackwang988/kicad-pcb-ai-workflow.git
cd kicad-pcb-ai-workflow/kicad-pcb-ai-workflow
```

## 配置与首次运行

必需环境是目标KiCad CLI、能导入同一安装对应`pcbnew`的Python，以及具备本地文件、命令和实际读图能力的Agent。核心Python脚本使用标准库；PDF文字资料提取需要`pdftotext`。独立ngspice、供应链数据及外部SI/PI/热/EMC工具按任务选用。

不要用普通Python或Anaconda中的`pip install pcbnew`替代匹配的KiCad环境。CLI路径、解释器和库初始化方法见[详细配置教程](kicad-pcb-ai-workflow/references/environment-onboarding.md)。

下列命令在Skill目录执行，`python3`和路径都应替换为本机实际值：

```bash
# 无需先填写项目配置，直接诊断环境
python3 scripts/workflow.py run /path/project --task environment.doctor

# 预览建立主配置；确认后在同一命令添加--apply
python3 scripts/workflow.py init /path/project

# Agent根据真实需求填写workflow.json，再预览生成新配置快照
python3 scripts/workflow.py build /path/project --bundle control-r1
# 确认后添加--apply；已有输出目录拒绝覆盖

python3 scripts/workflow.py status /path/project --bundle control-r1
```

公共路径、资料、规则策略和装配变体在主配置中填写一次，生成原工具需要的配置。生成配置表示声明已展开，不能当作工程检查通过。

首次完整环境验证须使用可在KiCad打开的合法非空工程，运行`environment.setup`；之后`environment.check`每次真实探测工具，环境记录有效时跳过重复配置。更换解释器、工具、核心文件或相关路径后重新验证。

## 开始一次原理图或PCB评审

给Agent的任务可以这样写：

```text
请使用kicad-pcb-ai-workflow检查这个KiCad 10.0.7工程。
先核对规格、器件型号、原厂手册和工程输入是否齐全。
原理图按推荐电路、模块接口、电源/复位/时钟和启动逻辑逐项评审。
PCB按实际叠层、原厂布局要求、全部铜层和关键网络逐项评审。
每项结论给出实际观察、资料位置、风险等级、修复建议和验证方法。
完成AI报告后交硬件工程师本人确认当前版本。
```

准备原理图评审资料包：

```bash
python3 scripts/workflow.py run /path/project --bundle control-r1 \
  --task schematic.prepare --output-dir /path/new-sch-review
```

AI实际阅读资料包、源图纸和原文，输出逐项报告；工程师本人确认后执行`schematic.gate`。PCB独立使用`pcb.prepare`和`pcb.gate`，布局同时保留布线前与最终复核。详细字段和命令见[静态AI评审](kicad-pcb-ai-workflow/references/static-ai-review.md)与[统一入口](kicad-pcb-ai-workflow/references/universal-workflow.md)。

## 制造前如何放行

风险分为 **阻断级 / 高风险 / 中风险 / 优化建议**，每项包含位置、描述、适用依据与可落地修复建议。阻断项或必需证据未补齐时，受控路径禁止生产候选导出。

设计预检通过后，从冻结工程向新目录导出Gerber、钻孔、BOM、CPL和图纸。成功状态为`EXPORTED_NOT_RELEASED`；后续仍需独立CAM、目标工厂EQ、装配变体和授权核对，再由`npi_release`复验发布。

工程写入默认预览，只有明确`--apply`才写入新候选；只读评审可向指定的新报告目录输出。`prototype`模式用于原型诊断，不能授予生产导出或发布权限。

## 环境接通与验证状态

**维护者已确认本机KiCad CLI和pcbnew基础调用接通（2026-10-20）。** 使用者仍需在自己的电脑执行doctor和首次环境验证，确认版本、解释器、库、读图与工程资源。

当前仓库的286项软件自动化检查全部通过，覆盖输入/来源、配置、网络、路径、布局、证据失效、受控导出与发布，以及独立ZIP运行和核心库存完整性。安装包含64文件、31个有效工具和18份通用模板。

```bash
# 在仓库根目录执行；环境软件测试不要求伪装成已安装KiCad
python3 -B -m unittest discover -s development/tests -v
```

基础工具接通、软件回归和真实产品验收分别记录。真实项目仍需完成原生同步、规则命中、布局布线、覆铜/DRC、AI/本人确认、CAM/工厂EQ和样机测试。静态线宽检查不是阻抗场求解，二维图不是完整3D干涉或热分析；未覆盖项按实际任务补证据。

[能力范围](kicad-pcb-ai-workflow/references/capabilities.md) · [31个工具索引](docs/SCRIPTS.md) · [版本说明](RELEASE_NOTES.md) · [贡献指南](CONTRIBUTING.md) · [数据处理](SECURITY.md)
