# 20260827 变更记录

> 本文档记录 `20260727` 分支在 2026-08-27 的变更。

## 维护规则

- 每次完成代码、配置、规则、文档、部署脚本、构建产物或测试修改后，自动同步本记录，无需再次提醒。
- 当天记录按功能最终状态组织：结合累计 diff 合并中间修改，修订过时描述，删除重复或已被后续实现取代的内容，只保留最终用户可见行为、重要内部契约、主要文件和最终验证结果。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314；部署前确认无活跃或排队任务，部署后确认两服务 `/`、`/health` 均为 200，并检查线上资源与启动日志。
- 历史 changelog（`changelog_8_26.md` 及更早）不再修改；昨日遗留事项如在今天继续处理，在本记录中按今天的最终状态归纳。

## 2026-08-27

### 默认模型切换为 DeepSeek V4 Flash

- 团队网关默认模型由 `Qwen/Qwen3-80B-AWQ` 调整为 `direct-deepseek-v4-flash`：同步更新 `open_claude/config.py` 内置回退值、`.env.example` 与本地/服务器 `.env`，后续服务启动及没有个人模型偏好的新身份默认使用 DeepSeek V4 Flash。
- 47313 任务 `RM2092866461941178368` 通过用户模型 API 热切换到 `direct-deepseek-v4-flash`；原 execution 命中执行次数保护进入 blocked 后，以 execute 意图原地续跑，新 execution `16cf8aa780d14a338b1de867461725e7` 已处于 working，事件日志已实际产生 DeepSeek reasoning（`thinking`）事件。全过程未重启服务、未丢弃会话或任务工作区。
- 47313 任务详情与增量事件窗口新增 `model` 字段，取任务 conversation 的实际 live model 且不会为历史任务强制创建 conversation；前端打开任务和轮询事件时同步实际模型。兼容尚未重启的旧后端：事件窗口没有 `model` 时回退读取 `/api/meta`，解决服务端/API 热切换后模型选择器仍显示旧值。

### 思考过程跨批次合并

- 47313 后台 execution 通过两秒轮询回传事件时，连续 reasoning 会跨多个事件窗口；此前仅在单个响应批次内合并，导致一个思考过程显示为大量“思考中”节点。`EventFeed` 现于完整去重、排序后的展示层再次执行相邻增量归并，跨 SSE、轮询、刷新、历史分页边界连续的 `thinking`/`text` 均显示为单一节点，遇到工具、审计、审批等真实事件边界才拆分。
- 合并只发生在展示层：服务端原始逐 token journal、单调 `seq`、绝对游标和审计历史完全保留，不修改或删除当前任务及历史任务事件；当前任务已有的连续思考在刷新新前端后自动按真实区段合并，后续增量继续并入同一节点。
- 验证：全量 `pytest tests` 663 passed / 13 skipped / 445 subtests；相关前端/任务/模型回归 94 passed；前端 Node 测试 47/47；`py_compile` 通过；`npm run build` 成功（仅既有大 chunk 提示）；`git diff --check` 通过。
- 发布：当前全部本地修改以 commit `bc0a380` 提交并推送 `20260727`；发布前确认 47313/47314 均无 active/queued execution。服务器快进到同一 commit，47313 经部署脚本重启为 pid `3040408`，47314 精确停止无活跃 run 的旧 pid `2639894` 后重启为 pid `3045138`；两服务 `/health` 均 ready、active/queued 均为 0，线上主 bundle 为 `index-T1HCUlYg.js`，默认模型配置为 `direct-deepseek-v4-flash`。

### 动作元模型：识别与输出规范

按 `rules/本体元模型模板v.0.0.1.xlsx` 动作 Sheet 将“动作”落地为正式独立元模型，正式产物 `actions.csv` 严格使用模板九个字段：动作编码、动作名称、动作英文名、动作描述、动作类型、业务对象编码、协议、服务节点、服务名称。

- 动作类型仅支持 新增/修改/删除（内部枚举 CREATE/UPDATE/DELETE，写入 CSV 必须用中文）；动作编码 `ACT` + 6 位流水码（如 `ACT000001`），当前任务内唯一、稳定排序、不使用随机数。
- 识别策略“明确证据优先、合理推断兜底”：优先 API/接口/Controller/Route、服务/Command/工作流、前端按钮/表单、业务操作文档；证据不足时按已确认业务对象生成 3 个 BO 级动作，并选择 0～6 个代表性逻辑实体生成 LE 级动作（明细、行、地址、联系人、附件、配置等），总量控制在 10～50 条；无业务对象不生成动作。
- 推断动作在动作描述中注明“演示候选动作，具体服务实现需结合实际系统确认”；协议/服务节点/服务名称无服务证据时留空，不得虚构；LE 级动作通过动作名称和描述表达，不新增逻辑实体编码等字段。
- 动作按（业务对象编码、动作类型、动作名称）去重，明确识别动作优先于同语义推断动作；新模板、空 Sheet、旧模板无动作 Sheet、表头顺序变化、BOM/空行均兼容；不同任务/工作区/run 严格隔离。
- 确定性兜底已接入正式建模 finalize/export 链路：`modeling_reliability.py::ensure_actions_artifact` 在 ACTION 被选择且 expectedFiles 允许 `actions.csv` 时执行。Agent 未生成、空文件或只有表头时，根据当前任务 `work/modeling_state.json` 或 `output/` 已确认 BO/LE 自动生成演示动作；Agent 明确动作优先合并、真实协议/服务节点/服务名称字段保留；表头缺失、悬空 BO 引用、非法动作类型、非空且非 `ACT+6位` 编码等结构错误不覆盖，继续进入正式产物门禁报告；ACTION 未选择、expectedFiles 不允许、没有已确认业务对象时不生成。`actions.csv` 已加入 `GOVERNANCE_AND_FINAL` 阶段输出与表头契约，内容变化会正确失效最终缓存，写入使用临时文件 + `os.replace` 原子策略。

