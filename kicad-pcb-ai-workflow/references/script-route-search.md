# 实验性离线网格路径搜索

`script_route_search.py` 提供**真实可运行**的八方向、多层A*，解决显式归一化网格中一条普通连接的路径搜索。它是离线实验功能，不从PCB自动提取网格，不改KiCad文件，不运行原生DRC，不是已验收的执行后端，也不证明完整PCB可布通、电气合格或可制造。

## 1. 入口

```bash
python scripts/script_route_search.py /path/project --problem route-problem.json
python scripts/script_route_search.py /path/project --problem route-problem.json --output-dir /path/new-route-search
```

问题文件及绑定源文件位于项目内。可选输出目录必须全新，只写 `route-plan.json`。Python入口为 `search(project, problem_file)`；问题相对路径以项目为根。该脚本不接受外部命令、不启动路由程序或shell。

从 `assets/route-problem.template.json` 建立问题；模板的null及false表示尚未完成归一化，故不能直接通过。不要为了试跑把未知输入改成看似合理的数值或把false改成true。

## 2. 实际实现范围

- 仅 `scope=ordinary_single_connection`，明确分类为 `LOW_SPEED_DIGITAL|GENERAL_SIGNAL` 的一条起终点连接；分类依据和最快边沿等适用条件需由项目审查确定。
- 八方向走线：水平/垂直步长1，斜向步长√2；使用octile距离作为下界，不使用会高估斜线成本的曼哈顿距离。
- 每层水平/垂直/无首选方向，非首选方向仅增加非负代价；允许必要的同层换向。可配置非负弯折代价。
- 搜索状态保留 `(x,y,layer,used_vias,heading)`，不会把相同位置/层上较长但剩余过孔预算更多的路径丢掉。未实现时延、差分耦合或多网络协商求解。
- 禁止对角切角：对角步的两个相邻正交网格都必须可用。
- 仅通孔候选，落点必须位于显式 `via_sites` 白名单；每次换层占用一个过孔预算。每个候选通孔按全物理铜层跨度检查归一化障碍，不能跳过内层障碍，也不能沿受保护平面走信号。
- 受时间、扩展状态、已发现状态及队列大小共同约束；不因输入大而无限搜索。单问题最多8个物理铜层、100万物理格、20万搜索状态、8次通孔换层、60秒。多层能力只针对这个归一化数学模型，不表示对应多层PCB工程已经验收。

未实现：PCB几何提取、精确实体碰撞、自动布局、全板多网络、rip-up、Shove、差分/DDR/RF/功率专用算法、盲埋孔/微孔、SI/PI/热求解、真实铜连通或KiCad执行。必要约束不在当前支持范围即BLOCKED，不靠删除约束继续。

## 3. 输入契约与归一化责任

问题绑定 `source_files.board/rules/normalization_basis` 三个源文件的真实SHA-256；开始和结束均检查，变化即撤销输出候选。哈希证明字节绑定，不证明网格是从这些文件正确提取。提取来源、适用规则、坐标变换、端点对应的实际引脚/焊盘及人工核对记录应保存在 `normalization_basis`，并由后续独立适配验收负责。

`normalization` 明确：

- `grid_pitch_mm`、`origin_mm=[x,y]`、当前连接的 `trace_width_mm/clearance_mm`。
- `trace_envelope_inflated=true`：所有障碍已经按该线宽、适用间距、孔/槽、禁布和板边等保守膨胀并栅格化。它是显式前提，不是本工具执行的几何膨胀。
- 若允许过孔，必须 `via_envelope_all_layers_inflated=true`：落点已考虑完整通孔的铜径、钻孔、全层跨度与相应间距；不能只对当前两个信号层检查。未完成时保持false并阻断过孔搜索。

`layers` 按全部物理铜层的 `F.Cu/In1.Cu/.../B.Cu` 顺序填写。每层含 `role`、`signal_enabled`、`preferred_direction`、`nonpreferred_penalty`；参考/电源平面必须禁用信号且列入 `protected_plane_layers`。`allowed_signal_layers`只能选择允许走信号的层。`blocked_cells`必须显式列出每个物理铜层，即使为空也需声明。

`via_sites`只表示已经按归一化依据许可的候选点；它不授权自动移除地铜、生成反焊盘或破坏参考面。换层时所有物理层对应网格必须无障碍。现有平面和连接复杂时，归一化可能保守地找不到路线，不能放宽障碍以追求成功。

起终点是网格中心，必须位于允许信号层、边界内且非障碍。它们与真实导电对象、同网及引脚端点的映射需要另行确认。相同格/同层端点直接阻断，避免把分辨率不足导致的端点合并当已连通。

支持的 `required_constraints` 仅为 `grid_clearance/layer_restrictions/protected_planes/via_budget`，四项均须显式声明。实际项目若还需要差分阻抗、时序、功率、Kelvin等约束，本工具不能处理，不得省略这些要求来获得可用路线。

## 4. 结果与失败区分

| 状态 | 含义 | 退出码 |
|---|---|---|
| `GRID_ROUTE_FOUND_NOT_NATIVE_VERIFIED` | 当前显式网格找到候选；输出网格路径、逐步track/via候选和代价 | 0 |
| `NO_ROUTE_WITHIN_BUDGET` | 时间、扩展、状态或队列预算耗尽；不证明无解 | 1 |
| `NO_ROUTE_IN_DECLARED_GRID` | 此归一化网格的可达搜索空间耗尽；不证明真实PCB无合法路线 | 1 |
| `BLOCKED` | 缺绑定、哈希漂移、不适用约束、错误归一化、保护冲突或非法输入 | 2 |

所有输出含 `execution_scope=experimental_offline_grid_planning`、`executed_on_pcb=false`、`accepted_execution_backend=false`、`native_validation=NOT_RUN`、`electrical_validation=NOT_VERIFIED`、`production_authorized=false`。

`composite_grid_cost`是长度、非首选方向、弯折和通孔的抽象搜索代价；`trace_length_mm`仅统计平面线段，不含通孔桶长/封装/端点内部或电气时延。输出代价不能直接当工程信号质量或制造成本。

## 5. 与受控布线入口的关系

该实验工具可供人工检查路径算法或后续适配器研发，不能把其成功结果登记成 `routing_policy.py` 所要求的KiCad端到端验收。也不能直接将网格成功结果当作 `NO_ROUTE_WITHIN_BUDGET` 回退记录：二者的源绑定、目标和验收范围不同，须由真实执行编排器明确转换并记录。

向KiCad投影前，需要实际板框/铜/孔/净空/规则解析与坐标校验，向独立候选写入，原生回读、覆铜、保存/重载、DRC/parity、全网连通和保护对象对账；再完成适用电气及工程评审。现有G1–G6、制造候选和放行边界继续有效。

软件测试覆盖八方向路径、避障与禁止切角、多层与过孔预算资源状态、通孔内层障碍、保护平面、各类预算与源变化、真实CLI报告及独立Dijkstra小网格对照。这些是软件算法合同证据，不是板级设计或制造验收。
