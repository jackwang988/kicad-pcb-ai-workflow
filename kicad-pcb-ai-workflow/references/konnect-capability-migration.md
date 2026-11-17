# R10 Konnect MCP 单写入后端迁移（动态发现、风险分级、按需验收、记录复用）

**版本**：`R10-G1-G4-konnect-single-writer-migration-1`  
**状态**：策略与离线实现已接入；当前运行机器的真实MCP/GUI、制造等价性仍需现场验收。不要将离线测试报告复制为生产能力证明。

## 1. 原则与技术边界

- **不固定工具数、不设工具数量白名单**：根据当前运行的Konnect `list_toolboxes` → `load_toolset` → `tools/list` 动态发现；按任务加载，`--all-toolsets` 用于显式完整盘点。228/235仅属不同版本、不同加载状态的历史数量。
- **工具发现 ≠ 工具已验收 ≠ 当前工程通过**。L0读取可以在目标身份核对后调用；L1–L3写入先在独立测试工程完成能力验收，再操作实际候选，且每次项目要独立回读、DRC和签核。
- **Konnect是唯一活动EDA写入者**。原自研kicad_bridge的插件/serve/request/启动路径全部阻断，`pcb.edit`历史导航任务也阻断；`kicad_bridge drc`仍可只读。禁止Konnect失效后自动改用pcbnew写入。`freeze_candidate.py`不再调用`pcbnew.SaveBoard`或`ZONE_FILLER`。
- **Python仍负责纯计算、知识库、规则和快照分析**；KiCad CLI负责独立ERC/DRC、原生检查与制造候选导出。少数仅供只读使用的旧pcbnew审计代码保留迁移期兼容，缺少经过现场验证的等价Konnect数据时对应放行仍BLOCKED，不能用静态预览伪造原生校验。
- **独立版本信任**：原包固定Windows Konnect 0.14.1为历史档案。若升级到别的真实版本，不因新版本号自动信任二进制：先检查官方下载和许可，操作者明确建立包含真实SHA/版本/commit/适用KiCad版本的**本地**授权记录，之后才允许启动该程序并发现工具。能力验收按实际版本重新绑定，不直接沿用旧报告。

## 2. 四级风险控制（只影响执行前核查，绝不隐藏已发现工具）

| 等级 | 例子 | 执行前要求 |
|---|---|---|
| L0 | get/list/read/check等查询 | 验明后端和目标板；无工程源文件写入 |
| L1 | move/rotate/update 等常规编辑 | 对实际工具做独立候选的几何/网络专项验收，记录可恢复条件 |
| L2 | route/track/via/zone/fill/save等工程编辑 | 验证相关约束、能力、保存后原生DRC与连通性 |
| L3 | 删除、替换、批量优化、自动布线、未知工具 | 指定隔离样板与明确的对象变更验证；未验证默认阻断 |

等级根据名称进行**保守初筛**，不能将名称判定等同于执行安全证明。未知工具归L3，后续可以建立专项验证器，不会从发现清单移除。名称为 `get_*` 仍需验证实际没有意外改文件；参数中的外部文件引用必须按工程身份及候选限制核对。

## 3. 能力验收库

记录存放在Skill目录、项目目录和公开ZIP之外（例如工作站私有目录`konnect-acceptances.json`）。每个通过的验收项至少绑定：

`Konnect executable SHA-256 + server version + build commit + KiCad版本 + MCP tool名 + inputSchema SHA-256 + 实际验证的操作/几何范围 + 原样板哈希 + 执行后哈希 + 独立KiCad DRC证据`。

重新发现工具之后，只有上述字段与特定工程操作范围**全部匹配**，才可复用；不能以一个移动测试外推为全部布局/布线能力。即使已复用能力记录，当前工程的设计意图/已保护对象/布线连通/DRC/G3/G4仍须重新验证。

### 动态发现（不写PCB）

