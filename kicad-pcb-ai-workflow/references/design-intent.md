# 原理图设计意图与PCB规则传递 · R9.3


## 目录

1. 工作方式与能力边界
2. 差分、电源、射频输入
3. 候选生成与生效审计
4. 安全和验证要求
5. KiCad10.0.7格式依据

## 1. 工作方式与能力边界

在原理图设计时声明每根关键网络的身份与约束。使用assets/design-intent.template.json；由AI根据用户要求、器件原厂指南、批准叠层/工艺填写，未知值保持null并阻断，不自动猜测。

数据链为：用户/原厂要求 → 精确网络名与引脚语义 → 原理图Net Class字段 → 项目类定义及精确匹配分配 → 原生Tuning Profile和逐层自定义规则 → 原理图更新PCB → 生效类/参数审计 → 最终ERC/DRC、SI/PI/热/CAM证据。

scripts/design_intent.py只在--apply时创建独立新候选目录，原工程完全保留。它向指定UUID的已有网络标签添加Net Class与隐藏Design Intent字段（记录配对/协议，或电流/温升/压降，或RF频率/功率/参考地/关联净空与回路，工程师可在标签属性中查看）；创建.kicad_pro类/分配/几何Profile；在同名.kicad_dru保留原规则并追加精确网络/层规则。它不会重命名网络、重新接线、自动执行F8，也不会自动完成布线。

同一KiCad工程使用共享项目规则，精确网络匹配使网络无需在PCB逐根手工分配。同步应使用KiCad原生“从原理图更新PCB”，随后运行audit --phase pre_route验证实际网络与有效类。没有官方后台原理图同步CLI的验证，不虚构此能力；AI可在具备授权与工具的环境操作原生同步，缺环境则停在候选。

目标10.0.7的Tuning Profile持久化格式已对照该版本官方源码核对。本版生成分层几何，**禁用时间域调谐、延迟字段为0**；不假造传播模型。时间域预算仍由link_audit与原厂/外部模型处理。GUI原生阻抗计算存在，但本脚本不自动操作其计算按钮、不宣称可用未验证CLI求解阻抗；接收工程师/板厂/工具批准的W/S。

## 2. 差分、电源、射频输入

### 差分与受控单端

- nets逐根声明完整网络名、kind、netclass、原理图label_uuid/file。只支持精确、无通配符的保守ASCII网络名；分层完整名必须与PCB一致，不能把局部标签名猜成完整网络路径。
- pairs必须给P/N、协议/PHY、chain_id与segment_index。生成器支持_P/_N或+/-，不混用；protocol仅接受已列出的USB2_HS/USB3/MIPI_DPHY/HDMI_TMDS/HDMI_FRL/ETH_MDI/PCIE/LVDS/DDR_DQS/DDR_CK；未知PHY或C-PHY三线组明确拒绝，不套两线差分。
- 串阻、AC耦合、共模器件两侧保留各自网络与配对；同一chain_id表示工程链路，不会因此在KiCad短接不同网络，也不宣称原生差分工具能跨任意器件求总延迟。
- classes要求正式类定义、间距、逐层线宽上下限/目标、差分间距上下限/目标、参考层、阻抗目标/容差、stackup_sha256、来源与真实批准证据。目标阻抗不能代替几何参数。
- 类可自动绑定原生DI_<类名>几何Profile，并开启tuning_profile_track_geometries等DRC为error；逐层.dru约束防止只配置默认值而不验收。
- coverage要求经评审的完整critical_nets清单，与声明逐根相等；另筛查PCB中未声明的_P/_N候选。命名筛查不是全网语义识别，工程师仍需从全部接口/电源清单审查覆盖完整性。

### 电源

原理图字段记录持续与峰值电流；完整数字保留于intent JSON。用户只提供“2A”时，追问或根据真实资料补齐以下条件，不能直接给固定宽度：

