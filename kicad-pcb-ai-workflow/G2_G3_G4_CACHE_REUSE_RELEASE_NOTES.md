# R10 G2/G3/G4 复用器件知识卡与工具职责统一 · 发布说明

**基线**：`R10.0-alpha.3-local.5+cache-first-1+g1-cache-reuse-1` 的上一轮公开分享版。当前为独立派生的**公开脱敏包**，没有修改用户电脑上的Skill或GitHub仓库。

## 这次实际修改

1. `device_knowledge.py` 新增 `project_stage_brief()`：对项目冻结的已核对原厂卡重新检查哈希、资料版本证据和身份；按G2/G3/G4提取少量带来源和条件的条目。无对应条目明确返回 `STAGE_CARD_COVERAGE_INCOMPLETE`；不下载、不做自动工程判定。
2. `resource_guard.py check --review-config`：节点7/G2重用节点3的知识卡，要求封装/型号/制造商与当前资源锁精确对应，输出 `g2_device_knowledge` 和待本项目审查状态；原Pin/Pad映射检查不被知识卡替代。统一工作流 `schematic.resources_check` 自动传递当前静态配置。
3. `placement_review.py --review-config`：节点9/G3重用已冻结布局条目，核对项目网表里的精确身份与原文绑定，确认目标核心位号真实在当前PCB内；仍执行原来的布局几何检查，AI/工程师确认仍须完成。统一工作流 `pcb.placement_pre/final` 自动传递当前静态配置。
4. `static_review.py --stage pcb`：节点11/G4新增知识卡摘要，复用SHA匹配的冻结原厂文本，不再重复解析其PDF文本；`static_review_gate.py`重算G4摘要，核对与项目冻结资料一致，检测被篡改或缺少证据。
5. `SKILL.md`、模块文档新增全局「仅单写入者」与「各关口共享原厂知识、独立验证当前设计」约束。完整16节点逐项流程见 `references/latest-complete-workflow.md`。

## 仍需项目/人工完成

- 真正工程师对G1–G4当前项目的审查；原厂图表、pinout、land pattern和布局/参考平面实际适用性确认。
- 在真实KiCad版本/主机执行Konnect MCP操作与CLI/pcbnew独立验证。只有当前工具版本、动作、对象范围通过本机验收，才允许写入；MCP与离线pcbnew禁止同时写同一板。
- 历史只有`power`等电源类条目的卡不能自动用于G2/G3/G4；需返回节点3对相应原厂章节补充、审核和冻结。不能通过简单改JSON字段绕过真实核对。

## 测试结论

本次新增G2/G3/G4多阶段离线回归测试；原有缓存与G1测试保留。测试仅覆盖软件逻辑、模拟板、缓存摘要、文件校验及跨阶段入口。非原生KiCad工程的测试不能宣称PCB已完成设计/制造验收。公开包不附个人、受版权限制的PDF、商业Konnect-EDA程序和真实项目资料。
