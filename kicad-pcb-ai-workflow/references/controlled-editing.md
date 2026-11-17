**注意：旧自研IPC桥入口在此次迁移中被关闭**（`plugin/launch/serve/request/open-editor`均返回 `LEGACY_IPC_WRITER_DISABLED`），下文仅保留历史设计说明，不可照此启用第二写入者；当前操作请用[Konnect迁移规范](konnect-capability-migration.md)。

# 实验性自研 PCB 编辑 · R10.0-alpha.2

2026-11-13策略调整：本工具保留实验源码，不再默认安装或自动回退。实时执行首选[Konnect MCP](konnect-backend.md)，须先完成本机验收。下文是实验实现说明，不表示完整写入/恢复已通过真实GUI验收。

本模块独立实现于官方 KiCad API，没有复制 Konnect 代码。Konnect 不属于默认依赖。执行范围是独立候选工程的封装移动、正交旋转、批量操作、结果回读、补偿恢复、保存和独立原生 DRC。脚本布线、原理图编辑与制造仍使用各自已有流程。

## 安装与连接

核心包只依赖标准库。实时编辑另外需要 KiCad 10.0.8 PCB Editor 和 `kicad-python==0.8.0`（导入名 kipy）。这是本版受限配置；其他版本不因方法存在而获得写入能力。首次插件依赖安装需要网络，不能把“已安装 Skill”等同于“IPC 编辑已就绪”。

1. 将核心 Skill 安装到干净目录，保留旧版作为回退；旧项目原位保留，重建配置 bundle 和受影响评审。
2. 建立供当前 OS 用户使用的 sessions 目录，不放共享网盘或多人可写目录。会话包含工程状态和快照，不能公开发布。连接凭证只保存在 KiCad 启动的进程环境和内存中。
3. 必须进入 PCB Editor（项目管理器的工具菜单不同）。其“工具→外部插件→打开插件目录”可能打开旧式 `10.0/scripting/plugins`；IPC 插件应放 `10.0/plugins`。以实际版本目录为准，必要时向上两级回到 10.0，再打开或创建同级 plugins。选择该 IPC 目录下尚不存在的子目录，不猜测系统或重定向后的 Documents 路径。
4. 执行插件生成预览，核对后加 `--apply`。生成器只在显式新目录写插件，不改 KiCad 设置。默认采用 KiCad 管理的 Python 插件隔离环境；requirements.txt 必须存在，即使预配置模式只含注释；已有隔离解释器时可提供 `--python-executable`，该解释器需预装固定版本依赖。两种模式都使用相对 connect.py 入口；预配置模式由标准库启动入口调用独立解释器，不使用 KiCad 10 会忽略的绝对动作入口。

```text
python scripts/kicad_bridge.py plugin --destination ABS_NEW_PLUGIN_SUBDIR --sessions-root ABS_EXISTING_PRIVATE_DIR
python scripts/kicad_bridge.py plugin --destination ABS_NEW_PLUGIN_SUBDIR --sessions-root ABS_EXISTING_PRIVATE_DIR --apply
```

5. 在 KiCad 偏好设置中启用 IPC API，重启 PCB Editor，打开目标板，点击顶部工具栏 **绿底白色 P** 按钮，悬停提示 **Connect PCB Skill**。KiCad 10 的 IPC 动作不能假定出现在旧式“外部插件”菜单；该菜单用于刷新和定位目录。图标是实际显示所必需的组件，首次隔离环境初始化未完成时按钮可能暂不可用。
6. 如果没有生成会话，先查看 sessions 根目录中新生成的 startup-error-*.json；包含固定错误代码和启动阶段；原生 API 错误经过连接凭证替换与长度限制后仅作本地诊断，不记录环境或请求有效载荷。在 sessions 目录的新 UUID 子目录中找到 `connection.json`，确认目标板路径。用 `inspect` 请求完成往返验证；存在历史 connection 文件不代表连接仍然有效。

总入口支持 `environment.bridge_plugin`，参数与上面一致。不要把 endpoint/token 复制到请求 JSON、命令行或日志。`kicad_ipc_probe` 仍保留独立只读用途。

## 请求与运行顺序

请求是 UTF-8 JSON，拒绝重复键、未知字段和非有限数值。请求队列不运行任意 Python、shell 或外部命令。客户端还核对执行桥源码指纹，旧进程与新包不一致时必须重新连接。客户端提交完整文件后才发布给执行桥；结果也通过完整文件发布。每个会话只运行一个串行请求处理器。

```text
python scripts/kicad_bridge.py request --session-dir ABS_SESSION_DIR --request ABS_REQUEST_JSON
```

涉及复制、应用、恢复或保存时，必须在命令行显式加 `--apply`，JSON 中写 true 不代替该开关。请求超过等待窗口返回 `PENDING_DO_NOT_RESUBMIT`，按返回的 result_file 查结果，不重复提交修改请求。

### 1. 读取源板

请求 `{"op":"inspect"}`。返回 KiCad 版本、目标路径、磁盘/内存指纹，以及封装与真实焊盘坐标。UUID 是对象身份，位号用于辅助阅读。内存与磁盘字节不同不能直接判断存在未保存修改。

### 2. 冻结候选

```json
{"op":"candidate","destination":"/absolute/new-candidate","files":["main.kicad_pro","main.kicad_sch"]}
```

源板名称自动包含，板内容来自稳定的 GUI 内存快照。所有当前存在的同名项目、原理图及库表必须显式包含；项目使用的本地资源也应加入 files。仅复制声明文件，不自动收集外部库、3D和资料；资源完整性继续由 resource_guard 和原生打开检查承担。外部依赖不完整不能宣称工程可移植。

