# 20260803–20260807 分支变更记录

> 本文档记录 `20260727` 分支在 2026-08-03 至 2026-08-07 的变更。

## 维护规则

- 每次功能修改后，在本周记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/wugefei/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`。
- 下周开始时，将本文件归档为对应日期范围，并新建下一周的变更记录。

## 2026-08-03

### 1. 任务执行状态与用户确认完成闭环

- Agent 真正开始执行前向本体平台回调 `RUNNING`；模型/工具流以不可恢复错误结束时回调 `FAILED`，包含统一的错误码和审计提示。
- MinIO 上传不再自动回调 `COMPLETED`，上传成功后任务仍保持 `RUNNING`，可继续检查、修改并重新上传结果。
- 对话任务栏新增“完成”按钮：仅当全部期望输出文件已上传、且本地文件 SHA-256 与已上传版本一致时，才回调 `COMPLETED`；完成后按钮变为“修改”，点击后回调 `RUNNING` 并恢复上传和继续执行。
- 上传清单（对象键、预览地址、文件指纹）与平台状态随会话持久化，服务器重启后仍可继续确认；已完成任务再次上传或执行前会明确提示先点击“修改”。
- 兼容本次状态字段上线前已在本体平台成功的历史任务：当平台返回“任务已成功，不能再次执行”时，将对应本地会话迁移为 `COMPLETED`，任务栏直接显示“修改”。
- 适配平台新版任务读取返回：兼容 `executionContext`、`taskContext`、`context` 等嵌套上下文，以及 `taskStatus`、`agentStatus`、`executionStatus` 等显式状态字段；恢复 `outputPrefix`、`expectedFiles` 和解析要素读取。
- 平台已验证当前任务后，会将旧版 `local:` 浏览器身份下的同一任务会话安全迁移到当前平台用户，修复历史任务能查看但无法读取文件、上传或修改的权限断链。
- 修复平台 `execution-context` 返回“解析要素未配置输出文件”时的任务不可用：仅对该明确配置异常回退到同任务的持久化上下文；若历史 `mission-output` 已具备全部期望文件，则恢复为 `COMPLETED` 显示“修改”。认证、无权限和任务不存在仍拒绝回退。
- 修复建模接口配置异常被后续整合接口“任务不存在”覆盖的问题；任务读取现在保留正确类型已确认的上下文配置异常，从而触发缓存恢复。
- 同步更新 Agent 与本体平台的状态接口约定，明确 `RUNNING`、`FAILED`、用户确认 `COMPLETED` 和“修改”恢复运行中的时机。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`backend-agent-interaction-api.md`、`tests/test_ontology_knowledge.py`、`tests/test_frontend_contract.py`。

### 2. 历史会话恢复提示降噪

- 打开历史会话自动恢复审批时，已处理或已过期的审批请求不再弹出错误提示；鉴权、网络等真实审批失败仍保留提示。
- 当前任务信息仅作为侧栏辅助内容；上游任务信息暂不可获取时改为页面空态，不再在打开对话时弹出“获取任务信息失败”。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 13. 审批结果节点样式与完成后收起操作

- `approval_result` 成功节点的思维链圆圈改为 `✓`，标题和内容使用与“模型切换”一致的紫色样式。
- 当前审批对应的 Agent 执行产生 `done` 事件后，审批请求下的“✓ 已允许执行”和“拒绝”操作按钮全部隐藏。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 14. 折叠思维链摘要宽度

- 思维链折叠状态下的摘要最长占当前行宽度的 80%，超出内容继续以省略号显示；展开状态不受影响。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 15. 思维链步骤耗时

- 已完成的思维链步骤在行尾显示耗时，例如 `32ms`；完成状态节点不显示额外耗时。
- 思考节点完成后显示“已思考 …s”，执行中的思考节点仍显示旋转提示。
- 工具执行按对应 `tool_result` 计算，审批等待按对应 `approval_result` 计算；当前尚未结束的步骤不显示耗时。
- 新产生的事件由服务端记录时间戳，重新打开会话时也可继续计算已持久化事件的耗时。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 16. 再次收窄折叠摘要

- 折叠思维链摘要最大宽度从原行宽的 80% 调整为原行宽的 64%，即当前设置的 80%。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 17. 折叠思维链整行交互提示

- 折叠状态下整行均可点击展开/收起，鼠标悬浮显示手形指针、圆角灰色背景和轻微阴影。
- 文件链接会阻止事件冒泡，点击文件仍只打开对应预览，不会误触发思维链展开。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 18. 展开标题行折叠交互

- 展开后的标题行也使用与折叠状态相同的整行悬浮样式和点击区域，点击标题行任意位置即可折叠详情。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 19. 思维链点击区域收窄

- 思维链悬浮和点击区域改为只包住标题、摘要和耗时文字的实际内容宽度，不再覆盖整行空白区域。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 20. 新消息自动滚动到底部

- 发送新要求、接收思维链事件或切换任务后，会话内容在渲染完成后自动滚动到最新底部，确保新回复始终可见。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 21. 思维链交互区域固定宽度

- 折叠和展开状态的思维链标题交互区域统一固定为当前内容行宽的 64%，摘要在该区域内自适应并以省略号截断，不再延伸到整行。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 3. Qwen 与团队模型重名路由修复

- 修复团队模型目录与 Qwen 模型目录存在同名模型时的 Provider 污染问题。
- Qwen 模式下，共享模型继续走 Qwen Base URL 和 Qwen Key；仅团队专属模型不会混入 Qwen 模型列表。
- 团队模式下仍按 `TEAM_MODELS` 暴露模型，并将共享模型标记为团队网关模型。
- 主要文件：`open-claude/open_claude/config.py`、`tests/test_team_config.py`。

### 4. OpenAI 兼容客户端纳入运行依赖

- 将 `openai` 纳入 Open Claude 的基础依赖，确保 Qwen、团队网关及其他兼容接口在按项目依赖安装后即可调用。
- 同步更新 `open-claude/open_claude/requirements.txt`、`open-claude/pyproject.toml` 与安装说明。

### 5. 任务上下文鉴权转发修复

- 读取 execution-context 和完成回写时保留平台传入的 Bearer JWT，避免 Agent 为本地任务隔离生成的临时用户标识覆盖上游登录态。
- 对无效或过长的鉴权头不转发，继续由服务端按现有鉴权规则处理。
- 主要文件：`open-claude/oc_codex_server.py`、`tests/test_ontology_knowledge.py`。

### 6. 术语、规则与指标建模专项技能

- 新增业务术语、业务规则、指标三个静态建模技能；任务选择 `TERM`、`RULE`、`METRIC` 或对应结果文件时自动注入。
- 技能按需加载在 V6 和输入源专项规则后，未选择时不会引导 Agent 生成额外文件。
- 主要文件：`agent_knowledge/业务术语.md`、`agent_knowledge/业务规则.md`、`agent_knowledge/指标.md`、`open-claude/open_claude/ontology_knowledge.py`、`open-claude/oc_codex_server.py`。

### 7. 恢复结果上传后自动完成

- 根据交互调整，移除任务栏“完成/修改”按钮及对应手动状态接口；任务可继续执行和上传，不再因已完成状态锁定操作。
- 上传到 MinIO 后，服务端会校验全部期望输出文件及其 SHA-256 一致性；校验通过即自动回调本体平台 `COMPLETED`，文件未传齐则保持 `RUNNING` 并提示缺少项。
- 保留 Agent 实际开始时的 `RUNNING` 回调以及不可恢复错误的 `FAILED` 回调。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`backend-agent-interaction-api.md`、`tests/test_frontend_contract.py`、`tests/test_ontology_knowledge.py`。

### 8. 完整实现分层建模与 artifact 依赖

- 建模任务统一生成 `repositoryId + taskCode + modelVersion + inputFingerprint` 身份，并在当前任务信息中展示 `modelingPlan` 和五类 artifact。
- `TERM` 作为独立分支；逻辑模型强制按候选属性、逻辑实体、正式业务属性、实体关系顺序执行；业务对象必须依赖逻辑模型；规则和指标必须引用已完成业务对象。
- 服务端在 Agent 真正执行前校验依赖，缺少上游 artifact 时回调 `FAILED`（`MODELING_DEPENDENCY_BLOCKED`），阻止下游文件生成和上传。
- 上传记录会更新各 artifact 的 `RUNNING`、`COMPLETED` 状态；跨任务引用只接受明确完成状态的 artifact，结果文件别名按 execution-context 的实际清单判定。
- 主要文件：`open-claude/oc_codex_server.py`、`agent_knowledge/modeling/base.md`、`backend-agent-interaction-api.md`、`frontend/src/main.jsx`、`tests/test_ontology_knowledge.py`。

## 2026-08-04

### 9. 任务读取与静态知识构建一致性

- 已完成任务或服务器重启后，任务信息中的 `modelingPlan` 会从当前用户绑定的本地任务快照恢复上传文件状态，不再把已上传 artifact 显示为 `PENDING`。
- 术语、规则、指标的合法别名结果文件按 execution-context 的实际清单判定完成，不再因未同时上传其他别名文件而误报 `PARTIAL`。
- 输入指纹生成排除数据库密码、Token、密钥等敏感字段，避免凭据变化导致同一任务身份漂移。
- `LOGICAL_MODEL` 计划展开现在显式包含候选属性阶段；正式逻辑实体、业务属性和实体关系仍作为进入业务对象层的完成条件。
- 将分层建模与 artifact 依赖说明纳入 `scripts/build_agent_knowledge.py` 的生成源，后续重新生成静态知识时不会丢失该规则。
- 主要文件：`open-claude/oc_codex_server.py`、`scripts/build_agent_knowledge.py`、`agent_knowledge/README.md`、`agent_knowledge/modeling/all_sources.md`、`tests/test_ontology_knowledge.py`。

### 10. 思维链空闲阶段加载提示

- Agent 正在执行但暂时没有新的 SSE 思维链事件时，补显示一个临时“思考中”旋转节点；新事件到达、等待审批或本轮结束后自动切换/移除。
- 页面：`frontend/src/main.jsx`。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 11. 指标规范更新与数据模型建模规范切换

- 同步 `agent_knowledge/指标.md` 的最新内容，保留输入体检、候选指标识别、无数据源路径、L4 降级推断、产出下限和执行总结等规则。
- 数据模型建模公共参考切换为 `数据模型建模规范-v0.2.xlsx`，生成对应的 `agent_knowledge/modeling/数据模型建模规范-v0.2.md`，并纳入 `modeling/base.md` 与 `all_sources.md`。
- `modeling/base.md` 会在每个建模任务中自动注入该公共参考；V6 仍是建模决策的核心规范，v0.2 作为数据模型补充参考，不需要用户重复上传。
- 主要文件：`agent_knowledge/指标.md`、`rules/数据模型建模规范-v0.2.xlsx`、`agent_knowledge/modeling/数据模型建模规范-v0.2.md`、`scripts/build_agent_knowledge.py`、`tests/test_ontology_knowledge.py`。

## 2026-08-05

### 12. 审批按钮状态反馈

- 审批请求点击“允许执行”并成功回写后，按钮显示为禁用状态“✓ 已允许执行”。
- 已允许的审批请求隐藏“拒绝”按钮，避免同一请求被重复处理。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 22. 移除旧静态前端

- 删除仓库根目录的旧产品原型 HTML 页面及 `open-claude` 的旧单文件聊天页面、旧桥接服务。
- Agent 服务现在只提供 `frontend/dist` 构建的 React + Ant Design 工作台；构建产物缺失时直接返回明确错误，不再回退到旧页面。
- 清理开发文档和回归测试中的旧页面依赖，保留 `frontend/index.html` 与 `frontend/dist/index.html` 作为 React 前端入口。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/README.md`、`open-claude/README.md`、`tests/test_frontend_contract.py`、`frontend/`。

