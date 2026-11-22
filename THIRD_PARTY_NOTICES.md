# 第三方组件

MIT许可覆盖本仓库有权授权的原创代码和文档。KiCad、ngspice及资料提取工具适用各自许可，本仓库不附带其二进制程序或原厂手册全文。

- [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html)
- [KiCad PCB Python API说明](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/)
- [KiCad Python API参考](https://docs.kicad.org/doxygen-python-10.0/namespaces.html)
- [ngspice](https://ngspice.sourceforge.io/)

核心Python工具使用标准库。PDF文本提取、外部模型、供应链接口与仿真工具由使用者按实际任务配置，其许可不因本仓库MIT许可而改变。

`development/konnect-field-extension` 为独立 **AGPL-3.0-only** 开源 Konnect 0.13.0 扩展组件；该目录附完整许可、固定上游源码 URL/提交/哈希及全部新增 Rust 模块与准备器。此组件不属于 MIT 最小 Skill ZIP，也不包含或改写商业 Konnect 0.14.1。仓库和 validation ZIP 不分发 Konnect 可执行文件或编译工具链。原生回归可选开发依赖 Gerbonara / resvg_py 适用各自发布许可，均不进入最小 Skill 包。
