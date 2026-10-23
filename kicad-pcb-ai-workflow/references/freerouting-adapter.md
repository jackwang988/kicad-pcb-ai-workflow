# 可选 Freerouting v2.5.0 适配器（实验性）

适用范围：**已布局的 KiCad PCB → 用户在 KiCad PCB Editor 导出 Specctra DSN → Freerouting CLI 产生 SES → 用户在 KiCad PCB Editor 导入 SES → 原生 DRC/逐层审查**。

不随 Skill 捆绑 Java 或 Freerouting，也不添加必需安装依赖。未安装/未识别 v2.5.0 时输出 `MANUAL_ROUTING_FALLBACK`，继续原有 KiCad 人工交互布线。适配器是**独立可选命令**，目前**未注册为既有 tool-manifest 的强制任务**，不能声称已进入 R9 的统一工作流门禁。

官方对应版本资料：
- https://github.com/freerouting/freerouting/tree/v2.5.0/docs
- https://github.com/freerouting/freerouting/blob/v2.5.0/docs/command_line_arguments.md
- https://github.com/freerouting/freerouting/releases/tag/v2.5.0

## 使用方法

1. KiCad 10 PCB Editor 完成正确封装/网络/叠层/板框/布局，在 GUI 中运行前置 DRC，按项目评审确定可由自动布线器处理的网络。**控制阻抗、RF、差分、高速、功率/热关键路径优先由工程师布线并审定**。
2. 在 KiCad GUI 使用 File → Export → Specctra DSN，将 `board.dsn` 导出到隔离目录。不要假设 `kicad-cli` 有经过验证的统一 DSN 导出命令。
3. 预览：

```bash
python3 scripts/freerouting_adapter.py --dsn /path/board.dsn --jar /path/freerouting-2.5.0.jar --output-dir /path/new-routing-result
```

4. 预览确认后，重复同一命令加 `--apply`。可选 `--passes 10 --threads 1 --timeout 1800 --expected-jar-sha256 <trusted_sha256>`。输出隔离目录必须不存在。只验证来自 JAR 元数据的 v2.5.0 身份；分发包若缺失版本证据，会安全回退人工布线，不能通过改名绕过。严格供应链要求必须同时提供可信校验值。
5. 找到生成的 `board.ses` 和 `freerouting-result.json`。在 **KiCad PCB Editor** 中将 SES 导入**工程副本**，检查导入错误、实际未连线、所有网络/过孔、DRC、布局干涉、阻抗和回流；确认后再由工程师合入正式工程。SES 存在**不等于**可生产。
6. 保存 PCB，按既有 `pcb.placement_final`、`pcb.prepare`、AI/工程师评审以及 `pcb.gate` 走完整质量门禁，不能复用导入前的检查报告。

### 失败、回退和限制

- 未传 `--jar`、版本无法由 JAR 元数据证明或 Java 不可用时：`MANUAL_ROUTING_FALLBACK`；不会创建输出目录，也不会动项目。
- 指定的 Jar SHA-256 不符：`BLOCKED`，不可静默切换。
- 输出目录已经存在：拒绝覆盖。
- 运行超时/异常、进程非零退出或空 SES：`ROUTING_FAILED`，保留证据但不得导入并批准。
- 缺 `--apply`：仅 `PREVIEW_NOT_EXECUTED`，不调用 router。
- 本适配器**不自动导出 DSN、不自动导入 SES、不自动覆铜、不执行 KiCad DRC、不保证布线完成率**。
- 此实现只针对经元数据识别的 v2.5.0 JAR CLI；MCP/API、桌面版安装器、不同 Java 发行包、KiCad 10 端到端兼容与复杂板规则保真尚未实测。
- 注意 Freerouting 可能读取与 DSN 同目录的 `board.rules`；请确保其来源可信，且已审核规则；外部路由器行为及规则保真必须通过最终 KiCad DRC 和工程审核验证。

## 集成状态

本分支增加**实验性工具脚本 + 文档 + 单元测试**；不修改统一工具清单、既有 31 个工具的哈希/门禁约定和稳定版安装包。实际环境通过验证后，再考虑在工具清单注册新适配器并更新测试、索引、打包和版本号。
