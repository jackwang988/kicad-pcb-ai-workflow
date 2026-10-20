# 模块化、引脚级与视觉布局评审 · R9.3

## 目录

1. 原则与执行顺序
2. 模块、角色与局部布局
3. 自动检查的确切范围
4. 布线前、最终与美观复验
5. AI/工程师与NPI门禁
6. 命令和四类交付
7. 实现边界

## 1. 原则与执行顺序

先满足适用安全/结构/制造硬约束，按实际器件电路与返回路径完成电气布局，再做可装配/测试/返修与视觉整理。美观建议不能抵消任何硬约束。不是所有R/C靠近IC外壳：应根据具体用途靠近相应引脚/驱动端/接收端/连接器/取样点。功能分区不等于切地，主控不强制居中，晶振/RF铜区按具体手册；历史legacy规则不能覆盖本规范。

布局按五步执行：固定板框/孔/接口/限高和净空→规划模块关系/关键通道→关键局部电路及外围→布线前扇出/参考面/通道评审→视觉整理并复验受影响约束。模块之间需要迭代，不是一轮放完再让布线迁就。

## 2. 模块、角色与局部布局

assets/placement-plan.template.json对应schema_version=1。每个模块含id、anchor、refs、roles、bounds_mm与source(file/sha256/locator)。当前PCB的每个封装（含机械/测试/DNP）必须唯一归属一个模块，明确核心锚点与允许区域；模块区域可按实际架构重叠，但器件不能重复归属。区域是功能布局约束，不创建地缝或自动禁布。

roles允许controller/decoupling/clock/power/connector/protection/termination/filter/feedback/rf/analog/passive/test/mechanical/reserve/other。角色由原厂功能与实际网络确认，脚本不从C/R前缀猜用途。原理图器件原则上在PCB库存中找到；确为仅原理图用途的符号用schematic_only逐项列ref/reason/evidence，不能无依据忽略缺封装。机械件可只存在PCB。漏分、错分和用other掩盖关键角色由AI/工程师核对。

critical_subcircuits逐项记录id/type/reason/refs/check_ids/source。类型为decoupling/power_loop/crystal/termination/protection/filter/feedback/rf/reserve/other。关键角色必须被局部清单覆盖；每个声明去耦电容必须关联一条引脚级decoupling规则。其他局部类型不能用普通距离证明功能，需具体原厂图示/网络与当前布局评审。

典型执行重点：

| 局部电路 | 应针对的具体位置/路径 | 不允许通用化 |
|---|---|---|
| 去耦 | 对应电源脚、电容电源端、地端和有效返回锚点 | 最近任意焊盘不等于有效去耦 |
| 开关电源 | 原厂定义的高di/dt热回路、反馈安静取样 | 包围盒不等于真实环路，SW区不按美观扩展 |
| 晶振/时钟 | 指定引脚、负载/回路与噪声隔离 | 不一律强制同种挖空或包地 |
| 串联/并联终端 | 根据终端拓扑选择驱动端/接收端 | 不把所有电阻都挤到芯片旁 |
| ESD/接口滤波 | 入口、保护前后走线和泄放路径 | 不只测到IC的距离 |
| 模拟/反馈 | 具体采样/驱动/滤波/取样要求 | 短线不自动证明建立时间/稳定性 |
| RF/天线 | 原厂匹配拓扑、参考地、辐射净空 | 不全局挖空RF下方铜 |
| 备用 | 默认装配与所有备选的寄生/返修条件 | 不贴器件的支线/焊盘仍存在 |

## 3. 自动检查的确切范围

placement_review.py只读，不移动器件，不改旧脚本。constraints每条含id/kind/level/source。硬规则不被例外或美观评分抵消；所有阈值由实际项目/原厂资料提供，不预设通用毫米。

| kind | 字段/自动核对 | 限制 |
|---|---|---|
| fixed | ref/position_mm/angle_deg/position_tolerance_mm/angle_tolerance_deg | 实际参考点/文件角度；不等于3D结构已验收 |
| pad_proximity | a/b明确ref/pad/net，max_mm，可指定same_side | 真正指定焊盘中心间距；不证明实际路由 |
| decoupling | ic_power、cap_power、cap_ground、return_anchor；max_power_mm/max_return_mm、same_side布尔 | 比较真实XML与PCB焊盘网名，明确电容两个不同端子、电源/返回不同网络；返回锚可为具体地焊盘或已识别地过孔UUID。只做几何，不证明地平面连续或电流路径 |
| corridor | bounds_mm/allowed_refs/margin_mm | 检查支持courtyard的保守AABB侵入；不是布线容量、层资源或SI求解 |
| alignment | refs/axis(x或y)/tolerance(mm) | 组内器件参考点对齐偏差，仅优化建议 |
| uniform_spacing | refs/axis/tolerance(mm) | 至少3个器件的投影中心间隔变化，仅优化建议；不是实体DFM间距 |
| orientation | refs/allowed_angles_deg/tolerance(deg) | 明确分组方向偏好，仅优化建议；不强制所有器件统一角度 |

