# KiCad PCB AI Workflow：完整系统运行流程 · R9.3

运行包提供通用入口、共享配置及独立核心库存，以下16节点及G1–G6全部保留。日常优先用`workflow.py`的六组待办和固定任务入口；公共字段写一次，编译为原脚本可读的新配置快照。原生、AI、工程师及生产放行门禁仍实时执行，不以缓存代替。操作方法见[统一入口](universal-workflow.md)。


通用入口、项目契约、原理图候选和受控制造导出见[universal-workflow.md](universal-workflow.md)。系统架构/跨模块接口有独立契约门禁；执行接口不授予自动设计或生产批准。

适配目标：KiCad10.0.7。当前为待真实原生与产品验收的工程候选工具链，不承诺一句话自动得到可直接投产的板。

## 目录

1. 系统组成与约束
2. 全流程与门禁
3. 逐阶段详细执行
4. 关键配置与执行命令
5. 风险、变更和失败回退
6. 当前可用范围与待验收

## 1. 系统组成与约束

| 执行者/工具 | 实际职责 | 不能据此宣称 |
|---|---|---|
| 用户/产品负责人 | 产品要求、成本/结构/环境与验收目标 | 未声明目标自动满足 |
| Agent | 组织需求、读原厂资料与图纸、设计候选、逐项语义评审 | 脚本运行过就等于AI读过图 |
| KiCad原生CLI/pcbnew | 已支持的工程读取、ERC/DRC、图纸/网表/制造导出、PCB操作 | 存在通用后台电路逻辑验证或全自动优质布线 |
| 新增审计脚本 | 数据、明确谓词、版本、装配、证据与发布门禁 | 代替完整电气/SI/PI/热/EMC求解或人员身份认证 |
| 硬件工程师 | 核对技术判断、例外与当前版本签核 | 可签字豁免未解决阻断或虚构实测 |
| PCB/PCBA厂与CAM | 确认实际叠层、工艺、制造和装配交付 | 导出文件存在就代表内容正确 |
| 实验/测试人员 | 回板功能、性能、可靠性和适用认证验证 | 静态检查已证明真实板正常 |

工程候选、缓存和首次启动验收默认预览，仅显式--apply执行相应写入；原始工程不覆盖。只读评审按显式output-dir生成全新报告，不要求统一--apply，也不改工程。运行包仅含有效工具；历史项目脚本不属于执行依赖。原型prototype不授予量产权限，mass_production执行新增DFX/NPI。不得虚构不存在的CLI/API或工具；每个模块退出0只代表其声明范围。

## 2. 全流程与门禁

原流程为阶段0–7，含阶段2.5叠层前置，保留六个工程确认点；这里用16个执行节点展开，避免把管理节点误当原始阶段数量。DFX检查叠加到各出口。

| 节点 | 原阶段 | 核心输出 | 进入下一步的条件 |
|---|---|---|---|
| 1 环境/保护 | 前置 | 环境结果、工程基线 | 工具可用；项目资源可读；副本策略明确 |
| 2 需求与架构 | 0 | 需求/框图/电源树/AVL | 目标与验收明确，未知不猜 |
| 3 器件资料 | 0→1 | 原文库、核对卡、来源版本 | 核心资料与适用性完整 |
| 4 预留决策 | 0→1 | 风险/成本决策与装配矩阵 | 默认态安全，有/无预留均有理由 |
| 5 原理图 | 1 | 架构首页、模块层级、接口契约、原理图候选 | 所有元件归属明确，跨模块网络端点与契约一致 |
| 6 原理图审查 | 1/G1 | ERC/系统接口/静态AI报告及工程师确认 | 接口电气和系统行为有依据，阻断关闭，当前版签核 |
| 7 封装 | 2/G2 | 符号/引脚/封装核对 | 原厂尺寸/引脚/工艺一致 |
| 8 叠层与规则 | 2.5 | 工厂批准叠层与W/S等约束 | 参数与实际项目规则生效 |
| 9 布局 | 3/G3 | 功能分区、关键回路与布局评审 | 结构/电源/回流/测试适用约束满足 |
| 10 布线/覆铜 | 4 | 完整PCB候选 | 连通、规则与覆铜最终状态可检查 |
| 11 PCB审查 | 4/G4 | 逐铜层/关键路径AI及工程师确认 | 原生/静态/语义阻断关闭 |
| 12 DFX/NPI预检 | 4→5 | 风险汇总与预导出结果 | 设计门禁通过；仍无生产授权 |
| 13 制造候选 | 5 | Gerber/孔/BOM/CPL/图纸等 | 从冻结源真实导出，完整可追溯 |
| 14 CAM/EQ/授权 | 5/G5 | 当前工厂确认的D2包 | 实际CAM、工厂EQ、装配及授权齐备 |
| 15 样机/试产 | 6 | 功能/性能/环境等实际记录 | 阶段目标按适用计划验收 |
| 16 ECO/归档 | 7/G6 | 变更、复验与发布基线 | 所有受影响证据重新有效 |