| 字段 | 含义 |
|---|---|
| continuous_a / peak_a | 保守持续电流与峰值电流，peak不得小于continuous |
| peak_duration_ms / peak_duty_cycle | 峰值持续时间与占空比；交由热/故障证据验证，不能仅看平均电流 |
| ambient_c / max_temp_rise_c / max_conductor_c | 最坏环境、允许温升与用于电阻估算的最高铜温 |
| max_drop_v / max_peak_drop_v | 稳态及峰值时允许的这段铜线压降 |
| max_path_length_mm | 预算采用的最大铜线路径长度 |
| layer_copper_um | 各允许走线层的经批准成品最小铜厚，单位µm |
| thermal_min_width_mm | 各层经外部热/载流分析批准的最小线宽，不套统一内外层系数 |
| stackup_sha256 / approval | 绑定实际叠层、分析来源、批准人/日期及真实文件哈希 |
| layout_review | 当前布局的过孔载流、焊盘颈缩、铜皮瓶颈、回流、触点、故障保护、瞬态热逐项PASS证据 |

支持single_uniform_trace保守模型：以铜电阻率与温度系数计算R=ρL/(wt)、稳态/峰值压降下限、I²R及两状态RMS上界。最小宽度取稳态压降、峰值压降、外部批准热宽度三者最大值。

**这是铜线直流预算，不是IPC-2152载流求解，也不是整路电源仿真。** 并联铜/分支/电源面、电感/连接器/过孔/焊盘与返回路径、保险丝和故障能量均须独立分析。累计段长仅做保守筛查；复杂电流分配不得套本模型自动放行。热批准应覆盖RMS、脉冲、铜厚公差及真实散热条件。

audit检查已有segment/arc的层、最小宽度和预算长度；任何窄颈与过孔不能因为主干较宽而自动忽略。后续layout_review缺失或不匹配当前布局摘要就阻断。

### 射频、天线与回路

- RF馈线按单端受控阻抗类处理：频率、功率dBm、目标/容差、允许层、参考层/网络、最大长度、原厂匹配与回流评审均必须明确。
- **馈线参考地与天线净空分别声明。** 不能把“射频下方净空”套用到所有RF走线；通常馈线需要连续参考地，辐射区域按具体天线手册净空。特殊匹配焊盘局部挖空也必须有原厂依据，本版不猜测。
- regions必须以rf_net关联具体RF馈线；当前仅支持明确PCB坐标、逐层声明的矩形antenna_keepout，生成真正KiCad rule-area zone，禁止区域内track/via/pad/copperpour/footprint。它不是普通图形或文字。天线器件anchor位置/角度变化即阻断，需重新定位区域。
- 原理图还没有布局坐标时，先记录天线角色与净空要求；保留待定位状态，进入PCB后完成坐标与审批再生成禁布区。不能从原理图自动推断板上区域。
- 需要保留天线本体铜形、区域内器件或复杂开窗的设计，不适用该“全部禁止”矩形模板；必须按实际对象设置原生区域/自定义规则并做独立验证，不能关闭限制强行通过。
- loops声明实际电流回路网络、面积上限、当前布局layout_sha256、测量/求解方法及实测面积。**不以器件中心包围盒代替实际高di/dt回路面积**，不从“单根线”推断完整回流。
- 本版不求解射频场、S参数、天线效率或EMC；净空生成不证明天线性能，回流/匹配/整机测试仍需证据。

## 3. 候选生成与生效审计

先复制模板填真实数据。证据统一为file/sha256数组；审批含source.document/revision/section、reviewer、ISO date和reason。模板null不能通过。布局摘要与叠层摘要可通过Python调用layout_digest/stackup_digest生成；生成摘要本身不是批准。

```bash
# 只预览，无任何工程写入
python3 scripts/design_intent.py /path/project --intent /path/project/design-intent.json --destination /path/new-intent-candidate
# 审阅后创建独立新副本（仍是未验证候选）
python3 scripts/design_intent.py /path/project --intent /path/project/design-intent.json --destination /path/new-intent-candidate --apply
# 在真实KiCad工程中同步原理图到PCB后核对
python3 scripts/design_intent_audit.py /path/new-intent-candidate --intent /path/new-intent-candidate/design-intent.json --phase pre_route
# 布线完成后执行最终范围
python3 scripts/design_intent_audit.py /path/new-intent-candidate --intent /path/new-intent-candidate/design-intent.json --phase final
```

