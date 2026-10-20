# 开发与测试

运行Skill位于kicad-pcb-ai-workflow目录；development保存软件测试与人工构造的测试输入。history/repair-status.json用于验证历史规则追踪，不能作为产品通过记录。

```bash
python3 -B -m unittest discover -s development/tests -v
python3 -B development/build_release.py --output-dir /path/new-release
```

构建默认预览，--apply只写新输出目录。安装时仅使用Skill目录或dist中的安装包；TEST器件、资料、网表和工程夹具不能用于制造或冒充工程师确认。

软件检查包含缺资料、错连、过期证据、工具缺失/篡改、原型禁生产和制造发布反例。真实KiCad、CAM/工厂EQ及硬件测试分别记录，不能以模拟器或单元测试替代。
