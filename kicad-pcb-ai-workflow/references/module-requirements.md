# 需求、架构与器件依据

适用：新设计、器件替换、接口或工况变化。

- 用 [统一入口](universal-workflow.md) 的单一workflow.json记录公共项目输入；保留完整16节点。
- 需求包含来源、量化验收、验证阶段及实际静态任务或外部测试计划。
- 按 [器件依据](device-knowledge.md) 读取准确MPN/封装对应的原厂资料及勘误，不从CAD转换结果反推原厂引脚。
- **强制缓存优先**：原理图需求的每个核心器件先跑 `device_knowledge.py resolve` 精确查已核对知识库；命中用 `brief` 获取必要条目、无需再次搜索下载；仅缺失/资料到期时回查原厂；第一次核对后用 `register` 入库。见[节点3缓存优先流程](device-knowledge.md)，不得直接跳过原有 `audit/bundle` 与G1/G2门禁。
- 按 [系统集成](system-integration.md) 建立架构首页、模块和接口端点。各模块一致不代表电气契约本身正确，仍需独立评审。
- 按 [备用方案](reserve-options.md) 决定预留、DNP与装配变体；不默认增加所有可选电路。

本模块负责依据和契约。外部datasheet子Skill仅提供带来源候选，不自动授予工程结论或制造许可。
