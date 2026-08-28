# 20260817–20260821 分支变更记录

> 本文档记录 `20260727` 分支在 2026-08-17 至 2026-08-21 的变更（按功能主题归纳，替代每日 changelog）。

## 维护规则

- 本周结束后按功能主题归档为 `changelog_8_17_21.md`，原每日 changelog（8_17/8_18/8_19/8_20/8_21）已按用户要求删除。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314（部署前确认无活跃任务），两服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。

## 1. 47314 独立建模服务建设与加固（8-17 ~ 8-18）

- 新增独立通用建模服务 47314：`ModelingRun` 边界（创建/上传/异步执行/事件查询/文件列表/校验），每 run 独立 `input/work/output` 工作区，通过 `mission-*` 安全别名复用现有建模引擎与 Sandbox；短期 HttpOnly 会话认证 + 长期 API Key 兼容；状态机阻止执行期非法上传/重复执行/外部校验；事件按 run 写 `.events.jsonl` 增量持久化，重启时处理中运行恢复为带原因的 FAILED。
- 数据库建模输入：服务端安全数据源注册（MetaERP `172.16.5.163`、guangfeng `172.16.5.66` 等），前端分步选择数据源 → Schema 多选 → 数据表 → 解析要素，密码不返回前端；只读账号 `ontology_agent_ro_47314` + `search_path` 隔离；表数量等只读问题服务端直接回答，不再误启动建模；`intent=execute/chat` 区分强制门禁与问答。
- 并发与恢复：新增 `QUEUED` 状态与可配置 worker semaphore（默认 2，`MODELING_SERVER_MAX_ACTIVE_RUNS`），单 run 并发门禁 `409 ACTIVE_RUN_EXISTS`；`FAILED` run 支持“继续运行”复用原工作区；历史会话选择与后台执行解耦。
- 文件与审计：文件树按 `root/input/work/output` 四目录展示，隐藏 `pylibs/.py_deps` 等运行时依赖；`mission-work` 决策审计收敛为五个固定 v0.0.1 中文表头 CSV；统一 47313/47314 共享 `.venv`（`ensure_agent_venv.sh`，沙箱只读挂载）。
- 主要文件：`open-claude/standalone_modeling_server.py`、`open-claude/open_claude/run_repository.py`、`scripts/run_standalone_modeling.sh`、`scripts/ensure_agent_venv.sh`、`frontend/src/main.jsx`、`frontend/dist/`、`API/standalone-modeling-api.md`。

## 2. 建模门禁体系重构（8-19 ~ 8-21）

- 门禁动作模型：问题统一分为 `STRUCTURAL_BLOCKER` / `DETERMINISTIC_NORMALIZATION` / `FORMAL_ELIGIBILITY` / `QUALITY_WARNING` 四类，阶段与最终状态只按结构性阻断判 FAILED；服务端确定性规范化 `normalize_modeling_state()`（资产覆盖自动补 UNKNOWN、弱 COMPOSITION 降级 REFERENCE、无证据/M:N CONFIRMED 关系降级 CANDIDATE、UNKNOWN→CONFIRMED 无证据升级拒绝、主逻辑实体缺失降级、证据循环清理、技术字段从正式输出排除等），幂等且审计留痕。
- 证据与严重度：R1–R5 证据归类修正；规则/指标弱证据、资产覆盖缺失、聚合语义未知等由 ERROR 降为 WARNING（不触发 retry/blocked/safety valve）；规则决策状态门禁（`business_rules.csv` 仅 CONFIRMED 规则，`强制状态=UNKNOWN/NOT_ENFORCED` 可正式输出）；`V0001_DUPLICATE_FORMAL_NAME` 收敛为同逻辑实体属性重名 ERROR、跨实体同名放行；门禁自动修复次数 3→10，相同错误无新证据仍立即 BLOCKED；`VALIDATION_CACHE_VERSION` 升级使旧 FAILED 缓存失效重算。
- 正式 CSV 门禁收紧（8-21）：新增集中式逐行字段契约注册表 `modeling_csv_contract.py`（25 个文件名含别名），上传与 finalize 共用同一 `validate_row_contract`；必填/布尔 Y/N/枚举/整数/编码/中英文名称分离/文件内唯一/条件结构规则/跨文件引用为确定性格式错误，恢复为 `STRUCTURAL_BLOCKER`；证据不足、定义质量等语义仍 WARNING；CANDIDATE/UNRESOLVED/REJECTED 行若仍出现在正式 CSV 报 `FORMAL_OUTPUT_INELIGIBLE_ROW` 阻断。
- 数据库证据门禁（8-21）：`ensure_database_helpers()` 自动生成 `mission-input/extract_schema.py`（只读提取选中表结构到 `work/schema_extract.json`，复用 `create_db_engine`，支持 `selectedSchemas`/`selectedTables`）；47313/47314 系统提示均要求数据库建模先执行 `extract_schema.py`、缺少表结构证据时禁止直接使用模板样例数据生成正式输出；`validate_database_modeling_evidence()` 对 db 模式缺 `work/schema_extract.json` 报 `DATABASE_SCHEMA_EVIDENCE_MISSING`（STRUCTURAL_BLOCKER），上传模式跳过；`FORMAL_OUTPUT_COPIED_TEMPLATE_SAMPLE` 检测正式 `business_objects.csv` 与 `mission-input/*样例数据*/02-*.csv` 完全一致时阻断。修复 guangfeng/metaerp 两个 run 输出完全一致（9 业务对象/5 逻辑实体）的根因。
- 表结构勘察提速（8-21）：`schema_extract.json` 首部新增 `tableNames` 表名清单；47313/47314 提示词要求先读表名清单、再按表名/列名 `grep` 定向查询单表定义、禁止反复整文件读取，模板与规范 CSV 只读一次，缓解 51 表任务勘察阶段上下文膨胀导致的逐步变慢（实测单步 9s→47s 恶化为整文件重复读取所致）。
- 主要文件：`open-claude/open_claude/modeling_reliability.py`、`modeling_rule_registry.py`、`modeling_csv_contract.py`、`open-claude/oc_codex_server.py`、`agent_knowledge/`、对应 tests。