将review-config.json中design_intent设置为该工程内相对路径；量产评审将强制执行本审计，缺配置直接阻断。project_file/board_file必须对应当前评审工程。模板内的审批/库/规则/意图文件纳入engineering_profile.source_files和基线流程。

native audit在临时副本用SETTINGS_MANAGER.LoadProject、LoadBoard、SetProject、SynchronizeNetsAndNetClasses(False)及逐网GetNetClass核对实际类成员、默认宽度/间距、clearance和Profile；核对源JSON的分层几何及.dru完整性。API缺失/失败/版本不符均阻断；不会把静态解析当原生成功。

pre_route只验证规则准备状态，允许尚未布线并延后最终电源/RF/回路布局证据；final要求已布线及当前布局证据，量产集成固定调用final。两阶段均不自动同步原理图。

audit不独立签发生产授权，即使返回PASS也只代表此模块范围通过。仍须完整NPI流程最终refill/save/reload、ERC/DRC/parity、路径与物料一致性、CAM/EQ、授权。

复核真实项目：

```bash
python3 scripts/design_intent.py /path/project --intent /path/project/intent.json --destination /path/new-candidate
# 默认预览；授权后--apply只写新候选。原生同步并确认规则后：
python3 scripts/design_intent_audit.py /path/new-candidate --intent /path/new-candidate/intent.json --phase pre_route
```

## 4. 安全和验证要求

- 历史项目脚本独立归档，不随运行包安装，不作为设计或发布判据。
- 原理图字段只对明确已有标签UUID追加，不暗中重命名或移动电气连接。新设计由Agent先按原厂引脚语义创建正确标签；旧设计名称调整走ECO。
- 工程修改只写新副本，目录存在/越界/符号链接/现有类与生成规则冲突均拒绝。保留原.dru规则，不覆盖已有类；重复编译从批准原版开始。
- 数字假设与真实证据分别记录；来源空、证据变化、叠层变化、实际几何超限、类被其它高优先级类覆盖均阻断。
- 修改布局后必须重新评审layout_sha256对应的RF/电源/回路证据；不能只更新哈希。设计意图变化需重生成规则、更新批准基线并完整重验。
- 原生打开/同步/Profile加载/规则解析/DRC须在目标工程实际验证；CLI/pcbnew基础接通不能证明全部设计意图或整板链路已验收。

## 5. KiCad10.0.7格式依据

实现采用公开字段结构与独立Python代码，不复制KiCad实现代码。源码路径均锁定10.0.7，不能用master中后续schema替换。

- [官方原理图Net classes](https://docs.kicad.org/10.0/en/eeschema/eeschema.html)：Net Class字段、原生指令与精确匹配。
- [官方PCB规则与Tuning profiles](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html)：分层几何、原生计算、可选几何DRC、diff_pair_gap等。
- [10.0.7 net_settings.cpp](https://github.com/KiCad/kicad-source-mirror/blob/10.0.7/common/project/net_settings.cpp)：net_settings schema5、classes、netclass_patterns、tuning_profile。
- [10.0.7 tuning_profiles.cpp](https://github.com/KiCad/kicad-source-mirror/blob/10.0.7/common/project/tuning_profiles.cpp)：schema0、tuning_profiles_impedance_geometric、layer_entries等。
- [10.0.7 tuning_profiles.h](https://github.com/KiCad/kicad-source-mirror/blob/10.0.7/include/project/tuning_profiles.h)：SINGLE=0/DIFFERENTIAL=1及原生字段。
- [10.0.7项目样例](https://github.com/KiCad/kicad-source-mirror/blob/10.0.7/qa/data/pcbnew/issue24543/issue24543.kicad_pro)及[原理图样例](https://github.com/KiCad/kicad-source-mirror/blob/10.0.7/qa/data/eeschema/issue24328/issue24328.kicad_sch)：结构核对；不等于本Skill实测通过。
- [Espressif ESP32-C3射频与天线布局指南](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32c3/pcb-layout-design.html)：馈线/参考地与天线区域分开；其数值不外推到其它天线。
