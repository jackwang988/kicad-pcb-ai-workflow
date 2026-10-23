# 通用运行接口 · R9.3

## 目录

- 日常入口：先用这六组
- 通用性与支持边界
- 1. 项目契约和统一入口
- 2. 原理图候选接口
- 3. 图面、布局和布线
- 4. 受控制造导出
- 5. 首次执行顺序

## 日常入口：先用这六组

| 分组 | 包含原节点 | 日常操作 |
|---|---|---|
| environment 环境 | 1 | doctor；首次setup；有效环境记录check |
| architecture 需求架构 | 2–4 | 明确需求、资料和预留；check只检查声明 |
| schematic 原理图 | 5–7 | 设计/架构首页/封装；prepare→真实AI评审→工程师确认→gate |
| pcb PCB | 8–11 | 规则/布局/布线；布局pre和final；prepare→AI逐层评审→工程师确认→gate |
| manufacturing 制造 | 12–14 | precheck→冻结候选→export→真实CAM/EQ/授权→release |
| lifecycle 试产/ECO | 15–16 | 真实样机测试、变更复验和归档；check只检查声明 |

六组可选择对话确认或正式工程签批，详细规则见 [双模式阶段确认](stage-approvals.md)。两种模式都不替代 G1–G6。

六组是操作导航，不是六个自动设计器。status不判断G1–G6通过，不隐式执行后续动作；专题设计、资料、封装、冻结和CAM操作继续用下文及对应专题接口。

### 1. 初始化一个主配置

下列命令在Skill目录执行；python3应替换为目标KiCad匹配的Python。项目目录已存在；所有路径示例须换成真实路径。

```bash
python3 scripts/workflow.py run /path/project --task environment.doctor
# doctor不需要主配置/快照，便于先诊断安装；其余项目任务需要快照
python3 scripts/workflow.py init /path/project
python3 scripts/workflow.py init /path/project --apply
```

第一条只预览；第二条新建workflow.json，已有文件拒绝覆盖。主配置的shared保存公共工程路径、完整原文资料清单、装配variant、设计意图、资料包、系统接口/图面/备用/布局策略和工程规格文件路径。configs.flow记录需求、适用性、验证映射和阶段输入；configs.static记录两阶段评审任务；configs.npi记录工艺和交付证据。实际专题策略仍在独立文件中，主配置只引用一次，不把全部规则强塞进一个大表。

共用值用`{"$ref":"/shared/inputs/board"}`这样的本地JSON指针，生成配置路径用`{"$config":"static"}`。需求verification中的静态task配置可以写`"config":{"$config":"static"}`；task仍需真实requirement_id绑定。禁止网络引用、表达式或循环引用。不猜工艺/电流/阻抗阈值，不预填PASS、N/A、人员签核或装配变体。阶段executor/method只有通用待办默认文字，应按实际执行者/适配器完善，绝不代表已经执行。

AI应根据用户需求帮助填写；用户主要确认规格、架构和工程决策。新手不应手工修改编译后的三个JSON。不适用功能在features填写理由和实际来源，再在原评审中按其规则判定；不能通过删除必需类别、接口门禁或签核来省步骤。未到阶段的PCB/制造文件可保持待办，不能用空文件占位。

### 2. 生成不可覆盖的配置快照

```bash
python3 scripts/workflow.py build /path/project --bundle control-r1
python3 scripts/workflow.py build /path/project --bundle control-r1 --apply
python3 scripts/workflow.py status /path/project --bundle control-r1
python3 scripts/workflow.py status /path/project --bundle control-r1 --format json
```

control-r1必须是项目内部、父目录已存在的新目录；写入flow.json、static.json、npi.json和绑定清单。编译只展开明确引用并检查一致性，不证明模板中未填写的工程值有效。status默认简短待办，JSON可看全部缺项。状态NEEDS_INPUT退出2表示仍有待办；可先处理环境/需求，不表示必须先造出未来PCB。已声明输入齐备同样不等于任何门禁通过。

