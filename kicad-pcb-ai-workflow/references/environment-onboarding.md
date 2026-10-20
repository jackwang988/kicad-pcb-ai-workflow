# 新手环境配置与日常启动 · R9.3


## 目录

1. 适用范围与准备
2. Windows首次配置
3. 第一次真实工程验证
4. 日常启动与重验条件
5. Linux/macOS与Agent连接
6. 常见失败与全流程入口

## 1. 适用范围与准备

首次配置一次，日常快速检查通过后直接进入项目输入。环境通过仅代表已测工具可运行，不代表电路正确或可以制造。本教程负责环境入口；备用/DNP方案按reserve-options.md执行，不自动全板增加器件。

需要：官方KiCad10.0.7、能导入对应pcbnew的Python、本地文件/命令执行与读图能力的Agent、当前完整Skill目录、一个合法且非空的KiCad示范工程。若只用云端聊天且无法访问装有KiCad的电脑，需要先建立平台支持的本地执行连接；MCP可选，不能只凭工具列表认定连接成功。

从https://www.kicad.org/download/获取官方软件；当前候选锁定10.0.7，其他版本保持未验收，不自动升级/卸载。以下为跨项目的配置步骤；每台机器必须实际检测安装位置、版本和解释器，不能沿用他人的环境通过记录。

## 2. Windows首次配置

1. 安装并启动KiCad，打开原理图编辑器和PCB编辑器，完成默认符号/封装库初始化。先用GUI确认选用工程能打开、库能解析、封装符合预期；外部库和路径变量也需配置。此步骤不能由版本检测替代。
2. 将完整Skill放在Agent支持的本地Skills目录，按该平台说明启用；没有统一跨平台安装目录。必须保留SKILL.md、scripts、references和assets的相对结构。
3. 在Agent使用的PowerShell中设置以下示例变量，改成实际路径。Test-Path为False时先找正确路径，不继续。

```powershell
$SkillDir = 'D:\AI-Skills\kicad-pcb-ai-workflow'
$KicadBin = 'C:\Program Files\KiCad\10.0\bin'
$CLI = Join-Path $KicadBin 'kicad-cli.exe'
$PYK = Join-Path $KicadBin 'python.exe'
Test-Path $CLI
Test-Path $PYK
Test-Path (Join-Path $SkillDir 'SKILL.md')
```

4. 验证CLI与绑定，必须使用匹配的解释器；不靠普通Python/Anaconda的pip install pcbnew解决版本问题。

```powershell
& $CLI version
& $PYK -c "import sys, pcbnew; print(sys.executable); print(pcbnew.GetBuildVersion())"
```

CLI目标为10.0.7，绑定也应匹配。找不到python.exe时查询实际安装布局，不创建假路径、不套用旧版Python3.11。

5. 将CLI目录加入当前会话PATH，运行自检。此命令不修改系统PATH；后续运行的Agent子进程必须继承同一配置。

```powershell
$env:Path = "$KicadBin;$env:Path"
Set-Location $SkillDir
& $PYK scripts/doctor.py --kicad-cli $CLI
$LASTEXITCODE
```

required_ok=true且退出0才是基础通过。把上述路径配置保存到用户自己的本地启动记录，日后在同一Agent执行环境加载；Skill不擅自写系统环境、安装软件或持久化全局配置。只在手工终端配置PATH、Agent却使用另一环境时仍会失败。

## 3. 第一次真实工程验证

选择一个你有权使用、已能在GUI打开的非空示范工程；顶层原理图、PCB、项目文件同名。运行包不附带生产示范工程，应选择已有合法工程；开发夹具不能冒充成功示范。准备一个位于工程外且尚不存在的报告目录。setup会复制整个工程（排除.git和__pycache__；符号链接拒绝），原工程不写入。

```powershell
& $PYK scripts/environment_start.py setup --project 'D:\Projects\demo' --schematic 'demo.kicad_sch' --board 'demo.kicad_pcb' --project-file 'demo.kicad_pro' --report-dir 'D:\KiCad-Checks\setup-r1' --kicad-cli $CLI
```

默认PREVIEW显示工程、输入和目标目录及步骤概述，不是完整原生argv清单；不写报告/副本，也不运行工程烟雾测试。基础工具缺失会先BLOCKED，此时不代表路径已经验收。基础探测阶段失败尚未创建目录，需保存终端输出用于排错。核对路径后加--apply执行实际验证：

```powershell
& $PYK scripts/environment_start.py setup --project 'D:\Projects\demo' --schematic 'demo.kicad_sch' --board 'demo.kicad_pcb' --project-file 'demo.kicad_pro' --report-dir 'D:\KiCad-Checks\setup-r1' --kicad-cli $CLI --apply
```

执行内容：复制项目→导出原理图PDF/XML→导出顶底铜层PCB PDF→ERC/DRC JSON及parity→pcbnew.LoadBoard→核对原工程未改变。输出仅在新报告目录，不导出Gerber/BOM。工程依赖绝对路径的外部库不会被自动打包，仍需人工核对。

成功为ENVIRONMENT_READY和startup-state.json；失败为BLOCKED，已开始的运行保留failed-setup.json/命令日志，不产生成功记录。报告目录已存在会拒绝覆盖，修复后用setup-r2等新目录。

