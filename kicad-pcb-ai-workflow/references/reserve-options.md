# 按风险的备用方案与可调试性评审 · R9.3

## 目录

1. 决策与边界
2. 配置和装配矩阵
3. 三阶段执行
4. 命令与验收

## 1. 决策与边界

从关键功能块/不确定性建立decisions清单，由AI根据需求、器件资料和改板代价提出reserve/no_reserve，工程师确认。没有预留且理由成立可以通过，不按数量打分，不自动给全板插入0Ω、焊盘或备用电路。原厂/需求明确必须的预留却遗漏时阻断；其余缺预留是否构成高/中风险由AI基于实际影响判断，便利性建议不自动升级为强制。

优先考虑明确调试需求、未知负载、隔离/测量、原厂建议的匹配/滤波位置。架构双方案、不同IC/电源/高速接口的共板复杂度更高，须比较面积、物料、装配误配和信号代价；可用调试板/外接模块时评估替代方式。量产前逐项retain或dnp_only；删除走ECO，移除实际设计与矩阵引用并重新评审，不能只改一个状态字掩盖仍存在的电路。

NC不用于表示不贴。元件custom field DNP=yes/no明确装配状态，value保留真实规格，不用NC代替value；MPN对实际贴装项必需。KiCad引脚的no-connect标记与装配不贴无关。项目变体需各自锁定BOM/网表/评审；本模块的variant仅是装配矩阵，不能代替原生KiCad变体。

0Ω默认值必须已有安全依据，不能随意替代反馈、限流、采样、启动偏置或RF匹配的未知参数。0Ω按实际MPN核对载流、最大电阻/寄生及温度条件，不是保险丝或理想导线。power情境要求required_current_a和经批准approved_current_a，脚本仅比较声明数值，真实脉冲/温升/故障和资料适用性仍需工程审查。

高速、RF、时钟必须核对主路径、焊盘/支线残桩、阻抗/回流和寄生；不贴器件的连接铜线仍存在。不自动执行“零残桩”判定，不以器件中心或0Ω状态证明SI通过。RF匹配按具体原厂拓扑和实际调试，不把任何芯片端匹配统一用0Ω直通。必需保护/终端/偏置不能借DNP默认省略。

## 2. 配置和装配矩阵

assets/reserve-plan.template.json中所有null必须补真实数据，不使用演示器件。schema_version=1，scope_reason写关键功能块清单的覆盖依据；default_variant明确默认装配。decisions至少一项，可全部为no_reserve且refs=[]；清单完整性由AI/工程师确认，脚本不自动发现所有风险。若声明删除既有预留，no_reserve项用absent_refs明确列出应消失的位号，脚本检查原理图/PCB/所选BOM；未列出的隐藏冲突不能从自由文本理由自动推断，必须由AI对实际拓扑复核。

每项decision：id、block、uncertainty、decision、required(boolean)、reason、verification_plan、source(file/sha256/locator)、cost(area_mm2/material_delta/currency/assembly_risk/signal_risk/benefit_reason)。成本数字是经项目核对的增量估计，不是脚本测量或自动报价，0要有理由。

reserve额外包含：refs/nets、context（low_speed/high_speed/rf/power/clock/analog）、role（selection_link/series_tuning/shunt_tuning/power_link/architecture_option/diagnostic）、safety_evidence、必要zero_ohm、layout_review和production。safety_evidence是实际默认状态/未贴状态/切换条件/不可同时装配的核对记录文件与SHA-256，不得伪造。脚本不认证人或证明记录内容正确，当前AI与硬件工程师确认仍必需。

variants每个包含name与parts；parts对每个预留位号均填写fitted(boolean)/value/mpn，fitted=true时MPN必填。所有variant的预留位号集合必须一致，默认态精确比较真实XML value、DNP和已贴MPN。不同变体value可不同，但必须有具体适用与安全评审；本模块不是自动求解全部变体电路逻辑。

groups用于互斥/必选，含id/members/min_fitted/max_fitted/reason。每个selection_link/architecture_option成员必须有组，常见二选一min=max=1。所有声明变体都检查装配数量；不同组之间的隐藏电气冲突还需要AI/工程师读真实连接，不把数量一致当电源不会短接的证明。

layout_review包含reason/reviewer/date/board_sha256/evidence，绑定当前实际板文件。敏感路径还需sensitive_path_checked=true及实际证据。核对不贴焊盘是否存在、可焊接/返修、结构间距、贴装及误装风险；脚本仅核对引用存在和记录时效，不求解完整几何。production.action=retain/dnp_only，含reason与evidence；pending阻断最终NPI。dnp_only要求全部声明变体均不装，若只某产品版本不装，应按独立已批准计划评审，不冒用全局不装。

资料来源必须作为原文加入静态评审documents；reserve_options semantic任务的source_refs包含每项来源的准确locator，targets覆盖所有预留refs/nets。AI逐项评审来源适用性、预留与不预留理由、默认安全、每种装配组合、布局影响和量产处置；所有附加问题结构化写入ai-review.json，禁止只写在总结里。

## 3. 三阶段执行

原理图：比较实际XML默认值/DNP/MPN、已声明网络、全部装配矩阵、互斥/必选、0Ω依据与安全记录。AI判断遗漏关键功能、预留收益与负担、是否可用更简单的调试办法；之后由真实工程师确认。

PCB：检查预留封装存在、当前板哈希绑定的布局记录和敏感路径核对；原生DRC/parity及逐层AI评审仍执行。板变化后旧layout_review无效。资料与该策略/证据自动纳入static_review的基线，gate再次执行本模块，不能只改旧报告哈希。

NPI：默认量产模式必须有reserve_review.policy；原型可作诊断，不授予制造许可。pre_export先要求当前PCB AI/硬件确认，并检查PCB阶段；release另外核对实际候选包所选BOM/CPL、value映射和生产处置，variant须与engineering_profile.assembly_variant、当前原生PCB评审variant及策略default_variant一致（未声明原生variant视为default）。NPI不能切换到另一策略、板文件或未被本版AI/工程师确认的装配变体。所有备用装配变体均应各自跑完整功能/原生/工程评审，本模块只保证所声明组合及当前交付装配一致性。

## 4. 命令与验收

```bash
python3 scripts/reserve_review.py /path/project --policy reserve-plan.json --netlist current.xml --stage schematic
python3 scripts/reserve_review.py /path/project --policy reserve-plan.json --netlist current.xml --stage pcb --board board.kicad_pcb
python3 scripts/reserve_review.py /path/project --policy reserve-plan.json --netlist current.xml --stage npi --board board.kicad_pcb --bom production-bom.csv --cpl production-cpl.csv --variant product-a
```

只读，stdout JSON；0仅表示STATIC_CHECKS_COMPLETE的声明范围检查完成，2=BLOCKED，永远production_authorized=false。--static-preview允许在无pcbnew时提取几何，但native_geometry_verified=false，不能据此签原生或生产通过。risk均有四级等级、位置、问题、参考及建议。

静态config：require_reserve_review=true；reserve_review={"policy":"reserve-plan.json"}；增加reserve_options semantic任务和真实sources/targets。NPI config同名字段还需variant。BOM使用assembly_guard已有严格CSV列；Specification在本模块按矩阵value精确比较，若工程导出名称不同，显式生成经核对的规范BOM，不静默猜测映射。所有DNP行仍需在审查BOM中明确列出，实际贴装CPL只包含已贴件。

模块不修改原理图/PCB或自动插器件。任何实际新增预留走原有预览→--apply独立候选→ECO/网表检查→重审流程。开发夹具不随运行包安装，不能用于制造或充当工程师签核。
