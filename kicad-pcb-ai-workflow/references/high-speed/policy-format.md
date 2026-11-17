# 专项输入与执行合同

运行时使用Python标准库逐字段验证，不依赖另一个未执行的JSON Schema。`rules.json`的16个ID与check_type必须与运行检查器的完整注册一致；未知、漏项或重复均阻断。目录的severity、requires和automation是原知识库的设计意图，实际已执行内容以每条结果中的checks、findings、limitations为准，不能按标签推断实现状态。

## policy（schema_version=1）

- `phase`：pre_route、post_route、handoff。
- `inputs`：至少board，每项`{file,sha256}`，均为项目内真实非空文件。建议包含同名工程、DRU、原厂及叠层等相关输入；init会自动绑定已存在的同名.kicad_pro/.kicad_dru。禁止遗漏会影响对应分析的模型/配置。
- `nets`：必须与快照实际网络精确覆盖；每项name、kind。kind为high_speed/low_speed/power/ground/analog/unknown；unknown阻止本次专项判断。空网伪网络不进入库存。提供allowed_layers时必须来自实际层；受控阻抗不因网络被误标低速而自动豁免。
- 高速网络另需interface、signal_edge_or_rate、source、allowed_layers及reference_by_layer。source统一为`{file,sha256,locator}`；reference_by_layer按路由层映射明确参考铜层，只检查声明存在，不证明填充铜面连续。
- 受控阻抗网络声明`impedance:{target_ohm,min_width_mm,max_width_mm,source}`。这只支持批准的线宽范围审计；差分间距、截面、材料和实际阻抗仍交现有规则工具、DRC及适用求解证据，不能以该字段集合证明阻抗已求得。
- `differential_pairs`：每项id、positive_net、negative_net、max_skew_mm、source。现阶段只有铜线长度统计，缺少真实端点拓扑、过孔/封装模型与逐段传播延迟；不得用统计值代替通道时序或接口合规。已有原厂毫米预算保留，不臆造时间换算。
- `power_rails`：仅列实际适用关键轨，每项name、voltage_v、ripple_percent、transient_current_a、target_impedance_limit_mohm、source。name应对应kind=power的真实网；初始Z预算不能代替频域/瞬态验证。
- `manufacturing`：source及min_track_width_mm、min_clearance_mm、min_via_drill_mm、min_via_diameter_mm、min_annulus_mm。数值来自当前板厂和工艺，不带通用默认。当前专项测量线宽/过孔；clearance等由已有原生DRC链承担。
- `stackup`：source绑定当前批准叠层文件。当前只验证实际铜层库存与来源，不声称自动求解或完整解析介质模型。
- `requirements`：对特定规则追加明确适用性，含rule_id、applicability(required/not_applicable/unknown)、reason、objects（实际网名列表）。not_applicable还需source，不能覆盖已存在的必要对象或制造要求。未知适用性不能悄悄跳过。
- `evidence`：见下文。不提供证据时，未实现物理验证保持REVIEW_REQUIRED；明确属于后期的检查可在pre_route显示延后，但失败/损坏证据不能被延后隐藏。

## evidence（外部或工程审查记录）

每项至少包含：

```text
rule_ids: [HSPCB-...]
artifact: {file, sha256}
inputs_sha256: {项目内文件相对路径: 当前SHA256, ...}
tool: {name, version}
method: 实际验证方式与范围
scope: [准确网名, ...] 或 [*]（仅确实覆盖全范围时）
created_at: 带时区的ISO时间
reviewer: 实际审查人或记录归属
result: PASS / FAIL / REVIEW
```

至少覆盖policy全部当前工程输入；附加模型、求解配方和原始输出也应记录真实哈希。artifact/source/input都在项目根内，拒绝越界、链接、空文件、缺失、旧哈希与对象范围不符。外部FAIL仍为失败，不能被配置或几何项覆盖。EXTERNAL_EVIDENCE_RECORDED仅证明记录结构和文件绑定通过，不证明报告内容真实、模型充分、审查身份已认证或求解器在本机运行过。

## 真正的操作与求解

本专项不直接写PCB。适用预算确定后，用已有design_intent与原生规则审计配置，再由当前Konnect受控执行器在候选板上操作、回读和保存，独立运行原生DRC。rule_id绑定检查结果与对象，不将自然语言rule直接当可执行程序。

ngspice适配器固定生成受限被动RLC模型，不接收项目任意netlist或命令。CLI要求当前--board与请求的board_sha256相符；model_source还需真实哈希与定位。仅显式solver-run运行已选择且哈希一致的工具。缺工具/身份错误/超时/无效结果分别保持BLOCKED。SAMPLED_MODEL_WITHIN_TARGET仅表示采样点在初始目标之内，不证明连续频段收敛、瞬态、稳压环路稳定性或整板PI。

外部场/通道求解器尚未集成；可按上面合同登记真实外部证据，不能把ngspice集中参数模型标为3D过孔、全板PDN或眼图求解器。进一步集成时先验证实际几何转换、材料、端口/参考、边界、网格与结果解析，再逐问题开放能力。