主配置、工具清单或生成文件变化后，旧快照拒绝运行。修改主配置后创建control-r2等新目录，并为变化影响的评审重新生成资料包、AI评审和本人确认。原签核不能复制到新快照充当通过。资料原文和工程改变也仍由原脚本的哈希/基线门禁检测。

### 3. 用固定任务执行，先plan可预览

```bash
python3 scripts/workflow.py run /path/project --bundle control-r1 --task environment.doctor
python3 scripts/workflow.py run /path/project --bundle control-r1 --task environment.setup --output-dir /path/new-environment-report
# setup预览确认后，加--apply；完成后使用实际startup-state.json
python3 scripts/workflow.py run /path/project --bundle control-r1 --task environment.check --state /path/new-environment-report/startup-state.json
python3 scripts/workflow.py run /path/project --bundle control-r1 --task architecture.check
python3 scripts/workflow.py run /path/project --bundle control-r1 --task schematic.prepare --output-dir /path/new-sch-review
# Agent实际读资料和图，输出AI评审；工程师本人确认后：
python3 scripts/workflow.py run /path/project --bundle control-r1 --task schematic.gate --packet /path/new-sch-review --ai-review /path/ai-review.json --engineer-review /path/engineer-review.json
python3 scripts/workflow.py run /path/project --bundle control-r1 --task pcb.rules_pre
python3 scripts/workflow.py run /path/project --bundle control-r1 --task pcb.placement_pre --netlist /path/current.xml --output-dir /path/new-pre-layout
# 实际布线、覆铜、保存和重载后：
python3 scripts/workflow.py run /path/project --bundle control-r1 --task pcb.placement_final --netlist /path/current.xml --output-dir /path/new-final-layout
python3 scripts/workflow.py run /path/project --bundle control-r1 --task pcb.rules_final
python3 scripts/workflow.py run /path/project --bundle control-r1 --task pcb.prepare --output-dir /path/new-pcb-review
# PCB独立AI/工程师评审后，用pcb.gate，参数同schematic.gate
python3 scripts/workflow.py run /path/project --bundle control-r1 --task manufacturing.precheck --output-dir /path/new-npi
```

netlist、packet、AI报告和工程师报告路径遵循原专题工具的本地路径规则；示例中的/path代表真实绝对位置，不能照搬。prepare/gate可使用独立报告目录；接入NPI前，按static-ai-review.md将完整资料包及两份真实报告纳入工程内独立证据目录，保持内容/哈希不变，并把工程相对路径写入主配置configs.npi.static_ai_reviews。不得用示例文件充当真实确认。创建新配置快照后继续；原门禁根据工程/策略/评审内容判断是否仍有效，改了评审配置则需重新评审。冻结项目副本后，在副本重新构建快照，核对路径与冻结证据：

```bash
python3 scripts/workflow.py plan /path/frozen-project --bundle control-r2 --task manufacturing.export --destination /path/new-candidate
python3 scripts/workflow.py run /path/frozen-project --bundle control-r2 --task manufacturing.export --destination /path/new-candidate
# 上条仅预览；显式加--apply才请求真实导出，原门禁仍须通过
python3 scripts/workflow.py run /path/frozen-project --bundle control-r2 --task manufacturing.release --candidate-dir /path/new-candidate --destination /path/new-release
# 实际CAM、工厂EQ及授权完成后，显式--apply才请求发布
```

plan只列出命令，不运行。run原样传播子工具退出码/结果，不把退出0转换成工程通过；environment.setup、export和release默认沿用原工具预览，只有显式--apply写新目录。其他只读检查可生成指定新报告，无需--apply。mass_production是NPI默认；`manufacturing.precheck --mode prototype`保留原型诊断，export/release拒绝prototype。

### 4. 兼容与减少重复的边界

已有R9.1项目可以继续使用原配置和原命令，无强制迁移。若迁移，将原配置内容放入主配置configs的对应位置，公共值改为shared引用；生成后比较内容并重新确认受影响评审。不会自动覆盖原配置或宣称旧签核已迁移有效。