不是把所有阶段交给一个Python命令无人值守执行。设计/读图/判断由实际Agent和工程师承担，脚本在明确接口执行检查；自动布局、布线、同步和环境连接必须有真实工具支持。

## 3. 逐阶段详细执行

### 节点1：首次配置与日常启动

输入：同一执行环境中的KiCad10.0.7、匹配Python、完整Skill和合法非空示范工程。先按environment-onboarding.md配置CLI路径/解释器/库，确认Agent能访问本地文件并实际读图。

首次environment_start setup预览，显式--apply才复制工程到独立报告目录，导出PDF/XML、执行ERC/DRC及LoadBoard并核对原工程未变；记录environment_only。日常check始终真实探测版本，比较工具/解释器/脚本与路径摘要、证据和有效期，通过则跳过重复配置。更换环境、变更/过期要求重验。新项目仍查自己的库和需求，生产前不跳过最终门禁。

### 节点2：需求、系统架构和选型

输入：功能、外部接口、工作模式、供电/持续峰值与异常电流、板框/孔位/限高、环境、功耗/热、成本/供货、目标工厂和可靠性/认证适用要求。先建立系统框图、电源树、接口/关键链路表与AVL；工程师确认关键选型、封装、温度等级和供应可行性。模块划分、接口边界和验收条件进入[系统架构与跨模块接口门禁](system-integration.md)；需求未明确时由AI列出假设/待确认项，关键未知不得猜定。

每项需求具备ID、来源、量化验收条件和方法。没有依据的参数保持未决；EOL/NRND与降额无外部数据库时输出人工查询清单，不声称自动查完。实际安全要求按产品和市场判断，不采用全行业统一距离或测试数值。

### 节点3：资料检查与复用

根据完整MPN/制造商/封装查缓存，缺资料由Agent确认原厂URL并获取datasheet/errata/指南/应用笔记；失败阻断或导入真实离线原件。device_knowledge按原文SHA去重和版本留存，draft仅生成未核对卡。Agent实际读相关全文、表格、脚注和图，关键内容经核对后与证据绑定；latest_checks保存实际原厂当前版本查询。

核对卡提取工作条件、引脚、供电/复位/启动/时钟、接口电平/终端、推荐电路、布局、封装和勘误。bundle将所选证据冻结到项目，产生规则候选；新项目重新判断适用性。原文仍作为评审documents，不能只读摘要。发现新版先比较影响，不覆盖旧项目基线。

### 节点4：关键不确定性、备用与可调试性

按功能块列decisions，比较失效/调试/改板代价与面积、物料、装配/信号负担，明确reserve/no_reserve及理由。没有备用方案且理由成立可以通过，不按数量加器件。

需要预留时，明确默认装配、其他变体、MPN/value/DNP、互斥/必选组、0Ω适用和默认上电/切换安全记录。NC不是不贴；用DNP=yes/no。功率0Ω核对载流和真实工况，未知反馈/限流/匹配参数不默认直通。高敏感链路按实际手册/模型检查焊盘、支线、回流；备选芯片还需电气/机械/固件兼容评审。

