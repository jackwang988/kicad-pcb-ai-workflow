---
name: kicad-pcb-ai-workflow
description: KiCad电子工程设计与评审Skill。按需调度需求/原厂资料、符号封装资源、原理图候选、PCB规则布局、脚本优先布线预检及DFX/NPI，主线截止设计资料待审核，样机/ECO为外部扩展。提供离线资源锁定、只读IPC探测/快照、Konnect MCP后端接入规范和受控路由计划；Konnect动态能力发现与单写入者、KiCad CLI独立验收；迁移期pcbnew仅可选只读。适用新建或已有KiCad工程，不承诺任意电路自动设计合格。
---

# KiCad工程工作流 · R10 G1–G4知识复用＋Konnect唯一实时写入（迁移版）

一个总入口按需读取七个模块，所有模块共享项目配置、版本证据和工程门禁。先执行下方模块发现，再只读取当前任务需要的资料；不加载全量库、3D或全部专题规范。本地修订版主线不含第六阶段；必须先读[主流程及执行修订](references/design-execution-local.md)。历史CLI仍保留六组/16节点兼容结构，不能据此要求执行外部生命周期。

## 按需模块

| 当前任务 | 读取模块 | 主要实际工具 |
|---|---|---|
| 日常连接检查；按需安装或诊断 | [环境与连接](references/module-environment.md) | 日常优先直接调用Konnect；安装/专项诊断才用doctor、environment_start、konnect_backend |
| 需求、架构、原厂资料、备用方案 | [需求与器件依据](references/module-requirements.md) | device_knowledge、system_integration、reserve_review |
| 器件替换、缺库、项目交付 | [项目资源](references/module-resources.md) | resource_guard、pad_audit |
| 原理图设计/读图/网络核对、PCB同步 | [原理图与衔接](references/module-schematic.md) | schematic_candidate、schematic_style、static_review |
| 叠层、布局、布线、覆铜 | [PCB设计](references/module-pcb.md) | design_intent、placement_review、routing_policy、script_route_search；Konnect MCP执行 |
| 受控阻抗、高速接口、关键电源轨或专项SI/PI检查 | [按需高速与PI模块](references/module-high-speed.md) | high_speed、hs_board_snapshot、hs_rule_engine；可选受限RLC求解适配器 |
| 工程评审、DFX、制造候选、CAM/EQ | [评审与制造](references/module-manufacturing.md) | static_review_gate、manufacturing_export、npi_release |
| 仅用户另行要求的外部扩展：样机验证、ECO、归档 | [样机与ECO](references/module-lifecycle.md) | project_flow、netlist_guard及实际外部验证 |

模块是包内明确引用的工作流，不依赖宿主递归发现嵌套Skill。外部依赖见[组件清单](references/component-manifest.json)。当前本地后端首选独立安装的Konnect-EDA 0.14.1，统一注册为`pcb_skill_konnect`；旧开源0.13.0仅作显式回退，不同时参与写入。发行物与构建按[后端版本档案](references/konnect-backends.json)核验；商业程序不纳入Skill分享包。每台电脑须通过安装/握手/目标板回读，具体操作按[接入规范](references/konnect-backend.md)及本机记录开放，不以工具发现代替验收。不自动导入其他全局Skill或运行未知工具。

**节点3缓存优先强制门禁（cache-first 增量）**：在原理图需求评审、架构阶段芯片选型/替换后，先依据准确制造商、MPN、封装生成器件清单，**必须离线执行** `device_knowledge.py resolve` 查共享器件知识库，命中后用 `brief` 取必要知识卡条目，禁止先联网搜索或重复全文加载。仅对 `MISS/STALE` 的具体资料类型补齐原厂来源；`AMBIGUOUS/INVALID_CACHE_ENTRY` 必须阻断。已核对的卡和版本检查通过 `register` 进入跨项目共享索引；资料候选仍需项目适用性审查、原生ERC和G1/G2确认。详见 [缓存优先器件知识库](references/device-knowledge.md)。

**节点6原理图G1评审再次缓存优先（G1-cache-first 增量）**：G1严格复用节点3生成的**项目冻结器件资料包**，不把新一轮评审当成重新搜芯片/重新下载手册的理由。`static_review.py --stage schematic` 先离线验证知识卡、型号/封装和资料时效，自动生成 `device-knowledge-brief.json`；AI先读摘要与本次电路的网表/图纸，再按缺项、图表和具体风险读取同一冻结包内原始PDF指定章节。已有缓存的PDF文字复用已验证的`texts/`文件，不重复提取；资料缺失/版本冲突先阻断相应G1判定并返回节点3补齐，不能默默联网。**知识卡仅为资料依据，不代表新项目电路已合格**。详见[静态评审](references/static-ai-review.md)。