## 3. DeepSeek thinking 400 全路径修复（8-19 ~ 8-20）

- 统一消息清洗 `sanitize_messages()`（`stream_message`/`complete`/`to_openai_messages` 共用，幂等）：合法 `reasoning_content + tool_calls`、`reasoning_content + content` 原样保留；仅 reasoning 或空 content 无 tool_calls 的 assistant 不发送；孤立/重复/错配 tool result 自动修复，缺结果时从 `remember_tool_result`/`seed_tool_results` 按 `tool_call_id` 恢复真实结果，找不到不伪造、截断到最后一致 checkpoint 并保留后续 user 消息。
- 400 自动修复（stream 与 send 同一策略，最多两次）：第一次恢复完整 reasoning 与工具链后只重试当前 LLM step；第二次从 checkpoint 重建出站历史、仅剥离孤立 reasoning（合法 reasoning+tool_calls 不剥离）。
- 流式 timeout：`LLM_STREAM_TIMEOUT`/`ProviderStreamTimeoutError` 独立可恢复，半截 reasoning/text 不进入 provider 历史（UI 仍可见），标记错误前先持久化最后合法阶段 checkpoint；继续运行从该 checkpoint 恢复当前 step。
- 工具执行安全：`repl.py`/子 Agent 执行前查 `lookup_tool_result()`，同一 `tool_call_id` 已有真实结果直接复用，写工具不因 retry/continue 二次执行。
- 主要文件：`open-claude/open_claude/openai_compat.py`、`repl.py`、`agent.py`、`open-claude/oc_codex_server.py`、`standalone_modeling_server.py`。

## 4. 前端与用户体验（8-17 ~ 8-21）

- 47314 standalone 页面：七个产物中文标签、历史运行标题/时间统一（`title → prompt → 本体建模` 降级）、运行态自适应布局、思维链增量合并为思考阶段、文件面板默认展开、`BLOCKED` 状态灰色标签 + 对话流自动追加建议消息（可继续运行或直接下载产物）、“下载所选”修复（显式传 selected、session 刷新、DOM 挂载下载、失败逐项提示）。
- Agent 错误展示友好化（8-21）：思维链/输出中的 `error`/`is_error` 不再显示红色感叹号，统一转为灰色提示（图标 `ℹ`、标题 `提示`、文案 `提示：{原因}`、done 显示“未完成（可继续执行）”）；任务列表 error 红点与 47314 FAILED Tag 改灰色；页面级原生错误（网络/401/接口失败）保留原样，后端协议与平台 FAILED 回调不变。
- 47314 会话命名（8-21）：新会话可输入“任务名称”（`ModelingRun.title` 全链路持久化，SQLite payload 快照无需迁移），会话名按 任务名称 → 建模要求 → 本体建模 降级显示。
- 状态展示改名（8-21）：`BLOCKED` 对外统一显示为 `EXECUTED`、`ANALYZING` 显示为 `EXECUTING`（历史列表与运行详情头部），内部状态码/状态机/继续运行判断保持不变，不影响已存 run 与恢复逻辑。
- 服务标识（8-21）：47314 页头蓝色标签由“47314 独立服务”改为“v0.0.1”，与当前输出契约版本保持一致。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`open-claude/standalone_modeling_server.py`、对应 tests。

## 5. 配置、部署与运维（8-21）

- 默认大模型切换：47313/47314 默认模型由 DeepSeek V4 Flash 改为 `Qwen/Qwen3-80B-AWQ`（服务器 `.env` `TEAM_MODEL`，`.env` 不入库）；修复浏览器用户模型偏好残留（`user_model` 实时读取）；`/api/model` 与 `/api/modeling-models` 均返回 Qwen，两服务重启验证健康。
- 部署线路核查：SSH/git remote/fetch 正常，部署脚本无需修改；确认服务器无活跃任务后部署。
- ⚠️ 运维事故：清理验证 run 时 `rm -rf ".../$run_id"` 变量未定义展开为空，误删 47314 `standalone-modeling-runs/` 全部历史 run 工作目录与 SQLite 数据库，无备份不可恢复（已如实记录并报告用户）。
- 事故后加固：`SQLiteRunRepository` 新增 `_with_schema_recovery`，表丢失（`no such table`）时幂等重建并重试一次，服务无需重启自愈（线上验证 `DROP TABLE` 后 API 自动恢复）；按用户强制要求把「文件与数据删除安全」写入 `AGENTS.md`（最高优先级：删除前完整路径/断言/dry-run、生产数据优先 API、变量为空禁止 `rm -rf`、拿不准先问）。

## 验证与部署基线

- 完整测试集由本周初 `117` 项增长至期末 `344` 项（skipped=3，macOS 无 bubblewrap），新增 `tests/test_database_modeling_evidence.py`（7 项）；各专项定向测试、`py_compile`、`git diff --check`、前端 `npm run build` 均通过。
- 本周所有功能修复均以同一 commit 部署 47313/47314，部署前确认两服务无活跃任务；最终服务器 HEAD 与 `origin/20260727` 同步，两服务 `/`、`/health` 200，启动日志无 Traceback。8-21 建模证据门禁 + 前端改名 commit `a0ebef6` 已部署 47313/47314（部署前确认 47313 的 `22dba975bd5e` 仅为重启前残留 `working` 快照，重启恢复逻辑已转为 `idle`）。
