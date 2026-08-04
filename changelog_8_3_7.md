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
- 同步更新 Agent 与本体平台的状态接口约定，明确 `RUNNING`、`FAILED`、用户确认 `COMPLETED` 和“修改”恢复运行中的时机。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`backend-agent-interaction-api.md`、`tests/test_ontology_knowledge.py`、`tests/test_frontend_contract.py`。

### 2. 历史会话恢复提示降噪

- 打开历史会话自动恢复审批时，已处理或已过期的审批请求不再弹出错误提示；鉴权、网络等真实审批失败仍保留提示。
- 当前任务信息仅作为侧栏辅助内容；上游任务信息暂不可获取时改为页面空态，不再在打开对话时弹出“获取任务信息失败”。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

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
