# 有效电子产品工程规则 · R9.3

## 权威顺序与适用性

适用法规/安全要求 → 产品规格与器件原厂设计约束 → 经批准的PCB/PCBA工艺及项目规则 → 通用经验 → 美观偏好。冲突要工程决策与ECO留痕，不允许自动降低硬约束。

仅使用当前有效规则与项目批准的依据。历史工程和审查记录独立归档，不作为运行依赖；单个工具退出0不能授予生产放行。

## 25项处置与验证边界

“规则/控制已落地”不等于某块产品已通过。涉及原生工具、封装复杂几何、独立CAM、工厂EQ和硬件实测的验收必须有真实项目证据，不能通过文档勾选假关单。

| ID | 优先级 | 修订 | 落地控制 | 已验证/待验证范围 |
|---|---|---|---|---|
| R01 | P0 | 电气变更不再要求无条件网表零差异 | netlist_guard.py：preserve/eco模式；ECO基线哈希及精确实际差异匹配 | 代码+反例测试；实际工程ECO待输入 |
| R02 | P0 | 违规计数不再作为发布通过条件 | engineering_gate.py：违规身份比较；原生error阻断，排除项阻断；高风险逐项证据审批 | 代码+反例测试；原生实测待完成 |
| R03 | P0 | 取消按告警类型整体豁免未连接 | 原生排除项阻断；不得用几何落点或pad-zone缺告警推断连通 | 规则+代码；实际填铜连通待原生/CAM |
| R04 | P0 | 孔类型、层跨度、制造意图必须一致 | 制造/叠层评审与CAM孔层对记录必需；盲埋孔矛盾不得人工忽略 | 证据门禁；逐孔原生/CAM待验证 |
| R05 | P0 | 撤销pitch-pad长边和45°能消铜短路判断 | pad_audit.py：旋转矩形/圆形铜重叠；其它形状明确未验证；原厂land pattern审查 | 代码+旋转几何测试；复杂pad依DRC/原厂证据 |
| R06 | P0 | 网表空解析/差异退出0假通过 | 严格XML结构/元件/网络/引脚校验；FAIL=1、BLOCKED=2；保留singleton与unconnected | 代码+CLI反例回归 |
| R07 | P0 | 差分审计不再漏圆弧或把圆弧算过孔 | link_audit.py：端点唯一链路、track/arc/via分开、ps预算、转层跨度/位置 | 代码+路径反例测试；原生板集成待验证 |
| R08 | P1 | 旧项目探针退出发布门禁 | 原usb_spec_check/zcheck只作诊断；缺courtyard/未闭合/异常阻断；新profile配置化 | 代码+缺失/畸形courtyard反例 |
| R09 | P1 | 取消缺失工具“已生效”宣称 | tool-manifest列文件哈希/合同/版本/命令/验证范围；缺工具阻断；未打包route_3d等不作依赖 | 代码+库存篡改测试 |
| R10 | P1 | 不再用固定8层名代替物理叠层 | 逐层顺序/介质/Dk/Df频点/铜厚/参考面/板厂签核证据；按路径选层 | 有效规则+证据门禁；无通用默认值 |
| R11 | P1 | 撤销AGND/DGND一律单点规则 | 依据具体芯片/隔离架构和回流设计接地，分区不等于必须切地 | 有效规则+原厂评审证据 |
| R12 | P1 | 撤销跨地缝电容默认许可 | 优先避免跨缝；区分GND到GND与电源参考转换；安全隔离不得随意桥接 | 有效规则+回流/安全评审证据 |
| R13 | P1 | 撤销接口统一毫米公差与错误分类 | 协议/PHY/版本独立profile；DDR按真实控制器；HDMI模式和RGMII/MDI分开，ps预算含封装 | 有效规则+端点profile门禁 |
| R14 | P1 | 禁止改网名和全局降级skew掩盖问题 | 逐串联段保持差分语义；跨器件端到端映射；支路和stub独立评估 | 有效规则+保守路径审计；复杂拓扑阻断 |
| R15 | P1 | 3W/20H/90°降为适用经验 | 明确边距/中心距、叠层和串扰预算；45°/圆弧是偏好，不是电气合格证明 | 有效规则+需求追踪证据 |
| R16 | P1 | 撤销固定线宽/内层一半/单孔1A | 载流、压降、I²R、温升和峰值由实际铜厚/镀铜/散热模型验收；不靠加锡默认放行 | 有效规则+电源/热/工艺门禁 |
| R17 | P1 | 撤销按速率统一背钻和任意盘中孔 | 按残桩/通道模型决策背钻，填孔盖帽平整度与板厂PCBA共同批准 | 有效规则+制造证据门禁 |
| R18 | P1 | 撤销小容值永远最近与全局FULL消警告 | 按原厂PDN、DC bias/ESR/ESL/反谐振/负载瞬态布局；热焊盘按焊接/载流核对 | 有效规则+PI/工艺签核 |
| R19 | P1 | 撤销逆向2mm必换层和所有过孔距pad0.8mm | 方向仅偏好；扇出、回流、时序与工艺共同约束；支持合格dogbone/盘中孔/激光孔 | 有效规则+封装/工艺证据 |
| R20 | P1 | BOM不再按Value+Footprint误合并 | assembly_guard.py按全部物料字段分组、DNP/变体隔离、CPL fitted集合一致；角度/极性人工审图 | 代码+BOM/CPL反例测试 |
| R21 | P1 | 不再拿PCB SVG当Gerber验收 | 核对实际Gerber/Excellon结构和哈希，独立CAM记录必须绑定当前所有铜/钻孔输出 | 代码+假文件/旧CAM证据测试；真实CAM待输入 |
| R22 | P1 | 最终替换后必须refill/save/reload再审计 | freeze_candidate只写独立副本；validate_frozen_candidate执行最终原生/规格检查；旧源不覆盖 | 代码+预览/陈旧freeze反例；原生运行待完成 |
| R23 | P2 | 撤销30器件/A4/绕行比绝对标准 | 按功能与可读性分页；数字只是提醒；关键时序不由几何美观验收。**用户/产品规格显式指定**版式时按[原理图图面规范](schematic-style.md)执行，此时A4横放/三页架构/居中为硬要求；未指定时维持弹性，不得由工具默认强加 | 有效规则；历史案例已隔离 |
| R24 | P2 | 统一阶段、签核与工厂EQ顺序 | 统一0–7+2.5、G1–G6，五个DFX检查叠加；D0/D1/D2/D3分级，EQ后才D2授权 | 有效规则+生产分级门禁 |
| R25 | P1 | 撤销所有产品通用测试/认证数值 | 每电源轨与工作环境独立验收标准；可靠性/认证按市场类别和产品适用性；D2不等于D3 | 有效规则+需求/验证计划门禁 |

