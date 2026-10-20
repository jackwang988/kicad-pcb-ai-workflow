# 器件资料检查、补齐与复用 · R9.3

## 执行流程

在static_review.py之前执行本流程。目的：减少重复下载和漏读，不把摘要当作完整规格或合格结论。先读取工程BOM/网表，逐一列出核心IC完整制造商、MPN、封装、工作模式及位号；人工检查清单是否漏项，不能仅按U前缀推断全部IC。

1. 创建device-requirements.json：schema_version=1、max_check_age_days（0–365，用户/企业明确采用的版本核对周期）、devices数组。每器件包含ref/manufacturer/mpn/package/application、required_kinds、cards、latest_checks。required_kinds必须含datasheet；按器件增加errata/hardware_guide/application_note。原厂没有独立勘误时保存查询记录，由工程师决定清单，不伪造空白勘误。日期政策不能证明厂商两次查询之间没有发布更新；新项目、定稿和生产签核前应主动再查。
2. 先audit本地缓存。缺少/过期资料时，Agent通过当前可用联网搜索工具找到原厂产品页，确认精确型号/封装和资料版本。检查datasheet、errata、硬件指南及应用笔记。不要从搜索摘要生成可信资料卡，不把第三方网站当原厂。
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
