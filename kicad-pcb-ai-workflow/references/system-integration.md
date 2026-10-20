# 系统架构与跨模块接口门禁 · R9.3

原理图设计前必须有系统架构首页和模块/接口契约。用户不必预先指定层级或页数：AI依据需求提出模块划分、页面和接口；信息不足或接口参数不确定时保留待确认项，不能自行编造。首页以项目顶层原理图为准，系统框图文件需哈希绑定到项目并进入实际AI/工程师图面评审。

## 必填契约

从`assets/system-integration.template.json`建立`system-integration.json`，并在静态评审配置中启用`require_system_integration=true`：

- `overview`：绑定顶层原理图文件、该顶层页的PDF/SVG/PNG视觉导出哈希和真实规格来源章节。视觉导出应是实际顶层原理图页，页内应能看到系统框图和分页索引，不能拿独立旁路框图替代。
- `modules`：列出模块ID、名称、功能、实际层级页列表和模块内完整元件位号。模块可跨多个页面；全部原理图元件必须且只能归属一个模块，位号须实际出现在声明页面。
- `interfaces`：列出模块间接口类型、用途、来源、方向以及每条网络的完整预期引脚端点；每个接口至少连接两个不同模块。
- `checks`：逐接口列出可量化验收条件和验证方法。可由明确静态谓词执行的绑定`static_task`；电路语义绑定`semantic`；需要仿真/仪器/外部软件的绑定`external_test_plan`。每一项均需真实资料来源和定位。
- `system_checks`：列出整机功能、供电树/上电复位等全局验收。单模块工程仍必须填写系统级检查，`interfaces`可以为空；多模块工程必须明确列出跨模块接口。

每个模块的`components`要覆盖实际网表中所有元件；`sheets`列出模块跨越的实际层级页面。每条接口网络的`terminals`必须列出该网完整的实际引脚端点，不能只写接口两端而漏掉中间串联器件或分支。示意字段如下，位号、网络和参数必须按真实工程替换：

```json
{
  "id": "HOST_TO_CONTROLLER",
  "kind": "digital",
  "purpose": "控制器向主控发送复位状态",
  "from_module": "controller",
  "to_module": "host",
  "source": {"document_id": "PRODUCT_SPEC", "locator": "§4.2"},
  "nets": [{
    "name": "RESET_STATUS",
    "terminals": [{"ref": "U2", "pin": "7"}, {"ref": "U1", "pin": "15"}]
  }],
  "checks": [{
    "id": "RESET_LEVEL",
    "method": "semantic",
    "acceptance": "两端逻辑电平与有效极性符合数据手册和产品时序",
    "source": {"document_id": "HOST_DATASHEET", "locator": "§8.1"}
  }]
}
```

## 自动检查和人工审查

`system_integration.py`在当前网表上核对层级页是否存在、元件模块归属是否完整唯一、每个接口网是否存在、精确引脚端点是否与契约一致、端点是否实际跨越声明模块。缺网、额外/缺少端点、错误模块归属、失效来源或不完整接口均为【阻断级】。结果绑定到原理图静态评审packet；packet gate复算，NPI检查必须与已确认packet完全一致。AI必须在同一个系统集成评审项中观察全部模块元件、所有接口网络、顶层架构页视觉图和当前KiCad原理图PDF；工程师确认这个系统图确实位于原理图首页且与分页一致。

网络端点匹配只证明当前原理图与预先声明的接口契约一致，不能证明契约设计正确。AI与工程师必须另外核对供电电压/电流预算、上电及复位次序、时钟、接口方向/电平/绝对最大值、上拉/端接、连接器针脚、共享资源、启动状态、异常状态与必要保护。复杂时序、模拟裕量、热/SI/EMC及功能行为由明确计算、仿真、外部计划或实测承担。`system_integration.py`不对这些模拟语义自动判PASS。

## 图面和分层方案

AI先从系统框图推导原理图首页、模块页和层级连接，再绘制具体器件网络。建议按产品信号流安排页面，电源树层次清晰，接口位于模块边界，跨页连接使用一致命名和清楚的层级标签；元件位置和连线不能改变已经确认的电气拓扑。输出KiCad PDF后逐页检查功能分组、输入到输出阅读顺序、文字重叠/交叉歧义、网名与端口一致性，并由工程师确认。脚本只核对声明的纸张/方向和层次接口等结构项；不自动证明图面清晰或电路正确。

```bash
python3 scripts/system_integration.py /project \
  --contract system-integration.json \
  --schematic main.kicad_sch \
  --netlist current.xml \
  --documents documents.json
```

生产级静态评审配置必须同时含`system_integration.contract`、`require_system_integration=true`及`category=system_integration`语义任务。缺其中任一项，原理图packet/NPI均阻断。R9.1仍不提供通用原理图自动推理/自动绘制引擎；它将系统接口需求变成明确的前置设计交付和可复验门禁。