模块边界按实际支持的courtyard完整顶点检查，不再只用中心。在本版支持顶层单闭合直线/矩形轮廓；非零旋转需用原生实际焊盘坐标验证变换，无法验证、底面、曲线/多轮廓或缺courtyard均标manual_required，不猜测形状。可在manual_geometry[ref]提交board_sha256/reason/evidence，表示由真实原生DRC/结构或工程复核完成；输出标人工证据，不变成自动几何PASS。courtyard本身是否符合原厂仍由封装评审负责。

无原生API时，底面/旋转焊盘的引脚级距离直接拒绝猜测。静态预览不授予原生或生产许可；native_geometry_verified只描述提取来源，不表示约束全部通过。

美观规则只能level=优化建议。适用普通器件组和重复通道，保留电气/结构例外：exception={reason,evidence:{file,sha256}}仅可用于美观。其他类型即使写exception也不能豁免失败。丝印遮挡/极性/引脚1/3D/焊接可达性需实际图纸/DRC和AI/工程师检查，本脚本没有完整文字包围盒/装配仿真引擎。

## 4. 布线前、最终与美观复验

reviews.pre_route与final必须是真实记录，含reviewer/date/reason/evidence，不能自动填批准。每次audit输出snapshots供核对版本，生成快照不是批准，不得只刷新哈希保留旧结论。

pre_route绑定placement_sha256（封装/焊盘/角色相关几何与叠层）、netlist_sha256、policy_sha256（不含reviews）；topics.routability/return_paths/source_layouts/mechanical逐项真实完成，并列出全部subcircuits。检查扇出方向/空间、通道与层资源、参考面、局部原厂布局、结构/装配。没有完整自动可布通性求解器，需读实际工程和原生工具结果。

final再次要求同一当前布局的pre_route记录，并绑定最终board_sha256；topics另含visual/moves_rechecked，确认全部局部电路、实际布线与覆铜及视觉整理后复验。单纯增加走线不会使布局快照失效，但会使final整板记录失效；任何位置/焊盘/规则/来源相关变化都要求相应重新审查。先布完再虚构早期评审不可接受；脚本验证绑定、不认证时间过程或人员身份。

## 5. AI/工程师与NPI门禁

静态配置新增require_placement_review=true、placement_review={"policy":"placement-plan.json"}，PCB stage增加placement_quality semantic任务。sources/locator覆盖模块、局部电路与每条约束来源；targets.footprints覆盖全体物理封装，targets.nets涵盖命名端点电源/返回网。AI观察物理对象用footprint与detail；电气引脚仍用ref/pin/net。机械封装不能冒充网表器件。

static_review.py将策略/证据纳入基线，运行final布局检查并生成四类资料；gate重算结果、验证物理观察/来源/实际版本。AI必须实际查看全部铜层、模块图和局部图，判断功能分区、关键路径与美观例外，不能用图中矩形或距离PASS替代回流/滤波证明。之后仍需硬件工程师对当前AI报告确认。

量产NPI必须有placement_review.policy，且与已确认PCB资料包和板文件一致；final检查未完成、旧证据或硬约束失败阻断。高风险沿用既有逐项审批，美观建议不阻断，也不会取消其他模块风险。原型诊断不授予生产权限。

## 6. 命令和四类交付

```bash
# 布局完成、布线前检查。输出新报告，不修改工程
python3 scripts/placement_review.py /path/project --policy placement-plan.json --netlist current.xml --board board.kicad_pcb --phase pre_route --output-dir /path/new-placement-report
# 布线/覆铜保存并完成视觉整理后，执行最终复验
python3 scripts/placement_review.py /path/project --policy placement-plan.json --netlist current.xml --board board.kicad_pcb --phase final --output-dir /path/new-final-placement-report
```

无pcbnew时可显式--static-preview，仅预筛；未知/不支持几何仍阻断或要求真实人工几何证据。输出目录必须新建，报告写入不需要--apply；没有工程变更。

四类交付：module-map.svg模块几何图；local-N.svg关键局部几何图；placement-report.json/.md约束与风险报告；visual-review.md视觉与例外待评审说明。SVG来自真实坐标，但只是courtyard/焊盘中心示意，不含完整铜层/丝印/实体，不是原生PCB/CAM。正式原生逐层图纸由既有static_review导出。

## 7. 实现边界

不保证自动布局最优、任意几何支持、真实滤波/抗干扰/热/SI性能；不会生成自动合格的原厂局部模板。Agent根据具体MPN资料填写可追溯实例，而非套固定数值。当前TEST示例故意失败，资料和阈值仅软件测试；不得制造或当工程师批准。真实KiCad10.0.7与产品验收仍待执行。

官方参考供Agent查具体适用章节：KiCad10 PCB/CLI文档；ADI混合信号布局指南；器件对应厂商硬件设计指南。通用经验和视觉偏好低于适用产品/原厂/制造约束。

## 独立试跑修订

同面受支持courtyard另做包围框重叠候选筛查，输出高风险；它可能保守误报，不能当实体碰撞或完整贴装间距结论，必须用原生DRC和结构/装配复核。局部SVG包含规则实际端点（含指定返回过孔）、引脚/网名、坐标和距离/阈值；图外引线标注避免位号互压。灰框为模块允许区，不是板框。Markdown列输入哈希、逐项实测与阈值及准确来源定位。pre_route/final缺项独立汇总；测试夹具标记始终单列阻断。策略结构错误仍可导致后续依赖项无法检查，需先修复契约错误再运行。
