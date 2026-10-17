# KiCad PCB AI 工作流

**从器件手册推荐电路出发，让 AI 按工程流程画板，用基线、机检和评审记录验收每一步。**

这是一套面向 **KiCad 9** 的 AI 辅助硬件设计 Skill：从需求、原理图、封装、叠层、布局布线，到制造文件、回板调试与 ECO。它把工作拆成 **十个阶段、六个评审门禁**，并提供一组通用脚本，帮助你检查“改了什么、依据是什么、还有什么没验证”。

作者：[Jack](https://github.com/jackwang988) · 版本 `2026.10.17-public.1` · [MIT](LICENSE) · [下载 ZIP](https://github.com/jackwang988/kicad-pcb-ai-workflow/archive/refs/heads/main.zip)

> **适合谁？**希望用 AI 辅助 KiCad 工作的硬件工程师、嵌入式开发者与电子爱好者。你仍需要提供设计需求、器件资料和可用的 KiCad 环境，并复核关键决定。它不是 KiCad 官方插件，也不是“一句话保证全自动画完任意板”的服务。

[完整流程](#完整流程十个阶段六个评审门禁) · [上手示例](#三个上手场景) · [安装](#安装与环境) · [脚本目录](docs/SCRIPTS.md) · [公开版清理记录](PRIVACY_REVIEW.md)

## 它解决什么问题

| 常见情况 | 这套工作流怎么处理 |
|---|---|
| AI 先画电路，事后才找手册 | 先核对具体型号、封装和推荐应用电路，记录偏离项 |
| 排版或分页后，原理图看起来正常却断了网 | 导出前后网表，区分严格比较与引脚连通拓扑比较 |
| DRC 总数没变，就被说成“没有新增问题” | 同时核查违规类型、对象、位置和严重度 |
| 自动布线或改铜皮后，不知道怎么退回去 | 原工程保留，转换写入新输出，再用 KiCad 验证 |
| 只给结果截图，没有交付证据 | 每阶段记录文件、命令、工具版本、检查结果与未覆盖项 |
| 把单块板子的参数套到所有设计 | 阻抗、线宽、孔径与叠层按实际器件、板厂和项目约束确定 |

## 核心依据：对照原厂推荐电路检查

原理图与封装阶段优先核对**原厂 datasheet 的推荐应用电路及对应章节**：

- 电源域、推荐工作范围、去耦及上电顺序；
- 复位、启动配置、使能、时钟与默认状态；
- 接口电平、方向、偏置及外围器件；
- 封装图、引脚编号、极性与推荐 land pattern。

报告应说明“手册要求什么、设计实际采用什么、为什么存在差异”。缺少手册或型号不清时列待确认，不能把其他型号的参数当作依据。推荐电路的适用条件仍需工程师确认，不能简单照抄而忽略供电、负载、接口与工艺差异。

## 完整流程：十个阶段、六个评审门禁

| 阶段 | 主要工作 | 阶段交付与评审 |
|---|---|---|
| **0 · 需求与器件依据** | 冻结功能、结构、电源、成本和制造约束，整理器件手册 | 需求表、器件候选与资料缺口 |
| **1 · 原理图** | 对照推荐应用电路，组织模块和跨页接口，建立网表与 ERC 基线 | **门禁① 原理图评审** |
| **2 · 封装** | 核实引脚映射、极性、尺寸、推荐焊盘与庭院 | 封装检查记录 |
| **3 · 叠层与规则** | 确定层数、参考平面、制造规则与实际阻抗约束 | **门禁② 封装/叠层评审** |
| **4 · PCB 布局** | 固定结构件，安排功能区、关键回路及密集封装扇出 | **门禁③ 布局评审** |
| **5 · 布线与覆铜** | 按关键网络及回流规划布线，核实 zone 和层对 | **门禁④ 布线评审** |
| **6 · 验证** | 重新加载、重填、比较网表与 ERC/DRC，复核图纸 | 检查结果、差异和未覆盖项 |
| **7 · 制造交付** | 导出并独立查看 Gerber、钻孔、BOM 与坐标等文件 | **门禁⑤ 制造交付评审** |
| **8 · 回板调试** | 制定限流上电、测量和功能验证清单，记录实测 | **门禁⑥ 上电/调试计划** |
| **9 · ECO 与归档** | 记录变更原因、前后版本、证据与回滚点 | 可追踪的工程与制造归档 |

完整细则见 [十阶段流程](references/workflow.md) 与 [设计检查要点](references/design-checks.md)。门禁用于确认尚未授权的设计决定，不要求重复确认已经明确授权的范围。制造下单、发送生产资料与实际硬件操作不由本仓库自动执行。

## 公开版包含什么

- Skill 入口、十阶段工作流、检查清单和详细脚本索引。
- **19 个 Python 文件**：16 个保留的通用脚本入口/模块（其中部分已重写），以及 3 个新增的诊断、保护与重填工具。
- 可直接运行的合成网表示例及自动测试。
- MIT 许可证、贡献指南、数据说明和默认忽略规则。

**与上传原包的区别：**原包有 44 个脚本。公开版排除了 28 个针对原工程或尚不满足分发条件的工具，包括固定坐标改网、按过孔尺寸删铜、批量清理布线、固定电源层分区等。原工程历史、私人路径、板卡默认文件名和实际评审案例也不公开。原包并未原样发布。

## 安装与环境

### 1. 下载整个目录

```bash
git clone https://github.com/jackwang988/kicad-pcb-ai-workflow.git
cd kicad-pcb-ai-workflow
```

也可以下载 ZIP 解压，建议把文件夹命名为 `kicad-pcb-ai-workflow`。

要作为本地 Codex Skill 使用，可将完整目录放到用户的 `~/.agents/skills/kicad-pcb-ai-workflow/`，或项目的 `.agents/skills/` 下。其他 AI 工具使用其支持的本地 Skills 目录；本次未对所有宿主做兼容性测试。参见 [官方 Skills 文档](https://learn.chatgpt.com/docs/build-skills)。

### 2. 按任务选择运行环境

| 任务 | 环境要求 |
|---|---|
| 网表 XML 对比、输出路径保护 | Python 3.10+ 标准库 |
| PDF 重排/重叠筛查、原理图路由候选 | PyMuPDF，部分工具还需 KiCad 导出的 PDF |
| PCB 检查、渲染、BOM、重填覆铜 | **能导入 `pcbnew` 的 KiCad 9 Python 环境**；渲染另需 Pillow |
| KiCad 加载、网表导出、ERC/DRC | 安装 KiCad 9，并配置 `kicad-cli` |

```bash
python -m pip install -r requirements.txt
python scripts/doctor.py --require core
python scripts/doctor.py --require pdf
```

PCB 工具要在能 `import pcbnew` 的解释器中运行，不是任意系统 Python。**不要执行 `pip install pcbnew`。**如果当前解释器缺少它，应选择 KiCad 安装提供或发行版配套的 Python；具体路径随平台与安装方式变化。

```bash
# 用你选定的 KiCad Python 运行，下面的 python 是占位解释器名
python -c "import pcbnew; print(pcbnew.Version())"
python scripts/doctor.py --require pcb
```

若 CLI 不在 PATH，可设置：

```bash
# macOS / Linux：替换为你实际找到的可执行文件
export KICAD_CLI='/path/to/kicad-cli'
```

```powershell
# Windows PowerShell：替换为实际安装路径
$env:KICAD_CLI = 'C:\path\to\kicad-cli.exe'
```

**IPC API 与 `pcbnew` 不相同。**这些离线板文件脚本不依赖“开启 IPC API”开关。KiCad 官方已标注 SWIG `pcbnew` 绑定在 9.0 起弃用，主要版本间不保证兼容；本项目以 9 为目标，不承诺未来版本无需修改。参见 [KiCad Python 说明](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/) 和 [KiCad 9 CLI](https://docs.kicad.org/9.0/en/cli/cli.html)。

## 三个上手场景

### 场景 A：先运行不需要 KiCad 的网表示例

仓库附带的 XML 是人工编写的合成测试输入，不是来自客户或真实板卡。

```bash
# 同一份网表：应返回 0
python scripts/diff_net.py examples/netlists/baseline.xml examples/netlists/baseline.xml

# 只改网名：strict 模式应返回 1；拓扑模式应返回 0
python scripts/diff_net.py examples/netlists/baseline.xml examples/netlists/renamed.xml
python scripts/diff_net.py examples/netlists/baseline.xml examples/netlists/renamed.xml --topo

# 连接改变：拓扑模式也应返回 1
python scripts/diff_net.py examples/netlists/baseline.xml examples/netlists/changed.xml --topo
```

退出码 `0=等价、1=有差异、2=输入无效`。只改网名不代表任何电路变更都可忽略；拓扑比较也不检查元件数值和封装。

### 场景 B：先检查自己的现有工程

把副本放在仓库外的工作目录，向支持该 Skill 的 AI 助手提出：

```text
用 $kicad-pcb-ai-workflow 检查我提供的 KiCad 9 工程。
先只读，不修改。确认运行环境与原厂手册是否齐全。
原理图重点对照各器件推荐应用电路；PCB 检查布局与走线规则。
每项结论附文件、位置、依据及实际命令。
输出资料缺口、已检查项、疑点和未完成检查，不要把缺工具当作通过。
```

PCB 几何筛查示例（用具备 `pcbnew` 的解释器）：

```bash
python scripts/zcheck.py /path/to/copy/board.kicad_pcb
python scripts/net_verify.py --board /path/to/copy/board.kicad_pcb SIGNAL_A
```

这些是几何/连接启发式工具，不能代替 KiCad DRC、规则求解和人工评审。更多参数见 [脚本目录](docs/SCRIPTS.md)。

### 场景 C：从需求开始做一块板

```text
用 $kicad-pcb-ai-workflow 帮我制定并执行 KiCad 9 设计流程。
我会提供需求、器件手册和结构条件。
先整理需求与待定项，对照原厂推荐应用电路设计原理图。
说明每阶段输入、产物、验证命令与回滚点。
在未授权的关键设计决定前停下；不要承诺一次自动布通或直接下单。
```

这段是任务模板，不是已完成的设计案例。层数、供电、器件与板厂规则必须由实际需求决定。

## 转换与覆铜工具的使用方式

实验性拆页/标签转换要求 `--apply` 且写到新输出。先生成副本，转换后必须重新用 KiCad 加载、导出网表并跑 ERC；这些转换未在本次环境做完整 KiCad 实测。

```bash
# 路由候选：只作用于原理图 label→wire，不是通用 PCB 自动布线器
python scripts/route_v2.py copy.kicad_sch routed.kicad_sch --pdf copy.pdf --apply

# 重填已有 zone：默认仅说明计划；--apply 才写入新文件
python scripts/refill_zones.py copy.kicad_pcb filled.kicad_pcb
python scripts/refill_zones.py copy.kicad_pcb filled.kicad_pcb --apply
```

输出已存在时会拒绝，不覆盖原文件。重填工具不创建电源分区，不证明重填后的设计符合制造或电气要求。

## 一份阶段报告应该说明什么

以下是报告结构模板，非真实工程检查结果：

| 字段 | 记录内容 |
|---|---|
| 任务与版本 | 处理范围、输入文件与版本/哈希、工具版本 |
| 修改依据 | 对应原厂手册版本、推荐电路章节、项目规则 |
| 变更清单 | 预期电气变化与非电气整理分别列出 |
| 验证记录 | 命令、退出码、报告文件及人工复核结果 |
| 待确认项 | 缺失资料、工具限制、未验证模块及下一步 |
| 回滚点 | 原文件、副本、新输出及可恢复版本 |
| 门禁决定 | 已授权范围、尚待确认的设计或交付动作 |

## 验证状态与能力边界

本仓库提供语法检查、标准库网表测试、PDF 合成输入测试和输出保护测试。本次发布环境**没有 KiCad CLI / pcbnew**，未执行真实 PCB 的加载、修改、拆页、覆铜、DRC 或制造导出端到端测试。

- 默认阈值不能当作阻抗、时序、装配或板厂能力证明。
- 正则原理图解析及几何连接检测存在格式与算法限制。
- 没有未经证实的“一次成功率”“自动布通率”或节省时间承诺。
- 实际硬件、EMC/ESD、热、信号完整性与上电需要对应工具、设备及人工验证。

```bash
python -m unittest discover -s tests -v
```

## 数据与贡献

用户工程、PDF、生产文件和报告默认由 `.gitignore` 排除，已跟踪文件仍须自行审查。脚本没有自动上传逻辑；云端 AI 的资料处理取决于平台和用户设置。

欢迎提交可公开的合成案例和版本兼容性验证。请勿上传公司/客户设计、原厂受限全文或个人凭据。

[贡献指南](CONTRIBUTING.md) · [数据与安全](SECURITY.md) · [清理记录](PRIVACY_REVIEW.md) · [第三方说明](THIRD_PARTY_NOTICES.md) · [许可证](LICENSE)