主要文件：
- 新增 `open-claude/open_claude/action_inference.py`（动作 Sheet 解析、类型归一化、BO/LE 推断、去重、稳定排序与稳定编码纯函数）与 `agent_knowledge/动作v0.0.1.md`（专项技能）。
- `open_claude/open_claude/modeling_csv_contract.py` 注册 `actions.csv` 九字段契约（必填六项、动作类型枚举、ACT 编码格式、业务对象编码引用）。
- `open-claude/oc_codex_server.py`：`_MODELING_CONTRACT_NAMES`、`MODEL_ARTIFACT_DEFINITIONS.actionArtifact`、`build_modeling_plan.executionOrder` 增加 ACTION、文档输出契约、建模指令动作技能注入与步骤 7 约定、输出文件标签、任务参考文件名称切换到 `本体元模型模板v.0.0.1.xlsx`。
- `open_claude/open_claude/ontology_knowledge.py` 注册 ACTION 技能模块；`modeling_rule_registry.py` 注册动作契约规则号与产物类型；`modeling_reliability.py` 增加 actions.csv 业务对象引用校验。
- `scripts/build_agent_knowledge.py` 增加动作知识并重新生成 `basev0.0.1.md`、`all_sourcesv0.0.1.md`、模板知识与 `动作v0.0.1.md`；集成版（消歧整合）知识 base/模板/all_sources 同步补充动作元模型规则与 actions.csv 字段规范；`agent_knowledge` 相关 Markdown 随构建刷新。
- 集成（消歧整合）链路同步注册 `actions.csv`（`_INTEGRATION_CONTRACT_NAMES`），`merged_elements` 等元素类型枚举加入 ACTION。
- 前端 47314 独立建模页“解析要素”新增“动作”（`frontend/src/main.jsx` STANDALONE_ARTIFACTS），并重建 `frontend/dist`（新 hash bundle 替换旧 bundle）；API 文档与 SOP 同步 actions.csv 输出文件映射与参考文件名称。

验证结果：
- 全量 `pytest tests`：576 passed / 13 skipped（10 项 Redis 集成无 `ONTOLOGY_TEST_REDIS_URL`、3 项平台沙箱）/ 371 subtests。
- 新增 `tests/test_action_inference.py`（27 项：BO/LE 动作生成、明确证据优先、去重稳定编码、九字段输出、任务隔离）与 `tests/test_action_production_fallback.py`（18 项：缺失/空/表头自动补充、明确动作合并与服务字段保留、编码保留与冲突规避、ACTION 与 expectedFiles 双门禁、无 BO 不生成、结构错误不被推断掩盖、任务隔离、严格九字段）；更新 `tests/test_ontology_knowledge.py`、`tests/test_modeling_csv_contract.py`（含集成版输出契约覆盖 actions.csv）。
- `python -m py_compile` 全部改动 Python 文件通过；`git diff --check` 通过；前端 `npm run build` 成功（仅既有大 chunk 警告，`frontend/dist` 已随解析要素新增动作重建为新 hash bundle）；前端 Node 测试 47/47 通过（`frontend/output/*.csv` 为 gitignore 本地测试夹具，来源于服务器恢复归档，不入库、不参与部署）。
- 本轮改动经 commit `2372291` 提交并推送、部署 47313/47314（见文末“部署与线上验证”）。

### 本体可视化预览：统一布局选择交互

将本体可视化预览卡片的布局切换收敛为右上角统一“布局”下拉框，删除旧的左侧“环形图/网络图”页签与右侧“重新布局 / ForceAtlas2”常驻入口，保留两种布局能力并统一命名与提示文案。

- 布局下拉框仅两项：`关系聚类可视化`（对应 ForceAtlas2/网络图）与 `语义环形可视化`（对应径向语义分层图）；选项悬浮提示分别为“ForceAtlas2 是一种先进的力导向图布局”和“按照业务对象、逻辑实体、业务属性等语义层级，由内向外分层排列节点”，下拉框旁信息图标始终展示当前布局说明。
- 打开预览默认优先展示关系聚类可视化（Sigma/ForceAtlas2）；语义环形布局（ECharts）不在首次打开时初始化。网络关系图展示期间，浏览器空闲时后台完成 `layoutOntologyRadial` 布局数据计算（natural bounds、fitScale、最终渲染节点）并写入有界缓存（LRU 上限 8 条），不创建隐藏 ECharts 实例；切换“语义环形可视化”时优先复用缓存，未就绪时显示统一加载态并复用 in-flight Promise（相同缓存键不重复计算），完成后自动 fit，不再需要独立“重新布局”按钮。
- 环形布局缓存键为 `radial:<数据指纹>:<layerKey>:<宽>x<高>:<布局版本>`：数据指纹由可见节点/连线集合决定，`appliedLayers` 确认后、viewport 实质变化（含全屏/退出全屏）后、任务/run 数据变化后失效并后台重算；`draftLayers` 变化与仅打开下拉框不触发；关闭预览即释放缓存。
- 布局失败恢复以“最后一次真正成功渲染”为准：关系图与环形图在 `setOption`/Sigma 渲染成功后通过 `onRendered` 更新 `lastGoodLayout`；Sigma 异步初始化错误经 try/catch 回调进入统一失败处理（不只依赖 ErrorBoundary），失败后保留上一成功布局、恢复下拉框并允许再次尝试，不会在 network/radial 之间循环切换。
- 切换布局真正重建对应布局结果：`draftLayers` 变更不触发重算，点击图层筛选“确认”后按 `appliedLayers` 作为布局缓存 key（`radial:`/`network:` 前缀）重建并自动 fit；全屏/退出全屏保持布局选择状态。
- 布局加载失败时保留上一次成功布局、恢复下拉框为上一次有效选项并显示错误提示，避免空白画布。
- 工具栏改为一行排列：布局选择器 + 图层筛选图标，与全屏/退出全屏、关闭按钮保持同一行；新增 `.ontology-toolbar`、`.ontology-layout-selector`、`.ontology-layout-error`、`.ontology-tree-loading-overlay` 样式，移除 `.ontology-view-switch`、`.ontology-sigma-actions` 样式。