### 23. 思考阶段耗时完整展示

- 思维链在“思考 → 输出”和“思考 → 执行工具”等连续阶段中，统一按思考节点的首个时间戳到下一个非思考事件计算并显示“已思考 …s”。
- 服务端将思考增量写入任务回放日志，前端恢复历史会话时合并连续思考片段并保留首个时间戳，历史任务也能继续显示思考耗时。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 24. 思维链交互区域宽度调整

- 折叠和展开状态的思维链标题交互区域统一从 64% 调整为 75%，保留整行之外的可控点击范围和摘要省略显示。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 25. 文档逆向建模闭环

- 根据 `DOCUMENT_MODELING`、`document`/`documents` 和 `sourceMode` 自动识别文档输入模式；任务上下文会附带明确的 `parseElement` 与文档输出文件契约，保持 TERM 独立、逻辑模型先于业务对象、规则/指标引用业务对象的分层依赖。
- DOCX、PPTX、PDF 输入在当前任务 `mission-input/` 中统一解析为 `manifest.json`、完整 `content.md` 和 `tables/*.csv`；manifest 记录来源指纹、章节/页和表格，Agent 按章节/页读取证据，避免只读摘要或第一页。
- 补齐文档结果文件映射：术语、逻辑实体、业务属性、实体关系、业务对象、规则、指标、活动及活动流均按 `expectedFiles` 受控生成和上传；同步更新接口文档和文档专项知识。
- 新增文档解析单元测试和文档任务闭环测试，覆盖对象存储下载、DOCX 解析、建模上下文契约、结果上传及 `COMPLETED` 回调。
- 主要文件：`open-claude/open_claude/document_parser.py`、`open-claude/oc_codex_server.py`、`scripts/build_agent_knowledge.py`、`agent_knowledge/modeling/business_document.md`、`backend-agent-interaction-api.md`、`tests/test_document_parser.py`、`tests/test_ontology_knowledge.py`。

