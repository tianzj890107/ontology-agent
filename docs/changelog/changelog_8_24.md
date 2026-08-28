# 20260824 变更记录

> 本文档记录 `20260727` 分支在 2026-08-24 的变更。

## 维护规则

- 每次功能修改后，在本记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314（部署前确认无活跃任务），两服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。
- 本周周报已基于 `changelog_8_17_21.md` 与日报规范生成并输出（文本，未落文件）。

## 2026-08-24

### 1. Git 部署线路问题处理（本地推送 / 服务器拉取）

- 本地 git push 直连 `github.com` 失败（SSH 解析/路由需走 `127.0.0.1:7890` 代理，直连超时）；改用 GitHub SSH-over-443（`ssh.github.com:443`）+ `nc -X connect -x 127.0.0.1:7890` 代理成功推送，无需修改 remote。
- 服务器 `git fetch` 受 `https_proxy=http://172.16.10.34:7890` 影响 TLS 握手失败；绕过代理直连后 fetch/merge 正常，服务器 HEAD 与 `origin/20260727` 同步为 `413c221`。
- 两服务运行代码不受影响（本次仅 changelog/运维动作），`/health` 保持 200。
- 主要文件：`changelog/changelog_8_24.md`。

### 2. 两个服务统一更新团队模型目录

- 47313 工作台与 47314 独立建模服务共用的团队模型目录由 8 个扩展为 24 个已验证可完成对话的模型，排除网关未路由或上游鉴权失败的 `mimo-v2-pro`、`mimo-v2-flash`、`claude-opus-4-8`、`test`。
- 两个服务的默认模型统一为 `qwen3.8-27b`；未显式配置、配置过期或无效时优先回退到该模型，仅当自定义目录不包含它时才回退到目录首项。
- 同步本地运行配置与 `.env.example`，真实团队密钥仍只保留在未提交的 `.env`；补充 24 模型数量、失败模型排除和默认模型回归测试。
- 验证：`python -m unittest tests.test_team_config` 通过（3 项）；隔离加载确认 47313/47314 均返回 24 个模型且默认 `qwen3.8-27b`；`git diff --check` 通过。完整 `tests.test_standalone_modeling_server` 因既有用例触发真实后台任务、清理阶段等待执行线程而中止，未计为通过。
- 已部署提交 `8a70629`：服务器 19 项部署相关测试通过，47313/47314 重启后健康检查均为 200，两个模型接口均返回默认 `qwen3.8-27b`、24 个模型且不含上述 4 个失败模型。依赖同步曾因服务器访问 PyPI 的 TLS 故障失败，本次无依赖变化，最终使用已通过测试的现有共享 venv 启动。
- 主要文件：`open-claude/open_claude/config.py`、`.env.example`、`open-claude/README.md`、`tests/test_team_config.py`、本地 `.env`。

### 3. 建模暂停提示改为可折叠详情