主要文件：
- `frontend/src/main.jsx`：`OntologyTreePreview` 改由 `layoutMode`（network/radial，默认 network）驱动，新增 `OntologyLayoutSelector`、`OntologyPreviewErrorBoundary`；`OntologyEChartsPreview` 增加加载态与失败回退。
- 新增 `frontend/src/ontologyLayoutOptions.js`（两个布局选项的 value/名称/提示纯常量与查询函数）、`frontend/src/ontologyRadialPrecompute.js`（数据指纹、缓存键、`prepareRadialLayout` 后台准备、`radialGraphOption`、有界缓存控制器与 in-flight Promise 复用纯函数）与 `frontend/tests/ontologyLayoutOptions.test.mjs`、`frontend/tests/ontologyRadialPrecompute.test.mjs`（12 项：指纹稳定性、缓存键失效、viewport 归一化、准备结果稳定性、graph layout none、视口不匹配拒绝、缓存 LRU 与 Promise 复用）。
- `frontend/src/main.jsx`：`OntologyTreePreview` 持有 `createRadialLayoutCache` 与空闲后台预计算；`OntologyEChartsPreview` 接收 `prepared` 缓存载荷，不再无条件重复 `layoutOntologyRadial`；`OntologySigmaPreview` 增加 `onError/onRendered` 统一失败与成功渲染上报。
- `frontend/src/OntologySigmaPreview.jsx`：删除 ForceAtlas2 常驻文字、重新布局按钮及 `layoutVersion/layoutRunning` 状态。
- `frontend/src/styles.css`：统一工具栏布局与布局选择器样式；`tests/test_frontend_contract.py` 更新旧入口断言并新增 `test_ontology_preview_unified_layout_selector`。
- 重建 `frontend/dist`（新 hash bundle 替换旧 bundle）。

验证结果：
- 前端 Node 测试 `node --test 'tests/*.test.mjs'`：47/47 通过（35 项既有 + 12 项环形预计算新增；`frontend/output/*.csv` 为 gitignore 本地测试夹具，来源于服务器恢复归档，不入库、不参与部署）。
- `pytest tests/test_frontend_contract.py`：13 passed；`pytest tests/test_tasks.py tests/test_standalone_modeling_server.py`：137 passed + 16 subtests。
- `npm run build` 成功（仅既有大 chunk 警告）；`git diff --check` 通过。
- 本段布局交互改动随 commit `2372291` 提交并推送、部署 47313/47314（见文末“部署与线上验证”）。

### 运行工作区统一命名：input/work/output 与仓库根遗留迁移

将任务/run 运行工作区正式命名从 `mission-input/mission-work/mission-output` 统一为 `input/work/output`，完成仓库根遗留 ad-hoc 工作区的识别、迁移、校验与本地清理，并为 47313/47314 增加防仓库根再成为工作区的边界保护。

- 遗留归属识别：本地根目录 `input/`（空）、`work/`（26 文件，含 `modeling_state.json`/`state_full.json`/`schema_extract.json` 及决策审计 CSV）与 `output/`（7 个正式 CSV）共 33 文件、7,504,414 B；`mission-input→input`、`mission-work→work`、`mission-output→output` 为符号链接。`modeling_state.json` 的 `identity` 中 `repositoryId/taskCode` 均为空、`inputFingerprint`（`73d71db2...`）与服务器全部 47313 任务及 47314 run 的 modeling_state 与 output CSV 哈希均不匹配，判定为无主 ad-hoc 遗留，不并入任何正式任务/run。
- 迁移与校验：已 rsync 至服务器独立恢复归档 `open-claude/sandbox/recovered-workspaces/repo-root-legacy-2026-08-27/`（含 `migration-manifest.json`、`checksums.sha256`、`verify.out`、`MIGRATION_COMPLETE`）；服务器 `sha256sum -c` 33/33 全部成功、0 失败，本地与服务器逐文件哈希、文件数（33）与总字节（7,504,414）一致。
- 本地清理：将仓库根六个精确目标（`input`、`work`、`output` 及三个 `mission-*` 符号链接）移至 `~/Trash/ontology-agent-legacy-workspaces-2026-08-27/`（可恢复），未使用 glob 或未验证变量；`ls -ld` 复核六路径均不存在，`git status` 无遗留运行目录。
- 命名统一：新增集中式路径兼容模块 `open-claude/open_claude/workspace_paths.py`（`input_dir/work_dir/output_dir` canonical 优先、legacy 只读回退；`ensure_workspace_dirs` 只创建 canonical；`normalize_relpath/resolve_workspace_path/validate_task_workspace`）。旧路径仅允许存在于该集中式兼容层、历史 run 数据与兼容测试。
- 旧命名进一步收敛：`tests/test_tasks.py`、`tests/test_pipeline_decision_audits.py`、`tests/test_gate_action_normalization.py` 的普通用例与证据来源字符串迁移到 canonical（`work/`、`output/`、`input/`）；旧名称仅保留在 `workspace_paths.py` 集中式兼容层、`oc_codex_server.py::migrate_legacy_mission_inputs` 历史迁移入口、专门的历史兼容测试（`test_workspace_paths.py`、`test_task_workspace_files.py`、`test_ontology_knowledge.py` 迁移用例）与历史 run 数据中；前端源码无 `mission-input/mission-work/mission-output`，也无 `misson` 拼写。
- 47313 改造：`oc_codex_server.py` 新任务只创建 `input/work/output`；上传、下载、预览、文件列表、MinIO 上传、数据库 helper、文档 bundle、参考文件、Agent 提示词（建模/文档/数据库/输出指令）、`agentOutputDirectory=output`、`agentIntermediateDirectory=work` 全部改用 canonical；`task_workspace_path/create_task` 增加 `_validate_task_workspace` 边界校验（拒绝空路径、仓库根、源码目录、HOME、sandbox 数据根自身、相对/symlink 逃逸）；`list_project_files` 返回统一逻辑路径并对历史任务做 `mission-*→canonical` 展示映射。
- 47314 改造：`standalone_modeling_server.py` 新 run 不再创建 `mission-*` 符号链接，只创建 `input/work/output`；删除本地重复 `LEGACY_ALIASES`，统一复用 `workspace_paths.normalize_relpath` 集中式只读兼容解析（输入上传与公共相对路径均先归一化再校验）；默认建模提示词与数据库 schema 指令改用 `input/`、`work/`；文件 API 只返回 canonical 逻辑路径。
- 建模引擎与前端：`modeling_reliability.py`、`document_parser.py` 改用 workspace_paths；前端文件树分组显示“输入/工作/输出”，`main.jsx` 的 `mission-output/` 产物匹配改为 `output/`；API 文档、SOP、`agent_knowledge/**` 活动规范与 `scripts/build_agent_knowledge.py` 提示词全部去除 `mission-*`（历史 changelog 不改）。
- 新增 `tests/test_workspace_paths.py`（15 项：仓库根/源码目录/HOME/空路径/相对与符号链接逃逸拒绝、合法任务目录可用、canonical 优先与 legacy 只读回退、新写入只进 canonical、47313/47314 新任务只创建 input/work/output）；重写 `tests/test_task_workspace_files.py`（canonical 列表、legacy 逻辑路径映射、双布局共存 canonical 优先）；更新 `test_sandbox_security.py`、`test_semantic_finalize_upload_boundary.py`、`test_modeling_csv_contract.py`、`test_modeling_reliability.py`、`test_database_modeling_evidence.py`、`test_document_parser.py`、`test_credential_crypto.py`、`test_ontology_knowledge.py`、`test_standalone_modeling_server.py`、`test_frontend_contract.py`、`test_v0001_rule_registry.py` 至 canonical 契约。
- 验证结果：全量 `pytest tests` 576 passed / 13 skipped / 371 subtests；`py_compile` 全部改动 Python 文件通过；`npm run build` 成功（仅既有大 chunk 警告，新 hash bundle 已生成）；`git diff --check` 通过。
- 前端 Node 测试 35/35 通过：将迁移校验后的真实五层输出 CSV 恢复为 `frontend/output/` 本地测试夹具（该目录已加入 `.gitignore`，不入库、不参与部署），消除此前既有的“仓库真实五层输出”夹具缺失失败项。

