**动态能力发现**：新安装或需要新操作时使用[Konnect迁移规范](konnect-capability-migration.md)。`environment.konnect_discover/assess/fixture/invoke`已作为总入口任务；日常连接检查仍不必发现全部工具。默认CLI-only环境烟雾不再强制pcbnew。

# 环境与KiCad连接

适用：确认连接、首次安装、版本变化或具体连接故障。先匹配用户请求的范围，日常默认轻量检查。

## 日常默认：一次查询，通过即止

| 用户请求 | 首选调用 | 能证明的范围 |
|---|---|---|
| MCP是否在线、ping一下 | 宿主支持的MCP协议ping；未暴露ping时用一次get_active_toolsets({})等已暴露的轻量只读调用 | Codex到Konnect服务响应正常；不证明KiCad在线 |
| KiCad是否连通、重启后再测、连接全链路 | 一次open_project；用户已给板路径则传path，否则省略 | 同时检查服务响应、KiCad IPC和打开的PCB文档 |

MCP使用本地stdio，不能用网络ICMP ping替代协议检查，也不臆造名为ping的工具。已有一次成功的直接工具调用时，不额外补ping；KiCad连接请求优先直接open_project，通常一次调用即可。此工具在启动工具集中，无需先加载所有工具集或完整读取安装信息。

结果按实际字段简短报告：

- ipc_available=true且无查询错误、有打开的板：实时PCB连接通过；指定path时还必须requested_open=true。
- ipc_available=true但无打开的板：MCP/KiCad接口可达，尚无PCB可读取。AS_UNHANDLED可能表示当前端点只提供管理器能力，不把它误报为服务宕机。
- ipc_available=false：报告返回的ipc_failure，例如未启动、无监听或地址不可达；不要猜测文件损坏。
- 多板、指定板未打开或返回路径不符：报告目标状态，连接检查不自行切换目标。

通过即结束，通常只需一两句话。不因“全链路”一词自动扩大为布局、布线或写入验收。不重复工具发现、版本查询、独立MCP子进程探测、器件/焊盘回读、哈希、DRC或安装器check；这些按具体需求调用。

连接检查默认仅接口读取，不截图、不控制桌面、不自动启动/关闭KiCad、不打开/新建测试板、不修改工程或配置。若没有打开的PCB，直接报告该状态。用户另行要求打开工程、修复连接或验证操作能力时，再执行相应范围。

## 失败后按原因诊断

先使用调用已经返回的错误。仍需区分原因时，只增加一次针对性的只读诊断，例如get_recent_calls或get_installation_info；不要把doctor、进程扫描、IPC探测、安装器检查和GUI检查串成默认流水线。结果仍不确定或超时，报告已知层级、失败点和最小下一步，避免无界重试。更深入的修复按用户任务范围进行。

需要核验精确板内容时，才按[Konnect接入规范](konnect-backend.md)加载对应只读工具并确认source=ipc；文件回退不能证明实时连接。若宿主没有暴露某个动态工具，不因此重复安装或扩大为桌面操作。

## 安装、工具链及操作能力验收

首次安装/升级按[Konnect后端](konnect-backend.md)核验发行物与注册信息；准备执行CLI/pcbnew工程操作时按[环境教程](environment-onboarding.md)验证匹配工具链。安装检查、日常连接和移动/旋转/保存等操作能力验收分别记录，后者仅在用户要求相应验收时使用隔离候选。

深入检查入口仍可用：`workflow run PROJECT --task environment.konnect_check --board BOARD --output-dir NEW_REPORT`，它会验证安装记录与唯一实时板，不是日常必跑命令。不带board仅证明MCP。独立[IPC读取适配器](ipc-backend.md)用于具体IPC诊断；实时快照与磁盘文件分别记录，同一工程保持单写入者。桌面注册名为pcb_skill_konnect；自研编辑桥不作自动回退。