**节点7、9、11跨阶段强制复用（G2/G3/G4-cache-reuse-1）**：节点3冻结同一芯片的原厂资料后，G2通过`resource_guard.py check --review-config`读取符号/引脚/封装相关知识卡，G3通过`placement_review.py --review-config`读取布局/去耦/晶振/RF相关卡，G4通过`static_review.py --stage pcb`读取PCB相关卡并在`static_review_gate.py`重验。统一`workflow.py`自动给G2/G3传递当前静态配置。阶段卡片缺失、过期、篡改或型号封装不匹配时阻断并返回节点3**针对性补卡**；各节点仍必须核对当前项目真实原理图/封装/PCB，不用已核对资料替代新工程签核。**完整16节点逐项输入、规则、失败回退及工具分工见[最新完整系统运行流程](references/latest-complete-workflow.md)**。

**统一工具职责（单写入迁移）**：AI负责设计策略，Python负责算法/知识库/检查，**Konnect MCP是唯一活动KiCad编辑写入端**；KiCad CLI独立核对保存的ERC/DRC。动态发现全部实际可见工具，不固定228/235；L0—L3按风险分级，未验收的写操作在独立夹具专项验证后可登记并复用。**原pcbnew覆铜写入已停用**，冻结改为Konnect操作凭证＋KiCad CLI复验；其他仅供只读的pcbnew几何/规则检查仍属迁移期可选兼容，缺少等价真实证据时生产关口保持BLOCKED。详情先读 [Konnect动态能力与迁移规范](references/konnect-capability-migration.md)。

## 开始与共同保护

1. 新工程先用workflow init预览主配置，仅显式--apply创建；公共路径、来源、变体只填shared。build预览/--apply生成不可覆盖的新bundle，status显示待办。已有工程保持原位，升级重建快照，不复制旧签核。
2. 单纯检查连接先走[轻量检查](references/module-environment.md)：MCP存活用协议ping或一次已暴露的轻量只读调用；KiCad实时连接优先一次open_project查询。通过即结束；未打开PCB就报告状态。连接检查不自动截图、控制桌面、启动/关闭软件、创建测试板或修改工程。首次安装或准备执行原生工程检查时，才按需用doctor/environment.setup验证工具链。默认只要求CLI真实烟雾检查；Konnect的MCP身份和操作能力单独核验，不因缺少pcbnew就阻断纯CLI/知识库任务。原生制造门禁在等价读取完成前仍保留旧兼容或阻断。
3. 本包Python工具只能经当前SHA-256白名单派发；Konnect动态MCP工具不写入固定数量白名单，执行时独立按二进制身份、API schema、风险和夹具验收分级。绝不执行项目供应的任意Shell命令。项目脚本放在Skill运行目录之外。模块/规则/工具变化使配置或评审证据失效，需按影响复验。
4. 工程写入默认预览，仅显式--apply写独立新候选。报告仅写显式新目录；资源锁仅创建新文件。任务已有授权内可继续常规操作，不把每次读取/移动都变成新的确认。
5. 一个工程安排一个写入者；当前实时KiCad编辑只允许Konnect。禁用旧IPC桥写入；离线文件生成只限独立尚未由Konnect打开的候选。只读资料/审查可并行。修改前后核对工程身份和版本，超时先回读，不盲重试。CLI检查必须针对保存后的同一候选，内存/磁盘快照不混用。
6. 按[工程规则](references/engineering-rules.md)使用当前产品/原厂/制造依据，参数缺失不猜测，不为通过检查删器件、改网络、降规则或自行增加层数。
7. 原生检查、AI内容评审和工程师确认分别执行。Agent不得代签。阶段协作按[阶段确认](references/stage-approvals.md)。量产使用--mode mass_production；--mode prototype只作诊断，不获得生产许可。

## 本版实际能力与执行边界

- **已加入**：模块发现与按需阅读计划；项目资源解析/一致性锁定；可选IPC只读探测与内存快照；脚本优先的路由预检/后端计划；离线实验路径搜索。读取[资源契约](references/project-resources.md)、[IPC适配器](references/ipc-backend.md)、[约束布线](references/constraint-routing.md)和[实验路径搜索](references/script-route-search.md)时按当前任务选择。
- **保留**：原理图精确候选写入、独立预期XML网络核对、原生ERC/DRC、引脚级布局审计、工程评审及隔离制造导出。原理图图面须真实阅读，不能由网表正确推断图面合格。
- **外部执行按已验收范围使用**：Konnect-EDA的标准符号放置、明确网标连接、参数修改及计划版本绑定的原理图到PCB同步已在两器件测试中独立核对原生网络。它是文件式原理图编辑与实时PCB操作，不是原理图IPC。现有复杂原理图、层次/多单元/换封装和其他写操作仍按具体能力与项目证据验证，缺能力只停止相应节点。
- **布线**：AI/脚本形成工程计划；实际后端只按已支持约束和验收范围使用。实验路径搜索不写PCB、不证明实际铜几何或电气合格。Konnect普通焊盘连线、跨网拒绝及受限DSN→Freerouting→SES候选→原生检查已有小测试板记录；[旧CLI适配器](references/freerouting-adapter.md)本身仍不负责导出/回导。复杂板、差分/回流及规则保真继续逐项验收，回退不得绕过缺资料、不支持规则或状态冲突。
- **资源**：优先本机官方库，按项目锁定实际使用文件及原厂依据；符号/封装彼此一致不代表原厂pinout/land pattern正确。shared.resource_lock可绑定当前锁，静态资料包和NPI会重新检查；缺失/篡改使相关证据失效。