量产前决定retain或dnp_only并有依据；删除走ECO实改工程和矩阵，absent_refs列明应移除位号以核对实际源与BOM。未声明的隐藏冲突仍需AI/工程师读真实拓扑，不能用一条“不预留”理由免检。详细schema和命令见reserve-options.md。脚本不自动插入器件，不自动求解全部装配组合的电气后果，AI及工程师仍审每个允许组合。

### 节点5：原理图与设计意图

先完成系统架构首页、模块清单、接口端点/电气契约及系统验收条件，见system-integration.md。用户无需先指定层级；AI根据功能和接口提出分页，再由硬件工程师确认。缺少首页架构图、元件模块归属、跨模块网络端点或接口验证方法时，原理图门禁阻断。按功能/连接/可读性选择纸张和页面；不使用88器件或固定页数通用门槛。Agent设计精确草稿，用schematic_candidate.py预览/--apply独立候选，并原生核对独立预期元件/全部网络，成功仍未批准。


Agent按需求/推荐电路组织功能模块、层级页面和实际连接。明确电源/地/裸露焊盘、使能/反馈/复位/启动、时钟、接口方向/电平/偏置/终端、保护、无源和未用引脚、型号与变体。版式改善不应破坏连接；改电气走ECO，保持拓扑的编辑才要求无未批准差异。

同时填写design-intent：差分P/N、协议/PHY及跨串联器件分段/端点；电源持续/峰值、压降、铜厚、温升与批准热宽度；RF频率/功率/参考地、匹配及天线净空。缺叠层/工艺不得猜W/S。设计意图脚本添加指定已有标签字段、精确类分配、原生分层几何与.dru，仅--apply新候选，不改网名/接线、不自动同步/整板布线。

### 节点6：原理图内容评审与G1确认

机器：原生ERC、层级/网表、元件字段/BOM、明确配置的pin_net/电平/分压等谓词、预留默认DNP/互斥/0Ω、纸张/层次接口结构，以及system_integration.py的模块归属和跨模块网络完整端点核对。机器不能判断接口电气兼容或系统时序正确；逐接口来源评审、供电/复位/时钟/电平/启动和故障行为由真实AI与工程师确认。原生网表来源未验证时只作预评审，签字不升级为原生通过。

AI：真实读原理图PDF、实际网络和具体器件原文/推荐电路，逐功能比较产品要求和实际实现。覆盖电源、复位启动、时钟、接口、保护、无源/未用脚、封装映射与变体；schematic_style语义任务按实际分页方案逐页核对层次连接、可读性、簇排版、电源/地作用域与原厂建议；reserve_options任务覆盖所有备用位号/网络及每项来源。引用有出处不等于推理正确。

输出逐项PASS/FAIL/NEEDS_EVIDENCE/NOT_APPLICABLE与真实观察、依据、适用性、修复和验证；附加发现结构化入报告。硬件工程师本人确认绑定本版packet/AI报告；不适用/非阻断偏差逐项处理。阻断或证据不足不能签字豁免，修改后重审。

### 节点7：封装与G2确认

核对具体MPN封装引脚编号/功能、顶底视角、极性/引脚1、裸露焊盘、原厂land pattern、阻焊/钢网/装配及连接器方向。替代料不能仅凭同封装认为兼容，必要时独立符号/封装/装配变体。复杂焊盘不由简单几何脚本证明正确；原厂资料、原生DRC和工艺证据共同完成。

### 节点8：叠层与约束生效

确认实际物理层顺序、介质/成品铜厚、Dk/Df及适用频点、参考面、对称/铜平衡、孔工艺/板厚和工厂阈值。外部计算/工程师/工厂批准阻抗几何，再生成逐层规则；目标阻抗数字本身不是已算出线宽。

在真实KiCad原生从原理图更新PCB后，design_intent_audit --phase pre_route检查实际类成员/覆盖与规则生效。脚本不虚构后台F8同步或自动操作GUI阻抗按钮。电源DC预算不覆盖复杂铜面电流、过孔/触点/铜颈、瞬态和故障；单独补证据。

