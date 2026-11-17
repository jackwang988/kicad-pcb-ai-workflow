> 本地修订：先读[主流程与执行修订](design-execution-local.md)。下文六组/16节点与G5/G6为历史兼容资料；当前AI设计主线删除第六阶段，截止DESIGN_PACKAGE_READY_FOR_REVIEW。外部制造/样机/ECO仅按另行任务调用；既有安全门禁保留。

# 规则、布局与脚本优先布线

适用：叠层、设计意图、引脚级布局、布线计划和最终PCB复验。

1. 按 [设计意图](design-intent.md) 编译已批准工艺与网络约束；检查实际NetClass/custom rules命中，不只看推荐值。
2. 按 [布局质量](placement-quality.md) 核对模块、准确焊盘、局部电路、回流和结构。placement_review负责检查；实际修改优先按[Konnect MCP接入规范](konnect-backend.md)在已验收的候选板上执行并回读，不能仅凭封装中心判断电气质量。自研桥不作默认或自动回退。
3. 按 [约束布线](constraint-routing.md) 预检和规划。工程策略为脚本规划；后端依能力/证据选择，缺验收不自动执行。
4. 当前 [Freerouting工具](freerouting-adapter.md) 仅已有DSN到新SES候选，不提供完整导出/回导闭环，继续按其授权与参数限制。
5. 部分布线检查仅允许逐项声明的待布连接；最终必须完成全部必要连接、覆铜保存重载及原生DRC/parity。
6. 对最终全部铜层、关键路径和必要专项验证完成真实评审，保持G3/G4及后续制造门禁。

R10-alpha新增预检与计划，不宣称已集成通用A*/Shove/差分/RF求解器。失败不放宽已批准层数、线宽、工艺或规则严重度。

受控阻抗、高速接口或关键电源轨适用时，另读[高速与PI专项](module-high-speed.md)。使用其真实工程快照、适用规则与绑定证据结果；它补充现有设计意图/布局/布线工具，不改变日常连接流程，也不直接编译或写入一套竞争规则。


## 新增：多阶段缓存复用与工程职责边界

**G3/G4知识库复用**：节点9布局运行`placement_review.py --review-config`读取冻结的去耦/晶振/RF/布局条目，节点11最终评审`static_review.py --stage pcb`自动输出器件卡摘要并由`static_review_gate.py`再次校验。只针对知识卡缺失类别返回节点3补卡，严禁自动下载同型号手册；所有实际位置/铜层/连通仍需独立验证。详见[最新16节点规范](latest-complete-workflow.md)。