## 产品规格必须量化或明确判据

使用assets/engineering-profile.template.json。每条需求有ID、源文档版本/章节、设计规则、验收条件、方法、实际证据文件SHA-256及状态。N/A要有理由与审查证据；null是未决，不是默认值。需求、原厂手册及工厂阈值缺失均阻断。

叠层证据必须包含实际物理顺序、介质与成品铜厚、Dk/Df及频点、参考面连续性、对称/铜平衡和目标工厂确认。阻抗不仅是线宽；需保留求解器输入/输出、角点/容差及板厂确认。未验证的netclass设置不能当全部DRC硬约束。

每条高速链路记录源宿引脚、协议/速率/最快边沿、串联器件跨网映射、分支、允许层/参考面、每层延迟及封装/连接器/过孔预算、解耦段/stub、时序/损耗/串扰与模型/测试需要。USB2/USB3、D-PHY/C-PHY、HDMI TMDS/FRL分别建profile；RGMII按单端时序，MDI另作差分。DDR必须按控制器与存储器指南分lane/CK/CA/DQS，不套统一毫米公差。

电源记录持续/峰值/异常电流、压降、I²R、负载瞬态与ΔV/ΔI目标阻抗、ESR/ESL/DC bias及热条件。安全间距以工作电压、过压类别、污染等级、材料组、海拔、绝缘和适用标准输入人工评估。禁止把示例电流/电压/纹波/温度数字外推到所有产品。

