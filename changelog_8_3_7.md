# 20260803–20260807 分支变更记录

> 本文档记录 `20260727` 分支在 2026-08-03 至 2026-08-07 的变更。

## 维护规则

- 每次功能修改后，在本周记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/wugefei/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`。
- 下周开始时，将本文件归档为对应日期范围，并新建下一周的变更记录。

## 2026-08-03

### 1. 历史会话恢复提示降噪

- 打开历史会话自动恢复审批时，已处理或已过期的审批请求不再弹出错误提示；鉴权、网络等真实审批失败仍保留提示。
- 当前任务信息仅作为侧栏辅助内容；上游任务信息暂不可获取时改为页面空态，不再在打开对话时弹出“获取任务信息失败”。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 2. Qwen 与团队模型重名路由修复

- 修复团队模型目录与 Qwen 模型目录存在同名模型时的 Provider 污染问题。
- Qwen 模式下，共享模型继续走 Qwen Base URL 和 Qwen Key；仅团队专属模型不会混入 Qwen 模型列表。
- 团队模式下仍按 `TEAM_MODELS` 暴露模型，并将共享模型标记为团队网关模型。
- 主要文件：`open-claude/open_claude/config.py`、`tests/test_team_config.py`。

### 3. OpenAI 兼容客户端纳入运行依赖

- 将 `openai` 纳入 Open Claude 的基础依赖，确保 Qwen、团队网关及其他兼容接口在按项目依赖安装后即可调用。
- 同步更新 `open-claude/open_claude/requirements.txt`、`open-claude/pyproject.toml` 与安装说明。

### 4. 任务上下文鉴权转发修复

- 读取 execution-context 和完成回写时保留平台传入的 Bearer JWT，避免 Agent 为本地任务隔离生成的临时用户标识覆盖上游登录态。
- 对无效或过长的鉴权头不转发，继续由服务端按现有鉴权规则处理。
- 主要文件：`open-claude/oc_codex_server.py`、`tests/test_ontology_knowledge.py`。
