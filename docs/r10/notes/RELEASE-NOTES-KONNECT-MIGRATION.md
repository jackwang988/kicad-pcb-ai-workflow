# KiCad PCB AI Skill R10：Konnect MCP 单写入后端迁移报告

**交付版本**：`R10.0-alpha.3-local.5+G1-G4+konnect-single-writer-migration-1`  
**范围**：在上一个“节点3器件知识库Cache-First＋G1/G2/G3/G4复用”完整包的基础上增量升级。  
**交付状态**：已完成代码与离线回归，**未完成运行用户Windows电脑上的Konnect/KiCad现场验收**，不表示已通过复杂PCB自动布局布线或制造放行。

## 一、当前架构（已实施的软件规则）

- **AI**：获取需求、选取器件知识卡、判断工程风险，制定工作计划和修复方案。
- **Python**：设备缓存、算法、规则和证据审查；默认**不通过pcbnew向活动KiCad PCB写入**。
- **Konnect MCP**：作为唯一允许对活动KiCad设计实施修改的工具调用通道；按现场实际工具集动态发现所有工具，按风险分级和现场夹具测试放行。
- **KiCad CLI**：在候选工程保存后独立执行原生ERC/DRC；必要时生产文件导出，但绝不替代人类CAM、EQ、生产授权。
- **硬件工程师**：每个新项目独立确认G1/G2/G3/G4。节点14–16仍属于外部人员参与的生产、样机、ECO流程。

## 二、本次实际变更

| 改造项 | 当前交付状态 | 说明 |
|---|---|---|
| 全工具动态发现 | 已编码／离线验证 | 根据真实MCP `list_toolboxes`、`load_toolset`、`tools/list` 获取；不写死228或235个工具，不隐藏未验收工具 |
| 风险分级 | 已编码／离线验证 | L0只读、L1普通编辑、L2布线覆铜等、L3未知／危险操作；风险判定是保守初筛，不等于安全证明 |
| 按需能力验收 | 已编码／离线验证 | 需要独立测试项目、预期几何、保存结果及真实CLI DRC；目前自动验收器只覆盖指定器件位置和限定覆铜情形 |
| 验收记录复用 | 已编码／离线验证 | 精确绑定Konnect可执行文件哈希、版本、构建、工具schema、KiCad版本和操作范围，核对原生DRC证据哈希 |
| 原自研实时写入入口 | 已禁用 | `kicad_bridge`历史实时编辑路径及 `pcb.edit` 调度返回明确阻断，不静默切回pcbnew |
| PCB覆铜／冻结 | 已改为Konnect交接 | `freeze_candidate.py`先复制独立候选并生成handoff；仅接受已验收Konnect覆铜、保存后的报告，再执行CLI重载／DRC；不能直接用pcbnew填铜 |
| 项目调度 | 已接入 | `workflow.py`登记discover/assess/fixture/invoke；写操作要求明确`--apply` |
| 安装诊断 | 已调整 | 一般环境检查默认CLI-only，不把旧pcbnew绑定当成全部功能的硬前提 |
| 器件知识库与G1–G4复用 | 完整保留 | 不重复网络搜索或全文解析已审核资料；每个项目仍需独立ERC/DRC与工程确认 |
| 完全去除pcbnew | **未完成** | 原生规则回读、部分高精度几何审计和DFX/NPI仍保留只读兼容依赖，尚无经现场确认的Konnect等价数据接口 |

## 三、重要限制，避免误用

1. **“全部可发现”不是“全部自动放行”**。工具能被看见不代表它在该版本、该项目和该操作范围下可靠。
2. 没有真实Konnect二进制与正在打开的KiCad候选工程，不能进行物理MCP验收；本次只有离线单元测试，**不会宣称所有Konnect工具都已测试通过**。
3. 未完成同等级读取能力迁移的检测项必须保留严格门禁，不能为了取消pcbnew而跳过 NetClass、几何、高速或制造预检查。
4. Konnect失败、超时或版本变化时，**不自动重试未知结果的写入操作**，也不自动切换到另一写入后端。
5. 新旧版本的KiCad/ Konnect并不能仅按版本号大小判断兼容，必须在本地确认实际API、工具schema和保存结果。
6. 只使用合法安装且已审核来源的Konnect；其可执行文件及第三方商业组件**不包含**在公开ZIP中。