### 节点9：布局与G3确认

执行R8 placement-quality.md：每个物理封装唯一模块归属与角色，模块有锚点、允许范围和来源。按固定物理边界→模块/通道→关键局部→布线前评审→视觉整理并复验执行。布局清单定义IC电源脚/电容电源端/地端/返回锚点，避免最近任意焊盘的误判；局部电路按具体原厂指南，未知几何需真实人工证据。pre_route绑定布局/网表/规则，final绑定最终整板及视觉移动复验。美观只为建议，不抵消硬约束。输出模块图、局部图、约束报告、视觉及例外说明，示意图不是铜层/CAM。

先结构/接口/限高和关键电路，再一般器件。审电源高di/dt回路、去耦的真实连接、时钟、高速端点及串联器件位置、RF馈线与天线净空、模拟敏感区/噪声源、机械/装配/测试点。RF馈线参考地与天线辐射区净空分别处理，不全局挖空。

备用焊盘需可装配/返修，避免不必要长支线；布局评审绑定当前板哈希，移动/布线变化后重新核对。热源位置/距离与中心距离只是静态预筛，不能当真实热/回路电感/3D无干涉证明。

### 节点10：布线、覆铜与最终保存状态

Agent/实际工具按规则布线：电源与关键链路、差分/单端高速、时钟/RF、敏感模拟及普通网络；顺序随实际架构判断。检查各串联段/端到端路径、线宽/间距/层、分支、过孔、颈缩和回流；不靠改网名/删规则消告警。

在新候选中处理铜后refill→save→reload，再执行最终原生DRC/parity与规格审计。不能在新旧铜并存时过检查，删旧铜后直接发厂。link_audit只对受支持唯一中心线路径保守检查，复杂分支/焊盘边缘入线等不支持则阻断，不以累计长度假通过。

### 节点11：PCB逐层内容评审与G4确认

采集最终布局/布线/覆铜、实际叠层、焊盘/线/弧/孔/铜区和全部铜层视图。AI实际逐层及按关键路径比较原厂/项目规则：参考面连续、跨缝与换层回流、差分/扇出/延迟、供电/颈缩/返回、去耦、时钟/RF/天线、装配机械、测试和预留寄生风险。

原生DRC、明确几何、语义评审各有范围；线宽检查不是阻抗求解，二维图不是CAM。每层/关键网/全体元件要有真实观察。输出AI及硬件工程师对当前版本确认；原理图和PCB签核独立。动态EMC/眼图/温升/可靠性仍标未验证，不伪造结果。

### 节点12：DFX/NPI预导出门禁

mass_production_review --phase pre_export汇总DFM/装配/DFT/可靠性静态、电源/信号、保护/安全/降额/生命周期证据、基线/变体/ECO、设计意图、两阶段AI与真实工程师确认以及备用方案。

缺必需资料、异常、不支持输入或阻断未关闭禁止生产导出。高风险按内容指纹逐项补证据处理，不按整类豁免。pre_export不是生产授权，也不自动生成Gerber/BOM。某些规则仅人工/外部证据门禁，不能宣称全部自动几何检测。

### 节点13：冻结与隔离制造候选

freeze_candidate创建新副本并进行支持的最终状态操作；validate_frozen_candidate复验。基线/源、工具、命令、最终保存状态与输出绑定。设计预检通过后，由真实KiCad直接export到隔离候选目录，导出成功仍不代表可以下单。

交付包含明确完整层的Gerber、钻孔/PTH/NPTH/槽及层对、选择变体BOM/CPL、制板/装配/叠层/阻抗要求、适用钢网资料。不得底面手工镜像或用SVG代替Gerber。jobset原生存在，但本工具链尚未完成目的地/输出语义自动验收，仅有jobset日志不足以放行。

### 节点14：CAM、工厂EQ、NPI最终审查与G5

