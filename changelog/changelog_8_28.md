# 20260828 变更记录

> 本文档记录 `20260727` 分支在 2026-08-28 的变更。

## 维护规则

- 每次完成代码、配置、规则、文档、部署脚本、构建产物或测试修改后，自动同步本记录，无需再次提醒。
- 当天记录按功能最终状态组织：结合累计 diff 合并中间修改，修订过时描述，删除重复或已被后续实现取代的内容，只保留最终用户可见行为、重要内部契约、主要文件和最终验证结果。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314；部署前确认无活跃或排队任务，部署后确认两服务 `/`、`/health` 均为 200，并检查线上资源与启动日志。
- 历史 changelog（`changelog_8_27.md` 及更早）不再修改；昨日遗留事项如在今天继续处理，在本记录中按今天的最终状态归纳。

## 2026-08-28

### 47314 独立建模 actions.csv 契约修复

- `open-claude/standalone_modeling_server.py`：`DEFAULT_ARTIFACTS` 加入 `actions.csv`，`ARTIFACT_PARSE_ELEMENTS` 将 `actions.csv` 映射为 `ACTION`；白名单不扩大到前端未提供的其他产物。
- 用户默认全选产物（含 `actions.csv`）创建 run 成功，`_context(run)` 的 `expectedFiles` 含 `actions.csv`、`parseElements` 含 `ACTION`；未知产物仍返回 422。
- 新增测试：`tests/test_frontend_contract.py`（前后端白名单契约）、`tests/test_standalone_modeling_server.py`（接受/映射/默认全选/未知拒绝）。
- 验证：全量 pytest 693 passed、Node 74/74、production build 成功、`git diff --check` 通过。

### 全局协作规则：提交与禁止部署

- `AGENTS.md` 新增“提交与禁止部署（最高优先级）”：修改并验证后必须 commit 并 push 到当前分支；push 不代表部署；除非用户逐次单独授权，否则永远不得部署、SSH、SCP/rsync、服务器 git pull、执行部署/重启脚本、`systemctl`、kill 线上进程、重启或停止线上服务；禁 force push。
- 同步修订 `debug.md`、`agent_knowledge/README.md`、`DEPLOYMENT.md`、`README (1).md`、`open-claude/README.md`、`日报.md`；历史运维部署说明仅供人工参考，保留不删。
- 新增防回归测试 `tests/test_repository_workflow_contract.py`（7 项断言）。
- 状态：今日所有修改均已 commit 并 push 到 `20260727`（含本 changelog 提交）；未部署、未连接服务器、未重启任何服务。