本轮减少公共字段复制、固定阶段执行说明和命令参数查找。专业任务、独立AI/工程师确认、原生ERC/DRC、最终版本复算、CAM与工厂EQ仍保留。没有为加速添加放行缓存：同一检查在评审准备与最终门禁再次执行，是防止旧证据放行。器件资料仍使用已有版本/哈希缓存。当前尚未提供自动条件裁剪全部规则或通用增量审计缓存，不据此宣称所有配置已经统一。

以下保留底层兼容接口，按当前任务需要阅读。

## 通用性与支持边界

本工具链能接收不同项目，复用阶段/规则/报告接口；不能预先保证任意电路设计正确。明确支持的自动谓词才自动检查；复杂几何、未验证库/接口或缺执行工具保持待办/阻断。Agent、原生工具和工程师各承担实际职责，不能用全绿管理状态替代工程结果。

## 1. 项目契约和统一入口

用project_flow.py init预览；--apply只创建一个新控制目录及project-flow.json，尚未生成电路。模板为assets/project-flow.template.json。把填好文件纳入真实项目版本管理。

契约：schema_version=1；project_id/revision非空；inputs指定schematic/board/project相对路径。requirements每条含id/requirement/acceptance/source(file/sha256/locator)/stages/verification。verification支持：

- static_task：config指静态评审JSON、stage为schematic/pcb、task_id实际存在且该task.requirement_id等于本需求id。
- external_test_plan：source绑定实际外部测试计划。计划存在不表示测试已完成；产品验收必须有实际结果。

features中power/differential/rf/high_speed/safety/thermal/testability/assembly_variants逐项声明required或not_applicable、reason及source；未定阻断。该声明不是物理属性自动识别，不能以错误not_applicable关闭实际需要的规则，AI/工程师须审查适用性。

stages保留16节点，每项填executor(agent/native/engineer/external/combined)、method、required_files和verification_tools。required_files是该节点实际输入，不能放空文件；未到阶段缺少内容允许计划显示待办。check/plan检查全部声明，输出DECLARED_CONTRACT_READY_NOT_APPROVED也只是输入齐备；NPI预导出只检查到npi节点，避免后置CAM输入造成导出循环；release检查到cam_release。样机/ECO继续在外部真实执行，不由D2自动授予D3。

project_flow.py run只派发当前tool-manifest中有CLI入口的有效脚本，用参数数组、无shell，不接受项目脚本路径、任意jobset或历史项目脚本。它不是系统级沙箱；不能限制用户在Skill外执行代码。

## 2. 原理图候选接口

原理图前置门禁见[系统架构与跨模块接口门禁](system-integration.md)：首页架构图、全部元件模块归属、跨模块网络完整端点及每个接口的量化验收/验证方法必须绑定静态评审。系统级行为与器件电气兼容仍须AI/工程师或外部验证，脚本只验证实际网表与声明接口一致。

schematic_candidate.py是通用文件写入和原生核对接口，不是电路推理/自动布局算法。Agent先按规格设计，输出assets/schematic-draft.template.json格式的草稿：

- files：相对文件名→精确完整文本。仅允许.kicad_sch/.kicad_pro/.kicad_sym/.kicad_mod/.kicad_dru；不接受可执行脚本/jobset。官方库使用实际符号引用；外部库/资源必须在目标环境配置并原生验收，未支持的文件类型不能用更改扩展名绕过。
- top/project：files中的顶层原理图与项目文件。
- design_basis：草稿目录内独立设计依据的file/sha256/locator。
- expected.components：完整物料位号→明确value/footprint/fields（至少一项，字段内容非空）；expected.nets：全部精确网络名→[[位号,引脚字符串],...]，保留单引脚网，不重复端点。预期表应先由需求/推荐电路独立建立，不能从生成结果复制来证明自身。

