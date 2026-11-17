# 原理图与PCB衔接

适用：创建原理图候选、修改连接、原理图评审或同步PCB。

- 先读取 [系统集成](system-integration.md)、[图面规范](schematic-style.md) 与 [拓扑绘图规则](schematic-ai-layout-rules.md)。
- schematic_candidate接收精确文件候选；独立预期元件/网络来自需求和原厂依据，不能从输出反推预期。
- **节点6 G1强制复用节点3成果**：优先使用已生成的项目冻结 `device-sources-*/device-bundle.json`（不是重新搜索芯片）；运行`static_review.py --stage schematic`会生成`device-knowledge-brief.json`供AI按本次位号/工作条件阅读，并沿用已核验的资料文字缓存。遇到推荐电路图、波形或脚注再按需打开同一冻结包内的原PDF；缺失/过时/冲突的知识卡回节点3核查，严禁假定缓存完备或自行联网重下。G1继续核对实际电路和当前ERC。
- 原生导出XML/PDF/ERC后，比较全部声明端点与元件身份，再做真实读图和当前版本工程师确认G1；封装资源继续G2。
- KiCad10的PCB IPC读取不提供原理图IPC编辑。Konnect-EDA通过文件式工具提供标准符号放置、网标/引脚连接及字段修改，按任务加载sch_components/sch_wiring/sch_export并使用实际schema；不能与未保存原理图编辑器同时写文件。普通工程仍先形成独立预期网络，再逐步执行、原生导出核对和读图。
- PCB同步可用`update_pcb_from_schematic`，先dry_run读取本次plan_revision，核对实际封装来源、创建/更新/保护对象及差异；apply必须传相同expected_plan_revision和相同替换策略。缺库、旧计划、结果不明或回滚失败按返回原因停止，先回读而不重放。两标准电阻的创建、连接与实时同步已有独立保存网络核验；层次、多单元、替换、删除及既有复杂板仍需对应验收。
- 同步后核对器件/焊盘网络/UUID关联，保护板框、锁定结构件、叠层、规则和既有铜，重新建立当前版本证据。

这些是外部MCP工具，不新增同名workflow CLI命令。按 [静态评审](static-ai-review.md) 保持原生检查、AI内容评审和工程师签核的职责边界。
