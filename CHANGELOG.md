# 20260727 分支变更记录

> 本文档记录 `20260727` 分支相对于基础版本的最终变更结果，不按每次小修改单独追加。
> 每次发布或阶段性整合时，只更新对应版本的最终状态，避免重复记录中间过程。

## 维护规则

- 以版本或阶段为单位记录最终变化，不为单个 CSS 调整、单个小修复单独新增条目。
- 记录用户可见变化、涉及页面/接口、主要文件和是否需要重启后端。
- 仅 HTML/CSS/JS 变更：同步源码后刷新浏览器；Python、模型、接口、环境变量或依赖变更：需要重启服务。
- 服务器目录：`/home/wugefei/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`。
- 真实密钥只放在未提交的 `.env` 或服务器配置中。

## 基础版本已有能力

### 1. Qwen 模型配置与动态模型目录

- 支持通过 `.env` 配置 Qwen Provider、API Key、兼容接口地址、文本/视觉模型和 thinking 参数。
- 动态注册 `QWEN_VISION_MODELS`、`QWEN_TEXT_MODELS`，同时保留 Anthropic、OpenAI、GLM、Kimi、DeepSeek 等模型目录。
- 主要文件：`open-claude/open_claude/config.py`、`open-claude/open_claude/openai_compat.py`。

### 2. Agent 工作台基础界面

- 完成浅色主题、自动确认开关、目录折叠文件列表、任务信息弹窗和文件预览基础能力。
- 主要页面：`open-claude/codex_web.html`。

### 3. 20260727 分支和服务器部署

- 使用 Git 分支 `20260727`，服务器运行 `python oc_codex_server.py --host 0.0.0.0 --port 47313`。
- Qwen 密钥仅保存在服务器 `.env`，不提交到 Git。

## 当前版本最终变更

### 1. 当前任务绑定与会话恢复

- 从智能建模页面点击小机器人时，自动携带当前任务的 `repositoryId`、`taskCode` 和任务类型进入 Agent。
- 历史任务只展示当前本体库和任务编码下的会话；可以重新打开历史任务，也可以创建当前 ID 下的新会话。
- 任务元数据、对话回放日志和 SessionStore session ID 持久化到 `open-claude/sandbox/.web_tasks.json`。
- 服务重新部署或重启后，会恢复上次任务和已有对话；正在执行中的任务恢复为可继续状态，不伪造为已完成。
- 对已完成任务，若上游网关拒绝再次读取 execution-context（例如“任务已成功，不能再次执行”），任务信息接口改用服务端持久化的可信快照只读展示，不再把已存在的任务误报为读取失败。
- 主要文件：`open-claude/oc_codex_server.py`、`open-claude/codex_web.html`、`智能建模任务.html`。

### 2. 当前任务上下文、输入文件和 Agent system prompt

