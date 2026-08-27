# 20260827 变更记录

> 本文档记录 `20260727` 分支在 2026-08-27 的变更。

## 维护规则

- 每次完成代码、配置、规则、文档、部署脚本、构建产物或测试修改后，自动同步本记录，无需再次提醒。
- 当天记录按功能最终状态组织：结合累计 diff 合并中间修改，修订过时描述，删除重复或已被后续实现取代的内容，只保留最终用户可见行为、重要内部契约、主要文件和最终验证结果。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314；部署前确认无活跃或排队任务，部署后确认两服务 `/`、`/health` 均为 200，并检查线上资源与启动日志。
- 历史 changelog（`changelog_8_26.md` 及更早）不再修改；昨日遗留事项如在今天继续处理，在本记录中按今天的最终状态归纳。

## 2026-08-27

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

### 本体建模 CSV 上传门禁修复：表头规范化与上传/完成门禁分离

修复 47313“上传到 MinIO”对本体建模 CSV 的两类错误拦截：`entity_relations.csv` 历史兼容字段名称被误报“期望16列、实际16列”；`logical_entities.csv` 业务对象编码为空的逻辑实体因缺少内部审计归属状态被上传门禁拒绝。

- 表头规范化（集中式）：在 `modeling_csv_contract.py` 新增 `HEADER_ALIASES` 契约配置与 `normalize_header_cell/normalize_csv_header/normalize_csv_blob/header_mismatch_messages` 纯函数。顺序为 UTF-8 BOM（`utf-8-sig`）→ 首尾空白/零宽字符清理 → 已登记兼容别名映射 → 与正式字段比较；未知字段、错误顺序、少列/多列仍拒绝。`entity_relations.csv` 登记历史等价别名 `源关联属性编码→源业务属性编码`、`目标关联属性编码→目标业务属性编码`。
- 表头错误信息：不再只显示“期望 N 列、实际 N 列”，改为逐列指出 `第 N 列期望“X”，实际为“Y”`、缺失字段、未知字段；字段集合正确但顺序错误时明确报告“字段顺序不符合模板”。
- 上传对象规范化：`/api/minio/upload` 对建模 CSV 先在内存中规范化为正式表头，MinIO 对象与响应 `sha256` 均对应规范化后的 blob；本地原始文件不被静默覆盖；历史任务原 CSV 不修改。
- 上传/完成门禁分离：`validate_row_contract` 新增 `ValidationPhase.UPLOAD/FINALIZE/COMPLETION` 阶段；上传阶段（`validate_modeling_upload_artifact_detailed`）只执行文件自身的确定性结构规则，不再读取 `work/modeling_state.json` 或决策审计。`logical_entities.csv` 空业务对象编码 + 空名称 + 主标志 `N` 可独立上传；空编码+非空名称、空编码+主标志 `Y`、编码存在但名称为空、主标志非法、编码重复仍在上传阶段拒绝。完成门禁保留归属审计（`ASSIGNED`/`NOT_APPLICABLE`/`UNRESOLVED`）、跨文件引用、R1–R5、决策审计覆盖率等语义检查；上传成功但完成门禁未通过时 `completionReady=false`、`completionCode=UPLOAD_COMPLETION_GATE_PENDING`，禁止发送 `SUCCESS`。
- 多行逐行校验修复：`validate_row_contract` 原先 required 循环遍历全部行，但 boolean/enum/整数/编码/中文名/英文标识/JSON/范围等规则在循环外使用泄漏的 `row/line_no`，只检查最后一个数据行。已重构为单一逐行循环执行全部单行规则，跨行规则（唯一性、主逻辑实体数量、页面显示、跨文件引用）独立聚合；空白行与行宽错误行不参与单行校验且不误判后续行。新增第一行/中间行非法值、多行错误行号、空 BO+主标志 `Y` 位于首行等回归测试。
- 规范化上传双哈希完成校验：上传记录保存 `sha256`（实际上传规范化 blob）、`sourceSha256`（本地原始文件）、`normalized`、`normalizationVersion`；完成门禁对规范化记录以相同契约版本重新规范化当前本地文件后比较 `sha256`，历史兼容表头上传后可正常完成，上传后修改数据或改成未知表头会被发现；旧记录只有 `sha256` 时保持原始哈希语义。`HEADER_NORMALIZATION_VERSION` 记录规范化契约版本，版本不匹配时 fail-closed 要求重新上传。
- completionReady 单一权威：新增 `completion_ready_for_task(task, gate_error=None)`，同时考虑上传完整性、任务状态（执行中/已完成/失败/阻断）与建模语义校验持久化标记；`Task.summary()` 默认调用该函数，`/api/minio/upload` 在跑完完整完成门禁后用同一结果同时写入外层 `completionReady` 与 `task.summary(completion_ready=...)`，二者永不矛盾。前端合并 `result.task` 时以服务端外层最终值为准，外层 `false` 不会被内层 `true` 覆盖；新上传开始前清理旧明细，全部成功时关闭 Modal，列表 key 使用 name+index。
- MinIO 逐文件结果：每个 `results` 项含 `name/ok/stage/code/error`，成功项 `stage=STORAGE`；格式失败 `stage=STRUCTURAL_VALIDATION`（表头 `UPLOAD_ARTIFACT_HEADER_INVALID`、行 `UPLOAD_ARTIFACT_ROW_INVALID`、白名单外 `UPLOAD_ARTIFACT_NOT_ALLOWED`），文件缺失/读取失败 `UPLOAD_CONTEXT_UNAVAILABLE`，对象存储异常 `UPLOAD_STORAGE_FAILED`；部分文件失败时其他合法文件继续上传，全部失败才返回顶层 422，不再把格式校验失败描述成 MinIO 网络失败。
- 存储全失败状态：全部文件通过结构校验但对象存储全部失败时返回顶层 502 且 `code=UPLOAD_STORAGE_FAILED`、`ok=false`，同时保留逐文件 `results`，不再以 200 静默成功。
- 前端：`uploadToMinio` 无论是否有顶层 `error` 都展示 `results` 逐文件原因；新增“上传结果明细”Modal（`stage`/`code` 标签 + 完整错误 `pre`）用于长错误；明确区分上传前校验失败、对象存储失败、上传成功但完成门禁未通过，并新增 `.upload-issue-*` 样式。
- 文档：`API/backend-agent-interaction-api.md` 与 `API/本体MAL层API.md` 明确各正式结果文件可独立上传、上传阶段只做结构校验、完成阶段执行跨文件/审计/语义门禁、历史关系字段别名兼容、上传成功不代表可完成、`completionReady` 语义与逐文件 `stage/code` 契约。