独立CAM实际加载Gerber/Excellon，核对层/极性/板框/内槽/孔位/铜/阻焊和坐标；PCBA核对旋转零点/底面/极性/引脚1/不贴与版本。关闭实际工厂对叠层、阻抗、孔工艺、制造和装配的EQ，补实际授权。

release阶段reserve_review比较实际候选BOM/CPL与所选矩阵，严查互斥/必选、默认值与DNP，生产variant与主profile、原生评审variant和当前矩阵default_variant相同，处置未决阻断。其他装配方案必须分别验证，不把默认态通过传播给所有备选。

build-manifest绑定冻结源和输出哈希、原生工具/日志、最终检查、CAM/EQ/授权。npi_release先预览，满足门禁且已有发布指令才--apply到全新目录。不会自动发送工厂或下单；生产授权记录不等于用户授权ChatGPT向第三方发送文件。

### 节点15：实际样机、EVT/DVT/PVT与后期验证

检查制造/焊接与短路，按真实计划限流上电并测各电源/复位/时钟/启动，验证接口、负载、噪声/纹波和功能。根据产品要求进行SI/眼图、温升、EMC/ESD和可靠性/环境及适用认证，保留条件、样本、指标、实测、问题和责任人。

本轮Skill不执行动态EMC/场求解或声明上述实测通过。ngspice需独立可用工具、完整模型/激励和明确分析；原生CLI网表导出不等于后台仿真。供应链/热/SI工具按实际接口与证据接入，不把缺软件写成通过。

### 节点16：ECO、重新评审与归档

需求/器件/参数/连接/叠层/布局/装配变化记录原因、范围、风险和验证。保留原版，在新候选修改。更新受影响资料、规则、网表、原理图/PCB评审、BOM/CPL和制造输出；相应签核失效重新确认。保留可复现源、所用资料版本、工具、命令、证据和发布包，后续同器件复用资料而非盲目复用通过结论。

## 4. 配置与执行入口

| 配置/材料 | 用途 | 模板/说明 |
|---|---|---|
| 环境状态 | 首次验证与日常启动 | environment-onboarding.md |
| device requirements/metadata/cards | 版本化资料及核对 | device-knowledge.md与assets/device-*.template.json |
| placement-plan.json | 模块/局部/引脚/视觉及pre_route/final复验 | placement-quality.md与assets/placement-plan.template.json |
| reserve-plan.json | 关键决策、装配矩阵/互斥与收敛 | reserve-options.md与assets/reserve-plan.template.json |
| design-intent.json | 差分、电源、RF规则传递 | design-intent.md与对应模板 |
| static-review.json | 两阶段来源、任务、资料包 | static-ai-review.md与对应模板 |
| engineering-profile.json | 需求/叠层/路径/证据/装配基线 | engineering-rules.md与对应模板 |
| review-config.json | DFX/NPI汇总和交付清单 | dfx-npi.md；演示配置需替换全部TEST参数 |
| 当前源/变体网表、BOM/CPL、CAM/EQ | 实际验收事实 | 真实工程与目标工厂，不使用演示替身 |

所有命令须在匹配Python/CLI环境运行。下面路径均为占位，不能直接当已有文件：