## 阶段和生产级别

0需求；1原理图/G1；2封装/G2；2.5叠层前置；3布局/G3；4布线/G4；5候选制造、CAM、EQ、生产授权/G5；6样机测试；7ECO与设计发布/G6。五道DFX/NPI检查嵌入相应出口，不替换六个签核点。

- D0：内部候选资料，标DRAFT，不可生产。
- D1：已完成设计检查/独立CAM，可按授权提交工厂工程审核，待EQ不可下单。
- D2：目标工厂EQ、叠层、孔工艺、阻抗和装配资料关闭，完整源/输出哈希及生产授权齐全，可供该工厂打样制造。
- D3：需求、可靠性/认证适用项、ECO、产线测试和过程验证完成后的发布；必须真实样机/试产证据。本扩展不自动授予D3。

默认预览，不发送工厂、不下单。build-manifest中的授权记录不是让ChatGPT向第三方发送资料的授权。实际发送/下单仍须用户明确指令。

## 制造最终状态

先在新候选目录进行铜替换，refill→save→reload；再跑完整ERC/DRC/parity和规格审计。切勿在新旧铜并存时通过后直接删旧铜发厂。源文件不覆盖，所有失败保留原版且非零退出。

```bash
python3 scripts/netlist_guard.py base.xml candidate.xml --mode preserve --topology
python3 scripts/netlist_guard.py base.xml candidate.xml --mode eco --eco approved-eco.json
python3 scripts/link_audit.py candidate.kicad_pcb --profile link-profile.json
python3 scripts/assembly_guard.py production-bom.csv --cpl cpl.csv --variant default
python3 scripts/freeze_candidate.py /path/project --board board.kicad_pcb --destination /path/new-candidate
# 预览后仅显式加--apply才复制与重填候选工程
python3 scripts/validate_frozen_candidate.py /path/new-candidate --config /path/new-candidate/review-config.json --output-dir /path/new-final-evidence
```

路径审计当前对中心线图保守处理；焊盘边缘入线、复杂分支、过孔中间层接入等不能建立唯一受支持路径时BLOCKED，不能用累计长度补过。它不证明阻抗、回流连续或眼图达标。需模型/测试而未提供时不得生产。

制造包必须含完整逐层清单、钻孔/槽/PTH/NPTH与层对、制板/装配图、所选变体BOM/CPL和适用Paste/钢网资料。独立查看实际Gerber/Excellon而非PCB SVG；合法内槽/挖空逐一核对，不套“唯一外框”。底层制造文件不手工镜像。角度零点、底面规则、极性、DNP和针脚一须经PCBA审查。

build-manifest.json包含D2、源/输出哈希、工具版本、实际命令/日志、最终状态验证、绑定实际输出哈希的独立CAM JSON、已关闭EQ和生产授权。结构标记检查只是格式sanity，不是完整Gerber解释器；独立CAM及板厂审图不能省略。

高风险必须按rule/location/description内容指纹逐项补证据批准，不能按类型整体豁免；原生error与排除项仍阻断，禁止批量降级skew/unconnected、改网名逃过识别或删规则消警告。

## 已核对的一手依据

- KiCad10.0.7 CLI：https://docs.kicad.org/10.0/en/cli/cli.html
- KiCad10 PCB/API：https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- ADI混合信号布局：https://www.analog.com/en/resources/analog-dialogue/articles/what-are-the-basic-guidelines-for-layout-design-of-mixed-signal-pcbs.html
- TI SLLA414A：https://www.ti.com/lit/an/slla414/slla414.pdf
- Espressif ESP32-S3指南：https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/pcb-layout-design.html

这些文档支持设计方法与接口能力，不证明某个项目已通过认证。IPC/IEC受许可条款、具体器件数据和板厂工艺必须锁定适用版本，不虚构查阅或合规结论。