- **执行后端**：按[Konnect动态能力与迁移规范](references/konnect-capability-migration.md)及[Konnect接入规范](references/konnect-backend.md)选择已固定的发行版本；`konnect_backend`按实际程序SHA-256选择版本档案，核验服务构建及指定实时板。旧开源版本的10.0.8实时操作记录不转记为新版通过，新版具体范围见本机验收。核心保留独立复验，不整体导入上游全局Skill。自研[候选编辑桥](references/controlled-editing.md)收为实验，不再默认安装或作为自动写入回退。

## 本地修订优先约定

涉及规则、布局、布线和交付时，先读[本地执行修订](references/design-execution-local.md)。节点10按其中七步执行；placement_review仍为检查器，新增优化接口是待开发方案。交付摘要状态与既有脚本状态分列，不伪造脚本支持。

高速/关键电源专项只在实际适用或用户要求时加载。以真实保存工程派生输入，按对象/阶段选择16条规则；未知分类不可默认为低速。规则审计不代替真实操作、独立DRC或SI/PI。外部证据必须绑定当前输入；仅填写报告路径不能完成检查。已有Konnect受控修改闭环继续使用，不另建并行写入者。日常连接检查不调用专项模块。正式交付前，已选为必需的专项阻断/失败/未决项必须关闭；专项结果不自动授予G3/G4、资料就绪或生产授权。

## 工程推进

需求与架构→原厂资料/备用决策→原理图候选/独立网络/读图及G1→符号封装原厂核对G2→真实PCB同步→工厂叠层及规则生效→布局pre_route与G3→受控布线/覆铜/保存重载→最终逐层评审G4→DFX/NPI→隔离制造候选→资料完整性核验与移交→DESIGN_PACKAGE_READY_FOR_REVIEW（设计资料已准备好，待审核）。CAM/EQ、生产授权、样机与ECO移至外部扩展，不作为本主线阶段。

特殊高速、差分、RF、电源、热/安全/认证按项目适用性和实际工具/实测完成；几何、连接或DRC通过不证明全部性能。中间布线仅允许逐项声明的待布连接，最终必须关闭全部必要连接。

## 快速调用

~~~text
python scripts/workflow.py modules --intent datasheets
# 节点3优先离线查库（项目内inventory，缓存可在项目外长期复用）
python scripts/workflow.py run /path/project --task architecture.sources_resolve --device-cache /path/device-cache --device-inventory device-inventory.json
# 全部命中后只写新文件，不覆盖原项目配置
python scripts/workflow.py run /path/project --task architecture.sources_resolve --device-cache /path/device-cache --device-inventory device-inventory.json --device-output resolved-device-requirements.json --apply
python scripts/workflow.py modules --intent routing
python scripts/workflow.py run /path/project --task environment.doctor
python scripts/workflow.py run /path/project --task environment.konnect_check --board board.kicad_pcb --output-dir /path/new-connection-report
# 动态发现当前后端实际工具，避免固定工具数量白名单
python scripts/konnect_capabilities.py discover --executable /actual/konnect --config /actual/config.json --all-toolsets --output-dir /new/konnect-discovery
python scripts/workflow.py init /path/project
python scripts/workflow.py build /path/project --bundle control-r1
python scripts/workflow.py status /path/project --bundle control-r1
python scripts/workflow.py run /path/project --task environment.ipc_probe --board board.kicad_pcb
python scripts/workflow.py run /path/project --bundle control-r1 --task pcb.routing_plan --routing-request routing-request.json
~~~

init/build审阅后加--apply；配置生成不等于检查通过。资源锁定与实验搜索参数按对应模块文档；所有命令使用本机实际解释器和路径。

## 放行与版本

阻断级/高风险/中风险/优化建议均记录位置、来源、修复和复验。制造候选成功仍为EXPORTED_NOT_RELEASED；实际工程师、工厂及授权门禁继续生效。脚本不能禁止用户绕过它在GUI导出。

制造预检与发布按[DFX/NPI](references/dfx-npi.md)及npi_release.py执行；不得以导航状态、资源一致或布线计划替代制造门禁。

R9.4的319项软件测试和10.0.8原生记录是历史证据，不代表R10新增能力已原生验收。按[能力边界](references/capabilities.md)及本次发布验证报告判断实际范围，TEST夹具永不授予生产许可。
