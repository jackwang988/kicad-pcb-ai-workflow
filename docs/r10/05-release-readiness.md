# R10 预发布与验收状态（2026-11-17）

[返回导航](README.md) · [预发布说明](../../R10_RELEASE_NOTES.md) · [稳定R9.4](../../README.md)

| 验证范围 | 结果 | 说明 |
|---|---|---|
| 完整R10 Skill源码及G1–G4/单写入迁移 | ✅ 已提交候选分支 | 44个登记Python组件，含JSON配置、文档、代码 |
| R9.4既有软件回归 | ✅ 319/319 | [GitHub Actions](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44015071931) |
| R10新增离线测试 | ✅ 33/33 | 真实后端调用不在此测试范围 |
| 独立Skill安装包结构 | ✅ 通过 | 构建器验证输入、脚本清单、相对文件 |
| KiCad 10.0.8原生工具链 | ✅ 通过 | [native验收](https://github.com/jackwang988/kicad-pcb-ai-workflow/actions/runs/44015065144) |
| Konnect商业MCP Windows实时操作 | ⚠️ 未进行本轮端到端验证 | 动态工具可发现不等于功能已验收 |
| 复杂板高速、自动布局/布线、工厂生产授权 | ⚠️ 未宣称通过 | 每个项目按G1–G4和CAM独立验证 |

**发布标签：R10.0.0-rc.1（pre-release），不是稳定/量产授权。** R9.4安装包仍可独立下载。回归测试的通过是代码兼容和工具链证据，不代替真实Konnect可用性及电气正确性。
