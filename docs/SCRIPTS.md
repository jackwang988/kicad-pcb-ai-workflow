# R9.3 工具索引

实际Skill位于仓库的kicad-pcb-ai-workflow子目录。以下命令在该Skill目录执行；Python须与KiCad10.0.7绑定匹配。按任务调用，不批量执行全部脚本。

| 职责 | 工具 |
|---|---|
| 统一入口与环境 | workflow.py、project_flow.py、doctor.py、environment_start.py |
| 原理图与接口 | schematic_candidate.py、schematic_io.py、schematic_style.py、system_integration.py、netlist_guard.py |
| 资料与静态内容评审 | device_knowledge.py、static_review.py、static_review_gate.py |
| 设计规则、布局及备用 | design_intent.py、design_intent_audit.py、placement_review.py、reserve_review.py |
| DFX及基础核对 | mass_production_review.py、engineering_gate.py、npi_common.py、npi_geometry.py、native_report.py、pad_audit.py、assembly_guard.py、link_audit.py |
| 冻结、制造与发布 | freeze_candidate.py、validate_frozen_candidate.py、manufacturing_export.py、build_manifest.py、production_contract.py、npi_release.py |
| 可选SPICE接口 | spice_precheck.py |

统一入口：

```bash
python3 scripts/workflow.py run /path/project --task environment.doctor
python3 scripts/workflow.py init /path/project
python3 scripts/workflow.py build /path/project --bundle control-r1
python3 scripts/workflow.py status /path/project --bundle control-r1
```

init/build默认预览；审阅后添加--apply，拒绝已有目标。环境诊断不要求先有主配置；其他项目任务使用生成的快照。status只是待办，不表示门禁通过。

专题命令及实际输入/输出见[统一入口](../kicad-pcb-ai-workflow/references/universal-workflow.md)、[静态评审](../kicad-pcb-ai-workflow/references/static-ai-review.md)与[制造门禁](../kicad-pcb-ai-workflow/references/dfx-npi.md)。模块型文件由其所属入口调用，没有通用CLI就不直接执行。

有效工具的存在、唯一性、SHA和合同由库存门禁验证；安装目录不混入项目脚本。工程写入保持预览/--apply新候选机制，报告使用新目录。各工具退出0仅代表声明范围，不自动产生制造许可。