## 四、实际可用的新入口

在Skill根目录使用命令（把占位符替换为本机真实文件路径；真实工具名必须从发现结果取得）。

**1. 发现所有工具：**

```bash
python scripts/konnect_capabilities.py discover \
  --executable /actual/konnect --config /actual/konnect-config.json \
  --all-toolsets --output-dir /new/report/discovery
```

**2. 查询某项能力是否已有匹配验收记录：**

```bash
python scripts/konnect_capabilities.py assess \
  --executable /actual/konnect --config /actual/konnect-config.json \
  --registry /private/konnect-acceptances.json \
  --toolset ACTUAL_TOOLSET --tool ACTUAL_TOOL \
  --scope 'placement:QFN-32:move-single:v1' \
  --board /candidate/main.kicad_pcb --output-dir /new/report/assessment
```

**3. 首次写入能力的隔离工程验收：**

```bash
python scripts/konnect_capabilities.py fixture \
  --executable /actual/konnect --config /actual/konnect-config.json \
  --registry /private/konnect-acceptances.json \
  --toolset ACTUAL_TOOLSET --tool ACTUAL_MUTATION_TOOL \
  --scope 'placement:QFN-32:move-single:v1' \
  --source-board /immutable/test-source/main.kicad_pcb \
  --board /independent/test-candidate/main.kicad_pcb \
  --arguments /fixture/arguments.json --expected /fixture/expected.json \
  --kicad-cli /actual/kicad-cli --output-dir /new/report/fixture --apply
```

**4. 复用成功验收记录后修改独立候选：**

```bash
python scripts/konnect_capabilities.py invoke \
  --executable /actual/konnect --config /actual/konnect-config.json \
  --registry /private/konnect-acceptances.json \
  --toolset ACTUAL_TOOLSET --tool ACTUAL_MUTATION_TOOL \
  --scope 'placement:QFN-32:move-single:v1' \
  --source-board /original/main.kicad_pcb \
  --board /independent/candidate/main.kicad_pcb \
  --arguments /request/arguments.json --save-after \
  --output-dir /new/report/invoke --apply
```

这些示例假设已在KiCad打开**候选**且工具真实存在；CLI不会自动启动KiCad，不会自动下载后端。未知Konnect版本需先人工审核来源并建立本地显式SHA固定记录，不能仅凭用户项目文件自声明许可。

## 五、后续现场验收清单（软件迁移之后必做）

1. 在目标Windows电脑确认KiCad版本、CLI以及Konnect已合法安装、可执行二进制SHA与实际服务构建一致。
2. 在**独立、可抛弃**的PCB样板工程中逐项发现并测试器件移动/旋转/丝印编辑、保存重载、普通布线、过孔、覆铜。
3. 对每一类操作在测试前明确预期对象、坐标、网络、约束与保护范围；变更后回读并执行独立CLI DRC。
4. 为 NetClass/几何/复杂铜区/高速专项建立同等级Konnect读取适配器与差异测试；验证通过后才可以移除剩余的pcbnew只读依赖。
5. 用完整项目跑通节点1–13的G1–G4审核、布局/布线、覆铜、制造候选导出及阻断路径；节点14–16仍须人工授权。
6. 完成回归后再考虑合并进GitHub main及生成正式安装包。

## 六、软件测试结果

本次通过 **33/33项离线单元测试**：包含上一版器件知识库复用、G1–G4读取与检查；新增动态工具发现、风险等级、完整身份约束、未知工具不自动验收、原桥写入阻断、候选冻结防护、`--apply`授权和DRC验收证据篡改失效等。软件语法、JSON和44个登记工具文件哈希均再次核对。

**最终状态**：`MIGRATION_CODE_READY — REAL_KONNECT/KICAD_VALIDATION_PENDING`。这是**受控迁移版本**，不是“已将全部pcbnew功能无条件等价替换完毕”的版本。
