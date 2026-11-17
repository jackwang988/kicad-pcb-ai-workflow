# KiCad IPC 只读接通与内存快照

本工具继续只读。R10.0-alpha.2新增独立的[受控候选编辑桥](controlled-editing.md)，不要将两个工具的权限与验收范围混用。

这是可选的只读适配器，不安装依赖、不启动或关闭 KiCad、不打开工程、不保存 GUI 当前文档、不移动/创建对象、不覆铜、不导出制造文件。探测通过只说明本次读取范围，不能作为 PCB 编辑后端完整验收、设计通过或制造授权。

## 适用条件

- 使用官方 `kicad-python` 包（导入名 `kipy`）；该依赖不包含在核心标准库工具链内，也不会自动安装。R10 接入前应锁定已验收的正式包版本与 KiCad 版本组合。
- KiCad 10.x 的 PCB Editor 已运行并启用 IPC API。原理图 IPC、headless、IPC 制造导出不在本适配器的范围内。不要把 KiCad 11 开发文档里的功能当作 10.x 已有能力。
- 通过 KiCad IPC 插件启动的客户端可获得 `KICAD_API_SOCKET` 和 `KICAD_API_TOKEN`。本适配器要求两者都显式存在于调用进程环境，不搜索默认端点。不要把 token 放进命令行、工单或日志。
- `--board` 必须提供目标 `.kicad_pcb` 的绝对路径。脚本将它与真实 `board.document.project.path` + `board.document.board_filename` 比较；仅名称相同不算匹配。多实例时必须使用对应实例提供的环境，不能仅连接第一块找到的板。

## 命令

```text
python scripts/kicad_ipc_probe.py probe --board ABSOLUTE_BOARD_PATH
python scripts/kicad_ipc_probe.py snapshot --board ABSOLUTE_BOARD_PATH --output-dir ABSOLUTE_NEW_REPORT_DIR
```

可选 `--timeout-ms 2000`（范围 1–60000）和 `--require-ipc`。`probe` 与 `snapshot` 均接受 `--output-dir`。未传目录只输出 JSON，不写文件；`snapshot` 此时只计算快照哈希，不输出原始板文本。报告目录必须是显式指定的绝对新目录，父目录已存在，并位于源 PCB 所在目录之外；已有目录拒绝覆盖。

成功快照目录包含：

- `ipc-report.json`：连接选择方式、目标/实际绝对板路径、KiCad 版本、方法存在性、内存/磁盘 SHA-256、字节数与状态。
- `memory-board.kicad_pcb`：`get_as_string()` 返回的 GUI 内存板文本，不是原工程保存或制造冻结。该文件未经过原生重载、设计检查或放行。

原始端点和 token 均不输出；错误只给固定代码，不回显第三方异常。端点 SHA-256 仅用于识别本次选择的端点，不是 token 哈希、服务端认证凭证或重启后身份连续性的证明。若返回的板文本包含连接敏感值，会拒绝保存而不是修改快照内容。

## 状态和失败处理

`READONLY_PROBE_OK` 表示版本和目标板身份读取成功。`board_method_presence` 仅是客户端方法存在性，不代表服务器支持、行为验证或任何写权限。`READONLY_SNAPSHOT_OK` 还要求两次内存读取相同、再次读取的板身份一致、读取期间磁盘哈希未变。这不是原生原子快照或 GUI 锁，生成后工程仍可能变化。

缺 `kipy`、未传连接环境、GUI/API 未连通、未打开目标板或内存读取不受支持会输出 `OPTIONAL_UNAVAILABLE` 与错误代码。默认退出 0，让离线读取、工程规则和已有 CLI 功能继续使用；需要 IPC 的节点必须检查 `ipc_ready` 或使用 `--require-ipc`，不足时退出 2。身份不匹配、读取期间状态变化、参数或报告路径错误总是退出 2；不要自动重试写入或换实例。

内存与磁盘字节哈希不同不一定等于“GUI 有未保存修改”，因为序列化格式可能不同。本报告明确将 `unsaved_changes` 保留为未判定。磁盘文件缺失/不可读会单独标记，不伪造磁盘验证。

## 验收边界

本版提供协议软件测试，可使用注入客户端验证只读调用、身份拒绝、敏感信息保护和输出隔离。注入客户端的报告会标 `injected_test_client`，不是 KiCad live 验收。本版不附带真实 GUI 接通证据；每台使用者电脑应在真实 KiCad 和自己的目标工程上执行命令，保留本次报告。写入、事务、撤销、断线恢复、原理图同步、布局/布线和制造仍须各自完成真实后端验收。

依据：[KiCad 官方 IPC 接入与版本边界](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/)、[官方 kicad-python](https://pypi.org/project/kicad-python/)、[正式版 Board API](https://docs.kicad.org/kicad-python-0.7.1/board.html)。