主要文件：
- `open-claude/open_claude/modeling_csv_contract.py`：`HEADER_ALIASES`、表头规范化、`ValidationPhase`、上传阶段 LE 文件内规则。
- `open-claude/oc_codex_server.py`：`validate_modeling_csv/validate_integration_csv/validate_modeling_upload_artifact(_detailed)`、上传错误码常量、`/api/minio/upload` 逐文件 `stage/code` 与规范化 blob 上传、`_cached_task_artifacts_complete` 改用 UPLOAD 阶段、`completion_ready_for_task` 统一完成可用性、完成门禁双哈希校验、存储全失败 502。
- `frontend/src/main.jsx` 与 `frontend/src/styles.css`：逐文件错误展示与上传结果明细 Modal。
- 新增/更新 `tests/test_upload_gate_separation.py`（63 项：表头规范化、多行逐行校验、LE 上传规则、双哈希完成校验、completionReady 一致性、用户两个实际场景、MinIO API 行为、前端契约）；`tests/test_ontology_knowledge.py` 假任务 `summary()` 兼容新签名。

验证结果：
- 全量 `pytest tests`：639 passed / 13 skipped / 371 subtests；`py_compile` 改动 Python 文件通过；Node 测试 47/47；`npm run build` 成功（仅既有大 chunk 提示）；`git diff --check` 通过。
- 发布：改动以 commit `0776364` 提交并推送 `20260727`，服务器快进到同一提交；发布前 47313/47314 均无活动或排队任务。47313 经 `scripts/deploy_server.sh` 重启为 pid `2639630`，47314 重启为 pid `2639894`；两服务部署后健康检查均通过，任务、run、数据库与历史用户产物未修改。
