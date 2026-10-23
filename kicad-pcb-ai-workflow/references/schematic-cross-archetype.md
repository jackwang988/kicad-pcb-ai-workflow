# 原理图三遍绘制与跨页面原型验证

本规范从附件 R9.6 的绘图原则抽取可复用部分，服从 [L0–L5 原理图规则](schematic-ai-layout-rules.md)；**不采用 POWER 页面固定坐标、默认方向等硬模板**。

## 三遍绘制与审图（执行顺序）

1. **拓扑与相对布局**：电路连接与电气角色先行，识别页面原型（POWER、MCU、连接器、总线、模拟/音频、离散、首页等），计算真实引脚方向、合法端点、元件相对位置、短正交路径，核对独立预期网表。
2. **文字和标签独立布局**：Reference、Value、引脚名/号、标签、注释根据真实文字包围盒、标签锚点和周围留白排版；不因改图面重定网络。
3. **两尺度视觉复核**：每页整页检查系统流向、内容居中和版心，200% 或可读等效放大核对引脚短线、标签方向、走线穿越、文字碰撞；再执行 ERC、导出网表与人工核读。未实现的几何自动检查必须显式写 UNAVAILABLE。

## 跨原型验证（推广前）

如果从某个已通过的代表页提取“通用布局策略”，在宣称可推广之前，至少用另一类页面验证；电源转换页成功后，必须选择 MCU/SoC 或多引脚接口页额外验证。严禁仅凭 POWER 页单一结果把坐标/流向模板推广到其他页面。

真实工程页面的可选结构证据门禁可在 \`schematic-style.template.json\` 的项目派生策略加入 \`prototype_validation\`。下面是**示例结构，不得使用示例哈希作为真实验收**：

\`\`\`json
{
  "schema_version": 1,
  "pages": {},
  "require_sheet_pin_wire": false,
  "source": null,
  "prototype_validation": {
    "required": true,
    "cases": [
      {
        "page": "power.kicad_sch",
        "archetype": "power_conversion",
        "evidence": {"file": "evidence/power-review.pdf", "sha256": "<actual-sha256>", "locator": "page 1, entire page and 200% local inspection"}
      },
      {
        "page": "mcu.kicad_sch",
        "archetype": "mcu_soc",
        "evidence": {"file": "evidence/mcu-review.pdf", "sha256": "<actual-sha256>", "locator": "page 1, ports and short leads"}
      }
    ]
  }
}
\`\`\`

允许原型：\`power_conversion\`、\`mcu_soc\`、\`multi_pin_interface\`、\`bus_storage\`、\`analog_audio\`、\`discrete_io\`、\`hierarchy_overview\`、\`debug\`。

脚本检查：页面路径必须可达且互不重复、不同页面原型不少于 2 类、电源页必须搭配 MCU 或多引脚接口页、证据文件必须存在且哈希匹配。输出仅为 **声明证据身份检查**，**不自动识别原型、不证明图面合格、不替代 ERC/网表和审核**。

对于合法单页小工程、未推广的单一原型项目，不强制采用此可选策略。跨不同项目/测试夹具的算法泛化性能，需要在独立回归环境另建真实样本库，不能强制把不属于当前项目的符号页塞进项目里凑数。
