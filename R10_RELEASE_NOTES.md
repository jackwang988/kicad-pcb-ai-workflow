# KiCad PCB AI Skill R10.0.0-rc.1 · 预发布说明（2026-11-17）

> **版本性质：公开发布候选（Release Candidate / GitHub Pre-release）**。主线 KiCad 设计资料交付以工程师审核为准，不授予真实PCB工厂生产许可。已有R9.4稳定版继续保留。

## 新版主要能力
- 7个按需知识模块及16节点工作流。节点01–13作为AI设计主线，14–16为实际工厂/样机/ECO外部扩展。
- 芯片知识库 **Cache-First**：按制造商+精确型号（MPN）+封装查找已审核原厂知识卡；G1原理图、G2封装、G3布局、G4最终PCB复用对应片段，但当前项目仍必须独立验证。
- Konnect MCP唯一活动EDA写入者，动态工具发现、L0–L3风险分级、首次隔离验收、能力记录复用；未验证工具不可偷偷切换pcbnew写入。
- Python保留算法、规则审计、证据哈希与只读兼容；KiCad CLI承担独立ERC/DRC和原生验证。
- 架构图/16节点图/知识库复用/动态工具闭环可见 [R10图文说明](docs/r10/README.md)。

## 软件与原生证据
- 仓库原R9.4软件回归 **319/319**，R10新增离线测试 **33/33**，独立Skill软件包预览通过：[PR分支Actions](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44015071931)。
- 真实 **KiCad 10.0.8**（官方稳定PPA）隔离工具链验证通过，包括原生加载、PCB几何、覆铜保存重载、ERC/DRC及制造命令检查：[Native Actions](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44015065144)。
- **尚未在用户的Windows电脑上完成Konnect-EDA真实MCP写入（复杂布局/布线/覆铜）端到端验收。** CI的KiCad native测试并不证明第三方商业MCP完整可用。
- 部分旧pcbnew**只读**几何/工艺审计仍为过渡兼容，不能宣称已删除全部旧API依赖。

## 安装与前提
- 从 [R10 RC1 安装包](dist/kicad-pcb-ai-workflow-R10.0.0-rc.1.zip) 下载，将ZIP解压得到的 `kicad-pcb-ai-workflow` 目录安装到Agent支持的Skills目录。不要与旧版目录直接合并。
- 需要KiCad原生CLI与适配版本的Konnect MCP服务；`konnect_capabilities.py` 的写入参数校验使用 `jsonschema>=4.18,<5`（见 `requirements.txt`）。Konnect是独立第三方服务，不包含在此ZIP中。
- 所有首次工具能力须按适用对象/版本/Schema进行受控验证；新项目G1–G4均需重新审核实际工程。
- 遵循预览、受控候选和明确授权原则；未通过验收的高风险写入应返回 `BLOCKED`。

## 发布边界
**“Skill软件版本公开发布”不等于“PCB设计、CAM、生产或样机通过授权”。** 未经过真实KiCad+Konnect联调的功能，不应作为已验证的稳定量产能力宣传。
