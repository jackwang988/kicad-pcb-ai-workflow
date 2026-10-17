# 脚本目录与调用约定

所有命令在仓库根目录执行。不要批量执行全部脚本；按任务选用。

## 标准库 / PDF 工具

| 文件 | 调用方式 | 写入与限制 |
|---|---|---|
| doctor.py | `python scripts/doctor.py --require core`，可选 pdf/pcb/all | 只读环境；core 就绪不代表 KiCad 可用 |
| diff_net.py | `python scripts/diff_net.py base.xml next.xml [--topo] [--json]` | 只读；0 等价/1 差异/2 无效；不比元件值和封装 |
| pdf_reorder.py | `python scripts/pdf_reorder.py in.pdf out.pdf --order 2,1` 或 `--move 2 1`；`in.pdf --info` | 新输出，不覆盖；不是原理图层级改造 |
| pdf_overlap.py | `python scripts/pdf_overlap.py exported.pdf [--min 0.30] [-v] [--ascii]` | 读取文字框筛查；图形或扫描页漏检需人工复核 |
| sch_parse.py | 模块；也可 `python scripts/sch_parse.py design.kicad_sch` | 按特定文本格式解析，非完整 KiCad 语法解析器 |
| audit_route.py | `python scripts/audit_route.py design.kicad_sch` | 原理图几何筛查，不是电气证明 |
| page_check.py | `python scripts/page_check.py ROOT.kicad_sch`，高级参数见源码 | 需 kicad-cli 真实加载；缺失时失败，不当作通过 |

## KiCad PCB 工具

先 `python -c "import pcbnew"`，并用 `doctor.py --require pcb` 检查。阈值须匹配项目，下面的数字仅示例。

| 文件 | 调用方式 | 写入与限制 |
|---|---|---|
| zcheck.py | `python scripts/zcheck.py board.kicad_pcb [--top 15] [--asm-gap 0.2]` | 布局几何筛查；默认位号文本为 INFO，不代替丝印规则 |
| audit_spec.py | `python scripts/audit_spec.py board.kicad_pcb [--pair P:N:tol_mm] [--diff-width mm] [--edge-clr mm] [--min-pwr-width mm]` | 几何/规则筛查；自动差分识别可能误判，线宽不证明阻抗 |
| net_verify.py | `python scripts/net_verify.py --board board.kicad_pcb [NET ...]` | 连通候选筛查，不代替 DRC；无 NET 时按脚本遍历 |
| detour_check.py | `python scripts/detour_check.py --board board.kicad_pcb [ratio]` | 绕行筛查；多点树/铜皮会影响判定 |
| fold_check.py | `python scripts/fold_check.py --board board.kicad_pcb [u_turns] [ratio]` | 折返筛查，不证明信号完整性 |
| snap.py | `python scripts/snap.py --help`，再按所需参数运行 | PCB 几何渲染，需 Pillow；不是 KiCad 3D/制造视图 |
| gen_bom.py | `python scripts/gen_bom.py board.kicad_pcb --out new-bom.csv` | 新 CSV；不保证 DNP、装配变体、厂家料号完整 |
| refill_zones.py | `python scripts/refill_zones.py in.kicad_pcb new.kicad_pcb [--apply]` | 无 --apply 为计划说明；仅重填已有 zone 到新文件 |

`net_verify`、`detour_check`、`fold_check` 可用 KICAD_BOARD 环境变量代替 --board。未提供有效板文件时拒绝运行，不再使用原工程默认文件。

## 实验性原理图转换

| 文件 | 调用方式 | 必须验证 |
|---|---|---|
| route_v2.py | `python scripts/route_v2.py SRC DST --pdf SRC.pdf --apply`，更多参数用 --help | KiCad 加载、网表、ERC 和视觉复核；标签转换不是 PCB 布线 |
| route_wires.py | route_v2 的内部路径规划模块 | 不承诺能覆盖所有语法、页面或连通情况 |
| split_sheets.py | `python scripts/split_sheets.py SRC NEW_DIR --map map.json --apply` | 映射需包含实际位号；检查父子页、网表、ERC 与属性 |
| _runtime.py | 内部 CLI 输入/输出保护模块 | 防止常见误覆盖，不提供事务级回滚或设计正确性保证 |

拆页映射格式示意（只表示结构，需换成自己图纸中的位号）：

```json
{"Power": ["U_A", "C_A"], "Interface": ["J_A", "R_A"]}
```

映射不完整或错误会导致不期望的输出。原理图转换具有格式假设，首次只在副本测试，不能用通过 Python 语法检查代替 KiCad 实测。

## 未发布的原脚本

原包共 44 个脚本；本版保留 16 个，排除 28 个。其中包括固定坐标/网络号修复、批量删线、固定电源层/板框铺铜、过孔重建、缺少依赖和不具备通用输出保护的脚本。排除不是说所有算法无价值，而是不能把它们原样推广为适用于其他工程的工具。
