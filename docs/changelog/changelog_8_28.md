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

- 新增 `personal` 私有远端：`git@github.com:zhenzhang0408/ontology-agent.git`，目标分支 `main`；`origin` 保持 `tianzj890107/ontology-agent` 的 `20260727` 分支。
- 同一 commit 双 push：`HEAD == origin/20260727 == personal/main`；`personal` 仅作为镜像与个人版本归档，禁止个人仓库独立提交。
- 新增 `scripts/push_dual_remotes.py`：校验远端映射、工作区干净、祖先关系与推送后三个 hash，支持 `--check` 只读检查，禁止 force push，origin 成功但 personal 失败时报告部分成功。
- 新增本地 bare remote 测试 `tests/test_dual_remote_push.py`（13 项），更新 `tests/test_repository_workflow_contract.py`（11 项）与 `tests/test_documentation_layout.py`。
- `AGENTS.md`、`debug.md`、`README.md`、`docs/git-dual-remote-workflow.md`、`docs/versions/v0.1.0.md` 同步双远端工作流说明。
- 实际结果：个人私有镜像仓库最终确认为 `zhenzhang0408/ontology-agent`，`personal` 远端已修正为 `git@github.com:zhenzhang0408/ontology-agent.git`；本地 `HEAD`、`origin/20260727` 与 `personal/main` 均同步到 `3af6d14`，未 force push；push 不代表部署。

### v0.1.0 功能部署与线上验证

- 部署范围：服务器由 `f5c67a1` 快进到 `3af6d14`，包含 47314 `actions.csv` 默认产物契约、47313/47314 统一“硕磐智能建模 v0.1.0”、文件与本体预览全屏无圆角、项目 README/版本文档与 changelog 目录整理，以及仅影响开发协作的双远端推送工具；无数据库迁移、无 run/任务数据格式迁移。
- 部署前确认：本地全量 pytest `722 passed / 13 skipped / 448 subtests`，前端 Node 测试 `76/76`，`npm run build` 与 `git diff --check` 通过；服务器 47313/47314 的 active/queued execution 均为 0，运行索引和既有备份保持原样。
- 部署结果：47313 经 `scripts/deploy_server.sh` 更新并重启为 pid `4122195`；47314 在再次确认无活动 run 后精确停止旧 pid `3830440`，经 `scripts/run_standalone_modeling.sh` 重启为 pid `4125590`。两服务 `/` 与 `/health` 均为 HTTP 200、readiness ready、active/queued 均为 0。
- 线上资源：47313/47314 均加载 `assets/index-DvhxxeJ3.js`；线上 bundle 已核对包含“硕磐智能建模”和 `v0.1.0`，CSS `index-CpwoD9tw.css` 已核对全屏预览 `border-radius:0!important`；两服务最近启动日志无 traceback/exception/error。

### v0.1.0 正式定版与版本规范

- v0.1.0 状态调整为已定版，正式 tag 为 v0.1.0。
- 新增 `docs/versions/versioning-policy.md`，明确语义化版本、每日稳定发布、部署与版本边界。
- 每个 commit 不自动升级版本；每次部署不一定创建正式版本。
- 每日稳定业务发布可以增加 PATCH；MINOR 由明显的新功能或兼容变化决定，不按自然周机械升级。
- 只有文档、测试或内部维护时可以不创建正式版本。
- Git commit、每日 changelog、版本文档、Git tag、GitHub Release 和服务器部署职责独立。
- v0.1.0 tag 不再移动；后续修复默认归入 v0.1.1。
- 本次只创建 Git tag，不创建 GitHub Release，不部署、不重启服务。

### v0.1.1 开发：会话缓存与本体图后台预加载（最终状态）