### 26. 审批请求节点图标

- 审批请求思维链节点保留现有橙色样式，图标由感叹号调整为问号，更明确表示等待用户确认。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 27. 错误节点图标与思维链竖线对齐

- 错误思维链节点使用红色圆形感叹号图标，并兼容 `error` 与 `is_error` 事件。
- 调整思维链竖线位置，使其穿过左侧图标圆圈的水平中心。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 28. 思维链行间距收窄

- 思维链节点内边距和节点之间间隔调整为原来的约 80%，减少连续步骤之间的空白。
- 同步调整竖线起始位置，保持与图标中心的视觉对齐。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 29. 大语言模型设置图标统一

- 两处“大语言模型设置”入口改用 Ant Design 线性 `SettingOutlined` 图标；模型选择按钮的下拉提示改用 `DownOutlined`，替换原来的字符图标。
- 保留原有点击、模型选择和参数设置行为，仅统一图标视觉风格。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/package.json`、`frontend/package-lock.json`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 30. 思维链行间距再次收窄

- 在原 80% 间距基础上继续调整为约 75%；节点内边距改为 3px，节点间隔改为 2.4px。
- 竖线起始位置同步调整，保持与图标中心对齐。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 31. 本体元模型 2 与页面显示字段

- 本体建模任务的两份固定参考输入更新为 `mission-input/本体元模型2.xlsx` 和 `mission-input/本体元模型模板 2.xlsx`；旧版元模型和模板仅保留为历史参考，不再自动复制到任务目录。
- 模板 2 的 `business_attributes.csv` 增加最后一列 `是否页面显示`：同一逻辑实体同时存在 `XXX编码`（主键）和 `XXX名称` 时，`XXX名称` 为 `Y`，其他业务属性统一为 `N`。
- Agent 静态知识、建模 system prompt、服务端 CSV 校验及接口文档同步使用模板 2 的十列表头；非法值、空值或不符合编码/名称配对规则的结果会在上传前拒绝。
- 主要文件：`rules/本体元模型2.xlsx`、`rules/本体元模型模板 2.xlsx`、`scripts/build_agent_knowledge.py`、`agent_knowledge/modeling/`、`open-claude/oc_codex_server.py`、`backend-agent-interaction-api.md`。

### 32. 输入框发送箭头图标

- 输入对话框的发送按钮改用 IconPark 提供的 SVG 箭头图标，保留原有发送、禁用和自动滚动行为。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

## 2026-08-06

### 33. 普通咨询不提前触发建模失败

- 任务会话中的普通提问、停止/取消指令不再在 Agent 调用前触发建模依赖校验，也不会因为历史建模计划不完整直接回调 `FAILED`。
- 这类回合以只读咨询模式交给 Agent，只回答当前问题，不调用工具、不生成或修改结果文件；明确点击“开始任务”以及“继续做/生成/执行”等建模指令仍保留严格依赖门禁。
- 前端向发送接口传递 `startTask`，服务端区分启动请求和普通会话请求；平台上下文漏声明实体关系时，将其作为业务对象任务的内部前置校验，不扩大 expectedFiles 或上传白名单。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_ontology_knowledge.py`、`tests/test_frontend_contract.py`。