- 进入当前任务后自动展示该任务项目文件，不要求重复上传已经存在的文件。
- execution-context 中的任务名称、提示词、解析要素、目标输出文件、数据源/文档信息和项目文件清单，会写入 Agent system prompt。
- 任务上下文中的 `objectKey`/文件 Key 会通过 FileServer 下载到项目的 `mission-input/` 目录，Agent 可以直接读取。
- 数据库任务会把真实连接配置写入当前项目受保护的 `mission-input/.db_connection.json`；system prompt 只提供路径和 `URL.create()` 使用规则，避免密码脱敏成 `********` 或被特殊字符 `@` 破坏连接 URL。
- 同时自动生成 `mission-input/db_connection.py` 和 `mission-input/verify_database.py`；Agent 必须自行执行验证命令、复用安全 helper，不能再要求用户手动执行 `psql`，也不能继续使用已损坏的 `extract_schema.py` 连接代码。
- 验证命令使用服务实际虚拟环境的 Python 解释器，避免系统 `python3` 缺少 SQLAlchemy 导致“未提供密码/连接失败”的误判；服务重启恢复时不会再用脱敏密码覆盖真实配置文件。
- 每个本体任务会自动准备 `mission-input/本体元模型.xlsx` 和 `mission-input/本体元模型模板.xlsx`，并将路径写入 system prompt；Agent 可直接读取，不再要求重复上传。
- system prompt 增加最终交接格式约束：回复最后必须列出实际 `outputPrefix`、输出文件树和各 CSV 去表头后的真实记录数；文件缺失或读取失败必须明确说明。
- 建模与消歧整合增加可见执行审计摘要：每个阶段需报告实际读取的文件/工作表/行数、静态规则文件名与章节定位、关键证据、产出数量和校验结果；不输出隐藏思维链或私有规则原文。
- 解析要素改为以任务 `execution-context` 为唯一许可来源：system prompt 明确禁止生成未勾选类型；MinIO 上传前重新读取并过滤标准结果文件，回调前再次按许可范围过滤，未选择 `RULE` 时不会上传或回写 `business_rules.csv`。
- `rules/` 中的规则、步骤表、本体元模型和本体元模型模板统一在本地离线编译为可审阅的静态 Markdown，存放于仓库更高一级的 `agent_knowledge/`；服务端运行时只读取已生成的 Markdown，不再实时解析 DOCX/XLSX，也不修改规则文件。
- `scripts/build_agent_knowledge.py` 负责规则变更后的离线重建；`modeling/base.md`、各输入源专项 Markdown、`integration.md` 以及单独的 `本体元模型.md`、`本体元模型模板.md`、`本体建模步骤拆解.md` 均可在本地和服务器源码目录审阅，但仍不进入 sandbox 或前端文件列表。
- 建模专项 Markdown 不再重复复制整份公共建模规范：`modeling/*.md` 只保留对应输入源规则；运行时由静态知识加载器拼接 `modeling/base.md` 与当前 `sourceMode` 专项文件，避免文件看似全部相同且降低 system prompt 重复内容。
- 补充独立的 `agent_knowledge/modeling/数据模型建模规范-20260626.md`，将数据库建模中的命名、定义、主键、归属、关系和质量规则单独提供给审阅，同时继续编入所有建模任务的 `base.md`。
- 消歧整合结果增加服务端 CSV 协议校验：逐文件校验 UTF-8 CSV、精确表头、列数、引号/换行解析、关系分类和关系基数字典；`business_rules.csv` 统一为五列（编码、名称、分类、描述、来源内容）。整合只有在全部 `expectedFiles` 和最后的 `ok.csv` 都存在并通过校验后才回写 `COMPLETED`。
- 修复 Ontology `DOCUMENT_MODELING`、`DATA_SOURCE_MODELING` 等任务类型没有被识别为 modeling 模式的问题；现在会正确注入建模私有规则和建模步骤。建模 CSV 也会拒绝 `id,name,description` 等临时表头。建模 XLSX 不再建议用 locale 相关的 `soffice` 转 CSV，避免中文被替换成 `?`。
- 全链路加固：对话任务上下文优先由服务端按 taskCode 重新读取，输出文件支持多种建模类型的动态映射，整合上传仅允许 expectedFiles/ok.csv，网页文件树和下载接口隐藏数据库密码及连接 helper。
- 工具执行会自动生成审计卡片：展示 Read 的文件范围、Write/Edit 的结果路径，并对 `head`、小范围 Read 等可能造成“只分析前几行”的操作显示警告。
- 任务模式右侧文件树请求现在携带当前 `taskCode`，服务端会隐藏同一项目中其他 RM/MI 任务目录的文件；Agent 的最终回复仍必须以实际存在文件为准，不能把未生成文件写成“已成功生成”。
- 文件树会对照当前任务 `expectedFiles` 提示实际缺失的输出文件，不会用任务声明或 Agent 文本虚构文件。
- 兼容网关将解析要素/期望文件拼接成无分隔符字符串的情况；输出回写改为完整清单校验，缺少任一期望文件时不再部分回写成功。
- 消歧整合任务新增专用执行规范：服务端私有读取 `rules/智能消歧与整合.docx`、`rules/智能消歧与整合规则v0.1.docx` 和 `rules/智能消歧与整合模板.xlsx` 的静态 Markdown 编译结果，统一放在 `agent_knowledge/integration/`；按一致性、完整性、正确性校验，结合语义相似度与关系图证据分类处理已合并、待确认、冲突、缺失元素。`output_schema.md` 明确十类结果 CSV 的精确表头和字段含义，并注入 `integration` system prompt，仅 Agent 内部使用，不返回前端。
- 从机器人入口进入建模或消歧整合页面后，只要当前会话为空，输入区按钮会显示对应的“开始智能建模”或“开始智能消歧与整合”，按钮宽度按实际文字自适应；点击后直接使用当前任务 `execution-context.prompt` 启动，无需用户再次输入。用户开始输入后按钮立即切换为发送箭头；已有用户或 Agent 对话的历史会话仍显示发送箭头。新建任务与历史空任务统一适用。
- 输入区工具按钮统一禁止自动换行；对话卡片默认最大宽度调整为 `720px`，确保文件、模型和自动确认等按钮始终在同一行。空任务或新会话时输入卡片居中显示，已有对话继续固定在底部。
- 输入区按钮不再横向滚动：空任务居中的输入卡片在有需要时自动拓宽；对话过程中优先保证最右侧发送按钮，空间不足时按按钮占用宽度从小到大逐级隐藏文字，仅保留图标。
- 空任务首页输入框按模式提示“你可以直接点击开始智能建模/开始智能消歧与整合任务，或者描述一个任务”；已有任务对话框的“继续对这个任务下指令…”提示保持不变。
- 点击空任务的开始按钮时，用户对话区只显示“请直接开始执行当前任务”；完整的执行约束仍发送给 LLM，并在服务端历史日志中保持同样的短显示文本。
- 首页和任务对话框的回形针按钮显示“上传文件到项目”；参数按钮统一显示“LLM模型参数”。
- 同一上下文不重复下载；同名远程文件按对象 Key 区分；`agent-output` 结果文件不会被当作输入文件下载。
- Excel 输入在进入 Agent 前由服务端用流式 XLSX XML 解析生成每个工作表的 UTF-8 CSV 和 `manifest.json`；Agent 禁止直接 `Read` 二进制 `.xlsx/.xlsm/.xls`，大表按工作表分块处理并依据 manifest 的完整行数校验。
- Qwen 表格/文本建模任务检测到视觉模型时，优先切换到 `.env` 中的 `QWEN_TEXT_MODEL`；视觉模型仅用于图片或扫描图纸类输入。
- 主要接口：`GET /api/mission/task`、`POST /api/tasks/{id}/send`、FileServer `/file/preview/{bucket}/{objectKey}`。

