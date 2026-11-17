# 项目资源核验与锁定

本模块只核验当前项目显式资源的内容、一致性与已声明引脚映射，不是全量符号/封装库，不访问网络，不安装工具，不调用 `pcbnew`，不自动生成、批准或替换资源。原厂手册才是引脚及封装适用性独立依据；供应商CAD、转换工具输出和文件存在均不能代替原厂核对。

## 轻量接入

先查用户已安装库和现有项目资源；按实际需要将使用的符号库、封装及必要模型复制为项目内普通文件。不要捆绑全量官方库或默认下载3D模型。共享缓存可复用，但本版本锁定的文件必须在项目内，不能以符号链接、Windows junction、绝对路径或环境变量引用外部缓存。离线交付包含清单实际使用的文件即可。

按需子Skill可以协助制作符号、封装或查找来源；它交付的是待核对候选。主工作流仍负责项目身份、G2及其他工程门禁。资源核验成功不能自动填入工程师确认或制造批准。

## 显式清单

从 `assets/resource-lock.template.json` 复制为项目内的 `resources.json`，据真实资源填写。模板中的 `null` 故意不能通过核验。顶层仅支持 `schema_version: 1`、`project_id`、非空 `resources`。

每项资源必须声明：

- 唯一 `id`、完整 `manufacturer`、精确可订购 `mpn`、对应封装后缀/变体 `package`。脚本只能拒绝空值及明显占位，不能判断型号是否真实或准确。
- `basis`：项目内原厂依据 `file`、真实小写 `sha256`、`document`、`revision`、图表/页码/章节 `locator`、`authority: manufacturer`。脚本验证文件与元数据存在及哈希，不判断文档是否确为原厂、原文含义或适用条件；Agent/工程师须实际读原文与图表，必要时复用器件资料模块。
- `symbol`：`.kicad_sym` 文件、SHA-256和库内精确 `name`。
- `footprint`：`.kicad_mod` 文件、SHA-256、文件内精确 `name`和 `library_id`（如 `ProjectLocal:ExactPackage`）。符号非空 `Footprint` 属性必须匹配此标识；这是声明校验，不证明实际工程库表或元件已使用该资源。
- 完整 `pin_pad_map`：逐项记录 `pin`、原符号中的 `name`、`electrical_type` 和对应 `pads` 数组；所有符号引脚及所有电气焊盘编号必须覆盖且不能歧义复用。EP必须显式列入，不可因ERC未报错而省略。一个引脚可对应多个不同焊盘编号；同编号多实体焊盘的实际数量会记录在锁中。
- 可选 `models`：仅在项目需要时提供 `.step` / `.stp` / `.wrl` 的文件与哈希。只锁内容，不验证机械尺寸或装配位置。

文件路径统一用项目内相对路径和 `/`；拒绝 `..`、绝对路径、盘符、反斜线、未解析变量、链接和Windows reparse路径。未知字段、未知schema、缺来源及重复JSON键均阻断，防止拼写错误静默忽略。清单涉及的全部文件必须非空且哈希匹配。

当前支持解析显式普通符号引脚与常规有编号电气焊盘，未编号NPTH可作为机械孔记录。继承符号、同编号多单元/替代表示引脚、未编号电气铜焊盘及其他未覆盖格式会阻断；应在独立候选中明确解析并评审后再使用，不能删引脚以便通过。此语法读取不代替KiCad原生解析、KLC及封装DRC。

## CLI与保护

以下命令在Skill目录运行，Python和项目路径替换为本机实际值。资源脚本使用标准库及现有纯文本解析辅助，不要求匹配的KiCad Python绑定。

```text
python scripts/resource_guard.py lock /actual/project --manifest resources.json --output resource-lock-r1.json
python scripts/resource_guard.py lock /actual/project --manifest resources.json --output resource-lock-r1.json --apply
python scripts/resource_guard.py check /actual/project --lock resource-lock-r1.json
```

`lock`即使预览也会真实读取并核对全部声明资源；默认仅向终端输出 `PREVIEW`，不创建文件或目录。`--apply`只用独占创建方式写一个新JSON锁文件，不覆盖旧锁或资源，不创建父目录。相对输出路径基于项目；可显式指定已存在目录中的绝对新文件路径。写入前会再次核对输入快照。

离线 `check`重读清单、原厂依据、符号、封装及可选模型，重新比较锁定观察与全部内容哈希，无网络请求且不扫描全量库。默认只读；可指定 `--output resource-check-r1.json` 预览报告位置，再加 `--apply`写新的独立报告。锁文件可为项目相对路径或显式绝对路径，链接路径仍拒绝。

退出0仅代表预览或声明范围内一致；缺失、篡改、未知能力或不安全路径返回 `BLOCKED` / 退出2。状态为 `RESOURCE_LOCK_CREATED_NOT_APPROVED` 或 `RESOURCE_CONSISTENCY_CHECKED_NOT_APPROVED`，始终 `production_authorized: false`。本地锁是未签名基线，不能抵抗有权限同时重写清单、资源与锁的人，不是批准防伪机制。

## 后续工程绑定

更换器件、封装、引脚名/类型/编号、焊盘、来源或模型后，旧锁检查失败；回到受影响原厂/电气/封装评审，完成后另建 `r2` 锁，保留原锁。禁止改写旧锁使其表面通过。

本模块不自动修改 `sym-lib-table`、`fp-lib-table`、原理图或PCB，也不证明资源在当前工程中的实际解析结果。主工作流应另行核对实际库解析、符号/焊盘映射、装配变体、原理图到PCB同步及原生检查，并把当前资源锁与全部输入哈希绑定到评审资料包。没有这些证据，资源一致也不得推进工程批准或制造放行。