### 34. 操作按钮与任务入口图标统一

- “允许执行”和“✓ 已允许执行”按钮统一使用“上传到 MinIO”相同的实色蓝；输入框发送按钮统一使用“+ 新任务”的渐变蓝。
- 当前任务信息入口替换为文件信息 SVG 图标；输入框上传文件入口替换为上传 SVG 图标，保留原有点击和上传行为。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 35. 文件复选框对齐文件夹箭头

- 文件列表中每个文件的复选框向右缩进，与文件夹标题左侧箭头保持竖直对齐；文件名、文件大小和选择行为不变。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 33. 发送和下载图标调整

- 发送箭头改为白色，提升蓝色发送按钮上的对比度。
- “下载所选”按钮改用指定的灰色下载 SVG，下载逻辑保持不变。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 34. 思维链文件操作图标

- “读取文件”使用文件文档 SVG；“写入文件”和“修改文件”共用编辑文件 SVG。
- “上传到 MinIO”按钮改用指定的上传 SVG，原有文件选择、上传和状态逻辑保持不变。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 35. 文件操作图标尺寸与颜色

- 读取、写入和修改文件图标缩小到思维链圆圈内，并分别使用与标题一致的颜色和浅色背景。
- “上传到 MinIO”图标改为白色，以匹配蓝色按钮背景。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 36. 审计与模型设置图标