### 部署与线上验证（工作区统一命名）

- 已提交并推送 `20260727`（commit `4813811`）；服务器 `git pull --ff-only` 到同一 commit，部署前备份服务器配置/索引至 `backup-pre-2026-08-27-111442/`（`.env`、`.standalone-modeling-api-key`、`.standalone-modeling-data-sources.json`、`open-claude/sandbox/.web_tasks.json`）。
- 47313 经 `scripts/deploy_server.sh` 重启，pid `1470949`；47314 经 `scripts/run_standalone_modeling.sh` 重启，pid `1472427`。
- 两服务 `/` 与 `/health` 均 200；`activeRuns=0`、`queuedRuns=0`；`coordination` 如实报告 backend=file、quotaScope=process、queueScope=process、multiHostSafe=false；`providerInUse/databaseInUse=0`。
- 线上 HTML 已加载新 bundle：`frontend/dist/assets/index-BcoJeGei.js` 与 `index-D7obonjB.css`（47313/47314 一致）。
- 新 47314 run 验证：通过 API 创建测试 run，磁盘只生成 `input/work/output`，无 `mission-*` 符号链接；验证后已完整清理（SQLite 索引行、`.runs.json` 条目与 run 工作目录），未影响既有 5 个 run。
- 历史 run 兼容验证：既有 run 文件列表返回 53 项且全部为 canonical 逻辑路径（`input/...`、`work/...`、`output/...`），无 `mission-*` 命名条目；`work/modeling_state.json` 经 canonical 路径可正常读取。
- 47313 历史任务端到端验证：用签名 cookie 调用 `/api/files`（280 项，无 mission 命名路径）、`/api/download`（200）、`/p/` 预览（200）；历史客户端使用的 `mission-work/modeling_state.json` 下载路径经兼容层仍可解析（200）。
- 两服务日志无 traceback/路径/符号链接错误；本体可视化仍读取任务 `output/` 产物。

### 部署与线上验证（动作生产接入与环形布局后台预计算）

- 已提交并推送 `20260727`（commit `2372291`）；服务器 `git pull --ff-only` 到同一 commit，部署前确认 47313/47314 均无 WORKING/QUEUED/ANALYZING/VALIDATING 任务（47313 仅 idle/error/blocked，47314 仅 BLOCKED/FAILED/INPUT_READY）。
- 47313 经 `scripts/deploy_server.sh` 重启，pid `1668573`；47314 经 `scripts/run_standalone_modeling.sh` 重启，pid `1669964`。
- 两服务 `/` 与 `/health` 均 200；`activeRuns=0`、`queuedRuns=0`；`providerInUse/databaseInUse=0`；`coordination` 如实报告 backend=file、quotaScope=process、queueScope=process、multiHostSafe=false。
- 线上 HTML 已加载新 bundle：`frontend/dist/assets/index-Cogll0Y3.js`、`index-D7obonjB.css`、`ui-Bb9cGRad.js`（47313/47314 一致）；懒加载的 `OntologySigmaPreview-BjlhtHl4.js` 两服务均 200，且主 bundle 已包含“关系聚类可视化”“语义环形可视化”及两个布局说明文案。
- 两服务日志无 traceback/error/exception；部署前备份目录 `backup-pre-2026-08-27-111442/`、run 索引与任务数据均未改动。

### 本体建模 CSV 上传门禁修复：规范化、门禁分离与语义非阻断完成

修复 47313“上传到 MinIO”对本体建模 CSV 的错误拦截：`entity_relations.csv` 历史兼容字段名称被误报“期望16列、实际16列”；`logical_entities.csv` 业务对象编码为空的逻辑实体因缺少内部审计归属状态被上传门禁拒绝；中文名称含 ID/PDF 等英文缩写被误拒；英文关系分类被误拒；语义校验问题错误地禁用了“完成”按钮。