```bash
python scripts/doctor.py --kicad-cli /actual/kicad-cli
python scripts/environment_start.py check --state /actual/setup/startup-state.json --kicad-cli /actual/kicad-cli
python scripts/device_knowledge.py --cache /actual/cache audit --requirements /actual/project/device-requirements.json
python scripts/placement_review.py /actual/project --policy placement-plan.json --netlist current.xml --board board.kicad_pcb --phase pre_route --output-dir /actual/new-layout-report
python scripts/reserve_review.py /actual/project --policy reserve-plan.json --netlist current.xml --stage schematic
python scripts/design_intent.py /actual/project --intent /actual/project/design-intent.json --destination /actual/new-candidate
# 上一条是预览；审阅后显式--apply创建新候选，再在原生KiCad同步PCB
python scripts/design_intent_audit.py /actual/new-candidate --intent /actual/new-candidate/design-intent.json --phase pre_route
python scripts/static_review.py /actual/project --config /actual/project/static-review.json --stage schematic --output-dir /actual/project/reviews/sch-r1
# Agent真实读资料/图纸→逐项AI报告→硬件工程师本人确认
python scripts/static_review_gate.py /actual/project --packet /actual/project/reviews/sch-r1 --ai-review /actual/project/reviews/sch-r1/ai-review.json --engineer-review /actual/project/reviews/sch-r1/engineer-review.json
# PCB完成后--stage pcb另建包并重复确认；final意图审计、冻结后执行：
python scripts/mass_production_review.py /actual/frozen-project --config /actual/frozen-project/review-config.json --mode mass_production --phase pre_export --output-dir /actual/new-preexport-report
# 设计通过后原生隔离导出、CAM/EQ闭环，再检查实际候选
python scripts/mass_production_review.py /actual/frozen-project --config /actual/frozen-project/review-config.json --mode mass_production --phase release --candidate-dir /actual/manufacturing-candidate --output-dir /actual/new-release-report
python scripts/npi_release.py /actual/frozen-project --config /actual/frozen-project/review-config.json --candidate-dir /actual/manufacturing-candidate --destination /actual/new-release
# 仅满足门禁且用户已授权发布时，最后一条增加--apply
```

这些不是一段无需人员参与的顺序批处理脚本。每个阶段先完成实际设计、资料、原生操作及确认，再执行下一条对应命令。冻结/路径变化后按现有原理图与PCB基线规则确认资料仍有效，不能只复制旧签核文件。

## 5. 风险、级别与回退

每条风险输出【阻断级/高风险/中风险/优化建议】、位号/网络/图层/位置、问题、适用参考和修复建议。阻断级必须修复或补齐证据，检查异常同样阻断。文档模板null、未读图、模型缺失、NEEDS_EVIDENCE均不是默认通过。AI不得代签工程师或伪造来源/实测。

D0内部草案不可生产；D1已审候选可按授权提交工程审核，待EQ不可下单；D2是指定工厂/版本的证据齐备打样制造资料；D3需要真实产品/试产验证，工具不自动授予。原型模式不降低物理安全和设计事实要求，也不授予量产。

失败回到受影响的最早阶段：规格错回需求，参数/连接错回原理图，封装错回库核对，叠层错重算并重布，布局/走线错在新候选修复，BOM/CPL错回装配和变体，CAM/EQ错修源并重新导出。原文/规则/工程/报告变化使相关证据失效；不要通过刷新哈希保留旧批准。

## 6. 当前可用范围与待验收

工具提供的主体：资料缓存/去重与证据、设计意图候选生成、明确静态谓词、网表/路径/装配审计、AI报告与工程师记录契约、启动记录、预留决策矩阵和受控发布控制。运行目录只包含有效通用工具，工程规则见engineering-rules.md；历史项目工具独立归档。

尚不能声称：通用可靠自动布局布线、KiCad10.0.7全平台原生集成、真实原厂HTTPS下载全成功、真实产品全流程打通、完整CAM语义自动验收、复杂几何/回流/全部BOM身份问题均关闭，或静态通过等于量产可靠。受支持子集之外保持阻断。不得用开发测试夹具作为制造工程；各产品仍须实际完成原生打开/同步/规则/导出和工厂验收。

专业落地最终需要同一真实项目的证据链：需求→适用资料→实际原理图/PCB→规则与评审→冻结制造输出→独立CAM与工厂EQ→样机实测。具体能力边界见capabilities.md，不把软件测试数当硬件合格项。

## 执行闭环与停止条件

project_flow负责所有阶段的项目输入/方法/验证映射，run只调用有效白名单工具；缺执行器显示待完成。schematic_candidate接受Agent设计文件、原生核对预期电路；schematic_style绑定静态资料包/复验；manufacturing_export在当前设计门禁通过且冻结后才产生新候选。模板未填、资料未读、未同步、未布局布线、未实际确认时均不能声称完成。详细命令/JSON字段见universal-workflow.md；没有新增通用自动放置/布线/动态求解器。