```bash
python scripts/konnect_capabilities.py discover \
  --executable /actual/path/to/konnect \
  --config /actual/path/to/konnect-config.json \
  --all-toolsets --output-dir /new/report/tool-discovery
```

如只需要某个工具集，把 `--all-toolsets` 换成重复的 `--toolset ACTUAL_NAME`；工具集名称来自实际`list_toolboxes`结果。命令不下载Konnect，不自行启动KiCad GUI，不做板修改。

### 查看某项能力状态（不写PCB）

```bash
python scripts/konnect_capabilities.py assess \
  --executable /actual/path/to/konnect --config /actual/path/to/konnect-config.json \
  --registry /private/konnect-acceptances.json \
  --toolset ACTUAL_TOOLSET --tool ACTUAL_TOOL \
  --scope 'placement:QFN-32:move-single:v1' \
  --board /candidate/project/main.kicad_pcb \
  --output-dir /new/report/assess
```

`ACCEPTED_WITHIN_RECORDED_SCOPE`表示曾有相同条件的夹具通过，**不是当前PCB通过**。`FIXTURE_REQUIRED`表示可按需验证而非永久禁止。实际字段/工具名取决于当前运行服务；示例字符串不保证某发行版存在该工具。

### 在隔离工程做一次真实功能验收（会写测试板）

1. 在另一个目录复制真实可打开的**专用测试工程**，把这份候选板在KiCad打开；不得以用户原板作为测试板。
2. 先按 `discover` 获取真实工具名、`inputSchema`，为指定能力准备 `arguments.json` 和 `expected.json`。
3. 执行（例如单器件位置修改，`expected.kind=placement`，包含实际应到的绝对坐标；工具的具体参数必须以实时schema为准）：

```bash
python scripts/konnect_capabilities.py fixture \
  --executable /actual/path/to/konnect --config /actual/path/to/config.json \
  --registry /private/konnect-acceptances.json \
  --toolset ACTUAL_TOOLSET --tool ACTUAL_MUTATION_TOOL \
  --scope 'placement:QFN-32:move-single:v1' \
  --source-board /immutable/test-source/main.kicad_pcb \
  --board /independent/test-candidate/main.kicad_pcb \
  --arguments /fixture/arguments.json --expected /fixture/expected.json \
  --kicad-cli /actual/path/to/kicad-cli \
  --output-dir /new/report/fixture --apply
```

当前自动验证器覆盖 **指定器件绝对位置的改变及其余器件位置不变**，以及 **zone fill新增铜区、多余非填铜对象不变**；不支持的工具类型不会自动获得PASS，需增加该对象类型的等价验证器。测试板必须能够通过独立的原生DRC（退出码0）。能力通过后才写外部注册表。工具超时后状态未知，不重放相对操作。

### 经匹配的验收记录调用实际工具（会写独立候选）

```bash
python scripts/konnect_capabilities.py invoke \
  --executable /actual/path/to/konnect --config /actual/path/to/config.json \
  --registry /private/konnect-acceptances.json \
  --toolset ACTUAL_TOOLSET --tool ACTUAL_MUTATION_TOOL \
  --scope 'placement:QFN-32:move-single:v1' \
  --source-board /original/project/main.kicad_pcb \
  --board /independent/candidate/main.kicad_pcb \
  --arguments /request/actual-arguments.json --save-after \
  --output-dir /new/report/operation --apply
```

`invoke`不会用一个工具失败自动调用另一个工具；日志状态只能是`OPERATION_EXECUTED_REQUIRES_PROJECT_REVIEW`，不能把MCP响应正确当成设计PASS。调用前必须保证候选是已打开的唯一目标PCB；后端对工具本身的其它文件副作用仍需相应能力验证约束。

### 新版冻结/覆铜交接