- 表头与受控值规范化（集中式契约）：`modeling_csv_contract.py` 新增 `HEADER_ALIASES`、`RELATION_CATEGORY_ALIASES` 与 `enum_aliases` 契约配置，以及 `normalize_header_cell/normalize_csv_header/normalize_enum_value/normalize_csv_blob/header_mismatch_messages` 纯函数。规范化顺序：UTF-8 BOM（`utf-8-sig`）→ 首尾空白/零宽字符清理 → 已登记表头别名映射 → 受控枚举别名映射 → 与正式契约比较。`entity_relations.csv` 登记历史等价表头别名 `源关联属性编码→源业务属性编码`、`目标关联属性编码→目标业务属性编码`；`关系分类` 登记英文枚举别名 `COMPOSITION→组合`、`AGGREGATION→聚合`、`EXTENSION/INHERITANCE→继承`、`REFERENCE/ASSOCIATION→关联`、`DEPENDENCY/TRANSFORMATION→依赖`（大小写与首尾空白兼容，未知英文值仍拒绝）。`CSV_NORMALIZATION_VERSION`（与既有 `HEADER_NORMALIZATION_VERSION` 同值兼容）记录规范化契约版本，完成门禁按同版本重放规范化后比较哈希，旧上传记录保持可读。
- 中文名称规则：所有声明为 `chinese_name` 的字段（业务对象名称、逻辑实体名称、业务属性名称、关系中文名称、规则名称、指标名称、动作名称、术语名称等）统一要求包含至少一个中文字符，允许混用英文缩写/数字/常用标点（如 `源头单据ID`、`税行ID`、`财报PDF文档`、`财报PDF数据行`、`API调用记录`、`B2B订单`、`2D图纸`、`3D模型`）；纯英文、纯数字或纯符号被拒绝并提示“未包含中文字符；该字段为中文名称，纯英文内容应填写到对应英文名称字段”。不再提示“中文名称不能混入英文字母”。
- 表头错误信息：不再只显示“期望 N 列、实际 N 列”，改为逐列指出 `第 N 列期望“X”，实际为“Y”`、缺失字段、未知字段；字段集合正确但顺序错误时明确报告“字段顺序不符合模板”。
- 上传对象规范化：`/api/minio/upload` 对建模 CSV 先在内存中把表头与受控字段值规范化为正式标准内容，MinIO 对象与响应 `sha256` 均对应规范化后的 blob（本地原文件保留英文关系分类与旧表头不被覆盖）；本地原文件不被静默覆盖；历史任务原 CSV 不修改。
- 上传/完成门禁分离：`validate_row_contract` 使用 `ValidationPhase.UPLOAD/FINALIZE/COMPLETION` 阶段；上传阶段（`validate_modeling_upload_artifact_detailed`）只执行文件自身的确定性结构规则，不再读取 `work/modeling_state.json` 或决策审计。`logical_entities.csv` 空业务对象编码 + 空名称 + 主标志 `N` 可独立上传；空编码+非空名称、空编码+主标志 `Y`、编码存在但名称为空、主标志非法、编码重复仍在上传阶段拒绝。
- 多行逐行校验修复：`validate_row_contract` 原先 required 循环遍历全部行，但 boolean/enum/整数/编码/中文名/英文标识/JSON/范围等规则在循环外使用泄漏的 `row/line_no`，只检查最后一个数据行。已重构为单一逐行循环执行全部单行规则，跨行规则（唯一性、主逻辑实体数量、页面显示、跨文件引用）独立聚合；空白行与行宽错误行不参与单行校验且不误判后续行。中英文混合名称与英文关系分类兼容在任意行位置生效，新增第一行/中间行非法值、多行错误行号、空 BO+主标志 `Y` 位于首行等回归测试。
- 规范化上传双哈希完成校验：上传记录保存 `sha256`（实际上传规范化 blob）、`sourceSha256`（本地原始文件）、`normalized`、`normalizationVersion`；完成门禁对规范化记录以相同契约版本重新规范化当前本地文件后比较 `sha256`，历史兼容表头/英文关系分类上传后可正常完成，上传后修改数据、改成未知表头或未登记枚举会被发现；旧记录只有 `sha256` 时保持原始哈希语义，版本不匹配时 fail-closed 要求重新上传。
- 空上下文防护：`Task.set_mission_context` 对规范化后仍为空的上下文直接返回，不再写入空指纹的 `modeling_state.json`，避免任务在拿到第一个真实 execution-context 时把当前状态归档并误删 `validation_report.json`；`validation_report.json` 作为非阻断 warnings 在任何上传/完成流程中保持可读。
- 语义校验改为非阻断 warnings：`completionReady` 与完成回调不再因 `semantic_validation_status != PASSED`、R1–R5 证据不足、`NOT_APPLICABLE` 缺证据、`UNRESOLVED` 未确认、决策审计覆盖率不足等语义/治理问题拒绝完成。这些问题继续保存在 `validation_report.json`、决策审计与 `modeling_state.json`，通过 `completionWarnings`/`completionHint` 提示，用户确认后仍发送 `SUCCESS`，本地记录 `completedWithWarnings`（不伪造 PASSED、不删除报告）。
- completionReady 单一权威：新增 `completion_readiness(task, gate_error=None)` 返回 `{"ready", "blockers", "warnings"}`，`completion_ready_for_task` 为其布尔形式。确定性阻断（任务执行中/排队、活动 execution、FAILED/CANCELLED、expectedFiles 为空或上下文无效、文件缺失或上传记录不完整、本地内容与已上传对象不一致、对象不在可信 outputPrefix、parseElements 与 expectedFiles 契约不一致）控制按钮与完成回调；语义问题只进入 warnings。`Task.summary()` 默认调用该函数并附带 `completionWarnings`，`/api/minio/upload` 在跑完完整完成门禁后用同一结果同时写入外层 `completionReady` 与 `task.summary(completion_ready=...)`，二者永不矛盾。前端合并 `result.task` 时以服务端外层最终值为准，外层 `false` 不会被内层 `true` 覆盖；点击完成时若存在 warnings 先显示非阻断确认（确认后直接完成，不要求修复或重新上传）。
- 上传提示更新：全部 `expectedFiles` 上传成功且哈希一致时提示“结果已上传，可以点击‘完成’确认任务。”；存在语义校验提示时提示“结果已上传，可以点击‘完成’；当前仍有建模校验提示，可在校验报告中查看。”；不再出现“修复后确认无误再点击‘完成’”。
- MinIO 逐文件结果：每个 `results` 项含 `name/ok/stage/code/error`，成功项 `stage=STORAGE`；格式失败 `stage=STRUCTURAL_VALIDATION`（表头 `UPLOAD_ARTIFACT_HEADER_INVALID`、行 `UPLOAD_ARTIFACT_ROW_INVALID`、白名单外 `UPLOAD_ARTIFACT_NOT_ALLOWED`），文件缺失/读取失败 `UPLOAD_CONTEXT_UNAVAILABLE`，对象存储异常 `UPLOAD_STORAGE_FAILED`；部分文件失败时其他合法文件继续上传，全部失败才返回顶层 422，不再把格式校验失败描述成 MinIO 网络失败。全部文件通过结构校验但对象存储全部失败时返回顶层 502 且 `code=UPLOAD_STORAGE_FAILED`、`ok=false`，同时保留逐文件 `results`。
- 前端：`uploadToMinio` 无论是否有顶层 `error` 都展示 `results` 逐文件原因；新增“上传结果明细”Modal（`stage`/`code` 标签 + 完整错误 `pre`）用于长错误；新上传前清理旧明细，全部成功时关闭 Modal，列表 key 使用 name+index；明确区分上传前格式校验失败、任务状态冲突、execution-context 失败、对象存储失败与上传成功但存在语义提示。
- 文档：`API/backend-agent-interaction-api.md` 与 `API/本体MAL层API.md` 明确各正式结果文件可独立上传、上传阶段只做结构校验、中文名称只需含中文字符、关系分类英文别名规范化为中文、完成门禁负责上传完整性与哈希一致性、语义校验作为非阻断 warnings、`completionReady` 新定义与逐文件 `stage/code` 契约。