默认只验证草稿结构并预览，不写工程。--apply需精确10.0.7 CLI，写草稿目录之外的新独立候选，遍历层次，原生导出XML/PDF/ERC。比较实际元件库存、明确身份字段、全部网络/端点；任何原生违规或被忽略检查阻断。失败保留候选及candidate-result.json以便修复，不标批准；成功为NATIVE_CANDIDATE_CHECKED_NOT_APPROVED。预期名称与原生层次网络路径不同须先处理合理命名，不自动改网名掩盖。

原理图到PCB同步：使用实际KiCad GUI更新或经过该工程验收的本地适配器；同步后按网表、封装映射、实际网络和design_intent_audit检查。没有通用CLI同步命令的实现，不虚构接口。

## 3. 图面、布局和布线

结构及系统接口检查已接入原理图资料包与gate，见schematic-style.md、schematic-ai-layout-rules.md 和 system-integration.md；Agent 在生成与评审阶段应用拓扑优先规则，未实现的几何检测不得虚报机器 PASS。PCB模块、局部引脚、回流锚点与视觉复验见placement-quality.md。布局和布线执行依真实原生编辑/实际适配器，当前没有通用自动放置器或高速自动布线引擎；不能用旧42×42/固定网络脚本补位。缺执行器时交付当前阶段产物和明确人工操作，不继续宣称已完成。

## 4. 受控制造导出

在独立冻结工程内完成refill/save/reload和当前原生设计门禁，从assets/review-config.template.json建立NPI配置；所有null未决字段和空需求清单必须按实际工程补齐，不能套用测试或其他项目的工艺阈值。静态模板不再预设U1/FB等测试位号网络。NPI配置加delivery_export（模板assets/delivery-export.template.json）及workflow_contract、schematic_style、system_integration；原理图静态配置必须绑定system-integration.template.json并覆盖全部接口来源。delivery_export填：schema_version=1、origin=absolute或drill、variant与config.variants唯一项相同、实际gerber_layers/assembly_layers、BOM字段、互不包含的相对输出目录/文件。保留BOM完整身份字段，按Reference分组，不按value+footprint合并不同物料。每变体一个独立候选，不能以一个包混装。

manufacturing_export默认预览固定类型CLI argv。--apply前必须有精确CLI/pcbnew、当前pre_export门禁通过与匹配freeze-log。导出实际所有铜层+阻焊+板框及项目明确层；钻孔Excellon mm/PTH与NPTH分离；CPL CSV mm双面排除DNP；BOM排除DNP并保留配置字段；装配PDF按指定层。钻孔、Gerber、CPL共用明确原点策略。指令根据官方10.0.7 CLI文档构建，不执行任意jobset/附加shell参数。

成功后核对delivery_manifest精确文件完整、源/评审依赖未变。失败清除本次部分制造文件，仅保留失败记录。成功只是EXPORTED_NOT_RELEASED；export-result.json保留argv/返回码/输出和源哈希，不是工程师或工厂批准。build_manifest应按production_contract要求整理真实工具/每命令日志/来源与输出绑定；本工具不伪造CAM、EQ或生产授权。实际CAM及npi_release完成后才可能D2，不能自动授予D3。

## 5. 首次执行顺序

```bash
python3 scripts/project_flow.py init --destination /path/new-control
python3 scripts/project_flow.py run doctor -- --help
python3 scripts/project_flow.py check /path/project --contract project-flow.json
python3 scripts/schematic_candidate.py --draft /path/drafts/draft.json --destination /path/new-schematic-candidate
python3 scripts/schematic_style.py /path/project --schematic main.kicad_sch --policy style.json --output-dir /path/new-style-report
# 实际原生同步/规则/布局/布线/覆铜及两阶段评审之后：
python3 scripts/manufacturing_export.py /path/frozen-project --config /path/frozen-project/review-config.json --destination /path/new-manufacturing-candidate
```

工程写入命令先预览，审阅并取得写入授权后--apply；报告只写新目录。环境安装/路径教程见environment-onboarding.md；每阶段门禁与回退见full-workflow.md。测试替身不证明KiCad原生执行成功；CLI/pcbnew基础接通后，真实工程全流程仍须在目标机器逐阶段验收。
