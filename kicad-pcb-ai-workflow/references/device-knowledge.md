# 器件资料检查、补齐与复用 · cache-first 增强（兼容R9.3契约）


## 节点3强制顺序：缓存优先、按需补齐（cache-first增强）

**所有新原理图需求、芯片替换、器件清单创建，在任何联网查找、PDF下载或向模型加载完整手册前，必须先执行以下离线步骤。** 旧的 `audit`/`bundle` 门禁保留；`resolve` 是自动查库的前置入口，不是放行引擎。

1. 从真实需求/既有BOM识别核心器件，写出 `assets/device-requirements.template.json` 格式的**新项目清单**。每个器件必须有精确 `manufacturer + mpn + package + ref + application + required_kinds`；`cards=[]`、`latest_checks={}`。相同芯片用于不同位号仍需各自独立标明应用工况。
2. 对**共享的、仓库外的** `device-cache` 运行 `resolve`（只读、默认不联网）。它从不可变 `registry/` 查找已核对知识卡和与该原厂文件绑定的最新版本核验记录；型号+制造商+封装精确匹配，不使用系列猜测或近似替代。
3. `CACHE_HIT_READY_FOR_AUDIT`：在规定的 `max_check_age_days` 内，直接把**卡片引用及已有真实版本检查证据**写入新项目 requirements；可调用 `brief` 按器件和类别只返回必要的条目、条件、原文短引、章节、版本、来源哈希。**无需重复联网、重新下载、全文转成Token或再次提炼卡片**。需要看波形、时序、推荐接线图、脚注等时仍须按需打开已缓存原始手册对应章节/图片。知识卡不代表新产品参数和拓扑已审定。
4. `MISS`：仅对缺少的准确器件/资料种类进行原厂资料搜索、下载、实际阅读核对、建立卡片；`STALE`：先检查官方版本/勘误，不假装仍为最新；`AMBIGUOUS`/`INVALID_CACHE_ENTRY`：阻断并人工解决版本或文件冲突，不自动退回旧卡。局部命中时保留有效卡，不重复获取。
5. 首次完成原始 `audit` 后执行 `register --requirements ... --apply`，把已验证卡片和实际 `latest_checks` 登记为可跨项目复用的不可变索引；旧项目已审核的 requirements 可以用该命令迁移到新索引。`register` 不会创建卡片、更改证据日期、在线查询或生成不真实审核记录。源文件变更/勘误发布必须重新核查和登记新记录；旧版本保留供冻结项目追溯。
6. 仅当全部必需资料 `resolve` 命中并通过原本的 `audit`，才可 `bundle --apply` 生成项目专属冻结证据，并为原理图G1/G2构建逐项审查任务。新项目的电压、工作模式、引脚、封装、硅版本、推荐电路和真实条件都要核对；**不能将历史项目通过自动转换为新项目通过**。
7. 该流程是**本机/共享目录离线知识库**，不会自动跨设备云同步，也不会自动联网监测厂商新版本。设计定稿、资料超时、重要勘误、安全关键设计或生产签核应主动核对官方最新资料，更新注册后重新解析，必要时重审受影响项目。

### 统一 `workflow.py` 节点3入口（推荐新项目使用）

```bash
# 工作流统一入口：优先只读查库。项目要求文件是project目录下的相对路径，缓存可以独立持久存放。
python scripts/workflow.py run /projectB --task architecture.sources_resolve --device-cache /shared/device-cache --device-inventory device-inventory.json
# 全部命中后写入新的项目绑定（单独的新文件）；失败保持阻断且不输出半成品。
python scripts/workflow.py run /projectB --task architecture.sources_resolve --device-cache /shared/device-cache --device-inventory device-inventory.json --device-output resolved-requirements.json --apply
# 已有项目完成原厂真实核对和audit后注册跨项目复用，仍使用显式--apply。
python scripts/workflow.py run /projectA --task architecture.sources_register --device-cache /shared/device-cache --device-inventory verified-requirements.json --apply
```

