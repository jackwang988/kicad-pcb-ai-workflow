# 六阶段双模式确认（可选 formal_engineering）

六阶段：environment → architecture → schematic → pcb → manufacturing → lifecycle。
本功能只用于协作控制及阶段输出追溯，**不替代 G1–G6、ERC、DRC、原厂资料核验或生产授权**，不能让对话“继续”自动签批任何工程。

## 选择模式

在项目 \`workflow.json\` 的 \`configs.flow.confirmation_mode\` 设置：
- \`dialogue\`（默认；老项目缺此字段也按该模式）：Agent 每组完成后报告实际产出、未解决问题、风险与下一阶段依赖。用户在聊天中确认后继续。程序不会生成电子签名或将确认视为技术通过，仍执行全部专项门禁。
- \`formal_engineering\`：启用上一阶段签批作为后续 \`workflow.py plan/run\` 的进入条件。需要人写的真实工程师记录及项目内证据文件，并以 SHA-256/配置基线绑定。

用户对话确认与硬件工程师审批应使用不同记录和状态。正式模式仅在统一工作流入口施行，无法拦截用户直接操作 KiCad 或独立脚本。生产输出还受原制造门禁限制。

## 正式阶段确认指令

前置：在项目中准备真实工程输出和审核证据（至少一份非空独立文件）。保证配置已经 \`build --apply\`，所有路径位于同一项目之下。

\`\`\`bash
python3 scripts/workflow.py stage-prepare /project --bundle control-r1 --group environment --evidence evidence/environment/report.json
# ENGINEER_REVIEW_PENDING，输出 packet.json 的 packet_sha256；此时尚未批准。
\`\`\`

硬件工程师审阅后，**由本人**在项目内填写 \`evidence/environment/engineer-review.json\`：

\`\`\`json
{
  "role": "hardware_engineer",
  "name": "真实审阅人",
  "date": "2026-10-23",
  "group": "environment",
  "decision": "approve",
  "reason": "具体证据审阅范围、结论及遗留问题",
  "packet_sha256": "stage-prepare 输出的准确64位SHA-256"
}
\`\`\`

\`\`\`bash
python3 scripts/workflow.py stage-confirm /project --bundle control-r1 --group environment --engineer-review evidence/environment/engineer-review.json
python3 scripts/workflow.py stage-check /project --bundle control-r1 --group environment
\`\`\`

后续按六组顺序执行。只要前一组证据、配置或审批包改变，后续组就不可沿用旧确认；修改工程后重新创建新版本 \`r2\` 等，保留历史包、不覆盖。状态 \`ENGINEER_APPROVED_CURRENT\` 只表示此组记录结构与哈希核验通过，**不代表审阅人身份得到程序认证，也不代表工程门禁通过**。

## 约束及注意

- 对话模式不创建审批文件；真实用户确认不写成自动 PASS。
- 正式模式必须由真实工程师创建记录；不得让 Agent 自动代填姓名、reason、审批结果。
- 审查包包含 master、flow 配置，以及阶段适用的 static/NPI 配置、当前 KiCad 文件和显式证据。项目特定的报告由审阅人纳入证据清单。
- 结构化签批只证明“有人声明审过且文件未变”，不能取代电气或物理真实性判断。
- 当前代码对 \`workflow.py plan/run\` 检查上一组批准；专题脚本直接执行不受此操作层限制，因此企业需另外控制软件执行权限和签批制度。