主要文件：
- `open-claude/open_claude/modeling_csv_contract.py`：`HEADER_ALIASES`、`RELATION_CATEGORY_ALIASES`、`enum_aliases`、`CSV_NORMALIZATION_VERSION`、`normalize_enum_value`、表头/受控值规范化、`ValidationPhase`、中文名称与枚举逐行规则、上传阶段 LE 文件内规则。
- `open-claude/oc_codex_server.py`：`validate_modeling_csv/validate_integration_csv/validate_modeling_upload_artifact(_detailed)`、上传错误码常量、`/api/minio/upload` 逐文件 `stage/code` 与规范化 blob 上传、`completion_readiness` 统一完成可用性（ready/blockers/warnings）、`build_completed_callback_payload` 语义非阻断与双哈希完成校验、`Task.summary` 增加 `completionWarnings`、存储全失败 502、`modeling_upload_dependency_errors` 不再依赖语义标记。
- `frontend/src/main.jsx` 与 `frontend/src/styles.css`：上传提示更新、逐文件错误展示与上传结果明细 Modal、完成前非阻断确认（`Modal.confirm`）。
- 新增/更新 `tests/test_upload_gate_separation.py`（88 项：表头规范化、多行逐行校验、LE 上传规则、双哈希完成校验、中英文混合名称、英文关系分类规范化、完成策略与语义非阻断、completionReady 一致性、用户实际文件组合、空上下文不误删校验报告、MinIO API 行为、前端契约）；`tests/test_modeling_csv_contract.py` 中文名称规则更新；`tests/test_ontology_knowledge.py` 假任务 `summary()` 兼容新签名。

### 本体可视化运行时错误隔离（47313/47314 useCallback 漏导入修复）

47314 点击“本体可视化”后整页空白、47313 入口存在同类风险的根因：`frontend/src/main.jsx` 顶部 React 导入缺少 `useCallback`，而 `OntologyTreePreview` 的 `ensureRadialReady` 使用它；首次渲染时抛出 `ReferenceError: useCallback is not defined`，异常发生在组件自身 render/hook 初始化阶段，原 `OntologyPreviewErrorBoundary` 只包裹 `OntologySigmaPreview` 无法捕获，异常继续传播到 React 根节点导致整页卸载。