- 新增 `frontend/src/sessionCache.js` 纯模块：`createSessionCache`（LRU，默认最多 10 个会话）、`artifactSignature`（基于产物路径与 size/mtime/modifiedAt/version/hash 等元数据的稳定签名）、`createInFlightRegistry`（在途 Promise 去重）、`createOntologyGraphCache`（按 scope 缓存 graph，签名失效自动重建，失败记录错误可重试，支持活动 scope 保护的 LRU 淘汰）；另提供可独立测试的开场/恢复辅助函数：`taskCacheKey`（namespaced key）、`sessionSnapshotFor`/`restoreTaskPlan`（缓存快照恢复）、`mergeLogWindow`（窗口合并，cursor 不倒退）、`commitSessionSnapshot`（写回并保护活动 key 的 LRU）、`createOpenGate`（请求 generation 判定）。
- 47313 任务工作台：`openTask` 先按 `taskCacheKey(task, MISSION)` 计算 namespaced key，缓存存在时在详情请求返回前立即恢复任务快照、合并事件、文件列表与事件窗口，后台再请求最新详情与事件增量并幂等合并；每次打开生成新请求代次并取消旧详情请求，迟到的旧响应不能覆盖当前会话；`loadFiles` 成功后写回文件列表与 `filesTaskId` 并触发 `preloadTaskOntologyGraph`；`drawOntology` 与预加载统一使用同一个 namespaced key 查询 `taskGraphCacheRef`（不再用裸 taskId），有有效缓存立即打开、有同签名在途 Promise 则复用、无缓存现场加载并写回；`activeTaskCacheKeyRef` 统一保护会话缓存与 graph 缓存的 LRU 淘汰；`ontologyDrawRequestRef` 防止旧请求的 finally 清除新请求的 loading 状态。
- 47314 独立建模：`selectRun` 从 `standaloneSessionCacheRef` 即时恢复事件、文件列表与事件窗口；`loadRunFiles` 成功后写回文件列表并触发 `preloadStandaloneOntologyGraph`；`drawStandaloneOntology` 与预加载共用同一 runId scope；`standaloneDrawRequestRef` 隔离 loading；LRU 淘汰时同步释放事件窗口/cursor/合并事件引用。
- 行为：A → B → A 切换立即恢复 A 的缓存；同一 task/run 同一产物签名只有一个在途 CSV 下载与构图；产物签名变化后 graph 失效并重新构图；预加载失败不阻止会话打开，点击可视化可重试；不使用 localStorage/sessionStorage/IndexedDB，缓存仅当前页面内存有效，刷新后自然清空。
- 测试：`frontend/tests/sessionCache.test.mjs` 覆盖 LRU、签名、去重、签名失效、迟到响应、错误重试、namespaced key 隔离、A → B → A 立即恢复与 generation 拦截；`frontend/tests/ontologyPreviewRuntime.test.mjs` 将原源码字符串测试替换为真实行为测试并保留直接防回归“drawOntology 用裸 taskId”的接线契约；`frontend/tests/ontologyForceLayout.test.mjs` 修复对仓库根目录运行时 `output/` 的依赖，改用可提交的合成五层 CSV 夹具 `frontend/tests/fixtures/five-layer/`（路径经 `import.meta.url` 相对解析）；`tests/test_frontend_contract.py` 的 selectRun 契约随新实现更新。
- 验证：前端 Node 测试 107/107 通过、Python 全量测试通过、`npm run build` 成功、`git diff --check` 通过。
- 状态：v0.1.1 尚未定版、未创建 tag、未创建 GitHub Release；commit/push 状态见最终报告；未部署。

### GitHub Release 双仓库发布规范

- 全局规则固化：用户在当前任务明确授权创建某版本的 GitHub Release 时，必须在 `tianzj890107/ontology-agent`（origin）与 `zhenzhang0408/ontology-agent`（personal）两个仓库同时发布绑定同一 immutable annotated tag 的 Release。
- 两个 Release 的 tag object hash、peeled commit、标题、正文、draft、prerelease 必须一致；已存在且符合要求的 Release 复用并验收，不重复创建；一个存在、另一个缺失时只创建缺失的那个。
- 任一仓库失败时报告部分成功：保留已成功 Release，不删除、不重建，修复权限或网络后只重试缺失仓库；禁止只发布一个仓库后宣称双发布完成。
- 禁止为了补齐 Release 移动 tag、重新打 tag、`git push --tags` 或 force push；`v0.1.0` tag 永远不得移动；`v0.1.1` 未定版前不得创建 tag 或 Release。
- Release 不等于部署；创建 Release 后如无额外部署授权，任务结束。
- 同步修改 `AGENTS.md`、`docs/versions/versioning-policy.md`、`docs/git-dual-remote-workflow.md`、`README.md`；新增 `tests/test_repository_workflow_contract.py` 双仓库 Release 策略测试（7 项）；`docs/versions/v0.1.0.md` 补充双仓库 Release 链接（创建并回查成功后写入）。
- 实际 Release 状态：personal 仓库已存在 `v0.1.0` Release（id 378309186），验收并复用，正文统一为最终文案；origin 仓库缺失，已创建（id 378324865）。两个 Release 均绑定 `v0.1.0` tag、标题“硕磐智能建模 v0.1.0”、非 draft、非 prerelease、正文一致。
- tag 核验：两端 `v0.1.0` tag object 均为 `38eae0402176e2e801ba92bcd00ee304b83eacf0`、peeled commit 均为 `188057d8a81b7d83f0aeb858e40c3ef14fddf539`，未移动；未创建 `v0.1.1` tag 或 Release。
- 验证：全量 Python 测试通过、`git diff --check` 通过；未部署、未连接服务器。
