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

主要文件：
- 新增 `open-claude/open_claude/action_inference.py`（动作 Sheet 解析、类型归一化、BO/LE 推断、去重、稳定排序与稳定编码纯函数）与 `agent_knowledge/动作v0.0.1.md`（专项技能）。
- `open_claude/open_claude/modeling_csv_contract.py` 注册 `actions.csv` 九字段契约（必填六项、动作类型枚举、ACT 编码格式、业务对象编码引用）。
- `open-claude/oc_codex_server.py`：`_MODELING_CONTRACT_NAMES`、`MODEL_ARTIFACT_DEFINITIONS.actionArtifact`、`build_modeling_plan.executionOrder` 增加 ACTION、文档输出契约、建模指令动作技能注入与步骤 7 约定、输出文件标签、任务参考文件名称切换到 `本体元模型模板v.0.0.1.xlsx`。
- `open_claude/open_claude/ontology_knowledge.py` 注册 ACTION 技能模块；`modeling_rule_registry.py` 注册动作契约规则号与产物类型；`modeling_reliability.py` 增加 actions.csv 业务对象引用校验。
- `scripts/build_agent_knowledge.py` 增加动作知识并重新生成 `basev0.0.1.md`、`all_sourcesv0.0.1.md`、模板知识与 `动作v0.0.1.md`；集成版（消歧整合）知识 base/模板/all_sources 同步补充动作元模型规则与 actions.csv 字段规范；`agent_knowledge` 相关 Markdown 随构建刷新。
- 集成（消歧整合）链路同步注册 `actions.csv`（`_INTEGRATION_CONTRACT_NAMES`），`merged_elements` 等元素类型枚举加入 ACTION。
- 前端 47314 独立建模页“解析要素”新增“动作”（`frontend/src/main.jsx` STANDALONE_ARTIFACTS），并重建 `frontend/dist`（新 hash bundle 替换旧 bundle）；API 文档与 SOP 同步 actions.csv 输出文件映射与参考文件名称。

验证结果：
- 全量 `pytest tests`：540 passed / 13 skipped（10 项 Redis 集成无 `ONTOLOGY_TEST_REDIS_URL`、3 项平台沙箱）/ 368 subtests。
- 新增 `tests/test_action_inference.py`（27 项：BO/LE 动作生成、明确证据优先、去重稳定编码、九字段输出、任务隔离）与 actions.csv 契约/引用用例；更新 `tests/test_ontology_knowledge.py`、`tests/test_modeling_csv_contract.py`（含集成版输出契约覆盖 actions.csv）。
- `python -m py_compile` 全部改动 Python 文件通过；`git diff --check` 通过；前端 `npm run build` 成功（仅既有大 chunk 警告，`frontend/dist` 已随解析要素新增动作重建为新 hash bundle）；前端 Node 测试 32/33 通过，1 项“仓库真实五层输出”需本地 `frontend/output/*.csv` 夹具（gitignore 数据目录，当前工作区不存在，与本次改动无关）。
- 未部署、未 SSH、未重启、未 commit、未 push。

### 本体可视化预览：统一布局选择交互

将本体可视化预览卡片的布局切换收敛为右上角统一“布局”下拉框，删除旧的左侧“环形图/网络图”页签与右侧“重新布局 / ForceAtlas2”常驻入口，保留两种布局能力并统一命名与提示文案。

- 布局下拉框仅两项：`关系聚类可视化`（对应 ForceAtlas2/网络图）与 `语义环形可视化`（对应径向语义分层图）；选项悬浮提示分别为“ForceAtlas2 是一种先进的力导向图布局”和“按照业务对象、逻辑实体、业务属性等语义层级，由内向外分层排列节点”，下拉框旁信息图标始终展示当前布局说明。
- 打开预览默认优先展示关系聚类可视化（Sigma/ForceAtlas2）；语义环形布局（ECharts）不在首次打开时初始化，仍通过 `requestIdleCallback` 后台预载 echarts 资源，切换时若未就绪显示统一加载态，完成后自动 fit，不再需要独立“重新布局”按钮。
- 切换布局真正重建对应布局结果：`draftLayers` 变更不触发重算，点击图层筛选“确认”后按 `appliedLayers` 作为布局缓存 key（`radial:`/`network:` 前缀）重建并自动 fit；全屏/退出全屏保持布局选择状态。
- 布局加载失败时保留上一次成功布局、恢复下拉框为上一次有效选项并显示错误提示（ErrorBoundary 兜底），避免空白画布。
- 工具栏改为一行排列：布局选择器 + 图层筛选图标，与全屏/退出全屏、关闭按钮保持同一行；新增 `.ontology-toolbar`、`.ontology-layout-selector`、`.ontology-layout-error`、`.ontology-tree-loading-overlay` 样式，移除 `.ontology-view-switch`、`.ontology-sigma-actions` 样式。

主要文件：
- `frontend/src/main.jsx`：`OntologyTreePreview` 改由 `layoutMode`（network/radial，默认 network）驱动，新增 `OntologyLayoutSelector`、`OntologyPreviewErrorBoundary`；`OntologyEChartsPreview` 增加加载态与失败回退。
- 新增 `frontend/src/ontologyLayoutOptions.js`（两个布局选项的 value/名称/提示纯常量与查询函数）与 `frontend/tests/ontologyLayoutOptions.test.mjs`。
- `frontend/src/OntologySigmaPreview.jsx`：删除 ForceAtlas2 常驻文字、重新布局按钮及 `layoutVersion/layoutRunning` 状态。
- `frontend/src/styles.css`：统一工具栏布局与布局选择器样式；`tests/test_frontend_contract.py` 更新旧入口断言并新增 `test_ontology_preview_unified_layout_selector`。
- 重建 `frontend/dist`（新 hash bundle 替换旧 bundle）。