- `useCallback` 导入修复：React 导入补上 `useCallback`（`useEffect/useLayoutEffect/useMemo/useRef/useState/useCallback`），保持既有 hooks 导入风格，不使用 `React.useCallback` 混用。
- 外层可视化错误隔离：47313（工作台文件面板）与 47314（独立建模页）两处预览 Modal 中的 `<OntologyTreePreview>` 整体包在 `<OntologyPreviewErrorBoundary resetKey={ontologyPreviewResetKey(preview.ontologyGraph)} message="本体可视化加载失败，请关闭后重试">` 内。渲染异常、hooks 初始化异常、图层筛选/布局选择器异常、Sigma/ECharts 初始化异常、图数据异常、ResizeObserver 异常与 `React.lazy` 加载异常都只影响预览卡片，页面侧栏、历史运行、会话内容、文件面板、输入框与 Modal 关闭按钮保留；错误后关闭 Modal 可再次打开，`resetKey` 随图数据（节点/连线数量 + 可用层级）变化可重试。
- 既有保护不回退：内部 Sigma ErrorBoundary 默认文案“关系布局加载失败，请稍后重试”保留；`OntologySigmaPreview` 保持 `React.lazy` + `React.Suspense` 懒加载；默认关系聚类可视化、后台环形布局预计算、五层筛选、布局下拉框、全屏与平移缩放均不变。
- `drawStandaloneOntology` 既有 try/catch 保留：CSV 读取/解析/构图失败时 `setError`，`selectedRunIdRef` 变化后不再写入旧 run 状态，`finally` 关闭绘制状态；React 渲染异常统一交给外层 ErrorBoundary。
- 测试：新增 `frontend/tests/hooksContract.test.mjs`（静态 hooks 契约：文件中使用的 React hooks ⊆ 导入集合、`useCallback` 导入并使用、无 `React.useXxx` 混用、47313/47314 两处 Modal 均被外层 ErrorBoundary 包裹、Sigma 懒加载与 Suspense 保留）。新增 `frontend/tests/ontologyPreviewRuntime.test.mjs`（Vite SSR 真实加载 `main.jsx` 渲染 `OntologyTreePreview`，复现修复前 `useCallback is not defined`、修复后正常渲染，覆盖仅 LE/BO+LE/LE+属性/五层/空数据等数据形态；`react-test-renderer` 验证外层 ErrorBoundary 局部占位、页面外壳与历史运行保留、`resetKey` 重试、卸载后重开、默认与自定义文案、`onError` 回调）。新增 devDependency `react-test-renderer@18.3.1`（与 react 18.3.1 匹配）与 `frontend/tests/fixtures/react-dom-client-stub.mjs`（Vite SSR 加载时桩掉 `createRoot` 启动入口，不新建任何隐藏 DOM）。`tests/test_frontend_contract.py` 预览契约断言更新为外层边界包裹结构并校验两处入口。

主要文件：`frontend/src/main.jsx`、`frontend/package.json`、`frontend/package-lock.json`、`frontend/tests/hooksContract.test.mjs`、`frontend/tests/ontologyPreviewRuntime.test.mjs`、`frontend/tests/fixtures/react-dom-client-stub.mjs`、`tests/test_frontend_contract.py`；`frontend/dist` 重新构建。

验证结果：
- 全量 `pytest tests`：664 passed / 13 skipped / 445 subtests；`py_compile` 通过；Node 测试 60/60（原 47 + 新增 13）；`npm run build` 成功（仅既有大 chunk 提示）；`git diff --check` 通过。
- 发布：本批改动仅完成本地修改与验证，未部署、未 SSH、未重启 47313/47314、未 commit/push；服务器任务、run、数据库与用户产物未修改。

### 自动确认修复：202 后台执行的审批自动放行

修复 47313“自动确认已开启，但任务仍等待用户点击允许执行”：HTTP 202 后台执行只通过 `/api/tasks/:id/events` 绝对游标轮询回传事件，旧的自动确认只挂在 SSE `consume` 分支，`pollTaskEvents` 仅合并事件不调用 `/approve`；且 `openTask`/`toggleAutoApprove` 用 `find(approval_request)` 找第一条请求，未排除已存在 `approval_result` 的历史请求，可能确认过期请求而漏掉真正挂起的新请求。

- 统一未决审批识别：`frontend/src/eventSync.js` 新增纯函数 `unresolvedApprovalRequests(events)`（收集 `approval_result` id 去重、过滤无 id 请求、按 seq 稳定排序、只返回无对应结果的请求）与 `approvalsNeedingAutoApprove({events, freshEvents, autoApprove, pendingApproval, inFlightIds})`（仅当自动确认开启，且请求属于“本窗口新到达”或“与服务端 `pendingApproval.id` 匹配”，并跳过 in-flight id）。轮询、刷新恢复、重开历史会话、动态开启开关统一使用该函数，服务端 `pendingApproval` 为最终权威，绝不确认历史已完成会话里的孤立旧请求。
- 前端轮询与开关：`pollTaskEvents` 用 `eventsRef.current` 与 delta 合并后即按上述规则逐个 `approve(id, true, task)`，同一 id 由 `approvalInFlightRef` 保证只有一个在途确认，400“请求已过期”按幂等竞争静默处理；`openTask` 不再找第一条请求，并按 `current.autoApprove` 恢复开关与批准服务端仍挂起的请求；`toggleAutoApprove` 同时调用服务端 `/auto-approve`；`sendToTask` 的 `/send` body 增加 `autoApprove`；`approve()` 成功响应不再本地合成 `approval_result`，正式结果统一由服务端经 SSE/轮询返回（带稳定 seq），避免重复结果事件。
- 服务端 execution 级自动确认：`Task` 新增任务级持久默认 `auto_approve` 与仅本次 execution 生效的 `_execution_auto_approve`；`stream_turn`/`_TaskExecutionAdapter.register` 透传 `auto_approve`；`_web_prompt_user` 记录 `approval_request` 后若本次 execution 或任务级已启用自动确认，立即记录 `approval_result {approved:true, automatic:true}` 并直接放行，不 `Event.wait()`；人工/超时结果的 `approval_result` 补充 `automatic:false`，审计事件完整保留。
- 幂等与竞态：新增 `_resolve_approval(req_id, approved, automatic)`（对同一 `_last_approval_id` 幂等，正式 `approval_result` 只由 worker 记录，最终每个审批 id 至多一个结果）；`auto_approve_current()` 放行当前挂起审批；超时与批准竞争下结果唯一；审批绑定 execution，旧 execution 的审批不能批准新 execution 的工具。
- 动态开关接口：新增 `POST /api/tasks/:id/auto-approve`（任务所有权鉴权），开启时立即放行当前挂起审批，关闭后恢复人工等待，已批准的工具调用不回滚；`Task.summary()` 与 `/events` 响应增加 `autoApprove`、`pendingApproval`（仅 `id/tool/summary`，不泄露敏感 detail）；`persist_tasks`/`restore_tasks` 持久化任务级 `autoApprove`，重启后按任务恢复。
- 47314 检查：`standalone_modeling_server.py` 权限模式为 `always_allow`、无人工审批通道，不需要自动确认改动，未修改。
- 测试：新增 `frontend/tests/eventApproval.test.mjs`（14 项：`unresolvedApprovalRequests` 未决/已处理/部分处理/重复 id/无 id/排序/跨 run 边界，`approvalsNeedingAutoApprove` 轮询触发/下一轮不重复/in-flight 跳过/关闭不批/刷新恢复/历史过期不批）；`tests/test_tasks.py` 新增 `AutoApproveFlowTests`（11 项：execution 级自动放行与审计、任务级默认、人工等待、超时唯一结果、幂等、`auto_approve_current`、summary 安全字段、`/auto-approve` 开启放行/关闭恢复、用户/任务隔离、重启持久化）；`tests/test_frontend_contract.py` 更新轮询合并与统一审批识别契约断言。
- 主要文件：`frontend/src/eventSync.js`、`frontend/src/main.jsx`、`open-claude/oc_codex_server.py`、`tests/test_frontend_contract.py`、`tests/test_tasks.py`、`frontend/tests/eventApproval.test.mjs`；`frontend/dist` 重新构建。