- 思维链 `audit` 节点改用指定的审计 SVG 图标。
- 侧边栏、模型选择区域和“修改模型参数”中的模型设置图标统一改用指定 SVG。
- 原有审计展示、模型切换和设置弹窗行为保持不变。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 37. 任务更新与执行命令图标

- `TaskUpdate` 思维链节点改用指定的循环更新 SVG，图标和标题统一为紫色并配套浅色背景。
- `Bash/执行命令` 思维链节点改用指定的命令 SVG，图标和标题统一为蓝色并配套浅色背景。
- 原有任务更新和命令执行行为保持不变。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 38. 侧边栏模型设置图标颜色

- 左侧“大语言模型设置”按钮的图标改为继承按钮文字颜色，与蓝色标题保持一致。
- 模型选择和参数设置入口继续沿用各自文字颜色，不改变点击行为。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 39. 审计图标更新

- `audit` 思维链节点改用新的审计 SVG 图标，保留原有灰色图标、标题和展开行为。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 40. 输入框模型名称展示

- 输入对话框中的模型切换入口最多显示 15 个字符，超出部分使用省略号。
- 移除模型名称右侧下拉箭头，保留点击模型名称打开模型选择列表的功能。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 41. 历史任务图标

- “历史任务”按钮新增与“大语言模型设置”一致的 16px 图标样式，并继承按钮文字颜色。
- 保留历史任务展开、收起和任务选择行为。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 42. 任务文件目录显示

- 本体任务文件面板始终显示 `mission-input/`、`mission-output/` 和“项目公共文件”三个目录，即使目录暂时为空也不会消失。
- 文件接口读取任务目录时会补齐输入、输出目录，并继续使用任务专属目录隔离；项目公共资料仍保存在项目工作区根目录，任务内通过 `project-shared/` 提供只读副本。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

## 2026-08-06

### 43. DeepSeek/LiteLLM 工具消息兼容修复

- 修复团队 DeepSeek 兼容网关返回 `Messages with role 'tool' must be a response to a preceding message with 'tool_calls'` 的 400 错误。
- OpenAI 兼容消息转换现在只发送紧跟匹配 assistant `tool_calls` 的工具结果；旧会话中缺失调用、调用已被压缩或工具 ID 缺失的记录会安全转换为普通历史文本，不再阻断后续对话。
- 会话压缩不会再把 assistant 工具调用和后续工具结果拆到不同上下文，避免产生孤立 `role=tool` 消息。
- 保留 DeepSeek 思考模式返回的 `reasoning_content`，在下一轮工具调用时原样回传；流式、非流式、网页 Agent、CLI 和子 Agent 共用同一兼容逻辑。
- 主要文件：`open-claude/open_claude/openai_compat.py`、`open-claude/open_claude/compact.py`、`open-claude/oc_codex_server.py`、`open-claude/open_claude/repl.py`、`open-claude/open_claude/agent.py`、`tests/test_openai_compat.py`。