- 47314 运行被门禁/安全阀暂停时，思维链末尾的暂停节点正式输出只保留【建模已暂停】、当前产物说明与继续运行指引；暂停原因和未通过的门禁校验项收进“暂停详情（点击展开）”折叠区，默认隐藏、点击展开。
- 前端 `AssistantText` 新增 `:::details` 折叠块渲染（复用现有迷你 Markdown 解析，内部段落/列表/表格均可正常渲染），新增 `.assistant-details` 折叠区样式；`frontend/dist` 已随构建更新。
- 验证：`npm run build`（vite 构建通过）；`.venv/bin/python -m unittest tests.test_frontend_contract` 通过（8 项）；服务器 `git pull --ff-only` 后两服务已重启至 `12100b1`，47313/47314 的 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`，两服务实际返回的新 bundle 均含“暂停详情”折叠标记。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`changelog/changelog_8_24.md`。

### 4. 独立建模默认模型固定为 qwen3.8-27b

- 修复 47314 打开历史 run 时用该 run 的历史模型（如 `qwen3.7-plus`）覆盖当前选择的问题；现在任何人刷新浏览器或重新进入页面，模型都固定取服务端默认 `qwen3.8-27b`，不再恢复 run 的历史模型，仅用户在当前会话显式选择才会改变。
- 前端移除打开 run、缓存命中、run 创建后的 `setStandaloneModel(run.model)` 恢复逻辑，组合框展示不再回退到 `run.model`。
- 验证：`npm run build`（vite 构建通过）；`.venv/bin/python -m unittest tests.test_frontend_contract` 通过（8 项）；`git diff --check` 通过；已部署 47313/47314 至 `a7fb0b0`，两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，`/api/modeling-models` 默认返回 `qwen3.8-27b`（24 个模型），线上实际返回的新 bundle 已不含 run 模型恢复逻辑。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`changelog/changelog_8_24.md`。

### 5. 续跑用户输入显示为用户气泡

- 修复 47314 续跑时用户输入不显示气泡的问题：服务端 `execute` 收到显式 `prompt` 时，先把用户文本作为 `user` 事件写入 run 日志（位于 `run_queued` 之前），并保留原始 `run.prompt` 不再被续跑文本覆盖；前端事件流因此按“原始提示气泡 → 历史事件 → 续跑用户气泡 → run_queued/run_started/…”顺序渲染，刷新后仍保留。
- 补充两条回归测试：续跑显式文本时写入单个 `user` 事件且原始 prompt 不变、事件顺序为 `user → run_queued`；无显式文本（如“继续运行”按钮）时不写入 `user` 事件。测试中先停并 join 调度线程，避免调度器 CLAIM 入队 run 触发真实后台任务。
- 验证：新增 2 项与相关续跑/表数量问答共 5 项测试连续 3 轮通过；`py_compile`、`tests.test_frontend_contract`（8 项）、`git diff --check` 均通过。
- 部署：已部署 47313/47314 至 `55cd46d`（与第 6 条同批）。部署前确认无活跃任务；服务器直连 `github.com` 超时，改用本地 bundle+scp 传输提交；服务器访问 PyPI TLS 故障导致 pip 构建隔离失败，改为 `--no-build-isolation --no-deps` 离线安装本地 wheel、`--no-index` 装齐 requirements 并更新依赖指纹 stamp 后重跑部署；47313 经 `scripts/deploy_server.sh`（16 项部署相关测试通过），47314 经 `scripts/run_standalone_modeling.sh` 重启，两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行。
- 主要文件：`open-claude/standalone_modeling_server.py`、`tests/test_standalone_modeling_server.py`、`changelog/changelog_8_24.md`。

### 6. 默认模型改回 Qwen/Qwen3-80B-AWQ

- 47313 工作台与 47314 独立建模服务默认模型由当日早前统一的 `qwen3.8-27b` 改回 `Qwen/Qwen3-80B-AWQ`（第 2/4 条曾为 27b，现按需求改回）：`config.py` 内置默认改回 80B，内置团队目录末尾显式保留 `qwen3.8-27b` 条目（避免与 80B 去重导致目录变 23 个）；`.env.example` 与本地、服务器 `.env` 同步为 `TEAM_MODEL=Qwen/Qwen3-80B-AWQ`。
- README 默认模型说明与团队配置回归测试同步更新；目录仍为 24 个模型，未显式配置、配置过期或无效时优先回退到 80B，仅当自定义目录不含它时才回退到目录首项。
- 验证：`tests.test_team_config` + `tests.test_frontend_contract` 共 11 项本地通过；已部署 47313/47314 至 `55cd46d`（与第 5 条同批），两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，`/api/meta`（47313）与 `/api/modeling-models`（47314，带 `X-Modeling-API-Key`）均返回默认 `Qwen/Qwen3-80B-AWQ`、24 个模型。
- 主要文件：`open-claude/open_claude/config.py`、`.env.example`、`open-claude/README.md`、`tests/test_team_config.py`、本地与服务器 `.env`、`changelog/changelog_8_24.md`。

### 7. 续跑意图误判修复：执行指令优先于疑问词判定

- 修复 `is_conversational_turn` 把带“是什么”的续跑指令误判成提问的问题：用户输入「上一个问题是什么来着 反正你接着上一个问题继续做」时，47314 把该回合按问答处理，只流式回复统计数字，随后 `restore_after_question` 把 run 恢复成执行前的 FAILED，界面表现为“跑完却 failed”。
- `open-claude/oc_codex_server.py` 在疑问词判定之前新增执行指令优先规则：`(?:继续|接着).{0,16}(?:做|执行|跑|生成|处理|修复|修改|建模|完成|导出|识别)`、`重新(?:做|执行|跑|生成|处理|修复|修改|建模|导出|识别)`、`^(?:请|帮我|麻烦你).{0,12}…` 执行动词；命中即按建模执行回合处理。“为什么执行失败”“怎么建模”“帮我看看”“先说说这个项目”等纯咨询仍保持问答。
- 补充 5 条回归断言（含线上真实触发文本）；`tests.test_ontology_knowledge` + `tests.test_frontend_contract` 共 16 项通过，`git diff --check` 通过。
- 部署：已部署 47313/47314 至 `8194cc2`（服务器直连 github 超时，沿用 bundle+scp；本次仅改 `oc_codex_server.py`，不在依赖指纹内，venv 无需重装），两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，模型接口默认仍为 `Qwen/Qwen3-80B-AWQ`。
- 运维：`run_6ed2452ad3c447c1a2bfb4edbaff76a7` 状态由 FAILED 重置为 INPUT_READY（服务端 `RunStore.transition`，API 复核通过）。该 run 的 FAILED 真实原因是第 3 轮建模续跑（08-24 10:59:28）撞团队网关预算上限（`Budget has been exceeded! Current cost: 30.35, Max budget: 30.0`）；第 4 轮被误判为问答。正式语义校验显示产物仍不合格（`logical_entities.csv` 第 16、26–44 行业务对象编码/名称为空；LE000001/009/011/013/016/019/024 的 `mainFlag=Y` 无 CONFIRMED 业务对象），因此不置 SUCCEEDED，重置为可续跑状态，待网关预算恢复后以明确建模指令重跑。
- 主要文件：`open-claude/oc_codex_server.py`、`tests/test_ontology_knowledge.py`、`changelog/changelog_8_24.md`。

### 8. 建模规范第 12 条修订：可实例化的低过拟合证据一致性门禁

- 规范源：`数据模型建模规范-v.0.0.1.xlsx` 是用户后来更新的权威版本（非临时变体），本次修订直接基于该文件；同时按构建链固定读取名 `rules/数据模型建模规范v0.0.1.xlsx` 同步一份内容完全一致的副本（原规范名文件此前在 git 中处于删除态，现已恢复为修改态），两个文件保持逐字节一致，运行时知识以构建链文件名生成。
- 修订第 12 条“可实例化”（保持严格表述，按用户校正后的口径）：基础数据、规则数据、报告报表数据三类明确不是业务对象（分别指分类/标签型参考数据、规则配置项/表达式/执行结果、报表模板/查询定义/统计展示等纯派生展示）；同时保留例外：可独立创建、版本化、审批、发布、生效、停用、审计的规则定义/规则版本可具有业务对象资格，有唯一报告编号和编制、审批、发布、归档独立生命周期的“某次报告实例”可作为文档型业务对象，主数据不因数量有限或当前行数少而否决；判定必须基于证据组合（实例来源、数量是否可预置、稳定身份、独立治理、业务行为、生命周期、是否纯派生展示），不得仅凭名称、表名或数据类别一刀切；证据不足用 UNKNOWN/CANDIDATE 并形成确认问题，不得臆造 PASS 或无反证直接 FAIL。
- 第 10 条“有生命周期和状态变化”同步对齐：分类/标签型基础数据和观测数据通常无状态变化、无独立生命周期，不属于业务对象；规则定义/版本和报告实例按第 12 条例外处理，消除“报告报表一律不能实例化”与“报告实例可作业务对象”的绝对表述冲突。
- 运行时知识重建：`scripts/build_agent_knowledge.py` 重新生成 `agent_knowledge/modeling/数据模型建模规范v0.0.1.md`、`basev0.0.1.md`、`all_sourcesv0.0.1.md` 及 integration 同名文件，均包含新第 12/10 条（仅手工改生成文件、不修源是禁止的；本次从源文件改起）。
- 建模提示词（`oc_codex_server.py build_modeling_instructions`，47313/47314 共用）：步骤 6 增加候选性质分类（OPERATIONAL_BUSINESS_OBJECT/MASTER_DATA/REFERENCE_DATA/RULE_DEFINITION/RULE_COMPONENT_OR_CONFIGURATION/REPORT_DEFINITION_OR_VIEW/REPORT_INSTANCE/DERIVED_ANALYTICAL_RESULT/UNKNOWN）与 R5 组合判定指引；证据门禁新增“低过拟合证据一致性”条目，明确反证存在仍写 PASS/CONFIRMED、或 CONFIRMED 正向证据只来自名称/表名/数据类别时将被阻断，名称/类别提示只触发复核并生成具体确认问题。
- 服务端门禁（`open-claude/open_claude/modeling_reliability.py`）：新增 `validate_business_object_evidence_consistency`，接入 `semantic_validation_issues` 与 `BUSINESS_OBJECTS` 阶段校验。反证词组只在证据文本中匹配（绝不匹配候选名称、表名或数据类别），单个强反证或两个以上弱反证视为明确反证；命中且 R5/R3=PASS 时输出 `R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE`/`R3_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE`（ERROR/STRUCTURAL_BLOCKER，阻断正式输出）；报告实例/规则版本带自身生命周期证据时放行；R5=PASS 但正向证据只来自名称/表名/数据类别时输出 `R5_PASS_WITHOUT_INSTANTIATION_EVIDENCE` 阻断。证据不足、名称/类别提示、正反冲突仍为 UNKNOWN/CANDIDATE，不直接 REJECTED。
- 修复推断缺陷：`infer_business_object_rule_status` 新增 `_marker_hit`，避免“不可实例化/不可重复创建/无业务编号”被正向标记误判为 PASS；R5 反证标记补充“不可实例化、不能形成可区分实例、纯查询结果、聚合结果、统计展示、计算派生”等规则 12 的显式证据短语。
- 测试：`tests/test_modeling_reliability.py` 新增 `BusinessObjectEvidenceConsistencyTests`（12 项），覆盖固定码表拒绝、低行数/0 行主数据放行、规则配置行拒绝、规则定义放行、SQL 聚合视图拒绝、报告实例放行、名称含“报告”降 CANDIDATE、名称/类别关键词只触发复核、正反冲突保持 UNKNOWN、finalization 阻断、47313/47314 共享同一门禁结论一致。
- 验证：`python -m unittest discover -s tests` 359 项通过（3 项跳过），其中 `tests.test_modeling_reliability` 71 项、`tests.test_ontology_knowledge` 等 114 项、`tests.test_standalone_modeling_server` 48 项；`py_compile` 与 `git diff --check` 通过。
- 未部署、未提交、未推送；生成知识中同步出现的 V6 标题归一（`通用业务对象与逻辑实体识别规范v0.0.1.md` 标题由 v0.0.1 归一为 V6）是构建脚本既有输出与上次提交产物之间的漂移，随本次重建一并落齐。
- 主要文件：`rules/数据模型建模规范v0.0.1.xlsx`、`scripts/build_agent_knowledge.py`（无改动，仅重建）、`agent_knowledge/modeling|integration/*v0.0.1.md`、`open-claude/oc_codex_server.py`、`open-claude/open_claude/modeling_reliability.py`、`tests/test_modeling_reliability.py`、`changelog/changelog_8_24.md`。

### 9. CANCELLED/BLOCKED 运行的提问与续跑修复

- 问题：`run_6ed2452ad3c447c1a2bfb4edbaff76a7` 在 08-24 14:54 用户点取消后最终状态为 CANCELLED（在途第 5 轮 14:56:02 门禁触发 blocked 后走取消收尾），此后无法继续提问；而 FAILED/BLOCKED 的 run 均可提问。
- 根因：状态机 `RUN_TRANSITIONS` 允许 `CANCELLED → QUEUED`（取消后恢复），但两处不一致：前端 `continueRun` 放行列表只含 `["CREATED", "INPUT_READY", "FAILED", "BLOCKED"]`（CANCELLED 直接静默 return，气泡不出现也无报错）；服务端 `execute()` 转 QUEUED 的 `allowed_from` 同样漏了 CANCELLED（会 409 `INVALID_STATE_TRANSITION`）。另外 `restore_after_question` 只接受 INPUT_READY/FAILED 作为回退目标，BLOCKED 会被强制归一成 INPUT_READY，问完问题会丢掉 BLOCKED 标记和暂停原因。
- 修复：前端 `continueRun` 放行列表加 `CANCELLED`，“继续运行”按钮对 CANCELLED 也显示（FAILED/BLOCKED/CANCELLED），run 状态色为 CANCELLED 增加 warning 色；服务端 `execute()` 的 QUEUED `allowed_from` 加 `CANCELLED`（表数量只读问答路径同步放行 BLOCKED/CANCELLED），且问答回合不再清空 FAILED/BLOCKED 的错误原因，只有真正的续跑才清；`restore_after_question` 接受 BLOCKED 原样回退，保留暂停原因，避免问完问题丢状态。
- 测试：`tests/test_standalone_modeling_server.py` 将“取消后不可执行”改为“CANCELLED 可重新排队执行”，新增 BLOCKED 上问答回合保持 BLOCKED 且保留门禁原因、CANCELLED 上问答回合回到 INPUT_READY；`tests/test_frontend_contract.py` 同步更新 3 处放行列表断言。
- 验证：`python -m unittest tests.test_standalone_modeling_server tests.test_frontend_contract` 通过，`python -m unittest discover -s tests` 361 项通过（3 项跳过）；`npm run build`（vite 构建通过）；`py_compile` 与 `git diff --check` 通过。
- 部署：已部署 47313/47314（服务器直连 github 超时，沿用本地 bundle+scp；本次改 `standalone_modeling_server.py` 与前端 dist，不在依赖指纹内，venv 无需重装），两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，模型接口默认仍为 `Qwen/Qwen3-80B-AWQ`；`run_6ed2452ad3c447c1a2bfb4edbaff76a7` 未改动状态，可直接按“继续运行”或提问恢复。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/*`、`open-claude/standalone_modeling_server.py`、`tests/test_standalone_modeling_server.py`、`tests/test_frontend_contract.py`、`changelog/changelog_8_24.md`。

### 10. 四类非业务对象不识别为业务对象：逻辑实体归属状态门禁

- 规范：以最新第 12 条内容为准修订构建链固定文件名 `rules/数据模型建模规范v0.0.1.xlsx`（权威源为未跟踪的用户新文件 `rules/数据模型建模规范-v.0.0.1.xlsx`，不长期保留两个仅标点不同的副本）。明确基础数据、规则数据、参考数据、报告报表数据不得识别为业务对象，但仍是合法逻辑实体；可独立创建/版本化/审批/发布/生效/停用/审计的规则定义或规则版本、有唯一报告编号和独立生命周期的报告实例、可治理主数据等例外保留。明确“不是业务对象”不等于“不是逻辑实体”，对应逻辑实体归属状态为 `NOT_APPLICABLE`，禁止创建 `BO0000`、`BO99999`、`非业务对象逻辑实体` 等占位业务对象。第 33 条归属唯一规则兼容 `NOT_APPLICABLE`。运行 `scripts/build_agent_knowledge.py` 重建运行时知识，`agent_knowledge/modeling|integration/*v0.0.1.md` 均同步新规则（构建可重复、无额外漂移）。
- 归属状态：逻辑实体内部归属统一为 `ASSIGNED`（编码/名称必填且必须引用本次 CONFIRMED 业务对象、有且唯一主实体）/ `NOT_APPLICABLE`（编码/名称必须为空、主标志 `N`、必须带非业务对象分类/排除原因/证据并关联对应 REJECTED 候选决策）/ `UNRESOLVED`（证据不足，编码/名称为空、主标志 `N`、必须保留确认问题，不得伪装 `NOT_APPLICABLE`）。空编码且无审计状态时是结构错误，绝不自动推断 `NOT_APPLICABLE`。
- CSV 契约：`modeling_csv_contract.py` 将 `logical_entities.csv` 的业务对象编码/名称改为条件必填（新增 `assignment_status_aware`、归属状态推断与 `FORMAL_CONTRACT_ASSIGNMENT_STATUS_MISSING`/`ASSIGNMENT_CONFLICT` 错误码）；`modeling_rule_registry.validate_formal_rows` 与服务端上传/缓存校验从 `modeling_state.json` 读取归属状态关联校验；未声明业务对象编码/名称/主标志列的简化 CSV 不做归属判定，保持 header-aware 兼容，不影响既有简化产物流程。
- 门禁：`modeling_reliability.py` 重写 `validate_logical_entity_assignments`（`NOT_APPLICABLE` 主标志 `Y`、填写编码/名称、缺审计证据、无对应 REJECTED 决策均阻断；`ASSIGNED` 缺编码或引用非 CONFIRMED 阻断；`UNRESOLVED` 主标志 `Y` 阻断）；候选性质/数据类别证据一致性新增 `CONFIRMED_WITH_NON_BUSINESS_OBJECT_KIND` 与 `R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE`（STRUCTURAL_BLOCKER 阻断正式输出，不做名称/表名/数据类别一刀切）；新增 `apply_not_applicable_normalization` 确定性自动修复（仅在有充分审计证据时把主标志 `Y→N`、清空错误编码/名称），禁止占位业务对象、禁止“门禁通过后二次清洗”。
- 提示词：47313/47314 共用 `build_modeling_instructions`，明确四类非业务对象判定、`NOT_APPLICABLE` 输出规范、禁止占位 `BO`、证据不足用 `UNRESOLVED`、输出前校验正式 CSV 与内部审计状态一致。
- 测试：`tests/test_modeling_reliability.py` 新增 `NotApplicableAssignmentTests`（12 项），覆盖四类非业务对象逻辑实体 finalize 通过、四类候选仍 CONFIRMED 阻断、`NOT_APPLICABLE` 主标志/编码/缺证据/无 REJECTED 阻断、`ASSIGNED` 缺编码/引用非 CONFIRMED 阻断、`UNRESOLVED` 保留确认问题等。
- 验证：`python -m unittest discover -s tests` 373 项通过（3 项跳过；`tests.test_standalone_modeling_server` 50 项单独运行通过）；`python -m py_compile` 与 `git diff --check` 通过；知识构建脚本重复运行无新增漂移。
- 部署：已提交 `45c02ca` 并部署 47313/47314。部署前确认无活跃任务（47313 无 RUNNING/QUEUED；47314 仅 BLOCKED×2、INPUT_READY×2、FAILED×1，均非执行中）。服务器拉取 github 需绕开 `https_proxy`（走代理 TLS 握手失败），直连 `git fetch` 后本地 `git merge --ff-only` 快进到 `45c02ca`；本次修改了 `open_claude/` 源码导致依赖指纹变化，按既有离线流程构建本地 wheel（`pip wheel --no-build-isolation --no-deps --no-index ./open-claude`）、`--no-index` 装齐 requirements 并更新 `.venv/.ontology-agent-deps.sha256`。47313 经 `scripts/deploy_server.sh`（16 项部署测试通过）重启，47314 经 `scripts/run_standalone_modeling.sh` 重启；两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，默认模型均为 `Qwen/Qwen3-80B-AWQ`，site-packages 的 `open_claude` wheel 已含新归属门禁代码（`ASSIGNMENT_STATUS_MISSING`/`CONFIRMED_WITH_NON_BUSINESS_OBJECT_KIND`）。
- 主要文件：`rules/数据模型建模规范v0.0.1.xlsx`、`agent_knowledge/modeling|integration/*v0.0.1.md`、`open-claude/open_claude/modeling_csv_contract.py`、`open-claude/open_claude/modeling_rule_registry.py`、`open-claude/open_claude/modeling_reliability.py`、`open-claude/oc_codex_server.py`、`tests/test_modeling_reliability.py`、`changelog/changelog_8_24.md`。
### 11. 会话状态同步统一修复：事件幂等合并与游标协议

- 问题 A（47314 重复用户气泡）：`/execute` 202 响应此前携带完整事件数组，前端写入 `run.events` 后又用旧游标拉 `/events?since=旧cursor`，同一用户事件以快照+增量两条路径直接拼接（`[...current, ...delta]` 无去重），页面出现两个气泡，刷新后从服务端日志重建才恢复一个。
- 问题 B（CANCELLED 后提问显示旧错误）：取消时服务端把 `run.error="cancelled by user"` 保留在 run 上；从 CANCELLED 发起普通问题时执行已转为 QUEUED，但会话回合不清除旧 error，前端用裸 `if (started.error)` 把 202 响应中的领域状态字段误判成接口失败，显示旧的“已取消”错误，刷新后才恢复。
- 统一事件身份与合并：新增 `frontend/src/eventSync.js`，两服务共用 `eventIdentity`（优先级：`clientMessageId → 服务端持久化 seq → 无标识旧事件的确定性指纹`，绝不用数组下标）、`mergeEvents`（幂等合并后按 seq 升序稳定排序）、`appendStreamEvent`（SSE 实时流增量去重+相邻 thinking/text 拼接）、`eventKey`（React key 与事件身份一致）、`nextCursor`（取服务端绝对位置）。快照、SSE、轮询、`/events?since=`、历史详情、向前分页、缓存恢复全部收敛到同一规范化事件集合。
- 47314 协议（方案 1）：`/execute`、`/cancel` 的 202 改为 `run.as_dict(include_events=False)` 摘要响应，事件统一走 `/events`；`/events` 响应补充 `eventEnd` 与 `nextCursor`（绝对 next-read 位置），`since` 返回严格大于游标、`before` 返回严格小于边界，无重叠；前端游标推进改用服务端 `nextCursor/eventEnd`，不再单独依赖 `cursor + delta.length`；`loadRun` 尾部窗口与既有缓存按 runId 合并（不替换、不收缩），`loadOlderStandaloneEvents` 向前插入走 `mergeEvents`。
- 47314 错误区分与生命周期：创建/继续/刷新全部改用 `standaloneRequestFailed`（HTTP 非 2xx/网络失败才算接口失败，202 中的 `run.error` 是领域状态）；服务端 `execute()` 只在 FAILED/BLOCKED 上做会话问答时保留原错误（供 `restore_after_question` 恢复），CANCELLED 提问与一切真实续跑立即清空当前 `run.error`，历史取消/失败原因仍保留在事件日志。
- 47314 轮询与合成气泡：全局 `pollInFlightRef` 改为按 runId 的锁 Map，A 会话轮询不再阻塞/释放 B；初始 prompt 气泡只在事件日志无正式 user 事件时合成（续跑不重复），BLOCKED 建议与 prompt 气泡带稳定 `_key`，刷新/轮询/回填不产生第二份。
- 47313 后端：`Task._record_event` 为每个事件打持久化单调 `seq`（`restore_tasks` 从 log/archive 最大 seq 恢复计数器，重启后不冲突）；`/send` 支持 `clientMessageId`（同 id 已存在时跳过再记录，防重），`stream_turn` 把带 `clientMessageId` 的正式 user 事件经 SSE 回传，前端用同一身份把乐观气泡替换为正式事件，不再出现双份。
- 47313 前端：`appendEvent`/`openTask`/`loadOlderTaskEvents` 全部走统一合并；乐观 user 消息带 `clientMessageId`；busy 改为请求级 generation（旧请求 finally 不再清掉新请求 busy）；SSE 消费按 `activeTaskIdRef` 校验，切会话后旧流不再污染新会话；历史分页 `[...older, ...current]` 改为 `mergeEvents`。
- 测试：`tests/test_standalone_modeling_server.py` 新增 4 项（execute 202 无 events 且 `/events` 返回绝对游标、CANCELLED 提问清旧错误、FAILED/BLOCKED 问答保留原因而真实续跑清空、`since/before` 边界无重叠）；`tests/test_tasks.py` 新增 `TaskEventSyncTests` 4 项（seq 单调持久化、clientMessageId 防重、stream_turn 回显带 id、restart 后 seq 恢复）；`tests/test_frontend_contract.py` 新增 eventSync 纯函数 Node 行为测试与统一契约断言，并同步更新旧断言（游标改 `nextCursor`、缓存合并、send body 带 `clientMessageId`、EventFeed 稳定 key）。
- 验证：`npm run build`（vite 通过，新 bundle `index-DNajaSjr.js`）；`.venv/bin/python -m unittest tests.test_standalone_modeling_server tests.test_tasks tests.test_frontend_contract` 97 项通过；`py_compile` 与 `git diff --check` 通过；全量 `discover -s tests` 383 项中仅 `test_tasks.ToolExecutionDedupTests.test_same_tool_call_id_is_not_executed_twice` 顺序相关失败，该失败在基线 HEAD 同样复现（既有问题，与本改动无关，未修复）。
- 部署：已提交 `b256e68` 并部署 47313/47314。部署前确认无活跃任务（47313 任务均 `idle`；47314 仅 FAILED run，无 QUEUED/ANALYZING）。本地直连 `git push origin 20260727` 成功；服务器绕开 `https_proxy` 直连 `git fetch` 并 `git merge --ff-only` 快进到 `b256e68`。本次改动在 `oc_codex_server.py`/`standalone_modeling_server.py`（`open-claude/` 顶层脚本，不在 `ensure_agent_venv.sh` 指纹范围内），依赖指纹 stamp 未变；按既有离线流程重装一次 wheel 后核对指纹一致（`920165ac…`），venv 无需真正重装。47313 经 `scripts/deploy_server.sh`（18 项部署相关测试通过）重启，47314 经 `scripts/run_standalone_modeling.sh` 重启；两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，默认模型均为 `Qwen/Qwen3-80B-AWQ`，47313 线上 HTML 已引用新 bundle `index-DNajaSjr.js`。
- 附注（非本改动引入）：三个相关测试文件合并运行时偶发挂起，定位为基线既有的调度器竞态（测试手动把 run 置 QUEUED 时，manager 调度线程并发 claim 并派发真实 worker 调用真实 LLM）+ 本机 `.env`（gitignore）配置 `LLM_PROVIDER=team` 使真实调用走 OpenAI 兼容网络路径，当前代理不可达时 `sock_recv` 无限阻塞、`close()` 的 `executor.shutdown(wait=True)` 随之挂起；HEAD worktree 对照中同一竞态因无 `.env` 走 Anthropic 路径无 key 快速失败而非挂起。单文件运行时全部稳定通过，未改动相关代码。
- `frontend/dist/` 已随构建更新（旧 bundle 移除、新 bundle 加入，未触碰用户数据目录）。
- 主要文件：`frontend/src/eventSync.js`（新增）、`frontend/src/main.jsx`、`frontend/dist/`、`open-claude/standalone_modeling_server.py`、`open-claude/oc_codex_server.py`、`tests/test_standalone_modeling_server.py`、`tests/test_tasks.py`、`tests/test_frontend_contract.py`、`changelog/changelog_8_24.md`。

### 12. 新增《本体建模识别过程SOP》文档

- 新增 `docs/本体建模识别过程SOP.md`，面向人阅读的识别过程全景全流程 SOP，结构参考 `openchat-BI/docs/ChatBI_Agent场景分析SOP.md`（文档目的 → 核心原则 → 主流程 → 速查表 → 异常与降级 → 产物速查 → 禁止事项 → 验收清单），内容不区分行业/场景，覆盖 47313/47314 全部建模输入源；增加 Mermaid 全景流程图，直观区分正式事实、待确认候选、驳回项及门禁后的交付/续跑分支。
- 主流程十步：任务启动与意图识别（执行指令优先于疑问词判定）→ 输入资产盘点 → 证据勘察与读取（`extract_schema.py`/`tableNames` 定向读取、文档 manifest/content/tables、样例模板只作格式参考）→ 候选业务属性（`allAttributes` 全量、属性角色、技术字段排除）→ 逻辑实体（生成/合并/拆分条件、实体角色）→ 业务属性正式归属与标准化 → 实体关系分类（关系类型与判定决策树、M:N 拆分、仅 COMPOSITION/EXTENSION 可聚合）→ 实体族/候选主实体/R1–R5 判定（CONFIRMED/CANDIDATE/REJECTED、四类非业务对象、ASSIGNED/NOT_APPLICABLE/UNRESOLVED 归属）→ 正式 CSV 输出与决策审计（模板契约、编码规范、5 个 decisions CSV）→ 门禁校验与状态流转（十阶段、四类门禁动作、BLOCKED/FAILED/续跑/取消恢复）。
- 文档内容与当前实现（`通用业务对象与逻辑实体识别规范v0.0.1.md`、`modeling_reliability.py`、`modeling_csv_contract.py`、`standalone_modeling_server.py`、`oc_codex_server.py build_modeling_instructions`、`API/standalone-modeling-api.md`）一致，纯文档新增，无代码/运行时变化。
- 主要文件：`docs/本体建模识别过程SOP.md`、`changelog/changelog_8_24.md`。