验证结果：
- 指定四文件 `pytest`：202 passed / 16 subtests；`py_compile` 通过（`oc_codex_server.py`、`standalone_modeling_server.py`）；Node 测试 74/74；`npm run build` 成功（仅既有大 chunk 提示）；`git diff --check` 通过。
- 发布：本批改动仅完成本地修改与验证，未部署、未 SSH、未重启 47313/47314、未 commit/push；服务器任务、run、数据库、MinIO 与用户产物未修改。

### 模型传输/协议错误改为本地可重试暂停

- 建模任务遇到模型传输或协议类错误时仍在本地事件日志记录完整 `error` 供排查，但不再向平台回写 `FAILED`；本地任务保留可续跑的 `error` 状态，平台任务状态维持 `RUNNING`，`runResult` 记录为 `PAUSED` 与 `RECOVERABLE_PROVIDER_ERROR`，用户可在同一任务直接重试。
- DeepSeek thinking 模式的 `reasoning_content must be passed back`、工具消息链不完整、无合法 assistant content/tool_calls，以及连接中断、连接/读写/网关超时均纳入可恢复范围；余额不足、鉴权失败和普通业务 400 不纳入，仍按真实失败处理。
- 完成门禁不再仅因历史 `FAILED/CANCELLED` 平台状态阻断已经齐备且哈希一致的正式产物；活动 execution、文件缺失、上传不完整、哈希不一致等确定性问题仍然阻断。
- 服务器最新任务 `RM2092866461941178368` 的 8 个真实输出文件均已上传至 `ontology/1/modeling-tasks/RM2092866461941178368/agent-output/`；会话尾部 DeepSeek 协议 error 将在精确备份后替换为基于真实产物统计的成功输出摘要，任务本地平台状态恢复为 `RUNNING`，不修改 CSV、MinIO 对象或数据库数据。

主要文件：`open-claude/oc_codex_server.py`、`tests/test_tasks.py`、`changelog/changelog_8_27.md`。

验证结果：`pytest tests/test_tasks.py -q` 92 passed；`py_compile open-claude/oc_codex_server.py` 与 `git diff --check` 通过。部署与服务器会话修复结果见文末最终发布记录。

### 业务对象编码契约收紧：BO + 4 位流水码

完成此前只改了一半的业务对象编码收紧：正式建模产物中的 `业务对象编码` 统一为 `BO` + 4 位流水码（`^BO\d{4}$`，如 `BO0001`），不再接受任意字母开头的旧格式（如 `CO001`、`BO1`）。

- 契约生效范围：`modeling_csv_contract.py` 中 `business_objects.csv`、`logical_entities.csv`、`business_object_relations.csv`（源/目标业务对象编码）、`statuses.csv`、`actions.csv` 的 `code_pattern` 全部收紧为 `^BO\d{4}$`；逻辑实体编码、状态编码、关系编码等保持各自原有格式不变。`tests/test_modeling_csv_contract.py` 新增非法用例 `BO00001`（5 位数字）、`BO001`（3 位数字）、`CO0001`（非 BO 前缀）。
- 知识库与文档同步：`scripts/build_agent_knowledge.py` 移除“Ontology平台模型编码规范”作为任务固定参考，`CODE_STANDARD_RULES` 改为“本体元素编码契约（强制）”并写明业务对象为 `BO` + 4 位流水码、示例 `BO0005`；`agent_knowledge/*` 相关 base/all_sources 重新生成；`API/backend-agent-interaction-api.md` 写入业务对象编码规范。任务参考文件不再下发旧编码规范，历史任务的旧格式产物仍按原样保留、不做批量迁移。
- 测试夹具对齐：正式 `business_objects.csv`/`logical_entities.csv`/`business_object_relations.csv`/`statuses.csv`/`actions.csv` 夹具中的 `CO1/CO001/CO0001/BO1/BO00001/BO00002` 统一改为合法 `BO0001/BO0002/BO0003` 等，保持测试内决策候选与正式 CSV 行配对一致；决策审计候选编码（`business_object_decisions.csv`、`candidateCode`）属于中间态内部标识，不强制 BO 格式。涉及 `tests/test_gate_action_normalization.py`、`tests/test_semantic_finalize_upload_boundary.py`、`tests/test_standalone_modeling_server.py`、`tests/test_v0001_rule_registry.py`、`tests/test_modeling_reliability.py`、`tests/test_ontology_knowledge.py`。
- 主要文件：`open-claude/open_claude/modeling_csv_contract.py`、`scripts/build_agent_knowledge.py`、`agent_knowledge/*`、`API/backend-agent-interaction-api.md` 及上述测试文件。

验证结果：
- 全量 `.venv/bin/python -m pytest tests`：676 passed / 13 skipped / 448 subtests；`py_compile` 通过（服务端与全部改动测试文件）；Node 测试 74/74；`npm run build` 成功（仅既有大 chunk 提示）；`git diff --check` 通过。
- 发布：本批改动仅完成本地修改与验证，未部署、未 SSH、未重启 47313/47314、未 commit/push；服务器任务、run、数据库、MinIO 与用户产物未修改。