### 3. 任务工作台和文件预览体验

- 左侧历史任务默认折叠，当前任务信息紧接其下并自动展开；支持展示完整 execution-context。
- 建模和消歧整合模式自动绑定当前 `repositoryId + taskCode` 对应的任务项目，隐藏全局“选择项目”和首页文件入口；文件浏览、预览、下载、上传及 MinIO 回写均由后端再次校验任务项目，不能切换或操作其他沙箱项目。普通 Agent 模式仍保留多项目选择。
- 即使历史会话尚未恢复，文件树也会先使用 `mission-{repositoryId}-{taskCode}` 确定当前项目，进入任务页即可读取已有项目文件，不需要新建会话或重新上传。
- 三栏宽度支持拖拽调整，文件区默认使用较窄宽度；文件目录按目录折叠。
- 文件名路径找不到时，预览会按完整路径、后缀路径和唯一文件名自动定位，解决 `logical_entities.csv`、`entity_relations.csv` 等输出文件点击 404 的问题。
- 任务信息接口失败显示为灰色小字；任务上下文标签统一为浅色背景；自动确认开启后保持低饱和绿色，悬停不再变橙色。
- 校验规则、整合策略等任务信息中的长标签支持按任意字符自动换行，不再撑出字段栏。
- 主要页面：`open-claude/codex_web.html`。

### 4. Qwen 配额自动切换

- Qwen 遇到配额不足、限流、余额不足或 HTTP 429 时，自动在当前能力类别内切换模型。
- 视觉模型只从 `QWEN_VISION_MODELS` 切换，文本模型只从 `QWEN_TEXT_MODELS` 切换，最多按配置顺序尝试 8 个模型。
- 页面提示实际发生的模型切换，并同步显示当前模型；同类模型全部失败后才显示最终错误。
- 主要文件：`open-claude/open_claude/openai_compat.py`、`open-claude/codex_web.html`。

### 5. 稳定性、错误处理和部署地址

