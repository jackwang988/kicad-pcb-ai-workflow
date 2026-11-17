> 本地修订：先读[主流程与执行修订](design-execution-local.md)。下文六组/16节点与G5/G6为历史兼容资料；当前AI设计主线删除第六阶段，截止DESIGN_PACKAGE_READY_FOR_REVIEW。外部制造/样机/ECO仅按另行任务调用；既有安全门禁保留。

# 脚本优先的受控布线请求与后端预检

`routing_policy.py` 是实际可运行的只读策略工具，负责校验请求、核对绑定文件、选择具备适用验收记录的后端并输出计划。它不是通用 Router，不执行后端、shell、KiCad编辑或DRC，不生成走线，不授予制造许可。所有结果均含 `execution_scope=planning_only`、`executed=false`、`production_authorized=false`。

继续复用 `design_intent.py` 的项目化规则编译和 `design_intent_audit.py` 的核对基础，不再编译第二套规则。NetClass推荐线宽/差分间距不等于min/max DRC约束；规则编译、实际命中及故意违规反例需另外验证。此工具只检查声明与文件，不证明参数计算正确、原厂资料适用或原生规则已经生效。

## 1. 调用与状态

```bash
python scripts/routing_policy.py preflight /path/project --request routing-request.json
python scripts/routing_policy.py plan /path/project --request routing-request.json --output-dir /path/new-routing-plan
python scripts/routing_policy.py plan /path/project --request routing-request.json --after-attempt failed-attempt.json
```

`--request`、`--after-attempt` 中的相对路径以项目为根；输入和证据仅接受项目内文件，不跟随符号链接逃出项目。可选报告目录必须全新；缺参数模板不自动补数值。

| 状态 | 含义 |
|---|---|
| `PREFLIGHT_READY_NOT_EXECUTED` | 请求和适用后端记录符合声明检查，未执行布线 |
| `PLAN_READY_NOT_EXECUTED` | 已选择后端并列出范围/预算，未执行布线 |
| `PENDING_BACKEND_ACCEPTANCE` | 没有后端或缺少/过期的验收记录；不能假装已接通 |
| `BLOCKED` | 缺规则、哈希失配、未知能力、保护冲突、不适用后端或其他请求错误 |

就绪状态退出0，其余退出2。就绪不表示PCB、DRC或电气检查通过。

## 2. 请求与工程绑定

从 `assets/routing-request.template.json` 建立请求。`null` 是待补输入，模板本身不能通过检查。

- `schema_version=1`、`request_id`、`strategy=script_planned`、`phase=incremental|final`。
- `runtime` 明确声明 `platform=windows|linux|macos`、精确KiCad版本、API版本。这里不探测运行进程，实际执行前仍需环境与连接验证。
- `inputs` 分别绑定 `board`、原生XML `netlist`、`stackup`、有效 `rules`、`protected_objects` 的 `file/sha256`。文件修改即失效，不替换为自动更新哈希。
- 每个目标网络有显式工程类别、必要约束及原厂/项目依据的文件哈希与定位。名称和前缀不推导参数。`parameters` 不允许空对象、null或非有限数；具体阈值的单位、正负值及电气适用性仍需现有规则编译器和工程审查负责。
- `pending_connections` 用稳定ID记录当前待连接项，端点精确绑定网表 `ref/pin`；`target_connection_ids` 选择本轮范围。程序核对声明端点的网表归属，不自行推算真实铜连通或认证待布清单完整性。
- `budgets` 必填总秒数、迭代数、最大过孔数与种子；允许0个过孔。若允许过孔，每个目标网络必须另有 `via_geometry/hole_clearance`。预算是计划上限，后端执行器仍须实施这些上限。

所有目标至少声明铜间距、线宽、板边间距和keepout约束。差分/时序/RF/大电流等类别会额外要求对应约束；这不是完整电路分类或SI/PI求解器。`MANUAL_ONLY`不得自动布线。不明特殊要求应先补资料与规则，不能改为普通网络绕过。

### 层策略文件

它是绑定于实际PCB铜层的路由使用声明，不是叠层或阻抗计算器。铜层名称与顺序必须匹配PCB，示例数值不提供制造依据：

```json
{"schema_version":1,"layers":[
  {"name":"F.Cu","role":"signal","signal_enabled":true},
  {"name":"B.Cu","role":"reference_plane","signal_enabled":false}
]}
```

允许 `role=signal|reference_plane|power_plane|mixed`。参考/电源平面不得启用信号走线，必须列入保护；`allowed_signal_layers`只能选实际允许的信号铜层。四层及更复杂情况需真实叠层、参考/回流与平面完整性专项验证，不因声明层数就视为支持。该工具读取静态铜层/UUID/部分几何特征以筛查能力，不执行原生精确几何或连续参考面分析。