```bash
# 1) 仅复制出新的候选，不直接使用pcbnew覆铜
python scripts/freeze_candidate.py /original/project --board main.kicad_pcb \
  --destination /independent/candidate --apply

# 2) 通过经过zone-fill专项夹具验收的Konnect工具编辑候选并保存，留下invoke报告
# 3) 使用实际Konnect调用报告和CLI独立完成原生重载/DRC；无证据必阻断
python scripts/freeze_candidate.py /independent/candidate --board main.kicad_pcb \
  --finalize --operation-report /new/report/operation/konnect-capabilities.json \
  --kicad-cli /actual/path/to/kicad-cli
```

此机制需要实际Konnect返回匹配的覆铜工具并通过`zone_fill`夹具验收；若工具未提供或测试不通过，状态保持`KONNECT_HANDOFF_PENDING`，**不会偷偷启动pcbnew完成覆铜**。保存/原生重载仅证明对应范围，完整G4/DFX/NPI仍独立检查。

## 4. 还没有完成的真实接口替代，不能伪称已经通过

| 原有读取点 | 当前迁移状况 | 当前处理 |
|---|---|---|
| `konnect_backend.py`封装锁/放置预检 | 已改为只读KiCad文件解析+MCP实时对照，不再要求pcbnew | 保存/实时不一致或锁定阻断；复杂文件版本仍需真实板测试 |
| `freeze_candidate.py`覆铜保存 | 已换成Konnect写入交接+操作证据+CLI验证；本机真实覆铜工具未测试 | 夹具未通过则阻断 |
| `environment_start.py` | 默认CLI-only烟雾检查，不把pcbnew视作一般安装前提 | pcbnew旧版只读烟雾测试为可选 |
| `design_intent_audit.py`原生NetClass | **尚无经过真实KiCad验收的Konnect等价回读** | 该部分工程放行仍阻断/使用隔离只读兼容，不降规则 |
| `placement_review.py`原生几何 | **仍有只读pcbnew兼容路径** | 静态解析仅预览，不充当G3原生验证 |
| `hs_board_snapshot.py`高速铜几何 | **仍有只读pcbnew兼容路径** | 无相同等级证据时高速专项不能假通过 |
| `npi_common.py`/`mass_production_review.py` | **原生制造级几何/网类完整性未等价验证** | 无只读兼容依赖或等价能力记录时保留生产阻断 |
| `manufacturing_export.py` | 仍由KiCad CLI执行（只写新的输出目录），但上游量产门禁保留 | 不能绕过源工程质量检查 |
| `schematic_candidate.py`/`design_intent.py` | 离线新候选/规则文件生成器仍保留，仅用于独立候选的声明式预处理 | 不可与Konnect同时写活动工程，进入GUI后需独立确认 |
| `kicad_bridge.py` | 直接插件/请求/启动实时写入路径已禁用 | 只读Drc辅助仍在；不作回退 |

**执行范围提示**：自动化软件测试对的是策略、参数、状态、异常和文件哈希，不能证明当前机器已安装/启动Konnect，不能证明228/235项工具均已通过真实工程验收，也不能证明KiCad 11或复杂高速PCB支持。

## 5. 与原16节点的对应关系

- **01**：环境启动改成KiCad CLI + Konnect动态发现及版本固定；不强制pcbnew可用。
- **05/08/09/10**：AI根据器件知识卡、叠层和项目规则做决定；Python做算法与预检；Konnect作为唯一活动KiCad操作通道；当前工具缺少专项验收时本节点阻断而不是切回旧API。
- **06/07/09/11**：G1—G4仍复用节点3冻结知识卡，工程每阶段独立检查；更改操作后旧审核证据失效。
- **11/12/13**：原生CLI/ERC/DRC、完整规则/几何验证、人工签核及制造分离，旧版无法等价验证的局部保持`BLOCKED`，制造文件仍`EXPORTED_NOT_RELEASED`。
- **14—16**：CAM/工厂EQ/样机/ECO为外部扩展，AI不冒充真实生产签核。
