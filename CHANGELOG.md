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
- 解析要素改为以任务 `execution-context` 为唯一许可来源：system prompt 明确禁止生成未勾选类型；MinIO 上传前重新读取并过滤标准结果文件，回调前再次按许可范围过滤，未选择 `RULE` 时不会上传或回写 `business_rules.csv`。
- 规则源文件统一在本地离线编译为可审阅的静态 Markdown，存放于 `agent_knowledge/`；服务端运行时只读取已生成的 Markdown，不再实时解析 DOCX/XLSX，也不修改规则文件。
- `scripts/build_agent_knowledge.py` 负责规则变更后的离线重建；`modeling/base.md`、各输入源专项 Markdown 和 `integration.md` 分开维护并按任务模式加载，仍不进入 sandbox 或前端文件列表。
- 全链路加固：对话任务上下文优先由服务端按 taskCode 重新读取，输出文件支持多种建模类型的动态映射，整合上传仅允许 expectedFiles/ok.csv，网页文件树和下载接口隐藏数据库密码及连接 helper。
- 任务模式右侧文件树请求现在携带当前 `taskCode`，服务端会隐藏同一项目中其他 RM/MI 任务目录的文件；Agent 的最终回复仍必须以实际存在文件为准，不能把未生成文件写成“已成功生成”。
- 文件树会对照当前任务 `expectedFiles` 提示实际缺失的输出文件，不会用任务声明或 Agent 文本虚构文件。
- 兼容网关将解析要素/期望文件拼接成无分隔符字符串的情况；输出回写改为完整清单校验，缺少任一期望文件时不再部分回写成功。
- 消歧整合任务新增专用执行规范：服务端私有读取 `rules_goals/智能消歧与整合.docx` 和 `智能消歧与整合规则v0.1.docx`，按一致性、完整性、正确性校验，结合语义相似度与关系图证据分类处理已合并、待确认、冲突、缺失元素；仅 `integration` 模式注入，不返回前端。
- 空会话进入任务页时，右下角发送按钮自动显示“开始任务”；点击后直接使用当前任务 `execution-context.prompt` 启动，无需用户再次输入。已有用户或 Agent 对话的会话继续显示原箭头发送按钮；建模和消歧整合模式统一适用。
- 同一上下文不重复下载；同名远程文件按对象 Key 区分；`agent-output` 结果文件不会被当作输入文件下载。
- 主要接口：`GET /api/mission/task`、`POST /api/tasks/{id}/send`、FileServer `/file/preview/{bucket}/{objectKey}`。

### 3. 任务工作台和文件预览体验

- 左侧历史任务默认折叠，当前任务信息紧接其下并自动展开；支持展示完整 execution-context。
- 三栏宽度支持拖拽调整，文件区默认使用较窄宽度；文件目录按目录折叠。
- 文件名路径找不到时，预览会按完整路径、后缀路径和唯一文件名自动定位，解决 `logical_entities.csv`、`entity_relations.csv` 等输出文件点击 404 的问题。
- 任务信息接口失败显示为灰色小字；任务上下文标签统一为浅色背景；自动确认开启后保持低饱和绿色，悬停不再变橙色。
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
- 数据库连接 helper 根据 PostgreSQL/GaussDB/MySQL/Oracle 选择驱动，并补齐 SQLAlchemy、psycopg2、PyMySQL、oracledb 依赖。
- 前端补齐非 200、非 JSON 和流式请求失败提示。
- 智能建模页面的 Agent 地址使用当前页面服务器主机名，服务器部署时不再错误连接访问者本机的 `127.0.0.1`。
- Python 后端、模型调用和接口变更均需要重启后端；当前版本已推送并部署到服务器。

## 当前最终版本

- Git 分支：`20260727`
- 最近一次全局审计提交：`20260727` 分支当前版本
- 服务地址：`http://172.16.10.34:47313/`
- 状态：本轮代码已部署服务器；本地和服务器离线验证通过，未调用 Qwen API。