### 保护对象文件

```json
{"schema_version":1,"locked_policy":"preserve_all",
 "object_uuids":[],"plane_layers":["B.Cu"],"nets":["GND"]}
```

显式UUID必须真实存在。所有已锁对象隐含保护；默认保留全部既有对象，只有请求 `reroutable_uuids` 中的既有segment/arc/via可供后续执行器重布。白名单不能包含锁定对象、保护对象、保护网、保护平面的走线或非走线对象。后续实际delta必须逐项对账，预检不代替修改后保护验证。

## 3. 后端登记与验收记录

请求 `backends` 为描述数组；字段严格限定为 `id/kind/version/artifact/acceptance`，禁止命令、shell或自定义启动参数。`artifact` 和 `acceptance` 都是 `file/sha256`。`kind`仅接受 `native_script|freerouting`；不捆绑也不默认登记任何第三方路由器。

验收JSON必须含：

- `schema_version=1`、`record_type=routing_backend_acceptance`、`decision=accepted`。
- `backend` 精确匹配登记的 `id/kind/version/artifact`。
- `checked_on/expires_on` ISO日期、真实 `reviewer/reason`，且未超请求的 `acceptance_max_age_days`（1–365）。
- `scope=kicad_end_to_end`。只有 `dsn_to_ses` 的记录不能取得KiCad闭环资格。
- `runtime` 的 `platform/kicad_version/api_version` 各为经实际验收的字符串数组，包含本次精确环境；不允许通配符代替版本验收。
- `constraints`、`capabilities` 明确枚举经过验收的范围；未知名称或本次所需能力缺失拒绝选择。名称定义见脚本 `CONSTRAINTS/CAPABILITIES`。底面、旋转、pad形状、arc/slot等观察到的几何会增加能力要求。
- `evidence` 包含六种工件绑定：`native_drc/netlist_parity/save_reload/protected_object_diff/rule_hits/connectivity`，每项为 `kind/file/sha256`。这些应来自实际独立验收，不能填测试夹具或代签记录。

**记录校验仅证明所声明记录与工件字节存在、身份/版本/范围一致且未过期；不认证人员身份，不判断报告内容真伪，不替代实际原生复验。** 伪造 `passed=true` 不增加能力，不授予执行或制造资格。测试中使用的合成记录仅验证软件合同。

满足同一请求全部条件时，`native_script`优先于`freerouting`，同类按ID稳定排序。脚本无验收时不会被选；有验收的其他后端仍必须满足同一硬约束。这里的“脚本优先”不是把临时项目代码自动登记为可信工具。

当前独立 `freerouting_adapter.py` 仅DSN→SES，不等于本节要求的KiCad端到端后端。真实DSN导出、SES回导、规则保真、覆铜、DRC及保护回读的适配验收完成前，不填闭环accepted记录。

## 4. 失败与受控回退

只有真实运行记录的 `NO_ROUTE_WITHIN_BUDGET` 允许工具继续规划另一具备同等能力的已验收后端；预算用尽不证明不存在合法路线。`RULES_MISSING`、不支持必要约束、工程漂移或保护破坏不能通过换后端绕过。

失败记录 `schema_version=1` 必须绑定 `request_sha256`、初始 `board_sha256`、当前首选 `backend_id`，记录 `status=NO_ROUTE_WITHIN_BUDGET`、非空 `remaining_connection_ids` 及真实日志 `evidence`（file/sha256数组）。工具仅校验声明及字节，不运行日志命令，不将日志中“通过”当原生证据。

本工具的回退计划基于**原请求检查点**，仍覆盖原目标集合，不能从失败日志猜测并复用部分新增铜。要保留部分已完成走线，必须先由真实适配器和独立验证器验收该候选，再建立绑定其新板/网表/规则/保护状态的新请求；不用整个设计回退到空板，也不修改原始工程。

## 5. 中间状态与最终状态

`incremental`仅可把本次明确目标外的待布项列入 `remaining_connections_after_target_scope`。后续真实执行检查允许这些逐项声明的待连接状态，禁止按整个告警类别豁免，也不得新增短路、几何违规或破坏既有连接。

`final`要求目标覆盖全部**已声明**待连接项，但仍只产生未执行计划。实际最终验证必须从原生填铜后的全网连接图重新核对全体必要端点，包括GND，不依赖声明清单来证明没有遗漏。

无论使用哪个后端，真实候选都需原生回读、重新覆铜、保存/重载、完整DRC/parity、保护对象差异、规则命中和适用工程专项验证。地网连通不等于高频回流连续，几何线宽/线长达标不等于SI/PI/热性能验证。保留现有G1–G6、AI/工程师确认和 `EXPORTED_NOT_RELEASED` 边界。