节点3无需先构建整个16节点配置bundle；由当前工具白名单校验并调用`device_knowledge.py`，不会偷偷执行联网搜索。生成的resolved文件仍需原有audit、bundle、G1/G2评审。

### 新增的命令（示例；路径替换为实际路径）

```bash
# 一次性：把以前已核对通过的资料卡/版本检查记录纳入共享索引
python scripts/device_knowledge.py --cache /absolute/path/device-cache register --requirements /projectA/verified-requirements.json --apply

# 每次新项目、原理图需求确认时最先执行：只读探测（不下载）
python scripts/device_knowledge.py --cache /absolute/path/device-cache resolve --requirements /projectB/device-inventory.json

# 只有全部命中时：保存到新项目的全新文件（不覆盖原要求）
python scripts/device_knowledge.py --cache /absolute/path/device-cache resolve --requirements /projectB/device-inventory.json --output /projectB/resolved-device-requirements.json --apply

# 只给模型看本次需要的知识条目，不把整份PDF加载到上下文
python scripts/device_knowledge.py --cache /absolute/path/device-cache brief --requirements /projectB/resolved-device-requirements.json --ref U1 --limit 8

# 原有门禁保持不变
python scripts/device_knowledge.py --cache /absolute/path/device-cache audit --requirements /projectB/resolved-device-requirements.json
python scripts/device_knowledge.py --cache /absolute/path/device-cache bundle --requirements /projectB/resolved-device-requirements.json --output /projectB/device-sources-r1 --apply
```

新项目清单与旧的已解析 requirements 使用同一 schema 1，**不破坏原本项目格式**。在 `resolve` 之前若已有 `cards` 或 `latest_checks`，应使用 `audit` 检查已有绑定，不自动覆盖。`resolve` 无需下载任何资料，缺失只报告状态；联网获取仍由Agent通过当前可用、经过授权的工具完成。

**隐私与授权：** 公开发布的Skill ZIP仅包含代码、模板和测试，不包含用户个人的共享器件库、厂商原版PDF、NDA资料、私有核对记录；将共享器件库同步给团队须单独确认数据访问权和原厂资料版权。

## 节点6 G1原理图评审：复用项目已冻结的器件知识库

**执行规则：** 节点3已经获取并冻结资料，G1不得默认再次联网搜索、下载芯片规格书、重新制作知识卡或把全文重复加载到模型。`static_review.py --stage schematic` 使用 `config.device_knowledge` 指向项目内原有的 `device-bundle.json`，在正式评审前重新执行原有 `validate_bundle` 门禁；它检查缓存源、已审核卡、实际版本检查证据和哈希，不假定共享缓存一定存在内容。已在项目中的冻结证据不依赖跨项目共享目录持续在线。无法匹配/过期/损坏/缺少真实证据 → 阻断相关评审并返回节点3精准补齐，不在G1静默重新下载。

脚本为G1创建 `review-packet/device-knowledge-brief.json`，按**位号 → 精确MPN/封装 → 应用工况 → 已核对规则条目/条件/原文定位**生成精简条目；默认每器件展示最多12条，`truncated=true`表示尚有未展示条目，需要按需读冻结卡片，不能忽略。`review-request.md` 明确让AI先读它，再针对实际网络、引脚、启动模式、电源域等进行逐项判断；卡片条目状态为候选，绝不是自动通过。原始手册/指南仍在评审 `documents` 和 `component_sources` 中绑定并纳入SHA基线；AI仅在参数不足、冲突、特殊工况、图表/推荐应用电路等情况下打开**本地冻结原文的相关章节及图**。不采用在线搜索摘要代替真实原厂证据。

为减少重复文件处理，若评审文档SHA和已审核卡绑定的原始文件完全一致，静态评审直接复用冻结的 `texts/` 文字，`documents[].text_origin=verified_project_device_cache`；不运行第二遍 `pdftotext`。其他项目规范/无缓存来源按原逻辑处理，不能当成器件库命中。最终G1仍需KiCad真实ERC/网表核对、AI项目适用性评审和工程师本人确认；对版本时效的政策核对不等于厂商实时更新通知。

