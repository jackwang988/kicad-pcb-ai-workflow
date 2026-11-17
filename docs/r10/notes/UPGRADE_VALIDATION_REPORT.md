# 2026-11-16 · G1–G4 器件知识库复用与分工统一验证报告

## 基线与范围
- 输入包：`kicad-pcb-ai-workflow-R10-cache-first-G1-reuse-public.zip`，独立派生增强；**没有修改真实本地安装和GitHub仓库**。
- 新版标识：`R10.0-alpha.3-local.5+cache-first-1+G1-G4-reuse-1`。
- 实际修改的运行脚本：`device_knowledge.py`、`resource_guard.py`、`placement_review.py`、`static_review.py`、`static_review_gate.py`、`workflow.py`。
- 未增删原有43项登记运行工具；新增离线回归测试文件与完整16节点工作流文档。工具清单哈希已重新生成。

## 测试结果
- Python `unittest discover`：**19项通过，0失败**。原有12项节点3/G1测试与新增7项多阶段测试。
- 覆盖：G2符号/封装类别筛选、G2精确身份与资源锁联合校验、G3当前PCB核心器件存在性、G4完整静态评审资料包生成与原厂已缓存文字复用、跨阶段分类提取、知识卡被篡改后阻断、缺少本阶段条目显式报告。
- 统一流程 `workflow.py modules --intent datasheets` 与 `--intent pcb` 通过；扫描发现43项工具哈希一致。
- Python语法检查和ZIP结构校验通过。

## 未验证 / 不可误读
- 所有新增测试使用模拟芯片卡、合成XML或模拟PCB数据，**未在本环境安装/操作真实KiCad、Konnect-EDA实时服务、硬件板或工厂CAM**。
- G2核对原厂卡片与资源锁一致，不等于自动比较真实PDF图片中的全部Land Pattern尺寸；G3仅静态布局证据；G4仍需逐层AI、实际KiCad DRC及硬件工程师审核。
- 本地缓存不会自动监测厂家发布新Errata，也不会替用户完成原厂视觉核对；过期/变更需节点3重新取得真实版本证据。缓存复用有望减少Token，不包含实测节省比例。
- 独立打包不是GitHub合并、不是外部可执行后端安装成功，也不是生产放行。

## 上线前需要的真实工程回归
1. 备份当前KiCad项目，并确认工具版本和MCP板身份。
2. 用精确MPN、封装、原厂手册和带已核对G2/G3/G4类别的卡执行节点3冻结。
3. 在真实当前原理图/PCB上分别执行G1、G2、G3（pre_route与final）和G4，并保留输入、SHA、ERC/DRC、独立对象回读及工程师审核记录。
4. 故障注入：错误封装、卡片篡改、原厂版本过期、PCB缺位号、GUI未保存与独立pcbnew写入冲突均应阻断。
5. 逐个确认真实后端能力，只有经过验收的操作才允许实际写入；再执行制造候选预检与导出。

## 公开包脱敏
未加入共享器件知识库、原版厂商PDF、客户工程、个人路径/凭据和Konnect-EDA商业执行程序；保留公共示例和官方来源说明。当前包未附授权该源代码的新LICENSE，公开再分发前仍需确认权利及第三方依赖许可证。
