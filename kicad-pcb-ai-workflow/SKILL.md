---
name: kicad-pcb-ai-workflow
description: KiCad10.0.7电子设计通用流程与项目化规则工具链。用于需求追踪、原厂资料、原理图候选写入/原生核对、层次结构检查、差分/电源/RF意图、布局布线审计、AI/工程师评审及DFX/NPI制造门禁。适用新工程或已有工程；缺规格、执行适配器或证据时阻断，不承诺任意电路自动设计合格。
---

# KiCad工程流程 · R9.3

先读[统一入口与公共配置](references/universal-workflow.md)，按环境、需求架构、原理图、PCB、制造、试产/ECO六组推进；需要细节时读取[完整16节点流程](references/full-workflow.md)。16个节点与G1–G6均保留。通用的是阶段、数据接口与验收方法；器件、电流、叠层、阻抗、工厂能力和适用标准必须按实际项目提供。工具退出0只代表声明范围，不表示电路合格或可以生产。

运行包可独立安装，不需要历史归档或开发包。升级时安装到干净的新目录，勿合并旧scripts；已有工程保持原位，迁移其主配置引用并重建快照。先列出实际项目对旧脚本的外部调用，再决定如何迁移，不能复制旧签核或他人环境记录。

## 入口与工程保护

1. 新项目优先用`workflow.py init`预览单一workflow.json；显式`--apply`才新建。公共工程路径、资料、策略和装配变体只填shared一次，阶段要求填configs；build预览/--apply生成独立新配置快照，status显示六组待办。生成配置不表示检查通过。旧project_flow.py及全部专题命令保持兼容，新工程尚无PCB时保持待办，不创建空文件绕过。
2. 先按[新手环境教程](references/environment-onboarding.md)运行doctor及首次原生setup；日常check只复用当前环境有效记录。环境记录只对实际验证过的电脑与工具版本有效，新工程仍需核对自身资源。
3. 日常用`workflow.py plan/run --task GROUP.TASK`；专题操作按需读对应文档，使用`project_flow.py run TOOL -- ARGS`或当前tool-manifest中有CLI入口的工具。两层入口均校验有效工具哈希，无shell或自定义可执行文件。运行目录只允许清单内的31个工具；项目脚本和历史源码独立存放，不复制进scripts。
4. 工程写入默认预览，仅显式`--apply`写独立新候选。只读报告按显式新output-dir写入，不覆盖原工程或旧报告。Agent生成的文件草稿先以精确文本方案呈现，只有用户已授权写入时才用候选写入接口落盘。
5. 读取[有效工程规则](references/engineering-rules.md)。法规/安全、产品及原厂、批准工艺高于经验与美观；不为通过检查删除器件、规则或改变网络。
6. 主配置修改、工具清单变化、生成配置被改动即拒绝复用原快照；创建新bundle并更新受影响的评审。导航不缓存或代替原生/AI/工程师门禁，不自动填PASS、N/A或签名。features不适用声明需理由和来源，不能据此删除强制评审类别。

保留`--mode prototype`原型诊断；量产必须用`--mode mass_production`，原型模式不授予生产放行。

## 阶段执行