- 任务执行状态和首条用户消息及时落盘，并增加状态文件并发写入保护。
- 状态文件采用加锁、刷盘和原子替换；事件日志限制为最近 10000 条，避免并发回合或长会话无限增长。
- 修复服务启动恢复任务时沙箱边界设置顺序问题。
- 客户端断开 SSE 后 Agent 继续后台执行并落盘；模型流式错误会将任务标记为 error，不再误报 idle。
- 后端对坏 JSON、非法 Content-Length、任务入口 taskCode/repositoryId 做安全校验，避免异常 500、HTML 注入和请求头注入。
- 任务输入文件按对象 Key 缓存并采用临时文件原子落盘，避免每轮上下文刷新重复下载或留下半截文件。
- 对象存储临时失败不会永久锁死同一任务上下文，后续回合可重新尝试；前端同步显示服务端 error 状态。
- 历史任务打开时由恢复后的真实会话判断是否已开始；只有空会话显示“开始任务”，不会因为工具卡片或旧日志误显示发送箭头。
- 建模和消歧模式点击左侧“新任务”时，直接创建当前任务 ID 下的空会话并显示“开始任务”；普通 Agent 模式仍保留输入后发送。
- 数据库连接 helper 根据 PostgreSQL/GaussDB/MySQL/Oracle 选择驱动，并补齐 SQLAlchemy、psycopg2、PyMySQL、oracledb 依赖。
- 前端补齐非 200、非 JSON 和流式请求失败提示。
- 智能建模页面的 Agent 地址使用当前页面服务器主机名，服务器部署时不再错误连接访问者本机的 `127.0.0.1`。
- Python 后端、模型调用和接口变更均需要重启后端；本轮任务项目隔离修改已重启并部署。

### 6. 外部登录态与用户级模型密钥隔离

- Agent 支持沿用外部本体平台登录态：入口可接收已验证的 HS256 `Authorization: Bearer JWT`，或在可信反向代理模式下接收 `X-User-Id`；入口响应写入签名 HttpOnly Cookie，后续前端请求不再需要暴露 Token。
- 任务、历史会话、文件访问和结果上传按用户归属校验；旧版本没有归属的任务仅在该用户首次访问时迁移绑定，其他用户不能读取或操作。
- `/api/apikey` 只保存当前用户自己的 Provider Key 到服务器权限为 600 的用户隔离文件；普通用户不再修改公共 `~/.claude/config.json`。`/api/admin/apikey` 仅管理员可维护服务器默认 Key，默认管理员由 `ONTOLOGY_ADMIN_USER_IDS` 配置。
- Agent 每次模型调用按任务用户解析 Key 并传入 OpenAI-compatible/Anthropic 客户端，Qwen 不再回退到公共 Key；没有个人 Key 的普通用户会在执行前收到配置提示。
- 模型选择也按用户保存，不再改变所有在线用户的会话模型；现有模型目录和 Qwen 同能力配额切换逻辑保留。
- 按用户记录调用次数、Token 和估算费用，默认设置为团队测试用的高额度（1000 次 / 2000 万 Token / 500 美元每日），达到上限时服务端拒绝继续调用；额度不在普通 UI 展示。
- 主要文件：`open-claude/oc_codex_server.py`、`open-claude/open_claude/api.py`、`open-claude/open_claude/openai_compat.py`、`open-claude/codex_web.html`、`.env.example`。
- 类型：后端鉴权、密钥存储、模型调用和环境配置变更，需要重启后端；未调用 Qwen API。启用生产鉴权前必须在服务端配置 `ONTOLOGY_JWT_SECRET`，或明确启用 `ONTOLOGY_TRUST_PROXY_AUTH=true` 并由反向代理提供 `X-User-Id`。

### 7. 模型与参数入口调整

- 输入对话框移除“大语言模型”和“大语言模型参数”两个独立按钮，避免工具栏过于拥挤。
- 左侧栏新增“设置”入口，模型选择和参数面板统一从这里打开，交互更接近常见聊天产品布局。
- 输入框底部仅保留无边框的“⚙ + 当前模型短名称 + 下箭头”提示（最多显示开头 9 个字符加省略号），并靠右放置在发送按钮左侧；悬停可查看完整模型和提供方名称。
- 模型提示本身仍可点击打开模型选择；悬停效果改为浅灰色，不再出现深色背景。
- 主要文件：`open-claude/codex_web.html`。
- 类型：前端静态资源变更，刷新浏览器即可生效；无需重启后端。

## 当前最终版本

- Git 分支：`20260727`
- 最近一次全局审计提交：`20260727` 分支当前版本
- 服务地址：`http://172.16.10.34:47313/`
- 状态：任务项目隔离修改已部署服务器；本地和服务器离线验证通过，未调用 Qwen API。