### 44. 思考过程支持上滑查看历史内容

- Agent 思考或执行任务期间，只在用户位于会话底部时自动跟随最新事件。
- 用户向上滚动后保持当前位置，不再被持续到达的思维链事件强制拉回底部；滚回底部后自动恢复跟随。
- 发送新的用户要求、切换历史任务或新建任务时仍自动定位到最新消息。
- 主要文件：`frontend/src/main.jsx`、`tests/test_frontend_contract.py`。

### 45. 历史任务归属校验与初始化竞态修复

- 历史任务详情接口不再因为携带相同 `repositoryId + taskCode` 就绕过任务归属校验；任务列表、任务详情和后续文件/操作接口统一使用当前用户的任务绑定。
- owner 为空的旧任务不再对所有外部用户可见，仅在同一任务经过本体平台鉴权后迁移到当前用户；本地开发模式继续支持显式的旧会话兼容。
- React 工作台启动时先完成当前任务信息读取和旧会话归属迁移，再加载并打开历史任务，避免首次进入页面时出现“任务详情/文件读取失败”的竞态。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`tests/test_ontology_knowledge.py`。

### 46. 鉴权密钥文件句柄清理

- 鉴权 Cookie 密钥读取改用上下文管理器，避免每次请求留下未关闭的文件句柄；密钥生成、权限和回退行为保持不变。
- 主要文件：`open-claude/oc_codex_server.py`。

### 47. 上传文件图标颜色统一

- 输入对话框“上传文件”图标改为继承按钮文字颜色，与“上传文件”文字保持一致的蓝色。
- 上传行为和文件选择逻辑不变。
- 主要文件：`frontend/src/main.jsx`、`tests/test_frontend_contract.py`。

### 48. 会话入口文案统一

- 侧边栏“+ 新任务”改为“+ 新会话”，“历史任务”改为“历史会话”。
- 空列表提示和打开失败提示同步使用“会话”文案，任务创建、历史恢复和消息处理逻辑不变。
- 主要文件：`frontend/src/main.jsx`、`tests/test_frontend_contract.py`。

## 2026-08-07

### 49. 恢复用户确认完成任务

- MinIO 上传只保存结果文件并保持任务 `RUNNING`，不再自动回调 `COMPLETED`。
- 会话顶部新增“完成”按钮，用户确认后才校验结果文件并回写 `COMPLETED`；已完成任务点击“修改”会先删除旧结果对象（包括整合任务的 `ok.csv`），再恢复编辑。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`backend-agent-interaction-api.md`。

### 50. 完成按钮渐变蓝样式

- 任务顶部的“完成”按钮改用与“新会话”一致的蓝色渐变和阴影样式。
- “修改”按钮继续使用默认按钮样式，不改变状态切换行为。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 51. 自动确认按钮状态样式与提示

- 自动确认关闭时显示蓝色边框和蓝色文字，开启后切换为与“完成”按钮一致的蓝色渐变。
- 点击切换时分别提示“已开启自动确认”或“已关闭自动确认”，开启后的待确认请求仍会自动处理。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 52. 自动确认入口移动到输入框

- 自动确认按钮从任务顶部移动到输入对话框“上传文件”右侧。
- “完成/修改”和“文件”入口继续保留在任务顶部。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 53. 任务与文件目录图标统一

- “完成”按钮使用勾选图标，“修改”按钮使用编辑图标，“文件”按钮使用文件夹图标。
- 文件面板中的 `mission-input/`、`mission-output/` 和项目根目录统一使用文件夹图标。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 54. 完成图标改为白色

- “完成”按钮的勾选图标改为白色，与渐变蓝按钮背景保持对比度。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 55. 文件目录箭头垂直对齐

- 文件目录折叠和展开箭头改用统一尺寸的 SVG 图标，固定在目录标题行中垂直居中。
- 折叠与展开状态的箭头保持同一位置，不再受文字基线影响产生上下偏移。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。
