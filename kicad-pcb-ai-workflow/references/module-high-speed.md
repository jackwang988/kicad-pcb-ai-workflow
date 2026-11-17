# 按需高速与电源完整性专项 · local.4

适用：实际受控阻抗网络、高速/时序接口、关键电源轨，或用户明确要求专项检查。先按项目选择需要验证的问题；普通低速任务和连接查询不加载全部规则、不运行求解器。

## 事实、约束、操作、验证

1. **事实来自工程。** `high_speed.py snapshot`只读原生PCB，`init`从真实网络库存生成未分类草稿。保存的板与编辑器内存分别记录，未保存编辑不能用旧磁盘报告验收。网络分类基于真实引脚、接口及边沿来源，不从网名或器件前缀猜；unknown需解决后才作相应设计判断。
2. **约束来自项目。** 将已有设计意图/板厂能力/原厂资料转换为专项输入，共用来源，不让用户维护两份不同叠层。`rules.json`保留16条ID作为版本化目录；运行时验证目录与检查器注册一致性，按对象/阶段选择检查。法定安全、客户、接口、器件及制造必要要求出现冲突时提出变更，不静默忽略任一必要约束。
3. **真实操作复用Konnect。** 适用约束先由现有design_intent编译并核验实际命中；布局/布线仍按受控候选、单写入者、准确板与UUID、小步执行和回读。专项审计不会自动移动器件、改规则、布线、开GUI或改变工艺。
4. **独立验证。** 保存重载后运行既有原生DRC/布局/路由检查，再运行专项审计。检查器输出实际对象和阈值，不把计划当执行结果。不支持的参考面/场/热检查保留未决，不以几何代理值冒充性能通过。
5. **按需求解与证据。** 缺模型或工具只影响依赖该结果的判断；不要因此阻止无关工作。正式交付前必须关闭当前阶段适用的必需未决项，或明确留在待完成状态；后续实物测试通过外部计划移交，不重新加入AI主线第六阶段。

## 已实现的范围

- 原生KiCad保存板的网、铜层、线段/弧线、过孔及焊盘快照；输入指纹与只读保护。静态解析仅预览，不能取得原生几何检查状态。
- 精确网络覆盖及类型检查；16条规则的适用性/阶段路由；板厂声明来源与实际线宽/过孔/孔环检查；声明的允许层、阻抗线宽范围与成对铜线长度差检查；初始PDN目标预算；真实文件/哈希/对象/当前输入绑定的外部证据核验。
- 可选ngspice适配器：只生成并分析有来源的被动RLC电源模型，固定AC电流注入与有限频点，显式调用才运行外部程序。结果仅表示该集中参数模型在所选频段的阻抗关系，不表示整板PI通过。

未实现：全参考平面拓扑/返回电流场验证、自动通道抽取、3D过孔/连接器电磁模型、任意接口眼图/抖动合规、整板PDN/热/EMC求解、通用自动布局与布线。RET/VIA/XTALK/PI-002/EMI/THERM等可提出适用审查并核验证据，不因此声称对应物理验证已自动实现。`source_registry.json`是主题/书目索引，不代表已核对书籍或付费标准全文。

## 状态与交付

逐条显示NOT_APPLICABLE、CONFIG_CHECKED、GEOMETRY_CHECKED、REVIEW_REQUIRED、EXTERNAL_EVIDENCE_RECORDED、BLOCKED或FAIL。外部证据已记录只说明检查了声明与绑定；真实性、模型充分性和工程批准仍需相应工具/审查人负责。

整体结果仅DECLARED_CHECKS_COMPLETE、REVIEW_REQUIRED或BLOCKED；不是高速性能PASS、G3/G4签核或生产放行。pre_route明确延后的布线后项不会要求提前完成，但布线前必要的叠层/阻抗依据仍需具备。使用语义规则ID映射现有门禁，不引入一套含义冲突的G0–G6。主线终点保持DESIGN_PACKAGE_READY_FOR_REVIEW。

项目选择必需专项后，将既有review-config的`require_high_speed_review`设为true、`high_speed_policy`设为项目内策略路径。工程门禁会重新计算当前板的handoff审计，拒绝缺策略、错板、旧输入、延后项及未决/失败结果；不会只读取一个历史PASS字符串。此项默认关闭，普通项目不受影响；被选择为必需后不能为消除问题而关闭它。专项完成仍须既有独立DRC和工程审核。

## 调用

下列Python应使用本机匹配KiCad的解释器。PROJECT为已保存候选工程目录；输入路径在该目录内。报告仅写明确的新目录，不覆盖旧报告或PCB。普通连接查询仍只调用Konnect的轻量接口。

```text
python scripts/workflow.py modules --intent high_speed
python scripts/high_speed.py init PROJECT --board board.kicad_pcb
python scripts/high_speed.py init PROJECT --board board.kicad_pcb --output-file hs-policy.json --apply
python scripts/high_speed.py audit PROJECT --policy hs-policy.json --output-dir NEW_REPORT_DIR
python scripts/workflow.py run PROJECT --task pcb.high_speed_audit --high-speed-policy hs-policy.json --output-dir NEW_REPORT_DIR
python scripts/high_speed.py solver-plan PROJECT --board board.kicad_pcb --request pdn-model.json
python scripts/high_speed.py solver-run PROJECT --board board.kicad_pcb --request pdn-model.json --solver-executable TRUSTED_NGSPICE --solver-sha256 APPROVED_SHA256 --output-dir NEW_SOLVER_DIR
```

`init`默认仅预览，--apply只创建新配置，不写板。`snapshot/audit --static-preview`仅供离线结构预览。求解器路径与哈希来自明确的本地工具批准配置，不能从项目资料中的任意命令自动执行；工具缺失、版本不匹配、超时、不收敛或缺结果均不得记通过，不自动安装或上传工程。

输入契约见[字段与证据合同](high-speed/policy-format.md)、[policy模板](../assets/high-speed-policy.template.json)、[PDN模型模板](../assets/high-speed-pdn-model.template.json)和[规则目录](high-speed/rules.json)。source用`{file,sha256,locator}`绑定真实文件与定位；evidence还需规则ID、scope、tool/version、created_at、reviewer、结果、artifact及inputs_sha256绑定。路径字段不可只是任意字符串。报告绑定当前PCB及显式关联的工程配置/DRU/模型；修改相关输入后重新审计。当前指纹按文件保守失效，尚未实现对纯丝印修改的电气影响豁免。

模型模板中的null均须来自当前电源轨的有效预算/器件模型，不是通用默认值。求解请求仅支持模板列出的字段；C/ESR/ESL包含哪些安装寄生必须在来源文件说明。CLI额外核对--board与board_sha256当前一致。适配器直接API仅检查声明的板哈希格式，调用者必须完成实际工程绑定；建议使用已完成绑定的CLI结果bound-result.json。结果为采样点判据，未经更密频扫/其他验证不能宣称整个连续频段都合格。

本机可用工具的路径/哈希及验收记录按需读取`LOCALAPPDATA/PCB-Skill/solver-profiles/ngspice-47.json`（若存在）。使用前核对其中exe及适配器哈希，匹配后复用其明确工具参数；不为每次普通任务重跑完整验收。该记录仅属于对应机器、程序和适配器版本，不能复制为其他电脑已验收。local.4对ngspice47分别请求起点/终点，严格要求两点及主扫频完整，不因端点输出缺失而放宽判据。