目标目录必须全新且与源项目隔离。候选包含 `candidate-manifest.json`，记录源文件和候选文件指纹。复制成功状态 `CANDIDATE_CREATED_NOT_NATIVE_VERIFIED` 不代表原生验证或设计批准。失败留下的部分目录不作为有效候选，不覆盖后重试。

### 3. 打开候选并重新连接

在 KiCad 打开新候选，执行连接动作获得对应会话。旧会话不能跟随切换到另一块板。候选原生打开失败时先解决项目/资源问题。

### 4. 生成操作计划

```json
{"op":"plan","candidate_manifest":"/absolute/new-candidate/candidate-manifest.json",
 "allowed_box_nm":[0,0,40000000,30000000],"max_delta_nm":5000000,
 "targets":[{"uuid":"00000000-0000-0000-0000-000000000000","x_nm":12000000,"y_nm":10000000,"angle_deg":90}]}
```

替换为真实 UUID、项目边界和目标。坐标单位为整数纳米，1 mm = 1000000 nm；角度是绝对角度。本版仅接受当前与目标角度均为 90° 倍数，每批 1–100 个封装。不换封装、不翻面、不改网络、不自动拖线。

检查锁定对象、源文件、候选资源、移动预算、封装中心及焊盘是否位于声明包络。包络不是精确板边、禁布区或 courtyard 检查；移动可能造成断线，后续需要布线和完整复验。返回 action_id、修改前后封装及焊盘坐标，并保存修改前检查点。计划不执行修改。

### 5. 应用与回读

请求 `{"op":"apply","action_id":"实际计划ID"}`，命令行加 `--apply`。执行前复核会话、文档身份及磁盘/内存基线；任一变化拒绝旧计划。一个批次开启一个原生 commit，检查 update 返回并提交，再读取全部封装 protobuf 状态，对照目标和未修改封装。

`APPLIED_READBACK_VERIFIED_NOT_REVIEWED` 表示实际对象与计划匹配，尚未保存或工程评审。项目已有的网络、布局、电源及制造审查仍需复验，不能直接跨过 G3/G4。

### 6. 取消、恢复与结果不明

提交前失败时取消未提交事务，并核对是否回到基线；确认后返回 `CANCELLED_READBACK_VERIFIED`。提交请求发出后丢失回复，不盲目取消或重试，标记 `RESULT_UNCERTAIN_WRITES_DISABLED`。

`{"op":"reconcile"}` 只观察最近动作的基线/目标状态；它不会解除结果不明会话的写入封锁。发现预期封装不代表整个板没有其他变化。需人工核对检查点和当前工程，重新连接并规划。

`{"op":"restore","action_id":"最近已验证动作ID"}` 加 `--apply`，仅在当前完整内存指纹仍与该动作结果一致时，将原封装对象作为新 commit 恢复并回读。它是补偿事务，不是假装撤销已提交 commit；不会覆盖后续手工修改，不自动保存。原生 Undo 仍由 KiCad 提供。进程重启后不重放旧计划，检查点用于人工恢复和重建候选。

### 7. 保存与原生复验

`{"op":"save","action_id":"最近已验证动作ID"}` 加 `--apply`，仅保存同一候选，保存前后检查状态和源文件保护。然后执行：

```text
python scripts/kicad_bridge.py drc --board ABS_CANDIDATE_BOARD --candidate-manifest ABS_MANIFEST --kicad-cli ABS_CLI --output-dir ABS_NEW_EXTERNAL_REPORT
```

该步骤用固定 KiCad 10.0.8 CLI 原生重载磁盘候选并记录 DRC/未连接项。执行成功与 DRC 合格分开，报告状态为 `NATIVE_DRC_RECORDED_NOT_APPROVED`。不覆铜、不保存 CLI 修改、不授予工程批准；最终覆铜、schematic parity、高级规则及制造门禁沿用已有工作流。

`{"op":"stop"}` 结束会话，不保存 GUI、不自动撤销当前工程。

## 总入口与证据

在已建立的新候选项目 bundle 下，用 `pcb.edit --bridge-request PROJECT_REL_JSON --session-dir ABS_SESSION_DIR` 派发请求；有写入授权时加 `--apply`。`pcb.edit_drc` 接受 candidate-manifest、kicad-cli 和 output-dir 参数。原始脚本接口也可通过白名单 project_flow 调用。

工程文件变化继续使已有文件哈希绑定的检查和评审失效；执行日志、连接成功、回读成功或原生 DRC 都不代替工程师签核。日志不伪造 PASS，不自动填制造授权。

## 多实例与启动故障

首次安装验收优先只保留一个 PCB Editor。AS_TOKEN_MISMATCH 表示响应实例与 KiCad 提供的实例标识不一致，必须拒绝连接，不能清空标识或自动连接其他端点。关闭残留旧实例后，若出现 Connection refused，应重启选定的 PCB Editor 重新启动其 API 服务。遇到 board_already_owned_in_sessions_root，不重复建立会话，先复用有效会话或显式 stop 后再连接。

## 并发与验证范围

同一 sessions_root 下，对同一路径的执行桥用 OS 文件锁互斥，进程退出后由 OS 释放。该锁不锁住 GUI 人工操作、第三方程序或使用另一个 sessions_root 的执行桥。所有协作者应共享同一私有根目录，并在执行窗口避免手工并发修改。前后回读提供冲突检测，不宣称 API 具有原子比较并写入能力。

软件契约、正式客户端变换、真实 GUI 正常路径、故障注入、跨平台及硬件验收分别记录。以本次交付的验证报告为准；本版不宣称通过所有故障、器件封装或版本组合。

依据：[官方 IPC 与插件边界](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/)、[正式 Board API](https://docs.kicad.org/kicad-python-0.7.1/board.html)。实现采用的实际正式客户端版本为 0.8.0，依赖及服务端能力仍需实际验收。
