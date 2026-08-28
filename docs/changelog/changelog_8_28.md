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

### 品牌统一与全屏预览（47313/47314 共用前端）

- 品牌统一：47313 左上角由“硕磐智能 + Agent”改为与 47314 一致的“硕磐智能建模 + v0.1.0”；47314 版本由 v0.0.1 改为 v0.1.0。品牌图标仍为“硕”，47314“服务已连接”状态不变。
- 在 `frontend/src/main.jsx` 定义 `PRODUCT_NAME`/`PRODUCT_VERSION` 单一常量，两个入口共同使用，防止再次不一致。
- 知识规范和建模契约中的 v0.0.1 未修改（本体元模型/模板/术语/动作/输入参考文件名仍为知识契约版本，不是产品 UI 版本）。
- 全屏预览样式：`frontend/src/styles.css` 全屏 Modal 从左上角开始并占满 `100vw × 100dvh`（`top:0`、`margin:0`、`padding:0`、`height:100dvh`）；全屏下 `ant-modal-content`、header、body、`ontology-tree-scroll`/`ontology-sigma-shell`/`ontology-sigma-loading` 及文本/CSV/图片预览容器全部 `border-radius:0!important`；普通模式圆角（如 `.ontology-tree-scroll` 的 `border-radius:8px`）保持不变；设置、任务信息、上传结果等普通 Modal 不受影响。
- 新增测试：`tests/test_frontend_contract.py`（品牌/版本契约、全屏样式契约、禁止全局取消圆角）、`frontend/tests/ontologyPreviewRuntime.test.mjs`（`PreviewModalTitle` 全屏按钮真实切换、两个入口 class 契约一致，`PreviewModalTitle` 导出供测试）。
- 验证：全量 pytest 695 passed、Node 76/76、production build 成功、`git diff --check` 通过。

### 项目 README、正式版本文档与工程记录目录整理

- 原根目录 `README (1).md` 是 Eimosp Foundation File Service 文档，已归档到 `docs/eimosp-foundation-fileserver.md`（`git mv` 保留原文与历史），根目录不再保留该文件。
- 新建根 `README.md`，介绍“硕磐智能建模”，当前版本 `v0.1.0`，包含项目简介、核心能力、服务组成、技术架构、项目结构、本地开发、配置说明、测试与构建、API 文档、版本历史、工程记录、安全说明和许可证；未复制 Eimosp 的 Java/Spring Boot 架构内容。
- 正式版本说明统一使用 `docs/versions/`：新增 `docs/versions/README.md` 版本索引和 `docs/versions/v0.1.0.md` 正式版本说明；不创建根目录 `CHANGELOG.md`。
- 原 `changelog/` 整体迁移到 `docs/changelog/`（`git mv` 保留全部历史记录），新增 `docs/changelog/README.md` 记录索引与使用规则。
- `AGENTS.md` 活动路径全部同步为 `docs/changelog/changelog_M_D.md`，新增“正式版本文档工作流”章节；历史 changelog 正文保留旧路径与历史事实不变。
- 新增 `tests/test_documentation_layout.py`（10 项布局契约断言）。
- 验证：全量 pytest 705 passed、`git diff --check` 通过；commit/push 状态见最终报告；未部署。

### Git 双远端私有镜像工作流

- 新增 `personal` 私有远端：`git@github.com:zhenzhan0408/ontology-agent.git`，目标分支 `main`；`origin` 保持 `tianzj890107/ontology-agent` 的 `20260727` 分支。
- 同一 commit 双 push：`HEAD == origin/20260727 == personal/main`；`personal` 仅作为镜像与个人版本归档，禁止个人仓库独立提交。
- 新增 `scripts/push_dual_remotes.py`：校验远端映射、工作区干净、祖先关系与推送后三个 hash，支持 `--check` 只读检查，禁止 force push，origin 成功但 personal 失败时报告部分成功。
- 新增本地 bare remote 测试 `tests/test_dual_remote_push.py`（12 项），更新 `tests/test_repository_workflow_contract.py` 与 `tests/test_documentation_layout.py`。
- `AGENTS.md`、`debug.md`、`README.md`、`docs/git-dual-remote-workflow.md`、`docs/versions/v0.1.0.md` 同步双远端工作流说明。
- 本次个人仓库创建状态、两个远端最终 hash、实际测试结果与 commit/push 状态见最终报告；push 不代表部署；未部署。
