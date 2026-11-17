# KiCad PCB AI Skill R10 · 节点6 G1缓存优先复用升级

基于上一版 `R10.0-alpha.3-local.5+cache-first-1` 脱敏分享包的独立派生增强版本：`G1-cache-reuse-1`。本文件说明本轮**真实修改**，并非表示已合并到GitHub仓库。

## 目标

节点三已核对并创建器件知识卡与原厂资料后，节点六G1原理图评审必须默认利用节点三的**项目冻结资料包**，而不是再次联网搜索、下载芯片规格书。没有缓存、证据无效或版本过期时，应返回节点三按需补齐，不在G1隐式重新下载或假定一定命中。

## 代码变更

1. `scripts/device_knowledge.py` 新增 `project_review_cache`：从项目冻结 `device-bundle.json` 与已验证的卡片生成G1小摘要，包含每个器件的具体型号、封装、条件、规则、原文短引用和章节/定位信息；只给出待评审候选，不自动判定PASS。默认每器件12条，超出显示 `truncated=true`，AI必须按需读取其余条目。
2. `scripts/static_review.py` 的 `--stage schematic` 自动生成 `device-knowledge-brief.json`，并在 `packet.json.device_knowledge_brief` 和 `review-request.md` 中强制指定先读知识卡。对匹配源文件SHA的已冻结原厂资料复用 `texts/`，不再重复运行PDF文字提取工具；其他非器件文档沿用原行为。源PDF依然保留且绑定哈希，需要看电路图/波形/脚注时只打开对应本地章节或图片。
3. `scripts/static_review_gate.py` 要求G1摘要存在、与项目冻结证据内容一致，并纳入评审资料包SHA清单；篡改、缺失、版本与资料不一致时阻断。
4. 同步更新 `SKILL.md`、原理图/器件知识库/静态评审文档及43个运行组件SHA清单，保留原来的只读/工程师确认/制造放行边界。

## 运行方式

先沿用节点三 `resolve → audit → bundle`，将已审核来源冻结到**当前项目目录**（不直接依赖跨项目共享缓存持续联网）；原理图静态评审配置的 `device_knowledge.manifest` 指向当前项目冻结包，`sha256` 写入真实文件哈希，并把原始资料按原先 `documents` 和 `component_sources` 正确引用。然后：

```bash
python scripts/workflow.py run /path/project --bundle control-r1 --task schematic.prepare --output-dir /path/project/reviews/schematic-r1
```

或调用原来的直接命令：

```bash
python scripts/static_review.py /path/project --config /path/project/static-review.json --stage schematic --output-dir /path/project/reviews/schematic-r1
```

在新生成的评审目录先读 `device-knowledge-brief.json`，再结合实际网表、ERC与必要原图进行评审。之后仍需原来的AI评审与硬件工程师确认。

## 验证与边界

- 12项离线合成测试通过，包括一个完整G1评审资料包的生成测试：它确实产生缓存摘要并复用已保存的源文字，且不依赖联网；篡改和无效引用检查通过。
- `workflow.py modules --module schematic` 组件清单与43个活跃工具文件哈希检查通过。
- 没有在本次对真实芯片、原理图ERC、外部MCP后端或KiCad GUI进行端到端硬件验收；真实工程适用性仍需要G1核对。
- 节省Token来自优先读取摘要和选择性展开全文，并非自动保证固定节省比例。
- 发布包**不包含**用户个人缓存、厂商受版权保护的PDF、NDA资料或真实工程项目；分享前须独立确认代码/文档授权。
