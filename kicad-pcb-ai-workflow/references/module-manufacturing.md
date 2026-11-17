**单写入迁移更新**：`freeze_candidate.py --apply`现在只创建独立候选及 `freeze-handoff.json`，Konnect已验收的覆铜工具执行真实写入和保存；`--finalize --operation-report`复核Konnect操作证据并以KiCad CLI独立重载/DRC。不能再理解为Python pcbnew自动覆铜。制造级几何/网络类等价回读未验证的门禁继续阻断；详细参见[迁移规范](konnect-capability-migration.md)。

> 本地修订：先读[主流程与执行修订](design-execution-local.md)。下文六组/16节点与G5/G6为历史兼容资料；当前AI设计主线删除第六阶段，截止DESIGN_PACKAGE_READY_FOR_REVIEW。外部制造/样机/ECO仅按另行任务调用；既有安全门禁保留。

# 工程评审与制造候选

适用：AI/工程师评审、DFX/NPI、候选制造输出、CAM/EQ和发布。

- 使用 [静态评审](static-ai-review.md) 的当前版本资料包；AI真实读图与来源，工程师本人确认，Agent不得代签。
- 按 [DFX/NPI](dfx-npi.md) 处理结构、工艺、装配、测试及风险；资料缺失或阻断未关闭则停止相关制造路径。
- 新增资源锁定、布线计划及IPC快照只是相应范围证据，不能替代原有工程门禁。
- freeze_candidate在新副本覆铜/保存/重载；manufacturing_export在隔离候选导出并保持EXPORTED_NOT_RELEASED。
- 工厂CAM/EQ、装配变体和授权确认后才按npi_release复验G5；不自动上传或发厂。

IPC读取适配器不解除现有pcbnew制造前置条件。未来完整IPC后端必须逐项验收后迁移；本版没有把连接成功当制造可用。
