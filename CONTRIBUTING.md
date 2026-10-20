# 参与改进

欢迎提交通用规则、可公开的合成案例、版本适配与错误修复。实际Skill在kicad-pcb-ai-workflow目录，开发测试在development目录。

从仓库根目录运行：

```bash
python3 -B -m unittest discover -s development/tests -v
python3 -B development/build_release.py --output-dir /path/new-release
```

构建默认预览；显式--apply只创建新目录。改核心工具时同步更新其manifest哈希，保留必需工具集合；不得为消除错误放宽工程规则或制造门禁。增加明确输入、来源、未覆盖项和反例，区分模拟测试与真实KiCad运行。

实际设计参数来自当前产品、原厂手册和批准工艺。不要将固定器件、板框、网络编号或叠层推广成通用默认值。写入工具应提供新候选、覆盖保护和可追溯验证。

只提交有权分发的原创内容，不上传客户工程、受限原厂全文、凭据或私人机器记录。