- 需求/架构：逐项建立ID、来源、量化验收、验证阶段，映射真实静态task的requirement_id或外部测试计划。契约检查只验证声明与文件，不替代实际验证。
- 原厂资料：[device-knowledge.md](references/device-knowledge.md)。按完整MPN/封装查缓存或原厂；实际阅读原文、图、勘误，核对卡后冻结资料包。脚本不代做语义判断。
- 备用方案：[reserve-options.md](references/reserve-options.md)。按风险决定有/无预留及DNP/0Ω/变体；不默认全板加器件。
- 原理图：[系统架构与跨模块接口门禁](references/system-integration.md)。先完成系统架构首页、模块清单、跨模块接口契约和系统验收条件，再按架构分层设计。`system_integration.py`强制核对所有元件模块归属、层级页、接口网络和实际端点；模块电平、供电预算、时序和功能行为仍由有来源的静态任务/AI/工程师或外部验证完成。用`schematic_candidate.py`接收Agent已设计的精确文件草稿并调用原生XML/PDF/ERC，核对独立预期元件及网络；这是候选写入/验收适配器，不是自然语言电路生成器。
- 图面：[schematic-style.md](references/schematic-style.md) 与 [拓扑驱动 AI 原理图设计规则](references/schematic-ai-layout-rules.md)。AI依据架构提出分页与页内流向，硬件工程师确认；系统架构图必须绑定首页并逐页评审。按功能/连接/可读性选择分页；纸张只按项目要求检查，不再使用88器件或固定页数的通用硬门槛。
- 原理图/PCB评审：[static-ai-review.md](references/static-ai-review.md)。实际读图、网络、原厂资料与全部铜层；输出AI报告，再由工程师本人确认当前版本。不得由Agent签工程师批准。
- 叠层及差分/电源/RF：[design-intent.md](references/design-intent.md)。先取得真实工艺、工作电流和温升等依据，再编译规则；原生同步PCB后检查实际归属与生效。同步需实际GUI或已验证适配器，禁止虚构CLI。
- 布局：[placement-quality.md](references/placement-quality.md)。模块/准确引脚/局部电路→pre_route→真实布线覆铜→视觉整理和final复验。不自动调用旧固定坐标放置器。布局、布线执行由原生工具/实际适配器和工程师负责，缺执行能力就说明并停止该节点。
- 可选自动布线（实验性）：[Freerouting v2.5.0 CLI 适配器](references/freerouting-adapter.md)。仅在用户显式指定本地合规 JAR、已有 KiCad 导出 DSN 并授权 `--apply` 时从 DSN 生成独立 SES 候选；未配置时保持 KiCad 人工布线。该独立工具尚未加入统一 tool-manifest，不自动完成 KiCad 回导、DRC 或放行。
- DFX/NPI：[dfx-npi.md](references/dfx-npi.md)。新R9项目必须在NPI配置绑定workflow_contract、schematic_style和system_integration，静态配置启用相应强制门禁。旧R8配置仍可诊断，不能据此宣称已执行R9全部控制。
- 制造：冻结副本refill/save/reload后，使用`manufacturing_export.py`预览；仅--apply且当前原生设计门禁通过才向新隔离目录导出Gerber/钻孔/CPL/BOM/装配PDF。输出EXPORTED_NOT_RELEASED，不接触任意jobset、不上传工厂。后续build_manifest、实际CAM/工厂EQ和npi_release.py重新验收。
- 样机/ECO：按需求计划进行真实功能/性能/环境/安全及适用认证验证，变更后失效相关证据并重新审查。动态EMC/眼图/热不假称静态已证明。

## 快速调用

```bash
python3 scripts/workflow.py run /path/project --task environment.doctor
# 环境诊断不要求先建主配置；后续项目任务才需配置快照
python3 scripts/workflow.py init /path/project
# 审阅后加 --apply；由Agent根据真实项目填写workflow.json，不手工维护生成配置
python3 scripts/workflow.py build /path/project --bundle control-r1
# 审阅后加 --apply；创建新快照，不覆盖已有目录
python3 scripts/workflow.py status /path/project --bundle control-r1
python3 scripts/workflow.py run /path/project --bundle control-r1 --task environment.doctor
python3 scripts/workflow.py run /path/project --bundle control-r1 --task schematic.prepare --output-dir /path/new-sch-review
# 后续先AI真实评审，再工程师本人确认，最后调用schematic.gate；其余见统一接口
```

## 放行边界

所有风险用阻断级/高风险/中风险/优化建议，记录位置、问题、依据和修复。缺原生工具、模型、来源、规则或必要实测不能假通过。static-preview和TEST夹具永不授予生产许可。原生导出文件存在不等于制造内容正确；Skill门禁不能禁止用户绕过它在GUI自行导出。

使用[能力边界](references/capabilities.md)判断自动、人工和外部验证范围。运行包仅含通用工具、模板和当前规范；历史源码、项目夹具和测试日志独立归档。不得用历史经验覆盖项目规格；对外发布或发厂需项目明确授权。
