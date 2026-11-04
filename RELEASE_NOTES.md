# R9.4 · 2026-11-04 · KiCad 10 向前兼容及原生验证

- **版本策略**：10.0.7继续为推荐基线，不再是安装上限；稳定KiCad 10.x逐项检测CLI和pcbnew同版本、真实项目烟雾记录及生产门禁。混合版本/开发版不可直接授权。
- **KiCad 10.0.8 真实测试**：在GitHub Actions Ubuntu 24.04上通过KiCad官方10.0 PPA实装10.0.8，验证版本匹配、原理图PDF/XML、ERC/DRC JSON、PCB读取、铜皮区域填充、保存重载、Gerber/Excellon/CPL/BOM/装配PDF等工具链操作；[测试定义](.github/workflows/native-kicad-10.0.8.yml)、[原生成功记录](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/41748194225)。
- **工程副本保护**：原生CLI可能写出`*.kicad_prl`设置文件。R9.4制造导出在独立临时工程副本上运行并核对原工程哈希；增加真实工具链检测与软件防回归测试。
- **未来KiCad 11+**：提供CLI-only候选检测和受控原生报告验证通道；旧SWIG `pcbnew`未适配IPC前，PCB原生写入及制造放行继续阻断。
- **KiCad 9**：离线工作流可用，未实际验证的原生KiCad 9 API/CLI不做兼容承诺。
- **质量保障**：GitHub Actions Python软件测试覆盖319项，发布前还需跑真实10.0.8原生测试；工具完整性SHA-256保持强制校验。
- **工程边界**：本版验证的是示例项目上的真实工具链功能，不是产品项目的原厂电路、NetClass设计值、制造CAM/DFM或工程师签核通过；所有G1–G6及NPI/工厂门禁均保留。其他操作系统和KiCad补丁需本地验证。

安装[最新R9.4 ZIP](https://github.com/jackwang988/kicad-pcb-ai-workflow/raw/refs/heads/main/dist/kicad-pcb-ai-workflow-R9.4.zip)，使用[SHA256SUMS](dist/SHA256SUMS)核对完整性。升级请在干净Skills目录重装，不叠加旧脚本。

---

# R9.3 · 2026-10-20

- 目标版本KiCad 10.0.7；维护者确认本机CLI与pcbnew基础调用已接通。
- 六组入口组织16个工程节点，保留G1–G6、原生ERC/DRC、AI与工程师确认、DFX/NPI、CAM/EQ及授权流程。
- 原厂资料检查与项目化缓存、架构首页和跨模块接口契约、差分/电源/RF设计意图、模块化布局及备用方案评审。
- 单一主配置共享路径、资料、策略与装配变体，编译为不可覆盖的新配置快照。
- 安装包64文件，包含31个有效工具和18份通用模板；核心库存强制验证完整集合、哈希及工具合同。
- 当前仓库286项软件测试全部通过，含ZIP独立运行、工具缺失/篡改、证据过期和生产阻断反例。

安装[当前ZIP](https://github.com/jackwang988/kicad-pcb-ai-workflow/raw/refs/heads/main/dist/kicad-pcb-ai-workflow-R9.3.zip)，或从仓库的kicad-pcb-ai-workflow子目录安装。升级使用干净目录，不合并旧scripts；配置与环境证据按当前版本复验。

CLI/API基础连通和软件测试不授予产品制造许可。真实产品仍需完成原生工程、工程师确认、CAM/目标工厂及实测验收。