ERC/DRC有违规但命令及已支持JSON解析正常时，记录design_issue_counts，仍可能ENVIRONMENT_READY；这是工具可运行，绝非设计通过。JSON模式未识别或命令失败会阻断，需查原始日志，不能修改报告伪造通过。

还需Agent实际打开导出的PDF，说清一个真实位号/网络/图层，并由用户检查它读对；GUI库/封装、读图能力和项目资源不是本脚本可自动证明的内容。PCB PDF只用于冒烟验证，不代表全部铜层评审或CAM。

## 4. 日常启动与重验条件

在已配置的同一Python/CLI环境运行：

```powershell
& $PYK scripts/environment_start.py check --state 'D:\KiCad-Checks\setup-r1\startup-state.json' --kicad-cli $CLI
```

check只读，不安装/配置/写报告；每次真实探测当前CLI和绑定，比较操作系统、Python/CLI/绑定及Skill脚本哈希、选定路径环境变量摘要和保存的烟雾证据。默认完整验证记录有效7天，可用--max-age-days 0..365按团队政策指定。7天是启动复验策略，不是硬件行业强制标准。

- ENVIRONMENT_READY/退出0：跳过重复安装和完整烟雾验证，进入当前项目需求及资源检查。
- FULL_SETUP_REQUIRED/退出2：无记录、过期、证据丢失、工具/解释器/脚本/相关路径变化；在新目录重新setup --apply，不手改日期/哈希。
- BLOCKED/退出2：当前工具缺失/版本不符或读取异常，先处理原因。

状态记录是本地复用依据，不是防伪签名，也不能穷尽全部DLL/操作系统/外部库变化。新电脑、新执行环境、异常或重大系统/工具变化应主动重验。新项目不能跳过自己的库、需求、规则、原厂资料和制造检查；生产前仍运行最终全量门禁。

## 5. Linux/macOS与Agent连接

命令结构相同，把$PYK替换为能导入目标pcbnew的Python路径，$CLI替换为实际kicad-cli路径。先执行：

```bash
/actual/python -c 'import pcbnew; print(pcbnew.GetBuildVersion())'
/actual/python /actual/skill/scripts/doctor.py --kicad-cli /actual/kicad-cli
/actual/python /actual/skill/scripts/environment_start.py check --state /actual/setup/startup-state.json --kicad-cli /actual/kicad-cli
```

Linux/macOS完整setup格式：

```bash
/actual/python /actual/skill/scripts/environment_start.py setup --project /actual/demo --schematic demo.kicad_sch --board demo.kicad_pcb --project-file demo.kicad_pro --report-dir /actual/new-setup --kicad-cli /actual/kicad-cli
# 核对预览后，在同一命令末尾加 --apply 执行真实副本验证
```

当前无工具时check优先BLOCKED，即使状态文件也缺失；工具匹配后才判断是否需要首次完整验证。不假定所有平台安装包都包含相同目录名或python可执行程序。系统包、沙箱安装、WSL调用Windows程序等要验证路径与资源可达，不把另一环境的检测结果复用。本版没有跨平台安装器或GUI自动化连接器。

## 6. 常见失败与全流程入口

| 现象 | 排查与处理 |
|---|---|
| Test-Path=False/找不到命令 | 检查实际安装目录，使用完整路径，确认Agent所在电脑/环境 |
| No module named pcbnew | 使用匹配绑定的解释器，别混用系统Python/Anaconda |
| CLI与绑定版本不一致 | 明确选中同一目标安装包，重新doctor，不关闭检查 |
| 手工终端可用，Agent不可用 | 在Agent实际执行环境检查PATH、Python及文件权限 |
| 库缺失/封装不解析 | GUI初始化库，修正项目库表和路径变量，再核对来源 |
| JSON/PDF导出失败 | 查看failed-setup.json内实际命令和输出，不把空文件当成功 |
| check要求完整重验 | 查reason，保留旧报告，在新目录运行setup，不改记录过期时间 |
| 原厂下载失败 | 参考device-knowledge.md用真实原始文件离线导入，仍需来源核对 |

环境就绪后的顺序：需求冻结→器件资料与规则→原理图/设计意图→AI及工程师确认→封装→叠层→布局/布线→PCB逐层AI及工程师确认→NPI→制造候选/CAM/工厂EQ→授权打样→真实验证。完整模块入口见SKILL.md、device-knowledge.md、design-intent.md、static-ai-review.md和dfx-npi.md。

可给Agent的首次指令：请使用本目录Skill，读取新手配置教程，检查本地KiCad10.0.7和匹配Python；先预览配置与测试命令，只在独立新目录验证已有示范工程，不改原工程。报告实际执行结果、缺项和下一步；禁止把环境通过当生产通过。

## 布局专项入口

完成环境配置后按full-workflow.md进入需求/资料/工程门禁；布局阶段按placement-quality.md建立placement-plan。检查模块归属、准确电源/地端子与局部电路、布线前和最终视觉复验，不自动移动器件。原生环境通过不代表布局或制造通过。

## 项目通用入口

环境可用后先读universal-workflow.md，建立project-flow并指定实际需求/执行方法。不要运行历史固定坐标或默认写入脚本。原理图精确草稿与制造导出均有新独立候选接口，环境通过不自动完成设计。
