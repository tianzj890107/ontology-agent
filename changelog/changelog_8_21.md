# 2026-08-21 变更记录

- 创建今日独立变更记录；从本文件创建后，今天后续完成的代码、配置、测试和部署变更统一按最终结果追加记录。

- 切换 47313/47314 两个服务的默认大模型：DeepSeek V4 Flash（`direct-deepseek-v4-flash`）→ Qwen3 80B AWQ（`Qwen/Qwen3-80B-AWQ`）：
  - 根因/背景：此前两个服务默认模型均为 `direct-deepseek-v4-flash`（`.env` 中 `TEAM_MODEL` 决定 `DEFAULT_MODEL`，provider 为 team 网关）；`Qwen/Qwen3-80B-AWQ` 已在 `TEAM_MODELS` 候选列表中但非默认。
  - 变更：仅配置改动，不涉及代码。本地与服务器 `.env` 的 `TEAM_MODEL` 均改为 `Qwen/Qwen3-80B-AWQ`（服务器改前备份 `.env.bak-20260821-092855`；`.env` 属 gitignored，不入库）；47313 与 47314 分别重启加载新默认值。
  - 验证：服务器侧 `get_model()` 返回 `Qwen/Qwen3-80B-AWQ`（provider=team），可用模型列表不变（deepseek-v4-flash/pro、qwen3.7-plus、glm-5.1、kimi-k2.6、glm-5.2、glm-5-turbo 等仍可手动选择）；47313 `/api/model` 与 47314 `/api/modeling-models`（带 X-Modeling-API-Key）均返回默认 `Qwen/Qwen3-80B-AWQ`；两个服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s` 且无新增 traceback；真实网关冒烟：`Qwen/Qwen3-80B-AWQ` 首轮产出 tool_calls、次轮回传后 end_turn，无 400。部署前确认两服务无活跃任务（47313 working=0，47314 active=0/queued=0）。

- 修复“前端默认模型仍不是 Qwen”的用户级偏好残留（服务器配置，不入库）：
  - 根因：浏览器用户 `local:Zzp-tQUyaM8YNUhRs0msfli-` 在 `~/.claude/ontology-agent-user-settings.json` 中保存了旧偏好 `qwen-vl-ocr-latest`（OCR 模型）。`/api/meta` 的 `model` 由 `user_model(user_id)` 决定，该偏好会在命中 `configured_models()` 时覆盖服务端默认；此前该 id 曾位于 Qwen 视觉模型列表，导致 47313 前端显示 OCR 模型而非 Qwen 默认。
  - 变更：将该用户偏好原子改写为 `Qwen/Qwen3-80B-AWQ`（python 原子写，保留文件权限；`user_model()` 实时读取，无需重启服务）。
  - 验证：服务器 `user_model(local:Zzp-tQUyaM8YNUhRs0msfli-)` 与无偏好用户均返回 `Qwen/Qwen3-80B-AWQ`；带该用户 cookie 请求 47313 `/api/meta` 返回 `model=Qwen/Qwen3-80B-AWQ`、`provider=team`；47314 `/api/modeling-models` 同样返回 Qwen。前端模型选择器按 `/api/meta.model` 展示，刷新页面即生效。
- 服务器部署线路核查（无代码变更）：
  - SSH `company-server`、git remote（`github.com/tianzj890107/ontology-agent.git`，分支 `20260727`）与 `git fetch` 均正常；`scripts/deploy_server.sh`、`scripts/run_standalone_modeling.sh` 无需修改。
  - 47313 `/`、`/health` 与 47314 `/`、`/health` 全部返回 200；两个服务启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。
  - 服务器存在 root 用户残留进程 `python3 -`（PID 2204477，父 2204441，已运行约 9 天，CPU 99.9%），为死循环占用，与本次部署无关；zhangzhen 无 sudo 权限，需管理员核实后 `kill 2204477`。