## 原有资料导入与工程门禁流程

在static_review.py之前执行本流程。目的：减少重复下载和漏读，不把摘要当作完整规格或合格结论。先读取工程BOM/网表，逐一列出核心IC完整制造商、MPN、封装、工作模式及位号；人工检查清单是否漏项，不能仅按U前缀推断全部IC。

1. 创建device-requirements.json：schema_version=1、max_check_age_days（0–365，用户/企业明确采用的版本核对周期）、devices数组。每器件包含ref/manufacturer/mpn/package/application、required_kinds、cards、latest_checks。required_kinds必须含datasheet；按器件增加errata/hardware_guide/application_note。原厂没有独立勘误时保存查询记录，由工程师决定清单，不伪造空白勘误。日期政策不能证明厂商两次查询之间没有发布更新；新项目、定稿和生产签核前应主动再查。
2. 对新项目先resolve共享索引，再audit已解析的本地资料。缺少/过期资料时，Agent通过当前可用联网搜索工具找到原厂产品页，确认精确型号/封装和资料版本。检查datasheet、errata、硬件指南及应用笔记。不要从搜索摘要生成可信资料卡，不把第三方网站当原厂。
3. 使用ingest从已确认的官方HTTPS URL下载。必须显式给出精确原厂主机allowlist；重定向也受同一白名单约束。禁止登录绕过、内网地址、执行下载内容。网络受限时使用用户或已授权下载工具提供的原始PDF以--source导入；仍标明本地来源未独立验证，不能把网页提取片段保存成完整PDF。下载失败保持阻断，不要求用户批准来掩盖环境问题。
4. 原文按SHA-256去重，保留独立文档/版本/型号记录和提取文字。ingest不会认定文档适用或可信；draft只生成待填写模板。Agent实际读全文相关章节、表格、推荐电路/布局图及勘误，再填写items。扫描PDF/识别失败保持gaps，不编造OCR。只读纯文字不能声称读过推荐电路图。
5. 核对资料卡后才标verified。verification必须绑定当前identity/record_sha256/items/gaps摘要和真实核对记录文件/哈希，注明reviewer/date/reason/source_identity_reason。PDF还需figures_checked=true，表示实际完成视觉核对。Agent可记录自己的真实提取复核，但不得冒充硬件工程师；关键内容应由硬件工程师复核。脚本验证声明与文件绑定，不验证人员身份和推理真伪。
6. latest_checks逐kind保存date/revision/source_sha256/file/sha256/checked_by/result=current，文件是实际原厂当前版本查询依据。脚本不自动声称“最新”。发现新版：保存新记录/新卡、比较变更、评估相关项目，保留旧项目冻结版本；未确认的新版不可静默替换，也不能仍写current。
7. audit通过后bundle --apply导出独立新目录，冻结所选资料与证据。candidates仅是逐项规则候选，Agent必须依据当前模式/电压/叠层/拓扑判定适用性，不能自动复制成PASS。
8. 在静态评审config增加device_knowledge，指定manifest/sha256/required_refs/identity_fields。原始datasheet/指南仍要列入documents，并绑定component_sources；摘要不替代原文。把候选逐项转为已有tasks（目标位号、引脚、网络、图层、风险等级、来源章节和谓词）。正常执行AI评审→硬件工程师确认→NPI。仅资料准备就绪不授予生产许可。

## 数据契约

metadata见assets/device-source.template.json。不要使用占位值完成可信核对。制造商主机白名单由Agent实际核对官方域名后声明，脚本不具备全球制造商域名认证能力。

card的items每项：id/category/requirement/conditions/locator/quote/strength/verification_method。quote为原文8–500字符短引用，保持短小并遵守来源许可；原文存在匹配不证明语义或页码正确。category采用static-ai-review.md的类别；strength区分mandatory/recommended/typical_example。保留单位、min/typ/max、温度/负载/模式、绝对最大与推荐工作条件、脚注及图表适用范围。相关图片保留在原PDF，只按需读取。