验证结果：
- 前端 Node 测试 `node --test 'tests/*.test.mjs'`：35 项中 34 通过，1 项仍为既有“仓库真实五层输出”夹具缺失（`frontend/output/*.csv` 为 gitignore 数据目录，与本次改动无关）。
- `pytest tests/test_frontend_contract.py`：13 passed；`pytest tests/test_tasks.py tests/test_standalone_modeling_server.py`：137 passed + 16 subtests。
- `npm run build` 成功（仅既有大 chunk 警告）；`git diff --check` 通过。
- 未部署、未 SSH、未重启、未 commit、未 push。

### 运行工作区统一命名：input/work/output 与仓库根遗留迁移

将任务/run 运行工作区正式命名从 `mission-input/mission-work/mission-output` 统一为 `input/work/output`，完成仓库根遗留 ad-hoc 工作区的识别、迁移、校验与本地清理，并为 47313/47314 增加防仓库根再成为工作区的边界保护。

- 遗留归属识别：本地根目录 `input/`（空）、`work/`（26 文件，含 `modeling_state.json`/`state_full.json`/`schema_extract.json` 及决策审计 CSV）与 `output/`（7 个正式 CSV）共 33 文件、7,504,414 B；`mission-input→input`、`mission-work→work`、`mission-output→output` 为符号链接。`modeling_state.json` 的 `identity` 中 `repositoryId/taskCode` 均为空、`inputFingerprint`（`73d71db2...`）与服务器全部 47313 任务及 47314 run 的 modeling_state 与 output CSV 哈希均不匹配，判定为无主 ad-hoc 遗留，不并入任何正式任务/run。
- 迁移与校验：已 rsync 至服务器独立恢复归档 `open-claude/sandbox/recovered-workspaces/repo-root-legacy-2026-08-27/`（含 `migration-manifest.json`、`checksums.sha256`、`verify.out`、`MIGRATION_COMPLETE`）；服务器 `sha256sum -c` 33/33 全部成功、0 失败，本地与服务器逐文件哈希、文件数（33）与总字节（7,504,414）一致。
- 本地清理：将仓库根六个精确目标（`input`、`work`、`output` 及三个 `mission-*` 符号链接）移至 `~/Trash/ontology-agent-legacy-workspaces-2026-08-27/`（可恢复），未使用 glob 或未验证变量；`ls -ld` 复核六路径均不存在，`git status` 无遗留运行目录。
- 命名统一：新增集中式路径兼容模块 `open-claude/open_claude/workspace_paths.py`（`input_dir/work_dir/output_dir` canonical 优先、legacy 只读回退；`ensure_workspace_dirs` 只创建 canonical；`normalize_relpath/resolve_workspace_path/validate_task_workspace`）。旧路径仅允许存在于该集中式兼容层、历史 run 数据与兼容测试。
- 47313 改造：`oc_codex_server.py` 新任务只创建 `input/work/output`；上传、下载、预览、文件列表、MinIO 上传、数据库 helper、文档 bundle、参考文件、Agent 提示词（建模/文档/数据库/输出指令）、`agentOutputDirectory=output`、`agentIntermediateDirectory=work` 全部改用 canonical；`task_workspace_path/create_task` 增加 `_validate_task_workspace` 边界校验（拒绝空路径、仓库根、源码目录、HOME、sandbox 数据根自身、相对/symlink 逃逸）；`list_project_files` 返回统一逻辑路径并对历史任务做 `mission-*→canonical` 展示映射。
- 47314 改造：`standalone_modeling_server.py` 新 run 不再创建 `mission-*` 符号链接，只创建 `input/work/output`；`LEGACY_ALIASES` 保留为集中式只读兼容解析；默认建模提示词与数据库 schema 指令改用 `input/`、`work/`；文件 API 只返回 canonical 逻辑路径。
- 建模引擎与前端：`modeling_reliability.py`、`document_parser.py` 改用 workspace_paths；前端文件树分组显示“输入/工作/输出”，`main.jsx` 的 `mission-output/` 产物匹配改为 `output/`；API 文档、SOP、`agent_knowledge/**` 活动规范与 `scripts/build_agent_knowledge.py` 提示词全部去除 `mission-*`（历史 changelog 不改）。
- 新增 `tests/test_workspace_paths.py`（15 项：仓库根/源码目录/HOME/空路径/相对与符号链接逃逸拒绝、合法任务目录可用、canonical 优先与 legacy 只读回退、新写入只进 canonical、47313/47314 新任务只创建 input/work/output）；重写 `tests/test_task_workspace_files.py`（canonical 列表、legacy 逻辑路径映射、双布局共存 canonical 优先）；更新 `test_sandbox_security.py`、`test_semantic_finalize_upload_boundary.py`、`test_modeling_csv_contract.py`、`test_modeling_reliability.py`、`test_database_modeling_evidence.py`、`test_document_parser.py`、`test_credential_crypto.py`、`test_ontology_knowledge.py`、`test_standalone_modeling_server.py`、`test_frontend_contract.py`、`test_v0001_rule_registry.py` 至 canonical 契约。
- 验证结果：全量 `pytest tests` 558 passed / 13 skipped / 371 subtests；`py_compile` 全部改动 Python 文件通过；`npm run build` 成功（仅既有大 chunk 警告，新 hash bundle 已生成）；`git diff --check` 通过。