identity固定manufacturer/mpn/package；器件硅版本、温度等级等有影响时还需在application/conditions和项目规则中明确。不通过MPN近似匹配或系列名共享整张卡；同源PDF可以去重，但每种器件的适用卡要独立核对。

verification.content_sha256为以下JSON对象使用design_intent.digest得到的SHA-256：identity、record_sha256、items、gaps。evidence文件不得为空。更新卡后必须重新核对，不能机械刷新哈希。latest_checks和verification可使用不同证据。

required_refs必须与bundle器件集合精确相同；identity_fields默认manufacturer=Manufacturer、mpn=MPN、package=Package，字段在真实XML中逐项精确匹配。封装字段是具体器件封装名称，不能把库Footprint字符串直接当原厂封装；由Agent/工程师核对映射。静态评审会校验bundle、型号和原文绑定，把全部证据纳入基线；门禁再次核对时效、文件和绑定。新版模板require_device_knowledge=true，未添加bundle直接阻断；旧R4配置仍可运行；新工程必须按本流程添加device_knowledge，缺失项由AI列阻断，不宣称旧项目已拥有该资料库。

## 命令

```bash
# 缺资料先经Agent搜索确认官方URL，编辑metadata
python3 scripts/device_knowledge.py --cache /path/device-cache ingest --metadata /path/metadata.json --official-host www.ti.com
# 默认预览；确需写缓存再添加--apply。已有本地原始文件可添加--source /path/source.pdf
python3 scripts/device_knowledge.py --cache /path/device-cache draft --record /path/device-cache/records/RECORD.json --output /path/device-cache/card.json --apply
# 实际阅读后编辑新卡，核对来源/参数/图表，保存真实证据；勿批量填verified
python3 scripts/device_knowledge.py --cache /path/device-cache check-card --card /path/device-cache/card.json
python3 scripts/device_knowledge.py --cache /path/device-cache audit --requirements /path/device-requirements.json
python3 scripts/device_knowledge.py --cache /path/device-cache bundle --requirements /path/device-requirements.json --output /path/project/device-sources-r1 --apply
```

config片段（真实hash与位号替换）：

```json
{"device_knowledge":{"manifest":"device-sources-r1/device-bundle.json","sha256":"ACTUAL_SHA256","required_refs":["U1"],"identity_fields":{"manufacturer":"Manufacturer","mpn":"MPN","package":"Package"}}}
```

所有写入仅显式--apply，且不得覆盖工程；draft/bundle目标必须全新。ingest是显式获取命令，可能联网；优先audit缓存，REUSED不增加对象，不能声称每次ingest都会免下载。提取需要可选pdftotext，下载仅Python标准库；无文字或无可读图纸保持待补。大于32MiB资料走显式离线流程；并发写/网络TLS/代理差异未作全平台验收。缓存置于Skill仓库外，项目只冻结已选证据，避免每次复制整库。原文完整保存，按需读卡节省上下文。

不得把原厂PDF、NDA资料或内部项目默认推到公开GitHub；公开Skill只含代码/模板及许可允许的内容。知识库不自动训练模型；只有经过核对和纠错的内容才能改善后续复用。


## 新增：多阶段缓存复用与工程职责边界

**新增G2/G3/G4阶段复用**：`project_stage_brief(root,binding,stage)`仅接受`g2/g3/g4`，自动依据项目冻结包和精确身份筛选已核对卡片的对应类别，输出`VERIFIED_FROZEN_STAGE_CARDS_NOT_DESIGN_APPROVAL`；某核心器件未找到该阶段条目则`STAGE_CARD_COVERAGE_INCOMPLETE`，业务入口BLOCKED。G2见`resource_guard.py check --review-config`；G3见`placement_review.py --review-config`；G4见`static_review.py --stage pcb`。完整规范见[最新16节点工作流](latest-complete-workflow.md)。
